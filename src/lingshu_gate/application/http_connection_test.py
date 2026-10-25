"""Bounded, ephemeral HTTP MCP diagnostics using the production protocol client.

An explicit administrator test permits only its exact draft target. It creates
neither a saved configuration nor a reusable trust/credential binding. Every
send rechecks live authority, the saved snapshot and credential revisions.
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import threading
import time
import urllib.error
from typing import TYPE_CHECKING, Any

from lingshu_gate.application.external_mcp_configuration import _control_lock, _error
from lingshu_gate.credential_refs import extract_credential_refs, resolve_env_credential_refs
from lingshu_gate.credential_store import CredentialRevisionConflict, CredentialUsageDenied
from lingshu_gate.invocation_payloads import audit_header_values
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_config_store import McpConfigConflict
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_http_trust import McpHttpTrustConflict
from lingshu_gate.mcp_manifest import validate_manifest_for_write
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext

if TYPE_CHECKING:
    from lingshu_gate.application.external_mcp_configuration import ExternalMcpConfigurationService
    from lingshu_gate.domain.http_mcp_management import HttpMcpTestInput

logger = logging.getLogger(__name__)
_REFERENCE = re.compile(r"^(?:(?:Bearer|Basic|Token) )?\$\{credential:[A-Za-z0-9_.-]+\}$")
_SENSITIVE_HEADER = re.compile(r"auth|token|key|secret|password|cookie", re.I)
_RESERVED = frozenset({"host", "content-length", "transfer-encoding", "connection", "proxy-authorization",
    "content-type", "accept", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name",
    "traceparent", "tracestate", "baggage", "x-correlation-id"})


class _TestBlocked(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def test_http_connection(service: ExternalMcpConfigurationService, body: HttpMcpTestInput,
                         context: ToolInvocationContext) -> dict[str, Any]:
    """No tool invocation, automatic retry, config write or registry publication."""
    target = body.manifest.get("id")
    if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", target):
        raise _error("external_config_invalid", "An exact server ID is required.")

    def authorize() -> None:
        service._authorize(context, write=True, tool_id="gate_http_mcp_test", target_id=target, action="test")

    authorize()
    if not body.confirmed:
        raise _error("confirmation_required", "Explicitly request this bounded connection test.")
    if not service._connection_tests.acquire(blocking=False):
        raise _error("http_test_busy", "Two connection tests are already running; retry after one finishes.")
    started = time.monotonic()
    deadline = started + body.timeout_seconds
    result: dict[str, Any] = {"ok": False, "status": "failed", "network_attempted": False,
        "config_saved": False, "trust_changed": False, "registry_changed": False,
        "business_permissions_verified": False,
        "stages": [{"id": stage, "status": "skipped"} for stage in
                   ("configuration", "http", "authentication", "handshake", "tools")]}
    stages = {stage["id"]: stage for stage in result["stages"]}
    current_stage = "configuration"
    client: StreamableHttpMcpClient | None = None
    observer: _TestOpener | None = None
    failure: Exception | None = None
    try:
        with _control_lock(service.configs.mutation_lock):
            actual_digest = service._config_digest(target)
            if body.existing_server_id is not None:
                if body.existing_server_id != target or not body.expected_config_digest or actual_digest != body.expected_config_digest:
                    raise _TestBlocked("config_changed")
                previous = service.configs.load_manifest(target)
                data = service.configs._preserve_masked_env(body.manifest,
                    previous.model_dump(mode="json", exclude={"manifest_path"}))
            else:
                if actual_digest is not None or body.expected_config_digest is not None:
                    raise _TestBlocked("config_changed")
                previous, data = None, body.manifest
            if len(json.dumps(data, ensure_ascii=False).encode()) > 65536:
                raise _TestBlocked("invalid_manifest")
            manifest = validate_manifest_for_write(data, check_http_trust=False)
            if manifest.launch.type != "external" or manifest.transport.type != "streamable_http":
                raise _TestBlocked("external_http_required")
            # Never borrow an administrator's personal downstream identity.
            # Personal slots retain their separate caller-owned connection flow.
            if manifest.user_credentials:
                raise _TestBlocked("personal_credentials_required")
            if not manifest.enabled:
                raise _TestBlocked("service_disabled")
            seen = set()
            for name, value in manifest.transport.headers.items():
                key = name.lower()
                if (not re.fullmatch(r"[A-Za-z0-9-]{1,128}", name) or key in seen or key in _RESERVED
                        or "\r" in value or "\n" in value or value == "***"):
                    raise _TestBlocked("invalid_headers")
                seen.add(key)
                if _SENSITIVE_HEADER.search(name) and not _REFERENCE.fullmatch(value):
                    # Existing masked secrets can only be reused on the exact saved
                    # endpoint. New secrets must enter the credential store first.
                    old = previous.transport.headers.get(name) if previous is not None else None
                    if previous is None or previous.transport.endpoint != manifest.transport.endpoint or value != old:
                        raise _TestBlocked("credential_reference_required")
            trust = service.configs.http_trust_store
            if trust is None:
                raise _TestBlocked("http_policy_unavailable")
            trust_plan = trust.plan_configuration(target, manifest.transport.endpoint,
                previous_endpoint=previous.transport.endpoint if previous else None, creating=previous is None)
            # A diagnostic cannot restore a revocation, even with a recreated ID.
            if trust_plan["policy_state"] in {"revoked", "needs_review"} or not trust_plan["connection_allowed"]:
                raise _TestBlocked("http_trust_revoked")
            refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
            revisions = {ref: service.credentials.get_credential(ref).updated_at for ref in refs}
            binding = service.configuration.http_credential_binding(manifest)

        def guard() -> None:
            authorize()
            if time.monotonic() >= deadline:
                raise TimeoutError("Connection test deadline exceeded")
            with _control_lock(service.configs.mutation_lock):
                if service._config_digest(target) != actual_digest:
                    raise McpConfigConflict("Configuration changed during test")
                trust.check_plan(trust_plan)
                service._require_reconciled_http_configuration(target, None)
                for ref in refs:
                    service.credentials.assert_http_binding(ref, server_id=target,
                        endpoint=manifest.transport.endpoint or "", server_binding=binding,
                        expected_revision=revisions[ref], allow_pending=True)

        class TestClient(StreamableHttpMcpClient):
            def _require_endpoint(self) -> None:
                # Explicit, request-local capability, not a permissive global mode.
                guard()

            def _resolve_headers(self) -> None:
                self._resolved_headers = {}
                guard()
                resolved, _ = resolve_env_credential_refs(dict(self.manifest.transport.headers),
                    self.credential_store, expected_revisions=revisions)
                if any("\r" in value or "\n" in value for value in resolved.values()):
                    raise _TestBlocked("invalid_headers")
                self._resolved_headers = resolved
                self._redaction_values = tuple(set((*self._redaction_values, *audit_header_values(resolved))))

        guard()
        stages["configuration"]["status"] = "passed"
        current_stage = "handshake"
        client = TestClient(manifest, service.settings)
        client.credential_store = service.credentials
        client.suppress_payload_logging()
        observer = _TestOpener(client._opener, guard, result)
        client._opener = observer  # type: ignore[assignment]
        with client.operation_bounds(threading.Event(), deadline, credential_revisions=revisions):
            try:
                client.start()
                stages["http"]["status"] = "passed"
                stages["authentication"]["status"] = "passed"
                stages["handshake"]["status"] = "passed"
                result["protocol_version"] = client.protocol_version
                current_stage = "tools"
                result["tool_count"] = len(client.list_tools())
                guard()
                stages["tools"]["status"] = "passed"
                result.update(ok=True, status="success")
            finally:
                client.stop()
    except ToolExecutionError:
        # Revoked/expired management authority is not a downstream diagnostic.
        raise
    except Exception as exc:
        failure = exc
        if observer is not None and observer.responded:
            stages["http"]["status"] = "passed"
        code, stage = _failure_code(exc, current_stage, observer, deadline)
        stages[stage].update(status="failed", code=code)
        result.update(code=code, failed_stage=stage)
    finally:
        if client is not None:
            client._resolved_headers = {}
            client._redaction_values = ()
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        service._connection_tests.release()
        log_event(logger, logging.INFO, "gate.mcp.connection_test.completed", "HTTP MCP connection test completed",
            server_id=target, actor_id=context.actor_id, ok=result["ok"],
            failure_type=type(failure).__name__ if failure else None,
            code=result.get("code"), network_attempted=result["network_attempted"], elapsed_ms=result["elapsed_ms"])
    return result


class _TestOpener:
    """Observe only status/challenge type; never copy untrusted response content."""
    def __init__(self, opener: Any, guard: Any, result: dict[str, Any]) -> None:
        self.opener, self.guard, self.result = opener, guard, result
        self.responded = False
        self.status: int | None = None

    def open(self, request: Any, *, timeout: float) -> Any:
        self.guard()
        if request.get_method() == "DELETE":
            return self.opener.open(request, timeout=timeout)
        self.result["network_attempted"] = True
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            self.responded = True
            self.status = exc.code
            self.result["http_status"] = exc.code
            challenge = (exc.headers.get("WWW-Authenticate") or "")[:2048]
            match = re.match(r"^\s*(Bearer|Basic)\b", challenge, re.I)
            if match:
                self.result["auth_scheme"] = match[1].lower()
            self.result["oauth_advertised"] = bool(re.search(r'\bresource_metadata\s*=', challenge, re.I))
            raise
        self.responded = True
        self.status = response.status
        self.result["http_status"] = response.status
        return response


def _failure_code(exc: Exception, stage: str, observer: _TestOpener | None, deadline: float) -> tuple[str, str]:
    if isinstance(exc, _TestBlocked):
        return exc.code, "configuration"
    if isinstance(exc, CredentialRevisionConflict):
        return "credential_changed", "authentication"
    if isinstance(exc, CredentialUsageDenied):
        return "credential_scope_denied", "authentication"
    if isinstance(exc, (McpConfigConflict, McpHttpTrustConflict)):
        return "config_changed", "configuration"
    if isinstance(exc, KeyError):
        return "credential_unavailable", "authentication"
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLError) or isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, ssl.SSLError):
            return "tls_failed", "http"
        if isinstance(cause, TimeoutError):
            return "timeout", "http" if observer is None or not observer.responded else stage
        cause = cause.__cause__
    if time.monotonic() >= deadline:
        return "timeout", "http" if observer is None or not observer.responded else stage
    status = observer.status if observer else None
    if status == 401:
        return "authentication_required", "authentication"
    if status == 403:
        return "access_denied", "authentication"
    if status is not None and 300 <= status < 400:
        return "redirect_blocked", "http"
    if status in {404, 405, 429}:
        return {404: "endpoint_not_found", 405: "http_method_not_allowed", 429: "rate_limited"}[status], "http"
    if status is not None and status >= 500:
        return "upstream_failed", "http"
    if observer is not None and not observer.responded:
        return "network_failed", "http"
    return ("invalid_manifest" if stage == "configuration" else "mcp_protocol_failed"), stage

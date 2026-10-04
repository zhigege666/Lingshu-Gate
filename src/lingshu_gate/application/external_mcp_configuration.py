"""Confirmed external HTTP configuration; no builds, commands or trust writes."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.mcp_configuration import McpConfigurationService, _restore_redacted_endpoint
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.credential_refs import extract_credential_refs
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.operation_deadline import TimedLock, check_operation, operation_lock
from lingshu_gate.mcp_config_store import McpConfigConflict, McpConfigStore
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import PROTECTED_HTTP_HEADERS, McpServerManifest, validate_manifest_for_write
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import McpConfigSaveRequest
from lingshu_gate.project_delivery_mcp import IDEMPOTENCY_PATTERN, SHA256_PATTERN, ProjectDeliveryMcpService, _parse_input
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext

TERMINAL = {"success", "partial", "failed", "cancelled", "timed_out", "interrupted"}
_HEADER_REFERENCE = re.compile(r"^(?:(?:Bearer|Basic|Token) )?\$\{credential:[A-Za-z0-9_.-]+\}$")
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _error(code: str, message: str, *, operation_id: str | None = None) -> ToolExecutionError:
    return ToolExecutionError(code, message, next_action="Query the operation/configuration; correct the issue and review a new plan.",
                              details={"operation_id": operation_id} if operation_id else {})


@contextmanager
def _control_lock(lock: TimedLock) -> Iterator[None]:
    try:
        with operation_lock(lock, cancel=None, deadline=time.monotonic() + 5):
            yield
    except TimeoutError:
        raise ToolExecutionError("external_config_busy", "Configuration is busy; retry the read or plan.",
                                 retryable=True, next_action="Poll the existing operation; do not repeat an apply with a new key.") from None


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ExternalConfigPlanInput(_Input):
    mode: Literal["create", "update"]
    manifest: dict[str, Any]
    expected_config_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    connect: StrictBool = False
    refresh_tools: StrictBool = False
    probe: StrictBool = False
    probe_confirmed: StrictBool = False
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class ExternalConfigApplyInput(_Input):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    connect: StrictBool = False
    refresh_tools: StrictBool = False
    idempotency_key: str = Field(min_length=8, max_length=200, pattern=IDEMPOTENCY_PATTERN)
    confirmed: StrictBool


class ExternalConfigStatusInput(_Input):
    operation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    server_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    @model_validator(mode="after")
    def exactly_one_target(self) -> ExternalConfigStatusInput:
        if bool(self.operation_id) == bool(self.server_id):
            raise ValueError("Choose exactly one operation_id or server_id")
        return self


class ExternalConfigCancelInput(_Input):
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    idempotency_key: str = Field(min_length=8, max_length=200, pattern=IDEMPOTENCY_PATTERN)
    confirmed: StrictBool


class ExternalMcpConfigurationService:
    """One application workflow shared by HTTP and MCP adapters.

    Persist through McpConfigurationService, retain the existing idempotency
    journal and runtime/classification boundaries used by project delivery.
    """

    def __init__(self, *, settings: Settings, database: SQLiteDatabase, auth: AuthStore,
                 access: AccessControlStore, configs: McpConfigStore, runtime: McpRuntimeManager,
                 credentials: CredentialStore, configuration: McpConfigurationService,
                 delivery: ProjectDeliveryMcpService) -> None:
        self.settings, self.database, self.auth, self.access = settings, database, auth, access
        self.configs, self.runtime, self.credentials = configs, runtime, credentials
        self.configuration, self.delivery = configuration, delivery
        self._lock = threading.RLock()
        self._cancels: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        for row in self.database.query_all(
            "SELECT e.* FROM external_mcp_config_operations e JOIN mcp_idempotent_operations j ON j.id=e.id "
            "WHERE e.status IN ('queued','running','cancel_requested') OR j.status='pending'"
        ):
            self._interrupt_unfinished(str(row["id"]))

    def _interrupt_unfinished(self, operation_id: str) -> None:
        """Recheck under the writer transaction; never replay or alter a runtime."""
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT e.*,j.status AS journal_status FROM external_mcp_config_operations e "
                "JOIN mcp_idempotent_operations j ON j.id=e.id WHERE e.id=?", (operation_id,),
            ).fetchone()
            if row is None or (row["status"] in TERMINAL and row["journal_status"] != "pending"):
                return
            result = json.loads(row["result_json"])
            result.update(status="interrupted", terminal=True, config_applied=None,
                          connection_state="unknown", discovery_state="unknown",
                          requires_reconciliation=True, next_action="Reconcile this target and operation before any new apply.")
            connection.execute("UPDATE external_mcp_config_operations SET status='interrupted',result_json=?,updated_at=? WHERE id=?",
                               (_json(result), _now(), operation_id))
            error = _error("operation_interrupted", "Previous external operation completion is unknown.", operation_id=operation_id)
            connection.execute("UPDATE mcp_idempotent_operations SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='pending'",
                               (_json(error.to_payload()), _now(), operation_id))

    def _authorize(self, context: ToolInvocationContext, *, write: bool = False) -> None:
        if context.auth_type not in {"session", "token"}:
            raise _error("external_config_admin_required", "Use an administrator Console session or an explicitly scoped Gate API token; OAuth is not a management connection.")
        try:
            user = self.auth.get_user(context.actor_id)
        except KeyError:
            raise _error("external_config_admin_required", "An active Gate administrator is required.") from None
        if user["status"] != "active" or user["must_change_password"] or "admin" not in self.access.roles_for_user(context.actor_id):
            raise _error("external_config_admin_required", "An active Gate administrator is required.")
        ceilings = [set(context.permissions), set(self.access.permissions_for_user(context.actor_id))]
        if context.auth_type == "session":
            row = self.database.query_one("SELECT user_id,purpose,expires_at FROM auth_sessions WHERE id=?", (context.session_id,))
            try:
                live = bool(row and row["user_id"] == context.actor_id and row["purpose"] == "console"
                            and datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) > datetime.now(timezone.utc))
            except (TypeError, ValueError):
                live = False
            if not live:
                raise _error("external_config_session_invalid", "The management Console session is unavailable or expired.")
        if context.auth_type == "token":
            row = self.database.query_one("SELECT user_id,scopes_json,revoked_at,expires_at FROM api_tokens WHERE id=?", (context.token_id,))
            try:
                expired = bool(row is not None and row["expires_at"] and datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) <= datetime.now(timezone.utc))
            except (TypeError, ValueError):
                expired = True
            if (row is None or row["user_id"] != context.actor_id or row["revoked_at"] is not None
                    or expired):
                raise _error("external_config_token_invalid", "The management token is unavailable or expired.")
            ceilings.extend([set(context.scopes), set(json.loads(row["scopes_json"]))])
        if context.delegated_scopes is not None:
            ceilings.append(set(context.delegated_scopes))
        for permission in ("operations.manage",) + (("tools.invoke",) if write else ()):
            if any("*" not in ceiling and permission not in ceiling for ceiling in ceilings):
                raise _error("external_config_permission_denied", "The current management connection lacks the required control permission.")

    @staticmethod
    def _principal_digest(context: ToolInvocationContext) -> str:
        return _digest({"actor_id": context.actor_id, "auth_type": context.auth_type, "token_id": context.token_id,
                        "scopes": sorted(context.scopes), "delegated_scopes": context.delegated_scopes,
                        "session_id": context.session_id})

    def _config_digest(self, server_id: str) -> str | None:
        try:
            digest = self.configs.get_config(server_id).digest
            if digest is None:
                raise _error("config_digest_unavailable", "The saved configuration digest is unavailable.")
            return digest
        except KeyError:
            return None
        except (ValueError, OSError):
            raise _error("config_digest_unavailable", "The saved configuration cannot be read safely.") from None

    def _credential_revisions(self, manifest: McpServerManifest) -> dict[str, str]:
        refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
        try:
            return {ref: self.credentials.get_credential(ref).updated_at for ref in sorted(refs)}
        except (KeyError, OSError, RuntimeError):
            raise _error("external_config_credential_unavailable", "An existing managed credential binding is unavailable.") from None

    def _normalize(self, body: ExternalConfigPlanInput) -> McpServerManifest:
        data = dict(body.manifest)
        try:
            with _control_lock(self.configs.mutation_lock):
                previous = self.configs.load_manifest(str(data.get("id", ""))) if body.mode == "update" else None
                if previous is not None:
                    data = _restore_redacted_endpoint(data, previous)
                    data = self.configs._preserve_masked_env(data, previous.model_dump(mode="json", exclude={"manifest_path"}))
        except (KeyError, ValueError):
            raise _error("config_digest_conflict", "The update target is unavailable.") from None
        if len(_json(data).encode()) > 65536:
            raise _error("external_config_invalid", "External manifest exceeds the size limit.")
        data.setdefault("enabled", True)
        data.setdefault("auto_start", False)
        data.setdefault("startup_policy", "gate_start_v1")
        data.setdefault("timeout_seconds", 120)
        try:
            manifest = validate_manifest_for_write(data, http_trust_store=self.configs.http_trust_store)
            self.configs._validate_server_id(manifest.id)
        except ValueError:
            raise _error("external_config_invalid", "External manifest syntax or current HTTP trust is invalid; check the configuration precheck and separate administrator trust policy.") from None
        launch = manifest.launch.model_dump(exclude={"type"}, exclude_none=True)
        if (manifest.launch.type != "external" or manifest.transport.type != "streamable_http"
                or any(launch.values()) or manifest.roots or manifest.manifest_path
                or manifest.analysis or manifest.permissions):
            raise _error("external_config_invalid", "This entry accepts external HTTP configuration only; commands, local paths, build data and permission changes are not accepted.")
        if not 1 <= manifest.timeout_seconds <= 120:
            raise _error("external_config_invalid", "Connection timeouts must be between 1 and 120 seconds.")
        for name, value in manifest.transport.headers.items():
            if (not re.fullmatch(r"[A-Za-z0-9-]{1,128}", name) or name.lower() in PROTECTED_HTTP_HEADERS
                    or not _HEADER_REFERENCE.fullmatch(value)):
                raise _error("external_config_credential_reference_required", "HTTP headers accept existing managed credential references only; never submit secret values.")
        if previous is not None and previous.launch.type != "external":
            raise _error("external_config_invalid", "A managed workload cannot be replaced through the external configuration entry.")
        if manifest.user_credentials != (previous.user_credentials if previous else []):
            raise _error("external_config_credential_reference_required", "Keep existing personal credential slot declarations; configure new slots separately in Console.")
        self._credential_revisions(manifest)
        return manifest

    def plan(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = _parse_input(ExternalConfigPlanInput, arguments)
        self._authorize(context, write=body.probe)
        if body.refresh_tools and not body.connect:
            raise _error("external_config_invalid", "Tool refresh requires an explicitly requested connection.")
        if body.probe and not body.probe_confirmed:
            raise _error("confirmation_required", "Confirm the bounded remote connectivity probe separately.")
        if body.mode == "update" and not body.expected_config_digest:
            raise _error("config_digest_required", "Updates require the current saved configuration digest.")
        manifest = self._normalize(body)
        if body.connect and not manifest.enabled:
            raise _error("external_config_invalid", "An explicitly requested connection requires enabled=true.")
        actual = self._config_digest(manifest.id)
        if (body.mode == "create" and actual is not None) or (body.mode == "update" and actual != body.expected_config_digest):
            raise _error("config_digest_conflict", "The target configuration does not match the requested create/update state.")
        validation = validate_mcp_manifest(self.settings, self.configs, manifest.model_dump(mode="json", exclude={"manifest_path"}),
                                           expected_id=manifest.id if body.mode == "update" else None)
        checks = [{"name": item["name"], "severity": item["severity"], "message": item["message"]} for item in validation["checks"]]
        if not validation["ok"]:
            return {"status": "blocked", "validation": {"ok": False, "checks": checks}, "network_contacted": False}
        probe: dict[str, Any] = {"status": "not_requested", "network_contacted": False}
        if body.probe:
            client = StreamableHttpMcpClient(manifest, self.settings)
            try:
                with client.operation_bounds(threading.Event(), time.monotonic() + min(body.timeout_seconds, 30)):
                    client.start()
                    count = len(client.list_tools())
                probe = {"status": "reachable", "network_contacted": True, "tool_count": count, "registry_changed": False}
            except Exception:
                return {"status": "blocked", "validation": {"ok": False, "checks": checks},
                        "probe": {"status": "failed", "network_contacted": True}, "error_code": "external_config_probe_failed"}
            finally:
                client.stop()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self._authorize(context, write=body.probe)
        payload = {"mode": body.mode, "manifest": manifest.model_dump(mode="json", exclude={"manifest_path"}),
                   "manifest_digest": self.runtime._manifest_digest(manifest), "server_id": manifest.id,
                   "expected_config_digest": actual, "credential_revisions": self._credential_revisions(manifest),
                   "connect": body.connect, "refresh_tools": body.refresh_tools,
                   "timeout_seconds": body.timeout_seconds, "expires_at": expires}
        plan_id, digest = uuid4().hex, _digest(payload)
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Retain plans while the operation journal needs them; prune expired
            # orphans after its existing retention removes the operation.
            connection.execute("DELETE FROM external_mcp_config_plans WHERE expires_at<? AND NOT EXISTS "
                               "(SELECT 1 FROM external_mcp_config_operations e WHERE e.plan_id=external_mcp_config_plans.id)", (_now(),))
            count = connection.execute("SELECT count(*) FROM external_mcp_config_plans WHERE actor_id=? AND expires_at>=? AND consumed_by IS NULL", (context.actor_id, _now())).fetchone()[0]
            if count >= 16:
                raise _error("external_config_plan_limit", "Too many active plans; wait for an earlier plan to expire.")
            connection.execute("INSERT INTO external_mcp_config_plans VALUES(?,?,?,?,?,?,NULL,?)",
                               (plan_id, context.actor_id, self._principal_digest(context), digest, _json(payload), expires, _now()))
        return {"status": "ready", "plan_id": plan_id, "plan_digest": digest, "manifest_digest": payload["manifest_digest"],
                "server_id": manifest.id, "instance_id": manifest.id, "expected_config_digest": actual,
                "expires_at": expires, "validation": {"ok": True, "checks": checks}, "probe": probe,
                "manifest": {key: value for key, value in manifest.safe_dict().items() if key != "manifest_path"},
                "connect": body.connect, "refresh_tools": body.refresh_tools,
                "timeout_seconds": body.timeout_seconds, "remote_process_started": False,
                "replaces_current_connection": body.mode == "update", "effective_permissions_expanded": False}

    def apply(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = _parse_input(ExternalConfigApplyInput, arguments)
        self._authorize(context, write=True)
        if not body.confirmed:
            raise _error("confirmation_required", "Confirm the exact external configuration and connection plan.")
        operation_id, replay = self.delivery._reserve_operation(context, "gate_mcp_config_apply", body.idempotency_key, arguments)
        if isinstance(replay, dict):
            return replay
        if isinstance(replay, ToolExecutionError):
            if replay.code == "operation_in_progress":
                try:
                    return {**self.status({"operation_id": operation_id}, context), "idempotent_replay": True}
                except ToolExecutionError as missing:
                    if missing.code == "external_config_operation_unavailable":
                        raise replay from None
                    raise
            raise replay
        try:
            with _control_lock(self._lock), self.database.session() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if len(self._threads) >= 4:
                    raise _error("external_config_busy", "External configuration queue is full; query existing operations before retrying.")
                row = connection.execute("SELECT * FROM external_mcp_config_plans WHERE id=? AND actor_id=?", (body.plan_id, context.actor_id)).fetchone()
                if row is None or row["digest"] != body.plan_digest or row["principal_digest"] != self._principal_digest(context):
                    raise _error("external_config_plan_conflict", "The plan is unavailable for this management connection.", operation_id=operation_id)
                if row["expires_at"] <= _now() or row["consumed_by"] is not None:
                    raise _error("external_config_plan_expired", "This plan is expired or already consumed; review a new plan.", operation_id=operation_id)
                plan = json.loads(row["plan_json"])
                if _digest(plan) != row["digest"]:
                    raise _error("external_config_plan_conflict", "Stored plan integrity is invalid.", operation_id=operation_id)
                if (body.connect, body.refresh_tools) != (plan["connect"], plan["refresh_tools"]):
                    raise _error("external_config_plan_conflict", "Requested actions differ from the reviewed plan.", operation_id=operation_id)
                initial = {"status": "queued", "operation_id": operation_id, "correlation_id": context.correlation_id,
                           "server_id": plan["server_id"], "instance_id": plan["server_id"], "config_applied": False,
                           "config_digest": None, "connection_state": "queued" if body.connect else "not_requested",
                           "discovery_state": "queued" if body.connect else "not_requested", "terminal": False,
                           "remote_process_started": False, "effective_permissions_expanded": False,
                           "poll_after_ms": 500}
                connection.execute("UPDATE external_mcp_config_plans SET consumed_by=? WHERE id=? AND consumed_by IS NULL", (operation_id, body.plan_id))
                connection.execute("INSERT INTO external_mcp_config_operations(id,plan_id,actor_id,status,result_json,updated_at) VALUES(?,?,?,?,?,?)",
                                   (operation_id, body.plan_id, context.actor_id, "queued", _json(initial), _now()))
                cancel = self._cancels[operation_id] = threading.Event()
                thread = threading.Thread(target=self._run, args=(operation_id, plan, context, cancel, time.monotonic() + plan["timeout_seconds"], initial), daemon=True, name="gate-external-config")
                self._threads[operation_id] = thread
            thread.start()
            return initial
        except ToolExecutionError as exc:
            self.delivery._fail_operation(operation_id, exc)
            raise
        except Exception:
            with self._lock:
                self._cancels.pop(operation_id, None)
                self._threads.pop(operation_id, None)
            self.database.execute("UPDATE external_mcp_config_operations SET status='failed',result_json=?,updated_at=? WHERE id=?",
                (_json({"status": "failed", "operation_id": operation_id, "config_applied": False,
                        "connection_state": "not_connected", "discovery_state": "not_requested", "terminal": True,
                        "error_code": "external_config_queue_failed", "remote_process_started": False}), _now(), operation_id))
            self.delivery._fail_operation(operation_id, _error("external_config_apply_failed", "The external operation could not be queued.", operation_id=operation_id))
            raise _error("external_config_apply_failed", "The external operation could not be queued.", operation_id=operation_id) from None

    def _progress(self, operation_id: str, result: dict[str, Any]) -> None:
        self.database.execute("UPDATE external_mcp_config_operations SET status=?,result_json=?,updated_at=? WHERE id=?",
                              (result["status"], _json(result), _now(), operation_id))

    def _check(self, context: ToolInvocationContext, cancel: threading.Event, deadline: float) -> None:
        check_operation(cancel, deadline)
        self._authorize(context, write=True)
        check_operation(cancel, deadline)

    def _run(self, operation_id: str, plan: dict[str, Any], context: ToolInvocationContext, cancel: threading.Event, deadline: float,
             initial: dict[str, Any]) -> None:
        result = dict(initial)
        result["status"] = "running"
        loaded = False
        runtime_applying = False
        try:
            self._progress(operation_id, result)
            with operation_lock(self.configs.mutation_lock, cancel=cancel, deadline=deadline):
                self._check(context, cancel, deadline)
                manifest = validate_manifest_for_write(plan["manifest"], http_trust_store=self.configs.http_trust_store)
                if self._credential_revisions(manifest) != plan["credential_revisions"]:
                    raise _error("external_config_credential_changed", "Managed credential bindings changed after planning.")
                if self._config_digest(manifest.id) != plan["expected_config_digest"]:
                    raise McpConfigConflict("Configuration changed after planning")
                request = McpConfigSaveRequest(manifest=plan["manifest"], apply=False, start=False,
                                               expected_config_digest=plan["expected_config_digest"])
                prepared = self.configuration.prepare_user_credentials(request, existing_server_id=manifest.id if plan["mode"] == "update" else None)
                if plan["mode"] == "create":
                    self.configuration.create(request, user_id=context.actor_id, prepared=prepared)
                else:
                    self.configuration.update(manifest.id, request, user_id=context.actor_id, prepared=prepared)
                result.update(config_applied=True, config_digest=self._config_digest(manifest.id))
                self._progress(operation_id, result)
                self._check(context, cancel, deadline)
                runtime_applying = True
                self.runtime.apply_external_configuration(self.configs.load_manifest(manifest.id), cancel=cancel, deadline=deadline,
                                                          before_apply=lambda: self._check(context, cancel, deadline))
                loaded = True
                runtime_applying = False
                if plan["connect"]:
                    result["connection_state"] = "connecting"
                    self._progress(operation_id, result)
                    reconciliation: dict[str, Any] = {}
                    def reconcile(definitions: list[Any]) -> None:
                        self._check(context, cancel, deadline)
                        reconciliation.clear()
                        reconciliation.update(self.access.reconcile_server_tools(manifest.id, definitions, context.actor_id))
                    server = self.runtime.connect_external_if_manifest_digest(manifest.id, plan["manifest_digest"], cancel=cancel, deadline=deadline,
                        operation_id=operation_id, before_connect=lambda: self._check(context, cancel, deadline), before_replace=reconcile)
                    if server.status != "running":
                        self._check(context, cancel, deadline)
                        raise _error("external_config_connect_failed", "Configuration saved; the external connection did not become ready.")
                    result.update(connection_state="connected", discovery_state="succeeded", tool_count=server.tool_count,
                                  counts=reconciliation["counts"],
                                  classification_state="needs_review" if reconciliation["counts"]["needs_review"] else "ready")
                    self._progress(operation_id, result)
                    self._check(context, cancel, deadline)
                    if plan["refresh_tools"]:
                        result["discovery_state"] = "refreshing"
                        self._progress(operation_id, result)
                        refreshed = self.runtime.refresh_server_tools(manifest.id, before_replace=reconcile, cancel=cancel, deadline=deadline,
                            before_discovery=lambda: self._check(context, cancel, deadline))
                        result.update(tool_snapshot_digest=refreshed["tool_snapshot_digest"],
                                      counts=reconciliation["counts"],
                                      discovery_state="succeeded",
                                      classification_state="needs_review" if reconciliation["counts"]["needs_review"] else "ready")
                self._check(context, cancel, deadline)
                result["status"] = "success"
        except InterruptedError:
            result.update(status="cancelled", error_code="external_config_cancelled")
            result["discovery_state"] = "cancelled"
        except TimeoutError:
            result.update(status="timed_out", error_code="external_config_timeout")
            if result["connection_state"] != "connected":
                result["connection_state"] = "timed_out"
            if result["discovery_state"] != "succeeded":
                result["discovery_state"] = "timed_out"
        except Exception as exc:
            code = exc.code if isinstance(exc, ToolExecutionError) else "config_digest_conflict" if isinstance(exc, McpConfigConflict) else "external_config_apply_failed"
            result.update(status="partial" if result.get("config_applied") else "failed", error_code=code)
            if time.monotonic() >= deadline:
                result.update(status="timed_out", error_code="external_config_timeout")
            if result["connection_state"] in {"queued", "connecting"}:
                result["connection_state"] = "failed"
            if result["discovery_state"] in {"queued", "refreshing"}:
                result["discovery_state"] = "failed"
        finally:
            if runtime_applying and not loaded:
                result.update(connection_state="unknown", discovery_state="unknown", requires_reconciliation=True)
            if result["status"] != "success" and loaded:
                try:
                    closed = self.runtime.disconnect_external_operation(plan["server_id"], plan["manifest_digest"], operation_id,
                                                                       deadline=time.monotonic() + 5)
                    result["cleanup_state"] = "disconnected" if closed else "superseded"
                    if closed and (result["connection_state"] == "connected" or result["status"] == "cancelled"):
                        result["connection_state"] = "disconnected"
                    elif not closed:
                        result.update(connection_state="superseded", requires_reconciliation=True)
                except Exception:
                    result.update(connection_state="unknown", cleanup_state="unknown", requires_reconciliation=True)
            elif result["status"] == "cancelled":
                result["connection_state"] = "not_connected"
            result.update(terminal=True, next_action=("Review and publish tool classifications separately; discovery grants no access."
                          if result["status"] == "success" else "Read the saved configuration and operation; use an update plan with its current digest for recovery."))
            try:
                with self.database.session() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute("UPDATE external_mcp_config_operations SET status=?,result_json=?,updated_at=? WHERE id=?",
                                       (result["status"], _json(result), _now(), operation_id))
                    self.delivery._complete_operation(operation_id, result=result, resource_type="mcp_config",
                                                      resource_id=plan["server_id"], connection=connection)
                self.delivery.observability.emit_event("gate.mcp.external_config.completed", source="configs", subject_type="config",
                    subject_id=plan["server_id"], payload={"actor_id": context.actor_id, "operation_id": operation_id,
                    "status": result["status"], "config_applied": result["config_applied"],
                    "connection_state": result["connection_state"], "discovery_state": result["discovery_state"]})
            except Exception:
                # No peer messages, URLs, credential values or tracebacks here.
                # Status/startup reconciles an unfinished journal conservatively.
                logger.error("External operation finalization unavailable; reconcile operation_id=%s", operation_id)
            finally:
                with self._lock:
                    self._cancels.pop(operation_id, None)
                    self._threads.pop(operation_id, None)

    def status(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = _parse_input(ExternalConfigStatusInput, arguments)
        self._authorize(context)
        if body.server_id is not None:
            with _control_lock(self.configs.mutation_lock):
                try:
                    config = self.configs.get_config(body.server_id)
                    manifest = self.configs.load_manifest(body.server_id)
                except (KeyError, ValueError):
                    raise _error("external_config_target_unavailable", "The saved external configuration is unavailable.") from None
                if manifest.launch.type != "external":
                    raise _error("external_config_target_unavailable", "Use the workload delivery entry for this target.")
                manifest_digest = self.runtime._manifest_digest(manifest)
                try:
                    runtime, runtime_digest = self.runtime.external_configuration_status(body.server_id, deadline=time.monotonic() + 5)
                except TimeoutError:
                    raise _error("external_config_busy", "Runtime is busy; poll the operation before querying the target.") from None
                matches = bool(runtime and runtime_digest == manifest_digest)
                return {"status": "configured", "server_id": body.server_id, "instance_id": body.server_id,
                        "config_digest": config.digest, "config_revision": config.digest,
                        "manifest_digest": manifest_digest,
                        "manifest": {key: value for key, value in config.manifest.items() if key != "manifest_path"},
                        "connection_state": "not_loaded" if runtime is None else "stale_config" if not matches else "connected" if runtime.status == "running" else "disconnected",
                        "discovery_state": "not_observed", "remote_process_started": False,
                        "effective_permissions_expanded": False}
        row = self.database.query_one("SELECT result_json,cancel_requested FROM external_mcp_config_operations WHERE id=? AND actor_id=?",
                                      (body.operation_id, context.actor_id))
        if row is None:
            raise _error("external_config_operation_unavailable", "Operation is unavailable for this actor.")
        result = json.loads(row["result_json"])
        if not result.get("terminal"):
            with _control_lock(self._lock):
                worker = self._threads.get(str(body.operation_id))
                lost_worker = worker is None or (worker.ident is not None and not worker.is_alive())
            if lost_worker:
                self._interrupt_unfinished(str(body.operation_id))
                row = self.database.query_one("SELECT result_json,cancel_requested FROM external_mcp_config_operations WHERE id=? AND actor_id=?",
                                              (body.operation_id, context.actor_id))
                if row is None:
                    raise _error("external_config_operation_unavailable", "Operation is unavailable for this actor.")
        return {**json.loads(row["result_json"]), "cancel_requested": bool(row["cancel_requested"])}

    def cancel(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = _parse_input(ExternalConfigCancelInput, arguments)
        self._authorize(context, write=True)
        if not body.confirmed:
            raise _error("confirmation_required", "Confirm cancellation; any saved configuration remains.")
        def action(cancel_operation_id: str) -> tuple[dict[str, Any], str]:
            current = self.status({"operation_id": body.operation_id}, context)
            with _control_lock(self._lock):
                if not current["terminal"]:
                    self.database.execute("UPDATE external_mcp_config_operations SET cancel_requested=1 WHERE id=? AND actor_id=?",
                                          (body.operation_id, context.actor_id))
                    event = self._cancels.get(body.operation_id)
                    if event is not None:
                        event.set()
            return {"operation_id": cancel_operation_id, "target_operation_id": body.operation_id,
                    "status": "already_terminal" if current["terminal"] else "cancel_requested",
                    "terminal": current["terminal"], "next_action": "Poll the target operation; in-flight HTTP ends within its request deadline. Saved configuration is retained."}, body.operation_id
        return self.delivery._run_idempotent(context, "gate_mcp_config_cancel", body.idempotency_key, arguments, "mcp_config_operation", action)

    def shutdown(self) -> None:
        """Request cancellation only for this process's outstanding operations."""
        with self._lock:
            for cancel in self._cancels.values():
                cancel.set()

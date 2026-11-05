"""One reviewable save for a configuration and its staged HTTP credential.

Files and SQLite have no shared transaction. Preflight precedes writes; a durable
receipt prevents repeated activation and exposes partial completion explicitly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.application.shared_credentials import SharedCredentialService, credential_context
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.credential_refs import extract_credential_refs
from lingshu_gate.credential_store import canonical_http_origin
from lingshu_gate.domain.http_mcp_management import McpConfigCredentialSaveRequest
from lingshu_gate.domain.mcp_configuration_errors import McpConfigPartialError
from lingshu_gate.registry import ToolExecutionError

OPERATION = "console_config_credential_save"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConfigurationCredentialSaveError(RuntimeError):
    def __init__(self, detail: dict[str, Any], status: int = 409) -> None:
        super().__init__(detail["message"])
        self.detail, self.status = detail, status


class ConfigurationCredentialService:
    def __init__(self, configuration: McpConfigurationService, shared: SharedCredentialService) -> None:
        self.configuration, self.shared = configuration, shared

    def save(self, request: McpConfigCredentialSaveRequest, principal: AuthPrincipal) -> dict[str, Any]:
        shared, write = self.shared, request.credential_write
        context = credential_context(principal)
        action = "create" if write.kind == "create" else "update"
        # Replays use the same live authority checks as a new write.
        shared._authorize(context, tool_id=f"gate_credential_{action}", credential_id=write.credential_id,
                          action=f"credential.{action}", write=True)
        actor = shared._current_actor(context)
        if not shared.access.has_control_permission(actor, "operations.manage"):
            raise ToolExecutionError("credential_permission_denied", "Configuration management permission is required.")
        fingerprint = shared.credentials.request_fingerprint({"request": request.model_dump(mode="json"),
            "user_credential_values": request.user_credential_values,
            "connection": {"type": context.auth_type, "session_id": context.session_id, "token_id": context.token_id}})
        server_id = str(request.manifest.get("id", ""))
        with shared.configs.mutation_lock:
            operation_id, replay = self._reserve(principal.id, request.idempotency_key, fingerprint, server_id)
            if replay is not None:
                return {**replay, "idempotent_replay": True}
            credential_saved: bool | str = False
            config_attempted = False
            config_completed = False
            response = None
            before_digest: str | None = None
            try:
                with shared.credentials.mutation_guard():
                    if request.existing_server_id:
                        current = shared.configs.get_config(request.existing_server_id)
                        before_digest = current.digest
                        if current.id != server_id or current.digest != request.expected_config_digest:
                            raise ValueError("config_revision_conflict")
                    else:
                        try:
                            shared.configs.get_config(server_id)
                        except KeyError:
                            pass
                        else:
                            raise ValueError("config_exists")
                    plan = self.configuration.plan_http_save(request.manifest, existing_server_id=request.existing_server_id,
                        action=request.http_trust_action, expected_revision=request.expected_http_trust_revision)
                    prepared = self.configuration.prepare_user_credentials(request, existing_server_id=request.existing_server_id,
                        http_trust_plan=plan, staged_credential_id=write.credential_id)
                    manifest = prepared.manifest
                    refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
                    if (manifest.transport.type != "streamable_http" or write.credential_id not in refs
                            or write.target.server_id != server_id
                            or canonical_http_origin(write.target.origin) != canonical_http_origin(manifest.transport.endpoint or "")):
                        raise ValueError("credential_target_changed")
                    if request.start and (not manifest.enabled or plan is not None and not plan["connection_allowed"]):
                        raise ValueError("configuration_cannot_start")
                    # Recheck trust CAS before creating a credential. The config
                    # writer repeats this check immediately before persistence.
                    if plan is not None and shared.configs.http_trust_store is not None:
                        shared.configs.http_trust_store.check_plan(plan)
                        if plan["change"] in {"authorize", "retire"}:
                            shared.configs.http_trust_store.require_admin(principal.id)
                    arguments: dict[str, Any] = {"credential_id": write.credential_id, "idempotency_key": operation_id}
                    if write.kind == "create":
                        if not write.name.strip() or write.value == "***" or "\r" in write.value or "\n" in write.value:
                            raise ValueError("invalid_http_credential")
                        shared.create({**arguments, "name": write.name.strip(), "value": write.value,
                                       "http_scopes": [write.target.model_dump()]}, context)
                    else:
                        shared.update({**arguments, "expected_revision": write.expected_revision,
                                       "expected_http_scopes_revision": write.expected_http_scopes_revision,
                                       "authorize_http_target": write.target.model_dump()}, context)
                    credential_saved = True
                # Never hold the credential writer barrier while runtime startup
                # dispatches HTTP on another thread. Config writers retain order.
                config_attempted = True
                if request.existing_server_id:
                    response = self.configuration.update(request.existing_server_id, request, user_id=principal.id,
                                                         prepared=prepared, http_trust_plan=plan)
                else:
                    response = self.configuration.create(request, user_id=principal.id, prepared=prepared, http_trust_plan=plan)
                config_completed = True
                if request.start and (response.server is None or response.server.status != "running"):
                    raise RuntimeError("Runtime activation was not confirmed")
                result = {**response.model_dump(mode="json"), "operation_id": operation_id, "credential_saved": True,
                          "credential_id": write.credential_id, "idempotent_replay": False}
                # Runtime errors may be represented by a server status instead of
                # an exception; retain that result without claiming a connection.
                shared.observability.emit_event("gate.config.credential_saved", source="configs",
                    subject_type="config", subject_id=server_id,
                    payload={"actor_id": principal.id, "operation_id": operation_id, "credential_id": write.credential_id,
                             "action": action, "apply": request.apply, "start": request.start,
                             "runtime_status": response.server.status if response.server else None})
                shared.database.execute("UPDATE mcp_idempotent_operations SET status='succeeded',result_json=?,updated_at=? WHERE id=?",
                                        (json.dumps(result), _now(), operation_id))
                return result
            except Exception as exc:
                if isinstance(exc, ToolExecutionError) and exc.details.get("credential_mutated"):
                    credential_saved = exc.details["credential_mutated"]
                config_saved: bool | str = False
                config_digest: str | None = None
                if config_attempted:
                    try:
                        config_digest = shared.configs.get_config(server_id).digest
                        config_saved = config_completed or config_digest != before_digest or isinstance(exc, McpConfigPartialError)
                    except KeyError:
                        pass
                    except Exception:
                        config_saved = "unknown"
                partial = credential_saved is not False or config_saved is not False
                detail = {"code": "mcp_config_credential_partial" if partial else "mcp_config_credential_rejected",
                    "message": "The credential/configuration save did not complete. Review the saved state before retrying."
                    if partial else "The credential/configuration save was rejected before changes. Check the target, permissions and current revisions.",
                    "operation_id": operation_id, "server_id": server_id, "credential_id": write.credential_id,
                    "credential_saved": credential_saved, "config_saved": config_saved, "config_digest": config_digest,
                    "runtime_state": (response.server.status if response is not None and response.server is not None else "unknown")
                    if config_attempted and request.apply else "unchanged",
                    "requires_reconciliation": partial,
                    "cause": exc.code if isinstance(exc, ToolExecutionError) else type(exc).__name__,
                    "next_action": "Read the configuration, credential and service state; reopen using current revisions."
                    if partial else "Correct the draft or reload current revisions before a new save."}
                try:
                    shared.database.execute("UPDATE mcp_idempotent_operations SET status='failed',error_json=?,updated_at=? WHERE id=?",
                                            (json.dumps(detail), _now(), operation_id))
                except Exception:
                    # The pending receipt still prevents a blind repeat.
                    detail["requires_reconciliation"] = True
                raise ConfigurationCredentialSaveError(detail) from None

    def _reserve(self, actor: str, key: str, fingerprint: str, server_id: str) -> tuple[str, dict[str, Any] | None]:
        with self.shared.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM mcp_idempotent_operations WHERE actor_id=? AND tool_id=? AND idempotency_key=?",
                                     (actor, OPERATION, key)).fetchone()
            if row is not None:
                if row["request_digest"] != fingerprint:
                    raise ConfigurationCredentialSaveError({"code": "idempotency_conflict", "message": "This operation key belongs to a different save."})
                if row["status"] == "succeeded":
                    return str(row["id"]), json.loads(row["result_json"])
                if row["status"] == "failed":
                    raise ConfigurationCredentialSaveError(json.loads(row["error_json"]))
                raise ConfigurationCredentialSaveError({"code": "mcp_config_credential_pending", "message": "The previous save is pending or was interrupted. Read its current state before another save.",
                    "operation_id": row["id"], "requires_reconciliation": True,
                    "next_action": "Read the configuration, credential and service state before reopening the editor."})
            operation_id = uuid4().hex
            connection.execute("INSERT INTO mcp_idempotent_operations (id,actor_id,tool_id,idempotency_key,request_digest,status,resource_type,resource_id,created_at,updated_at) "
                               "VALUES(?,?,?,?,?,'pending','config_credential_save',?,?,?)",
                               (operation_id, actor, OPERATION, key, fingerprint, server_id, _now(), _now()))
            return operation_id, None

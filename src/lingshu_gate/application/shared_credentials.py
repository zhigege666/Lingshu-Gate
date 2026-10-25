"""Shared system credentials: one authorized workflow for Console and MCP."""
from __future__ import annotations

import json
import sqlite3
import builtins
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.credential_refs import extract_credential_refs
from lingshu_gate.credential_store import (
    CredentialAlreadyExists, CredentialPersistenceInterrupted, CredentialRevisionConflict, CredentialStore,
    CredentialUsageDenied, canonical_http_origin,
)
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.mcp_authorization_policy import server_binding
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.models import CredentialHttpScope, CredentialResponse
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.oauth_server import OAuthError
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext

ID_PATTERN = r"^[A-Za-z0-9_.-]+$"
WRITE_TOOLS = ("gate_credential_create", "gate_credential_update", "gate_credential_delete")


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class CredentialListInput(CredentialInput):
    pass


class CredentialGetInput(CredentialInput):
    credential_id: str = Field(min_length=1, max_length=512, pattern=ID_PATTERN)


class CredentialCreateInput(CredentialInput):
    credential_id: str | None = Field(default=None, min_length=1, max_length=512, pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=65536, repr=False)
    description: str = Field(default="", max_length=4096)
    http_scopes: list[CredentialHttpScope] = Field(default_factory=list, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=128)


class CredentialUpdateInput(CredentialGetInput):
    expected_revision: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=256)
    value: str | None = Field(default=None, min_length=1, max_length=65536, repr=False)
    description: str | None = Field(default=None, max_length=4096)
    http_scopes: list[CredentialHttpScope] | None = Field(default=None, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=128)


class CredentialDeleteInput(CredentialGetInput):
    expected_revision: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _error(code: str, message: str, **details: Any) -> ToolExecutionError:
    return ToolExecutionError(code, message, details=details)


def credential_context(principal: AuthPrincipal) -> ToolInvocationContext:
    """Carry authenticated proof, never the bearer or credential value."""
    return ToolInvocationContext(actor_id=principal.id, username=principal.username, auth_type=principal.auth_type,
        token_id=principal.token_id, correlation_id=uuid4().hex, roles=principal.roles, permissions=principal.permissions,
        scopes=principal.scopes, delegated_scopes=principal.delegated_scopes, session_id=principal.session_id,
        oauth_builtin=principal.oauth_builtin, oauth_issuer=principal.oauth_issuer, oauth_resource=principal.oauth_resource,
        oauth_client_id=principal.oauth_client_id, oauth_grant_id=principal.external_grant_id,
        oauth_family_id=principal.oauth_family_id, oauth_token_expires_at=principal.oauth_token_expires_at,
        oauth_target_revision=principal.oauth_target_revision, oauth_tool_snapshots=principal.oauth_tool_snapshots)


class SharedCredentialService:
    def __init__(self, *, database: SQLiteDatabase, auth: AuthStore, access: AccessControlStore,
                 credentials: CredentialStore, configs: McpConfigStore,
                 observability: ObservabilityStore) -> None:
        self.database, self.auth, self.access = database, auth, access
        self.credentials, self.configs, self.observability = credentials, configs, observability
        self._migrate_legacy()
        # A file write and SQLite receipt are not a distributed transaction.
        # Restart never retries a pending mutation whose completion is unknown.
        interrupted = _error("credential_operation_interrupted", "Previous credential operation completion is unknown.",
            requires_reconciliation=True).to_payload()
        self.database.execute("UPDATE mcp_idempotent_operations SET status='failed',error_json=?,updated_at=? "
            "WHERE status='pending' AND resource_type='shared_credential'", (_json(interrupted), _now()))

    @staticmethod
    def _parse(model: type[BaseModel], arguments: dict[str, Any]) -> Any:
        try:
            return model.model_validate(arguments)
        except (ValidationError, ValueError, TypeError, RecursionError):
            raise _error("credential_request_invalid", "Check the declared credential fields and current revision.") from None

    def _authorize(self, context: ToolInvocationContext, *, tool_id: str = "gate_credential_list",
                   credential_id: str | None = None, action: str = "credential.read", write: bool = False) -> None:
        if context.auth_type == "oauth":
            if self.auth.builtin_oauth is None or not context.oauth_builtin:
                raise _error("credential_permission_denied", "A separately authorized management connection is required.")
            try:
                self.auth.builtin_oauth.management_authority(context, tool_id, write=write,
                    target_id=credential_id, action=action)
            except (OAuthError, HTTPException, ValueError, KeyError, TypeError):
                raise _error("credential_permission_denied", "The live management grant does not allow this credential action.") from None
            return
        actor = self._current_actor(context)
        if "admin" not in actor.roles:
            raise _error("credential_permission_denied", "An active system credential administrator is required.")
        required = {"credentials.manage.system"} | ({"tools.invoke"} if write else set())
        # The admin role does not bypass a removed live control permission or
        # the token/delegation ceilings.
        if any(permission not in actor.permissions and "*" not in actor.permissions
               or not self.access.has_control_permission(actor, permission) for permission in required):
            raise _error("credential_permission_denied", "The current connection lacks the required credential permission.")

    def _current_actor(self, context: ToolInvocationContext) -> AuthPrincipal:
        actor = AuthPrincipal(id=context.actor_id, username=context.username,
            role=context.roles[0] if context.roles else "viewer", roles=context.roles, auth_type=context.auth_type,
            token_id=context.token_id, permissions=context.permissions, scopes=context.scopes,
            delegated_scopes=context.delegated_scopes, session_id=context.session_id)
        try:
            return current_tool_principal(self.auth, actor)
        except McpGroupError:
            raise _error("credential_permission_denied", "The current credential management connection is unavailable.") from None

    def list(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        self._parse(CredentialListInput, arguments)
        self._authorize(context)
        visible = []
        for credential in self.credentials.list_credentials():
            try:
                self._authorize(context, tool_id="gate_credential_list", credential_id=credential.id)
            except ToolExecutionError:
                continue
            visible.append(credential.model_dump(mode="json"))
        return {"credentials": visible}

    def get(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = self._parse(CredentialGetInput, arguments)
        self._authorize(context, tool_id="gate_credential_get", credential_id=body.credential_id)
        try:
            result = self.credentials.get_credential(body.credential_id).model_dump(mode="json")
            result["dependencies"] = self._visible_dependencies(self._dependencies(body.credential_id), context)
            return result
        except KeyError:
            raise _error("credential_unavailable", "The credential is unavailable.") from None

    def create(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = self._parse(CredentialCreateInput, arguments)
        credential_id = body.credential_id or self.credentials._make_id(body.name)
        def mutate() -> CredentialResponse:
            return self.credentials.create_credential(credential_id=credential_id, name=body.name, value=body.value,
                description=body.description, http_scopes=self._scopes(body.http_scopes))
        return self._run(context, "gate_credential_create", "credential.create", credential_id,
                         body.model_dump(mode="json"), mutate, value_saved=True)

    def update(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = self._parse(CredentialUpdateInput, arguments)
        def mutate() -> CredentialResponse:
            return self.credentials.update_credential(body.credential_id, expected_revision=body.expected_revision,
                name=body.name, value=body.value, description=body.description,
                http_scopes=self._scopes(body.http_scopes) if body.http_scopes is not None else None)
        return self._run(context, "gate_credential_update", "credential.update", body.credential_id,
                         body.model_dump(mode="json"), mutate, value_saved=body.value is not None)

    def delete(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        body = self._parse(CredentialDeleteInput, arguments)
        def mutate() -> CredentialResponse:
            current = self.credentials.get_credential(body.credential_id)
            if current.updated_at != body.expected_revision:
                raise CredentialRevisionConflict("Credential revision changed.")
            dependencies = self._dependencies(body.credential_id)
            if dependencies:
                visible = self._visible_dependencies(dependencies, context)
                raise _error("credential_in_use", "Detach the credential from its consumers before deleting it.",
                             dependencies=visible)
            return self.credentials.delete_credential(body.credential_id, expected_revision=body.expected_revision)
        return self._run(context, "gate_credential_delete", "credential.delete", body.credential_id,
                         body.model_dump(mode="json"), mutate, value_saved=False)

    def _scopes(self, scopes: builtins.list[CredentialHttpScope]) -> builtins.list[dict[str, Any]]:
        result, seen = [], set()
        for scope in scopes:
            if urlsplit(scope.origin).path not in {"", "/"}:
                raise CredentialUsageDenied("Credential scope must be an origin, without a path.")
            origin = canonical_http_origin(scope.origin)
            key = (scope.server_id, origin)
            if key in seen:
                raise CredentialUsageDenied("Duplicate credential HTTP scope.")
            seen.add(key)
            if scope.server_binding is not None:
                manifest = self.configs.load_manifest(scope.server_id)
                if manifest.transport.type != "streamable_http" or canonical_http_origin(manifest.transport.endpoint or "") != origin:
                    raise CredentialUsageDenied("Saved service does not match the requested scope.")
                with self.database.session() as connection:
                    if server_binding(connection, scope.server_id) != scope.server_binding:
                        raise CredentialUsageDenied("Saved service identity changed.")
            # None is an explicit pending grant for precisely this service and
            # origin. Only configuration save can consume it into a generation.
            result.append({"server_id": scope.server_id, "origin": origin, "server_binding": scope.server_binding})
        return sorted(result, key=lambda item: (str(item["server_id"]), str(item["origin"])))

    def _migrate_legacy(self) -> None:
        scopes: dict[str, list[dict[str, Any]]] = {}
        with self.configs.mutation_lock, self.credentials.mutation_guard():
            for config in self.configs.list_configs().configs:
                try:
                    if config.id in getattr(self.configs, "invalidated_startup_identities", set()):
                        continue
                    manifest = self.configs.load_manifest(config.id)
                    if manifest.transport.type != "streamable_http" or not manifest.transport.endpoint:
                        continue
                    if self.configs.http_trust_store is None:
                        continue
                    self.configs.http_trust_store.require_endpoint(manifest.id, manifest.transport.endpoint)
                    origin = canonical_http_origin(manifest.transport.endpoint)
                    with self.database.session() as connection:
                        binding = server_binding(connection, manifest.id)
                    refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
                    for ref in refs:
                        scopes.setdefault(ref, []).append({"server_id": manifest.id, "origin": origin, "server_binding": binding})
                except (KeyError, ValueError, OSError):
                    continue
            self.credentials.migrate_legacy_http_scopes(scopes)

    def _dependencies(self, credential_id: str) -> builtins.list[dict[str, str]]:
        dependencies: list[dict[str, str]] = []
        configs = self.configs.list_configs()
        if configs.errors:
            raise _error("credential_dependencies_unavailable", "Repair unreadable configurations before deleting credentials.")
        for config in configs.configs:
            manifest = self.configs.load_manifest(config.id)
            if credential_id in extract_credential_refs(_json(manifest.model_dump(mode="json"))):
                dependencies.append({"type": "mcp_server", "id": config.id,
                    "transport": manifest.transport.type})
        for row in self.database.query_all("SELECT DISTINCT v.profile_id FROM network_profile_versions v "
            "JOIN network_profiles p ON p.id=v.profile_id WHERE v.credential_ref=? AND "
            "((p.deleted=0 AND p.revision=v.version) OR EXISTS (SELECT 1 FROM network_profile_references r "
            "WHERE r.profile_id=v.profile_id AND r.version=v.version))", (credential_id,)):
            dependencies.append({"type": "network_profile", "id": str(row["profile_id"])})
        settings_row = self.database.query_one("SELECT settings_json FROM delivery_network_settings WHERE id=1")
        if settings_row and self._contains_reference(json.loads(settings_row["settings_json"]), credential_id):
            dependencies.append({"type": "network_settings", "id": "defaults"})
        for row in self.database.query_all("SELECT id,plan_json FROM git_import_plans WHERE expires_at>?", (_now(),)):
            if self._contains_reference(json.loads(row["plan_json"]), credential_id):
                dependencies.append({"type": "git_plan", "id": str(row["id"])})
        for row in self.database.query_all("SELECT id,plan_json FROM builds WHERE status IN ('queued','running','cancel_requested')"):
            if self._contains_reference(json.loads(row["plan_json"]), credential_id):
                dependencies.append({"type": "build", "id": str(row["id"])})
        return dependencies

    @staticmethod
    def _contains_reference(value: Any, credential_id: str) -> bool:
        if isinstance(value, dict):
            return any((str(key).endswith("credential_ref") and item == credential_id)
                       or SharedCredentialService._contains_reference(item, credential_id) for key, item in value.items())
        if isinstance(value, list):
            return any(SharedCredentialService._contains_reference(item, credential_id) for item in value)
        return isinstance(value, str) and credential_id in extract_credential_refs(value)

    def _visible_dependencies(self, dependencies: builtins.list[dict[str, str]], context: ToolInvocationContext) -> dict[str, Any]:
        visible = [item for item in dependencies
                   if item["type"] == "mcp_server" and self._can_view_server(context, item["id"])]
        if self._can_view_system_dependencies(context):
            visible.extend(item for item in dependencies if item["type"] != "mcp_server")
        return {"items": visible, "hidden_count": len(dependencies) - len(visible)}

    def _can_view_system_dependencies(self, context: ToolInvocationContext) -> bool:
        if context.auth_type not in {"session", "token"}:
            return False
        try:
            actor = self._current_actor(context)
        except ToolExecutionError:
            return False
        if ("operations.manage" not in actor.permissions and "*" not in actor.permissions
                or not self.access.has_control_permission(actor, "operations.manage")):
            return False
        if actor.auth_type == "session":
            return True
        policy = self.database.query_one("SELECT mode FROM api_token_authorizations WHERE token_id=?", (context.token_id,))
        return policy is None or policy["mode"] == "account"

    def _can_view_server(self, context: ToolInvocationContext, target_id: str) -> bool:
        if self._can_view_system_dependencies(context):
            return True
        if context.auth_type == "oauth" and self.auth.builtin_oauth is not None:
            try:
                self.auth.builtin_oauth.management_authority(context, "gate_mcp_config_status", write=False, target_id=target_id)
                return True
            except (OAuthError, HTTPException, ValueError, KeyError, TypeError):
                return False
        return False

    def _run(self, context: ToolInvocationContext, tool_id: str, action: str, credential_id: str,
             arguments: dict[str, Any], mutate: Callable[[], CredentialResponse], *, value_saved: bool) -> dict[str, Any]:
        self._authorize(context, tool_id=tool_id, credential_id=credential_id, action=action, write=True)
        fingerprint = self.credentials.request_fingerprint({"action": action, "target": credential_id, "request": arguments,
            "connection": {"type": context.auth_type, "token_id": context.token_id, "session_id": context.session_id,
                "oauth_grant_id": context.oauth_grant_id, "oauth_family_id": context.oauth_family_id}})
        operation_id, replay = self._reserve(context, tool_id, arguments["idempotency_key"], credential_id, fingerprint)
        if replay is not None:
            return replay
        mutation_done = False
        try:
            # Configuration writers and HTTP dispatches use these same locks.
            # No new request can dispatch an old value after this write returns.
            with self.configs.mutation_lock, self.credentials.mutation_guard():
                self._authorize(context, tool_id=tool_id, credential_id=credential_id, action=action, write=True)
                connections, hidden_count = (self._connection_summary(credential_id, context)
                                             if tool_id != "gate_credential_delete" else ([], 0))
                credential = mutate()
                mutation_done = True
                result = credential.model_dump(mode="json")
                result.update(operation_id=operation_id, value_saved=value_saved, connection_verified=False)
                result["connections"] = connections
                result["affected_connection_count"] = len(connections) + hidden_count
                result["hidden_connection_count"] = hidden_count
                self.observability.emit_event("gate.credential." + action.split(".")[-1], source="credentials",
                    subject_type="credential", subject_id=credential_id,
                    payload={"actor_id": context.actor_id, "operation_id": operation_id, "value_changed": value_saved,
                             "revision": credential.updated_at})
                self.database.execute("UPDATE mcp_idempotent_operations SET status='succeeded',result_json=?,updated_at=? "
                    "WHERE id=? AND status='pending'", (_json(result), _now(), operation_id))
                return result
        except Exception as exc:
            if mutation_done or isinstance(exc, CredentialPersistenceInterrupted):
                committed = mutation_done or isinstance(exc, CredentialPersistenceInterrupted) and exc.committed is True
                error = _error("credential_operation_interrupted",
                    "Credential changed, but audit or receipt completion failed." if committed
                    else "Credential persistence completion cannot be confirmed.",
                    operation_id=operation_id, requires_reconciliation=True,
                    credential_mutated=True if committed else "unknown", value_saved=value_saved if committed else None)
            elif isinstance(exc, CredentialAlreadyExists):
                error = _error("credential_exists", "A credential with this ID already exists; use a revision-checked update.")
            elif isinstance(exc, CredentialRevisionConflict):
                error = _error("credential_revision_conflict", "The credential changed; reload its revision before writing.")
            elif isinstance(exc, CredentialUsageDenied):
                error = _error("credential_http_scope_invalid", "Check the explicit service, HTTP origin and saved service identity.")
            elif isinstance(exc, KeyError):
                error = _error("credential_unavailable", "The credential or its requested service is unavailable.")
            elif isinstance(exc, ToolExecutionError):
                error = exc
            elif isinstance(exc, (ValueError, TypeError)):
                error = _error("credential_request_invalid", "Check the credential fields; use null to retain an existing value.")
            else:
                error = _error("credential_operation_interrupted", "Credential operation completion cannot be confirmed.",
                    operation_id=operation_id, requires_reconciliation=True, credential_mutated="unknown")
        try:
            self.database.execute("UPDATE mcp_idempotent_operations SET status='failed',error_json=?,updated_at=? "
                "WHERE id=? AND status='pending'", (_json(error.to_payload()), _now(), operation_id))
        except Exception:
            # A receipt outage must preserve the safe reconciliation result.
            # The pending journal record remains non-replayable after restart.
            pass
        raise error from None

    def _connection_summary(self, credential_id: str, context: ToolInvocationContext) -> tuple[builtins.list[dict[str, str]], int]:
        result, hidden_count = [], 0
        for config in self.configs.list_configs().configs:
            manifest = self.configs.load_manifest(config.id)
            refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
            if manifest.transport.type == "streamable_http" and credential_id in refs:
                if self._can_view_server(context, config.id):
                    result.append({"server_id": config.id, "state": "refresh_on_next_dispatch"})
                else:
                    hidden_count += 1
        return result, hidden_count

    def _reserve(self, context: ToolInvocationContext, tool_id: str, key: str,
                 credential_id: str, fingerprint: str) -> tuple[str, dict[str, Any] | None]:
        operation_id = uuid4().hex
        existing: dict[str, Any] | None = None
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("INSERT INTO mcp_idempotent_operations "
                    "(id,actor_id,tool_id,idempotency_key,request_digest,status,resource_type,resource_id,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'pending','shared_credential',?,?,?)",
                    (operation_id, context.actor_id, tool_id, key, fingerprint, credential_id, _now(), _now()))
            except sqlite3.IntegrityError:
                row = connection.execute("SELECT * FROM mcp_idempotent_operations "
                    "WHERE actor_id=? AND tool_id=? AND idempotency_key=?", (context.actor_id, tool_id, key)).fetchone()
                if row is None:
                    raise
                existing = dict(row)
        # Live OAuth/visibility checks can open their own store sessions. Never
        # run them under this operation's SQLite writer transaction.
        if existing is None:
            return operation_id, None
        if existing["request_digest"] != fingerprint:
            raise _error("idempotency_conflict", "This key already belongs to a different credential request.")
        if existing["status"] == "succeeded":
            result = dict(json.loads(existing["result_json"]))
            connections = result.get("connections", [])
            visible = [item for item in connections if self._can_view_server(context, str(item.get("server_id", "")))]
            total = int(result.get("affected_connection_count", len(connections)))
            result.update(connections=visible, affected_connection_count=total,
                          hidden_connection_count=total - len(visible))
            result["idempotent_replay"] = True
            return str(existing["id"]), result
        if existing["status"] == "failed":
            error = json.loads(existing["error_json"]).get("error", {})
            details = dict(error.get("details", {}))
            dependencies = details.get("dependencies")
            if isinstance(dependencies, dict):
                visible_dependencies = self._visible_dependencies(dependencies.get("items", []), context)
                visible_dependencies["hidden_count"] += int(dependencies.get("hidden_count", 0))
                details["dependencies"] = visible_dependencies
            raise ToolExecutionError(str(error.get("code", "credential_operation_failed")),
                str(error.get("message", "The previous request failed.")), details=details)
        raise _error("credential_operation_pending", "The previous request is still pending; reconcile before retrying.",
                     operation_id=str(existing["id"]))

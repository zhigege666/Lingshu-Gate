"""Business-account policy and controlled, reference-only MCP dispatch."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Callable
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.business_credential_adapters import ADAPTERS, BROWSER_FIELDS
from lingshu_gate.application.schema_validation import validate_arguments
from lingshu_gate.argument_policy import check_policy
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.business_credential_store import BusinessCredentialStore
from lingshu_gate.domain.business_credentials import (
    BusinessCredentialBindingCreate, BusinessCredentialBindingUpdate, BusinessCredentialCreate,
    BusinessCredentialError, BusinessCredentialUpdate,
)
from lingshu_gate.domain.tool_structure import copy_bounded_json
from lingshu_gate.mcp_authorization_policy import server_binding
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolDispatchRejectedError, ToolExecutionError, ToolRegistry, tool_definition_revision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection(actor: AuthPrincipal) -> str:
    return hashlib.sha256(json.dumps([actor.id, actor.auth_type, actor.session_id, actor.token_id,
        actor.external_grant_id, actor.oauth_client_id, actor.oauth_family_id], separators=(",", ":")).encode()).hexdigest()


class BusinessCredentialService:
    def __init__(self, store: BusinessCredentialStore, auth: AuthStore, access: AccessControlStore,
                 registry: ToolRegistry, runtime: McpRuntimeManager, configs: McpConfigStore,
                 events: ObservabilityStore) -> None:
        self.store, self.auth, self.access = store, auth, access
        self.registry, self.runtime, self.configs, self.events = registry, runtime, configs, events
        self.database = store.database

    def _current(self, actor: AuthPrincipal) -> AuthPrincipal:
        if not self.auth.enabled:
            raise BusinessCredentialError("authentication_required", "Business credentials require Gate authentication.", 403)
        try:
            current = self.access.refresh_principal(actor) if self.access.refresh_principal else actor
        except Exception:
            raise BusinessCredentialError("credential_authority_changed", "The current connection was revoked or changed.", 403) from None
        if current.status != "active" or current.must_change_password:
            raise BusinessCredentialError("credential_authority_changed", "An active Gate identity is required.", 403)
        return current

    def _permission(self, actor: AuthPrincipal, permission: str) -> None:
        if not self.access.has_control_permission(actor, permission):
            raise BusinessCredentialError("credential_permission_denied", "The current identity cannot perform this credential operation.", 403)

    def manage(self, actor: AuthPrincipal, scope: str, record: dict[str, Any] | None = None) -> AuthPrincipal:
        actor = self._current(actor)
        if actor.auth_type not in {"session", "token"}:
            raise BusinessCredentialError("credential_management_denied", "Use the Console or an explicitly scoped Gate token.", 403)
        self._permission(actor, "credentials.manage.system" if scope == "shared" else "credentials.manage.self")
        if record and scope == "personal" and record["owner_id"] != actor.id:
            raise BusinessCredentialError("credential_not_found", "The business credential is unavailable.", 404)
        return actor

    def _record(self, credential_id: str, actor: AuthPrincipal, *, management: bool = True,
                active: bool = False) -> dict[str, Any]:
        record = self.store.get_credential(credential_id)
        if management:
            self.manage(actor, record["scope"], record)
        else:
            actor = self._current(actor)
            allowed = record["owner_id"] == actor.id
            if record["scope"] == "shared":
                role_ids = {row[0] for row in self.database.query_all(
                    "SELECT r.id FROM roles r JOIN user_roles ur ON r.id=ur.role_id "
                    "WHERE ur.user_id=? AND r.enabled=1", (actor.id,))}
                allowed = allowed or actor.id in record["allowed_user_ids"] or bool(role_ids & set(record["allowed_role_ids"]))
            if not allowed:
                raise BusinessCredentialError("credential_not_found", "The business credential is unavailable.", 404)
        if active and not record["enabled"]:
            raise BusinessCredentialError("credential_disabled", "This credential is disabled; existing website sessions are not revoked.", 403)
        return record

    def _subjects(self, request: BusinessCredentialCreate | BusinessCredentialUpdate) -> None:
        for table, ids in (("users", request.allowed_user_ids), ("roles", request.allowed_role_ids)):
            if any(self.database.query_one(f"SELECT id FROM {table} WHERE id=?", (item,)) is None for item in ids):
                raise BusinessCredentialError("credential_subject_unavailable", "Select existing Gate users and authorization roles.", 422)

    def _event(self, action: str, actor: AuthPrincipal, credential_id: str, **safe: Any) -> None:
        self.events.emit_event("gate.business_credential." + action, source="business_credentials",
            subject_type="business_credential", subject_id=credential_id,
            payload={"actor_id": actor.id, **safe})

    def detail(self, credential_id: str, actor: AuthPrincipal) -> dict[str, Any]:
        record = self._record(credential_id, actor)
        return {**record, "bindings": self.store.list_bindings(credential_id=credential_id)}

    def list(self, actor: AuthPrincipal, scope: str) -> dict[str, Any]:
        actor = self.manage(actor, scope)
        return {"credentials": [{**item, "bindings": self.store.list_bindings(credential_id=item["id"])}
            for item in self.store.list_credentials() if item["scope"] == scope
            and (scope == "shared" or item["owner_id"] == actor.id)]}

    def create(self, actor: AuthPrincipal, draft: BusinessCredentialCreate) -> dict[str, Any]:
        actor = self.manage(actor, draft.scope)
        self._subjects(draft)
        result = self.store.create_credential(actor.id, draft)
        self._event("created", actor, result["id"], version=result["version"])
        return {**result, "bindings": []}

    def update(self, actor: AuthPrincipal, credential_id: str, draft: BusinessCredentialUpdate) -> dict[str, Any]:
        with self.store.lock:
            self._record(credential_id, actor)
            self._subjects(draft)
            result = self.store.update_credential(credential_id, draft)
            self._event("updated", actor, credential_id, version=result["version"], enabled=result["enabled"])
            return {**result, "bindings": self.store.list_bindings(credential_id=credential_id)}

    def delete(self, actor: AuthPrincipal, credential_id: str, expected_version: int) -> dict[str, Any]:
        with self.store.lock:
            self._record(credential_id, actor)
            self.store.delete_credential(credential_id, expected_version=expected_version)
            self._event("deleted", actor, credential_id)
            return {"deleted": True}

    def _tool(self, server_id: str, prefix: str, action: str) -> ToolDefinition:
        try:
            tool = self.registry.get_definition(f"mcp.{server_id}.{prefix}{action}")
        except KeyError:
            raise BusinessCredentialError("adapter_tool_missing", "Enable the agent-browser core,state tools and refresh discovery.", 409) from None
        if (tool.source != "mcp" or tool.metadata.get("server_id") != server_id
                or tool.metadata.get("original_tool_name") != prefix + action):
            raise BusinessCredentialError("adapter_contract_incompatible", "The target tool identity does not match the binding.", 409)
        return tool

    def _target(self, server_id: str) -> tuple[str, str]:
        try:
            manifest = self.configs.load_manifest(server_id)
            runtime_digest = self.runtime.get_manifest_digest(server_id)
            saved_digest = self.runtime._manifest_digest(manifest)
            with self.database.session() as connection:
                identity = hashlib.sha256(server_binding(connection, server_id).encode()).hexdigest()
        except (KeyError, ValueError, RuntimeError):
            raise BusinessCredentialError("credential_target_unavailable", "The selected MCP instance is unavailable.", 409) from None
        if runtime_digest != saved_digest or not manifest.enabled:
            raise BusinessCredentialError("credential_target_changed", "Apply the current MCP configuration before binding credentials.", 409)
        if manifest.user_credentials:
            raise BusinessCredentialError("credential_target_user_routing", "Use a dedicated browser instance without per-user transport credentials.", 409)
        if manifest.transport.type == "streamable_http":
            endpoint = urlsplit(manifest.transport.endpoint)
            if endpoint.scheme != "https" and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise BusinessCredentialError("credential_transport_insecure", "Secret transfer to the MCP instance requires HTTPS or loopback.", 409)
        # An externally attached browser/profile cannot provide account isolation.
        forbidden = ("--cdp", "--profile", "--session-name", "--state", "--restore", "--config",
                     "--provider", "-p", "--auto-connect", "--executable-path", "--extensions", "--extension", "--args")
        if any(any(arg == flag or arg.startswith(flag + "=") for flag in forbidden) for arg in manifest.launch.args):
            raise BusinessCredentialError("credential_target_shared_browser", "Use a dedicated browser without CDP, profiles, state restore or provider overrides.", 409)
        env = {**manifest.launch.env, **manifest.launch.environment}
        if any(name in env for name in ("AGENT_BROWSER_CDP", "AGENT_BROWSER_PROFILE", "AGENT_BROWSER_STATE",
                "AGENT_BROWSER_RESTORE", "AGENT_BROWSER_PROVIDER", "AGENT_BROWSER_SESSION_NAME", "AGENT_BROWSER_AUTO_CONNECT",
                "AGENT_BROWSER_CONFIG", "AGENT_BROWSER_EXTENSIONS", "AGENT_BROWSER_EXECUTABLE_PATH",
                "AGENT_BROWSER_ARGS", "AGENT_BROWSER_PLUGINS")):
            raise BusinessCredentialError("credential_target_shared_browser", "Remove browser-sharing defaults from this dedicated instance.", 409)
        return runtime_digest, identity

    def _capture(self, server_id: str, prefix: str) -> tuple[str, dict[str, str]]:
        digest, identity = self._target(server_id)
        adapter = ADAPTERS["agent_browser"]
        revisions = {"instance_identity": identity}
        for key, action in (("save", "auth_save"), ("login", "auth_login"), ("delete", "auth_delete"), ("open", "open")):
            definition = self._tool(server_id, prefix, action)
            adapter.check_contract(definition, action)
            revisions[key] = tool_definition_revision(definition)
        for action in BROWSER_FIELDS:
            try:
                definition = self._tool(server_id, prefix, action)
                adapter.check_contract(definition, action)
                revisions[action] = tool_definition_revision(definition)
            except BusinessCredentialError:
                continue
        if "close" not in revisions:
            raise BusinessCredentialError("adapter_tool_missing", "A session-scoped close tool is required for cleanup.", 409)
        return digest, revisions

    def targets(self, actor: AuthPrincipal, scope: str) -> dict[str, Any]:
        actor = self.manage(actor, scope)
        can_enable = (self.access.has_control_permission(actor, "credentials.manage.system")
                      and self.access.has_control_permission(actor, "operations.manage"))
        managed = {row["server_id"]: row for row in self.store.list_managed_servers()}
        servers = []
        for item in self.configs.instance_metadata():
            if not can_enable and item.instance_id not in managed:
                continue
            prefix = managed.get(item.instance_id, {}).get("tool_prefix", "agent_browser_")
            compatible_prefixes: list[str] = []
            reason = "adapter_tool_missing"
            candidates = [prefix] if item.instance_id in managed else ["agent_browser_", ""]
            for candidate in candidates:
                try:
                    definition = self._tool(item.instance_id, candidate, "auth_login")
                    self._authorize_tool(actor, definition)
                    self._capture(item.instance_id, candidate)
                    compatible_prefixes.append(candidate)
                except BusinessCredentialError as exc:
                    if candidate == prefix:
                        reason = exc.code
            if not compatible_prefixes and reason == "credential_tool_denied":
                continue
            servers.append({"server_id": item.instance_id, "name": item.name, "compatible": bool(compatible_prefixes),
                "reason": "" if compatible_prefixes else reason, "managed": item.instance_id in managed,
                "tool_prefix": compatible_prefixes[0] if compatible_prefixes else prefix,
                "compatible_prefixes": compatible_prefixes,
                "safe_tools": sorted(BROWSER_FIELDS)})
        users = roles = []
        if scope == "shared":
            users = [{"id": row["id"], "label": row["display_name"] or row["username"]}
                for row in self.database.query_all("SELECT id,username,display_name FROM users WHERE status='active' ORDER BY username")]
            roles = [{"id": row["id"], "label": row["name"]}
                for row in self.database.query_all("SELECT id,name FROM roles WHERE enabled=1 ORDER BY name")]
        return {"servers": servers, "users": users, "roles": roles}

    def bind(self, actor: AuthPrincipal, credential_id: str, draft: BusinessCredentialBindingCreate,
             expected_version: int) -> dict[str, Any]:
        with self.store.lock, self.configs.mutation_lock.read_lock():
            record = self._record(credential_id, actor)
            self.store._version(record["version"], expected_version)
            current = self._current(actor)
            if not self.store.is_managed_server(draft.server_id):
                self._permission(current, "credentials.manage.system")
                self._permission(current, "operations.manage")
                if not draft.confirm_managed_mode:
                    raise BusinessCredentialError("managed_mode_confirmation_required", "Confirm managed mode for the entire dedicated browser instance.", 422)
            self._authorize_tool(current, self._tool(draft.server_id, draft.tool_prefix, "auth_login"))
            # Serialize first activation against ordinary calls. Their final
            # guard checks the permanent marker under this same runtime lock.
            with self.runtime.route_instance_guard(draft.server_id):
                digest, revisions = self._capture(draft.server_id, draft.tool_prefix)
                result = self.store.create_binding(credential_id, draft, manifest_digest=digest, tool_revisions=revisions)
            self._event("bound", actor, credential_id, binding_id=result["id"], server_id=draft.server_id)
            return result

    def binding(self, actor: AuthPrincipal, credential_id: str, binding_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        record = self._record(credential_id, actor)
        binding = self.store.get_binding(binding_id)
        if binding["credential_id"] != credential_id:
            raise BusinessCredentialError("binding_not_found", "The credential binding is unavailable.", 404)
        return record, binding

    def update_binding(self, actor: AuthPrincipal, credential_id: str, binding_id: str,
                       draft: BusinessCredentialBindingUpdate) -> dict[str, Any]:
        with self.store.lock, self.configs.mutation_lock.read_lock():
            _, binding = self.binding(actor, credential_id, binding_id)
            # Toggling a binding never silently accepts a different server/tool.
            result = self.store.update_binding(binding_id, draft,
                manifest_digest=binding["manifest_digest"], tool_revisions=binding["tool_revisions"])
            self._event("binding_updated", actor, credential_id, binding_id=binding_id, enabled=result["enabled"])
            return result

    def delete_binding(self, actor: AuthPrincipal, credential_id: str, binding_id: str, revision: int) -> dict[str, Any]:
        with self.store.lock:
            self.binding(actor, credential_id, binding_id)
            self.store.delete_binding(binding_id, expected_revision=revision)
            self._event("binding_deleted", actor, credential_id, binding_id=binding_id)
            return {"deleted": True}

    def _authorize_tool(self, actor: AuthPrincipal, tool: ToolDefinition) -> AuthPrincipal:
        actor = self._current(actor)
        # A credential grant never grants tool authority or expands OAuth scope.
        if not self.access.evaluate(actor, tool)["allowed"]:
            raise BusinessCredentialError("credential_tool_denied", "Current MCP tool authorization is required for this operation.", 403)
        return actor

    def _pin(self, binding: dict[str, Any], action: str) -> ToolDefinition:
        digest, identity = self._target(binding["server_id"])
        key = {"auth_save": "save", "auth_login": "login", "auth_delete": "delete"}.get(action, action)
        tool = self._tool(binding["server_id"], binding["tool_prefix"], action)
        if (digest != binding["manifest_digest"] or identity != binding["tool_revisions"].get("instance_identity")
                or tool_definition_revision(tool) != binding["tool_revisions"].get(key)):
            raise BusinessCredentialError("credential_contract_changed", "The bound instance or tool contract changed; review the target before use.", 409)
        return tool

    def _raw(self, actor: AuthPrincipal, record: dict[str, Any], binding: dict[str, Any], action: str,
             arguments: dict[str, Any], *, management: bool, active: bool = True,
             before: Callable[[], None] | None = None) -> dict[str, Any]:
        """Only this boundary sends decrypted fields. No payload audit or retries."""
        tool = self._pin(binding, action)
        self._authorize_tool(actor, tool)
        validate_arguments(tool.input_schema, arguments)

        def guard() -> None:
            current_record = self._record(record["id"], actor, management=management, active=active)
            current_binding = self.store.get_binding(binding["id"])
            self.store._version(current_record["version"], record["version"])
            self.store._version(current_binding["revision"], binding["revision"])
            if active and not current_binding["enabled"]:
                raise BusinessCredentialError("credential_binding_disabled", "The binding is disabled.", 403)
            current_tool = self._pin(current_binding, action)
            self._authorize_tool(actor, current_tool)
            check_policy(self.access.argument_policies.current(current_tool.id), arguments)
            if before:
                before()

        self.runtime.suppress_credential_payloads(binding["server_id"])
        return self.runtime.invoke_mcp_tool_for_user(binding["server_id"], binding["tool_prefix"] + action,
            arguments, user_id=actor.id, retry_read_only=False, dispatch_guard=guard)

    def synchronize(self, actor: AuthPrincipal, credential_id: str, binding_id: str,
                    expected_version: int, expected_revision: int, *, delete_remote: bool = False) -> dict[str, Any]:
        with self.store.lock, self.configs.mutation_lock.read_lock():
            record, binding = self.binding(actor, credential_id, binding_id)
            self.store._version(record["version"], expected_version)
            self.store._version(binding["revision"], expected_revision)
            action = "auth_delete" if delete_remote else "auth_save"
            if delete_remote and not binding["remote_copy_possible"]:
                # No remote write was attempted, or a deletion was already
                # verified. An idempotent cleanup must not invent uncertainty.
                return binding
            self._pin(binding, action)
            self._authorize_tool(actor, self._tool(binding["server_id"], binding["tool_prefix"], action))
            if not delete_remote and (not record["enabled"] or not binding["enabled"]):
                raise BusinessCredentialError("credential_disabled", "Enable the credential and binding before synchronizing.", 403)
            values = ({"name": binding["profile_name"]} if delete_remote else
                ADAPTERS[binding["adapter"]].save_arguments(record, binding,
                    self.store.resolve_secret(credential_id, expected_version=expected_version)))
            binding = self.store.mark_sync(binding_id, expected_revision=expected_revision,
                expected_version=expected_version, status="unknown")
            try:
                with self.runtime.route_instance_guard(binding["server_id"]):
                    result = self._raw(actor, record, binding, action, values, management=True, active=not delete_remote)
                    if not ADAPTERS[binding["adapter"]].receipt(result, action, profile=binding["profile_name"]):
                        raise BusinessCredentialError("downstream_unknown", "The target did not return a verifiable completion receipt.", 409)
            except Exception:
                # A failed/ambiguous reply may follow a successful remote write.
                updated = self.store.mark_sync(binding_id, expected_revision=binding["revision"],
                    expected_version=expected_version, status="unknown", error_code="downstream_unknown")
                self._event("remote_unknown", actor, credential_id, binding_id=binding_id, operation=action)
                return updated
            updated = self.store.mark_sync(binding_id, expected_revision=binding["revision"], expected_version=expected_version,
                status="deleted" if delete_remote else "synced")
            self._event("remote_deleted" if delete_remote else "synchronized", actor, credential_id,
                binding_id=binding_id, version=expected_version)
            return updated

    def _session(self, actor: AuthPrincipal, server_id: str, logical: str) -> dict[str, Any] | None:
        row = self.database.query_one("SELECT * FROM business_credential_sessions "
            "WHERE connection_key=? AND server_id=? AND logical_session=?", (_connection(actor), server_id, logical))
        return dict(row) if row else None

    def sessions(self, actor: AuthPrincipal, credential_id: str) -> dict[str, Any]:
        self._record(credential_id, actor)
        rows = self.database.query_all("SELECT id,server_id,logical_session,status,credential_version,created_at,updated_at "
            "FROM business_credential_sessions WHERE credential_id=? ORDER BY created_at", (credential_id,))
        return {"sessions": [dict(row) for row in rows]}

    def close_session(self, actor: AuthPrincipal, credential_id: str, session_id: str) -> dict[str, Any]:
        with self.store.lock, self.configs.mutation_lock.read_lock():
            record = self._record(credential_id, actor)
            row = self.database.query_one("SELECT * FROM business_credential_sessions WHERE id=? AND credential_id=?",
                (session_id, credential_id))
            if row is None:
                raise BusinessCredentialError("browser_session_not_found", "The browser session is unavailable.", 404)
            if row["status"] != "closed":
                binding = self.store.get_binding(row["binding_id"])
                self._close(actor, record, binding, dict(row), management=True)
            return {"status": "closed", "website_logout_verified": False}

    def _close(self, actor: AuthPrincipal, record: dict[str, Any], binding: dict[str, Any],
               session: dict[str, Any], *, management: bool, before: Callable[[], None] | None = None) -> dict[str, Any]:
        def mark_closing() -> None:
            if before:
                before()
            # Persist before I/O: a lost reply may follow a successful close.
            self.database.execute("UPDATE business_credential_sessions SET status='unknown',updated_at=? WHERE id=?", (_now(), session["id"]))

        try:
            with self.runtime.route_instance_guard(binding["server_id"]):
                result = self._raw(actor, record, binding, "close", {"session": session["id"]}, management=management,
                    active=False, before=mark_closing)
                if not ADAPTERS[binding["adapter"]].receipt(result, "close"):
                    raise BusinessCredentialError("browser_close_unknown", "Browser closure is unverified; website sessions may remain active.", 409)
                self.database.execute("UPDATE business_credential_sessions SET status='closed',updated_at=? WHERE id=?", (_now(), session["id"]))
        except (BusinessCredentialError, ToolDispatchRejectedError):
            raise
        except Exception:
            raise BusinessCredentialError("browser_close_unknown", "Browser closure is unverified; website sessions may remain active.", 409) from None
        self._event("browser_closed", actor, record["id"], binding_id=binding["id"], session_id=session["id"])
        return {"content": [{"type": "text", "text": "Browser closed. Website logout and server-side session revocation are not verified."}],
            "isError": False}

    def invoke(self, actor: AuthPrincipal, definition: ToolDefinition, arguments: dict[str, Any], *,
               arguments_guard: Callable[[dict[str, Any]], None], dispatch_started: Callable[[], None],
               dispatch_context: AbstractContextManager[None] | None = None) -> dict[str, Any]:
        """Called by the same access boundary as normal tools, before final I/O."""
        try:
            with self.store.lock, self.configs.mutation_lock.read_lock(), dispatch_context or nullcontext():
                return self._invoke(actor, definition, arguments, arguments_guard, dispatch_started)
        except BusinessCredentialError as exc:
            raise ToolDispatchRejectedError(exc.code, exc.message) from None
        except ToolDispatchRejectedError:
            raise
        except Exception:
            raise ToolExecutionError("credential_operation_unknown", "The managed browser operation could not be verified. Check its status before retrying.") from None

    def _invoke(self, actor: AuthPrincipal, definition: ToolDefinition, arguments: dict[str, Any],
                arguments_guard: Callable[[dict[str, Any]], None], dispatch_started: Callable[[], None]) -> dict[str, Any]:
        actor = self._current(actor)
        server_id = str(definition.metadata["server_id"])
        target = self.database.query_one("SELECT * FROM business_credential_targets WHERE server_id=?", (server_id,))
        if target is None:
            raise BusinessCredentialError("credential_target_unavailable", "The managed target is unavailable.", 403)
        prefix = target["tool_prefix"]
        name = str(definition.metadata["original_tool_name"])
        action = name[len(prefix):] if name.startswith(prefix) else ""
        logical = arguments.get("session")
        if not isinstance(logical, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", logical):
            raise BusinessCredentialError("browser_session_required", "Use an explicit logical session of 1–64 letters, digits, dots, underscores or hyphens.", 422)
        session = self._session(actor, server_id, logical)

        def before() -> None:
            # Audit and argument policy see only the original reference/session.
            arguments_guard(arguments)
            dispatch_started()

        if action == "auth_login":
            if set(arguments) != {"name", "session"} or not isinstance(arguments["name"], str) or not re.fullmatch(r"gate:[a-f0-9]{32}", arguments["name"]):
                raise BusinessCredentialError("credential_reference_required", "Use only name=gate:<credential ID> and an explicit session.", 422)
            record = self._record(arguments["name"][5:], actor, management=False, active=True)
            binding = self.store.find_binding(record["id"], server_id)
            if not binding or not binding["enabled"]:
                raise BusinessCredentialError("credential_binding_unavailable", "No enabled binding authorizes this credential at this instance.", 403)
            if binding["sync_status"] != "synced" or binding["synced_version"] != record["version"]:
                raise BusinessCredentialError("credential_sync_required", "Synchronize the current credential version in Gate before login.", 409)
            if session and session["status"] != "closed":
                raise BusinessCredentialError("browser_session_in_use", "Close this logical session or choose a fresh one before another login.", 409)
            now, session_id = _now(), "gate_" + uuid4().hex
            if session:
                self.database.execute("DELETE FROM business_credential_sessions WHERE id=? AND status='closed'", (session["id"],))
            # Durable intent precedes navigation: an interrupted login is never
            # reported as no browser/session having been created.
            self.database.execute("INSERT INTO business_credential_sessions "
                "(id,connection_key,owner_id,server_id,logical_session,credential_id,binding_id,credential_version,"
                "binding_revision,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'unknown',?,?)",
                (session_id, _connection(actor), actor.id, server_id, logical, record["id"], binding["id"],
                 record["version"], binding["revision"], now, now))
            with self.runtime.route_instance_guard(server_id):
                opened = self._raw(actor, record, binding, "open", {"url": record["login_url"], "session": session_id},
                    management=False, before=before)
                adapter = ADAPTERS[binding["adapter"]]
                if not adapter.receipt(opened, "open", login_url=record["login_url"]):
                    raise BusinessCredentialError("credential_origin_unverified", "The browser did not confirm the bound login origin; no login was sent.", 409)
                result = self._raw(actor, record, binding, "auth_login", {"name": binding["profile_name"],
                    "session": session_id, "noNavigate": True}, management=False, before=before)
                if not adapter.receipt(result, "auth_login", profile=binding["profile_name"]):
                    raise BusinessCredentialError("browser_login_unknown", "Login execution is unverified; check the browser before retrying.", 409)
            self.database.execute("UPDATE business_credential_sessions SET status='active',updated_at=? WHERE id=?", (_now(), session_id))
            self._event("login_executed", actor, record["id"], binding_id=binding["id"], version=record["version"])
            return {"content": [{"type": "text", "text": json.dumps({"status": "login_executed", "credential_ref": record["credential_ref"],
                "session": logical, "authentication_verified": False}, ensure_ascii=False)}], "isError": False}

        if action not in BROWSER_FIELDS:
            raise BusinessCredentialError("managed_browser_tool_denied", "Use Gate credential management for vault operations; this browser tool is restricted.", 403)
        if not session or session["status"] == "closed":
            raise BusinessCredentialError("browser_session_unavailable", "Start this logical session with the authorized credential reference.", 403)
        record = self._record(session["credential_id"], actor, management=False, active=action != "close")
        binding = self.store.get_binding(session["binding_id"])
        adapter = ADAPTERS[binding["adapter"]]
        effective = adapter.browser_arguments(action, arguments, native_session=session["id"], login_url=record["login_url"])
        if action == "close":
            return self._close(actor, record, binding, session, management=False, before=before)
        if (session["status"] != "active" or record["version"] != session["credential_version"] or not binding["enabled"]
                or binding["revision"] != session["binding_revision"]
                or binding["sync_status"] != "synced" or binding["synced_version"] != record["version"]):
            raise BusinessCredentialError("browser_session_stale", "The credential or binding changed; close this session and start a new one.", 409)
        with self.runtime.route_instance_guard(server_id):
            result = self._raw(actor, record, binding, action, effective, management=False, before=before)
            secret = self.store.resolve_secret(record["id"], expected_version=record["version"])
            return self._safe_browser_output(result, secret)

    @staticmethod
    def _safe_browser_output(result: dict[str, Any], secret: dict[str, str]) -> dict[str, Any]:
        # Never forward raw CLI stdout/stderr or binary screenshots. Known secret
        # redaction also covers the structured response's common encodings.
        if not ADAPTERS["agent_browser"].succeeded(result):
            raise BusinessCredentialError("browser_action_failed", "The browser action failed; raw output was suppressed.", 409)
        # Native content text appends diagnostic stderr, so even that envelope
        # is unsafe to forward. Only verified response data reaches the model.
        owned = copy_bounded_json(result["structuredContent"]["response"]["data"],
            max_bytes=1_048_576, max_nodes=8192, max_depth=32)
        tokens = set()
        for value in secret.values():
            tokens.update({value, json.dumps(value, ensure_ascii=True)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1],
                quote(value, safe=""), quote_plus(value), base64.b64encode(value.encode()).decode()})

        def clean(value: str) -> str:
            for token in sorted(tokens, key=len, reverse=True):
                if token:
                    value = value.replace(token, "[REDACTED]")
            return value

        def clean_data(value: Any) -> Any:
            if isinstance(value, str):
                return clean(value)
            if isinstance(value, dict):
                return {clean(key): clean_data(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean_data(item) for item in value]
            return value

        return {"content": [{"type": "text", "text": json.dumps(clean_data(owned), ensure_ascii=False)}], "isError": False}

"""Admin-owned group metadata over existing manifests; no runtime or grant writes."""
from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.domain.mcp_groups import McpGroupCreate, McpGroupDraft, McpGroupError
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.persistence.mcp_groups import McpGroupStore


class McpGroupService:
    def __init__(self, store: McpGroupStore, configs: McpConfigStore, runtime: McpRuntimeManager) -> None:
        self.store, self.configs, self.runtime = store, configs, runtime

    @staticmethod
    def authorize(connection: sqlite3.Connection, principal: AuthPrincipal, *, write: bool = False) -> None:
        required = {"operations.manage", "tools.invoke"} if write else {"operations.manage"}
        user = connection.execute("SELECT status,must_change_password FROM users WHERE id=?", (principal.id,)).fetchone()
        roles = {row[0] for row in connection.execute("SELECT r.code FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
            "WHERE ur.user_id=? AND r.enabled=1", (principal.id,))}
        permissions = {row[0] for row in connection.execute("SELECT p.code FROM user_roles ur "
            "JOIN roles r ON r.id=ur.role_id AND r.enabled=1 JOIN role_permissions rp ON rp.role_id=r.id "
            "JOIN control_permissions p ON p.id=rp.permission_id WHERE ur.user_id=?", (principal.id,))}
        if (principal.auth_type not in {"session", "token"} or user is None or user["status"] != "active"
                or user["must_change_password"] or "admin" not in roles or not required.issubset(permissions)
                or not required.issubset(principal.permissions)):
            raise McpGroupError("group_admin_required", "Use a current administrator with operations.manage; writes also require tools.invoke.", 403)
        if principal.auth_type == "session":
            row = connection.execute("SELECT user_id,purpose,expires_at FROM auth_sessions WHERE id=?", (principal.session_id,)).fetchone()
            valid = bool(row and row["user_id"] == principal.id and row["purpose"] == "console")
        else:
            row = connection.execute("SELECT user_id,expires_at,revoked_at,scopes_json FROM api_tokens WHERE id=?", (principal.token_id,)).fetchone()
            scopes = set(json.loads(row["scopes_json"])) if row else set()
            valid = bool(row and row["user_id"] == principal.id and row["revoked_at"] is None
                         and ("*" in scopes or required.issubset(scopes))
                         and ("*" in principal.scopes or required.issubset(principal.scopes)))
        try:
            expired = bool(row and row["expires_at"] and datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc))
        except (ValueError, TypeError):
            expired = True
        if not valid or expired or (principal.delegated_scopes is not None
                and "*" not in principal.delegated_scopes and not required.issubset(principal.delegated_scopes)):
            raise McpGroupError("group_connection_invalid", "The administrator connection is unavailable or lacks the required read/write scopes.", 403)

    def check(self, principal: AuthPrincipal, *, write: bool = False) -> None:
        with self.store.database.session() as connection:
            self.authorize(connection, principal, write=write)

    def _catalog(self, *, refresh: bool = False) -> dict[str, dict[str, Any]]:
        return {config.instance_id: {"instance_id": config.instance_id, "name": config.name,
                           "available": True, "status": "not_loaded"}
                for config in self.configs.instance_metadata(refresh=refresh)}

    def list_groups(self, principal: AuthPrincipal, **query: Any) -> dict[str, Any]:
        return self.store.list_groups(**query, authorize=lambda connection: self.authorize(connection, principal))

    def detail(self, group_id: str, principal: AuthPrincipal) -> dict[str, Any]:
        with self.configs.mutation_lock, self.store.database.session() as connection:
            self.authorize(connection, principal)
            result = self.store.detail(connection, group_id)
            catalog = self._catalog()
            result["members"] = [{**item, "available": item["status"] == "active" and item["instance_id"] in catalog}
                                 for item in result["members"]]
            return result

    def instances(self, principal: AuthPrincipal, *, q: str, group_id: str | None, ungrouped: bool,
                  offset: int, limit: int, refresh: bool = False) -> dict[str, Any]:
        self.check(principal)
        with self.configs.mutation_lock, self.store.database.session() as connection:
            # Never acquire runtime locks under a SQLite writer: discovery does the reverse.
            states = {server.id: server.status for server in self.runtime.list_servers().servers}
            self.authorize(connection, principal)
            catalog = self._catalog(refresh=refresh)
            for key, item in catalog.items():
                item["status"] = states.get(key, "not_loaded")
            if group_id:
                group = self.store.detail(connection, group_id)
                members = {item["instance_id"]: item for item in group["members"]}
                catalog = {key: {**catalog.get(key, {"instance_id": key, "name": key, "status": "missing"}),
                                 "available": key in catalog and item["status"] == "active"}
                           for key, item in members.items()}
            elif ungrouped:
                grouped = {row[0] for row in connection.execute("SELECT DISTINCT m.server_id FROM mcp_group_members m "
                    "JOIN mcp_groups g ON g.id=m.group_id WHERE m.status='active' AND g.status='active'")}
                catalog = {key: item for key, item in catalog.items() if key not in grouped}
            needle = q.strip().casefold()
            items = sorted((item for item in catalog.values() if needle in f'{item["instance_id"]} {item["name"]}'.casefold()),
                           key=lambda item: (str(item["name"]).casefold(), item["instance_id"]))
            page = items[offset:offset + limit]
            for item in page:
                item["groups"] = [dict(row) for row in connection.execute("SELECT g.id,g.name,g.status FROM mcp_groups g "
                    "JOIN mcp_group_members m ON m.group_id=g.id WHERE m.server_id=? ORDER BY g.name,g.id", (item["instance_id"],))]
            return {"instances": page, "total": len(items), "offset": offset, "limit": limit}

    def save(self, draft: McpGroupDraft, principal: AuthPrincipal, *, group_id: str | None = None,
             expected_revision: int | None = None, request_key: str | None = None,
             request_digest: str | None = None) -> dict[str, Any]:
        with self.configs.mutation_lock:
            self.check(principal, write=True)
            if group_id is None:
                if isinstance(draft, McpGroupCreate):
                    request_key = request_key or draft.request_key
                if request_key is None or not re.fullmatch(r"[a-f0-9]{32}", request_key):
                    raise McpGroupError("group_request_key_required", "A new group needs an actor-bound request key.", 422)
                request_digest = request_digest or hashlib.sha256(json.dumps(draft.model_dump(), ensure_ascii=False,
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            # Read current files under the same mutation lock, even when list metadata is cached.
            available = set(self._catalog(refresh=True))
            return self.store.save(draft, group_id=group_id, expected_revision=expected_revision,
                                   actor_id=principal.id, authorize=lambda connection: self.authorize(connection, principal, write=True),
                                   available_instances=available, request_key=request_key, request_digest=request_digest)

    def create_result(self, request_key: str, principal: AuthPrincipal) -> dict[str, Any]:
        return self.store.create_result(request_key, actor_id=principal.id,
            authorize=lambda connection: self.authorize(connection, principal))

    def delete(self, group_id: str, revision: int, principal: AuthPrincipal) -> dict[str, Any]:
        self.check(principal, write=True)
        return self.store.delete(group_id, revision, actor_id=principal.id,
                                 authorize=lambda connection: self.authorize(connection, principal, write=True))

"""个人 API 令牌业务范围、配额与事务内确认。"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.console_session_security import live_console_session
from lingshu_gate.auth import AuthPrincipal, AuthStore, _is_expired, hash_secret, iso_now
from lingshu_gate.mcp_authorization_policy import bind_server_policies, server_binding, tool_snapshot
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import RegistrySnapshotCapacityError, ToolRegistry
from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed


def digest(value: Any) -> str:
    return hash_secret(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def authorization_data(row: Any) -> dict[str, Any]:
    if row is None:
        return {"authorization_mode": "account", "authorization_revision": 0,
                "server_policies": [], "tool_ids": [], "rate_per_minute": None, "concurrency": None}
    return {"authorization_mode": row["mode"], "authorization_revision": row["revision"],
            "server_policies": json.loads(row["server_policies_json"]),
            "tool_ids": list(json.loads(row["tools_json"])),
            "rate_per_minute": row["rate_per_minute"], "concurrency": row["concurrency"]}


class TokenAuthorizationStore:
    def __init__(self, auth: AuthStore, access: AccessControlStore, registry: ToolRegistry,
                 observability: ObservabilityStore) -> None:
        self.auth, self.access, self.registry, self.observability = auth, access, registry, observability

    def _owner(self, principal: AuthPrincipal, session: str) -> AuthPrincipal:
        current = live_console_session(self.auth, principal, session)
        if not self.auth.enabled or current is None:
            raise HTTPException(403, detail="session_required")
        self.access.require_control_permission(current, "credentials.manage.self")
        return current

    def _state(self, connection: sqlite3.Connection, principal: AuthPrincipal, target_id: str) -> dict[str, Any]:
        if target_id == "new":
            scopes = sorted(scope for scope in principal.permissions if scope != "*") if "admin" in principal.roles or principal.role == "admin" else (
                ["tools.read"] if "tools.read" in principal.permissions else [])
            return {"revision": 0, "mode": "independent", "scopes": scopes, "tool_ids": [],
                    "server_policies": [], "tools": {}, "rate_per_minute": 6000, "concurrency": 100,
                    "name": "", "expires_at": None}
        token = connection.execute("SELECT * FROM api_tokens WHERE id=? AND user_id=?", (target_id, principal.id)).fetchone()
        if token is None:
            raise HTTPException(404, detail="token_not_found")
        if token["revoked_at"] or _is_expired(token["expires_at"]):
            raise HTTPException(409, detail="token_authorization_unavailable")
        row = connection.execute("SELECT * FROM api_token_authorizations WHERE token_id=?", (target_id,)).fetchone()
        data = authorization_data(row)
        return {"revision": data.pop("authorization_revision"), "mode": data.pop("authorization_mode"),
                **data, "scopes": json.loads(token["scopes_json"]), "name": token["name"], "expires_at": token["expires_at"],
                "tools": json.loads(row["tools_json"]) if row else {}}

    def _catalog(self, connection: sqlite3.Connection, principal: AuthPrincipal,
                 state: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        # 复用账号资源覆盖规则，再强制检查已发布分类；管理员独立范围也不能绕过发布。
        if state is None:
            definitions = self.registry.list_definitions()
        else:
            selected = self.registry.get_definitions(state["tool_ids"])
            try:
                continuous = self.registry.mcp_snapshot((item["server_id"] for item in state["server_policies"]), max_tools=5000)
            except RegistrySnapshotCapacityError as exc:
                raise HTTPException(409, detail="authorization_scope_limit") from exc
            definitions = list({item.id: item for item in [*selected,
                *(entry.structure.copy_definition() for entry in continuous.tools)]}.values())
            if len(definitions) > 5000:
                raise HTTPException(409, detail="authorization_scope_limit")
        visible = self.access.visible_tools(principal, definitions, connection=connection)
        classifications = self.access._load_classifications(connection,
            ((str(tool.metadata.get("server_id", "")), tool.id) for tool in visible))
        catalog: dict[str, Any] = {}
        servers: dict[str, Any] = {}
        for tool in visible:
            server_id = str(tool.metadata.get("server_id") or "")
            if tool.source != "mcp" or not server_id:
                continue
            try:
                binding = server_binding(connection, server_id)
            except ValueError:
                continue
            name = tool.metadata.get("server_name") or server_id
            servers.setdefault(server_id, {"server_id": server_id, "server_name": name,
                                           "server_binding": binding, "tool_count": 0})
            if len(servers) > 100:
                raise HTTPException(409, detail="authorization_catalog_limit")
            classification = classifications.get((server_id, tool.id))
            if not classification or classification["status"] != "published" or classification["effective_access"] not in {"read", "write"}:
                continue
            policy = tool.metadata.get("gate_access", {})
            if policy.get("classification_status") != "published":
                continue
            access = classification["effective_access"]
            catalog[tool.id] = {"id": tool.id, "name": tool.name, "server_id": server_id, "server_name": name,
                                "access": access, "snapshot": tool_snapshot(tool, classification), "server_binding": binding}
            servers[server_id]["tool_count"] += 1
            if len(catalog) > 5000:
                raise HTTPException(409, detail="authorization_catalog_limit")
        return catalog, list(servers.values())

    def _editor_catalog(self, connection: sqlite3.Connection, principal: AuthPrincipal, state: dict[str, Any],
                        target_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        try:
            catalog, servers = self._catalog(connection, principal)
            return catalog, servers, False
        except HTTPException as exc:
            if target_id == "new" or exc.detail != "authorization_catalog_limit":
                raise
        # 大账号的编辑目录超出本版上限时，仅允许修改既有授权的配额。
        # 从精确工具与服务索引读取原范围，不能因无关 MCP 数量阻断配额维护。
        catalog, servers = self._catalog(connection, principal, state)
        return catalog, servers, True

    @staticmethod
    def _binding(principal: AuthPrincipal, state: dict[str, Any], catalog: dict[str, Any], servers: list[dict[str, Any]]) -> str:
        return digest([state, catalog, servers, principal.roles, principal.permissions])

    def _ticket(self, connection: sqlite3.Connection, principal: AuthPrincipal, session: str,
                target_id: str, purpose: str, binding: str, target: str = "") -> str:
        now = int(time.time())
        connection.execute("DELETE FROM api_token_authorization_tickets WHERE expires_at<=?", (now,))
        if purpose == "confirmation":
            # 同一目标只保留最近一次预览，取消后重新预览不会积累或保留多个可写确认。
            connection.execute("DELETE FROM api_token_authorization_tickets WHERE user_id=? AND session_hash=? "
                               "AND target_id=? AND purpose='confirmation'", (principal.id, hash_secret(session), target_id))
        count = connection.execute("SELECT COUNT(*),SUM(user_id=?) FROM api_token_authorization_tickets", (principal.id,)).fetchone()
        if count[0] >= 4096 or (count[1] or 0) >= 32:
            raise HTTPException(429, detail="authorization_ticket_capacity")
        token = secrets.token_urlsafe(32)
        connection.execute("INSERT INTO api_token_authorization_tickets VALUES(?,?,?,?,?,?,?,?)",
            (hash_secret(token), principal.id, hash_secret(session), target_id, purpose, binding, target, now + 300))
        return token

    def _consume(self, connection: sqlite3.Connection, principal: AuthPrincipal, session: str, target_id: str,
                 purpose: str, token: str, binding: str, target: str = "") -> None:
        sql = "SELECT 1 FROM" if purpose == "options" else "DELETE FROM"
        result = connection.execute(sql + " api_token_authorization_tickets WHERE token_hash=? AND user_id=? "
            "AND session_hash=? AND target_id=? AND purpose=? AND binding_digest=? AND target_digest=? AND expires_at>?",
            (hash_secret(token), principal.id, hash_secret(session), target_id, purpose, binding, target, int(time.time())))
        valid = result.fetchone() is not None if purpose == "options" else result.rowcount == 1
        if not valid:
            raise HTTPException(409 if purpose == "confirmation" else 403, detail="authorization_confirmation_changed" if purpose == "confirmation" else "invalid_csrf")

    def options(self, principal: AuthPrincipal, session: str, target_id: str) -> dict[str, Any]:
        with self.auth.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            principal = self._owner(principal, session)
            state = self._state(connection, principal, target_id)
            catalog, servers, limited = self._editor_catalog(connection, principal, state, target_id)
            # 已订阅而暂时无工具的服务仍可取消或检查，不因目录瞬时空缺丢失。
            known = {item["server_id"] for item in servers}
            for policy in state["server_policies"]:
                if policy["server_id"] not in known:
                    servers.append({"server_id": policy["server_id"], "server_name": policy["server_id"],
                                    "server_binding": policy["server_binding"], "tool_count": 0})
            binding = self._binding(principal, state, catalog, servers)
            csrf = self._ticket(connection, principal, session, target_id, "options", binding)
            return {**state, "selected_tools": list(state["tools"].values()), "tools": list(catalog.values()), "servers": servers, "csrf": csrf,
                    "catalog_complete": not limited, "scope_editable": not limited,
                    "catalog_revision": binding, "expires_at": state["expires_at"]}

    def _target(self, connection: sqlite3.Connection, principal: AuthPrincipal, state: dict[str, Any],
                catalog: dict[str, Any], body: dict[str, Any], target_id: str) -> dict[str, Any]:
        if body["expected_revision"] != state["revision"]:
            raise HTTPException(409, detail="revision_conflict")
        if body["mode"] == "account" and (target_id == "new" or state["mode"] != "account"):
            raise ValueError("account_mode_cannot_be_restored")
        scopes = self.auth._normalize_api_token_scopes(principal=principal, scopes=body["scopes"], allow_default=False)
        if (type(body["rate_per_minute"]) is not int or not 1 <= body["rate_per_minute"] <= 10000
                or type(body["concurrency"]) is not int or not 1 <= body["concurrency"] <= 100):
            raise ValueError("invalid_quota")
        # 只改配额时保留原快照，包括当前不可用的历史项；不会重新批准已失效绑定。
        previous_policies = {item["server_id"]: item for item in state["server_policies"]}
        requested_policies = [{**item, **({"server_binding": previous_policies[item["server_id"]]["server_binding"]}
            if "server_binding" not in item and item["server_id"] in previous_policies else {})}
            for item in body["server_policies"]]
        same_policies = sorted(requested_policies, key=lambda item: item["server_id"]) == state["server_policies"]
        policies = state["server_policies"] if same_policies else bind_server_policies(connection, requested_policies)
        ids = body["tool_ids"]
        if len(ids) > 5000 or len(set(ids)) != len(ids):
            raise ValueError("invalid_tool_selection")
        if body["mode"] == "account" and (ids or policies):
            raise ValueError("account_mode_has_no_independent_scope")
        tools = {}
        quota_only = (set(ids) == set(state["tool_ids"]) and same_policies and body["mode"] == state["mode"]
                      and scopes == state["scopes"])
        for key in ids:
            if quota_only and key in state["tools"]:
                tools[key] = state["tools"][key]
                continue
            if key not in catalog:
                raise HTTPException(409, detail="tool_scope_changed")
            tools[key] = catalog[key]
        continuous_ids = {policy["server_id"] for policy in policies}
        if continuous_ids & {item["server_id"] for item in tools.values()}:
            raise ValueError("server_scope_modes_conflict")
        if len(continuous_ids | {item["server_id"] for item in tools.values()}) > 100:
            raise ValueError("server_scope_limit")
        for item in tools.values():
            required = "tools.read" if item["access"] == "read" else "tools.invoke"
            if required not in scopes and "*" not in scopes:
                raise ValueError("tool_scope_exceeds_function_permissions")
        for policy in policies:
            required = "tools.read" if policy["access"] == "read" else "tools.invoke"
            if required not in scopes and "*" not in scopes:
                raise ValueError("server_scope_exceeds_function_permissions")
            # 持续授权不能通过猜测服务 ID 获得本人不可见服务。
            if not any(item["server_id"] == policy["server_id"] for item in catalog.values()) and not any(
                item["server_id"] == policy["server_id"] and item["server_binding"] == policy["server_binding"] for item in state["server_policies"]):
                raise ValueError("server_scope_unavailable")
        name = (body.get("name") or state["name"] or "API Token").strip()
        expires_at = body.get("expires_at") if target_id == "new" else state["expires_at"]
        if expires_at and _is_expired(expires_at):
            raise ValueError("invalid_expiration")
        return {"mode": body["mode"], "scopes": scopes, "tools": tools, "tool_ids": sorted(tools),
                "server_policies": policies, "rate_per_minute": body["rate_per_minute"],
                "concurrency": body["concurrency"], "name": name, "expires_at": expires_at}

    def change(self, principal: AuthPrincipal, session: str, target_id: str, body: dict[str, Any], *, save: bool) -> dict[str, Any]:
        with self.auth.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            principal = self._owner(principal, session)
            state = self._state(connection, principal, target_id)
            catalog, servers, limited = self._editor_catalog(connection, principal, state, target_id)
            known = {item["server_id"] for item in servers}
            for policy in state["server_policies"]:
                if policy["server_id"] not in known:
                    servers.append({"server_id": policy["server_id"], "server_name": policy["server_id"],
                                    "server_binding": policy["server_binding"], "tool_count": 0})
            binding = self._binding(principal, state, catalog, servers)
            if body["catalog_revision"] != binding:
                raise HTTPException(409, detail="authorization_catalog_changed")
            target = self._target(connection, principal, state, catalog, body, target_id)
            if limited and any(target[key] != state[key] for key in ("mode", "scopes", "tools", "server_policies")):
                raise HTTPException(409, detail="authorization_catalog_limit")
            self._consume(connection, principal, session, target_id, "confirmation" if save else "options",
                          body.get("confirmation", "") if save else body.get("csrf", ""), binding, digest(target) if save else "")
            if not save:
                confirmation = self._ticket(connection, principal, session, target_id, "confirmation", binding, digest(target))
                return {**target, "revision": state["revision"], "confirmation": confirmation,
                        "confirmation_expires_at": int(time.time()) + 300, "previous": state,
                        "added": sorted(set(target["tools"]) - set(state["tools"])),
                        "removed": sorted(set(state["tools"]) - set(target["tools"]))}
            token_id = str(uuid4()) if target_id == "new" else target_id
            secret = "lgt_" + secrets.token_urlsafe(32) if target_id == "new" else None
            if secret:
                connection.execute("INSERT INTO api_tokens(id,user_id,name,token_hash,token_prefix,scopes_json,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (token_id, principal.id, target["name"], hash_secret(secret), secret[:9] + "…", json.dumps(target["scopes"]), target["expires_at"], iso_now()))
            else:
                connection.execute("UPDATE api_tokens SET scopes_json=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                                   (json.dumps(target["scopes"]), token_id, principal.id))
            connection.execute("INSERT INTO api_token_authorizations VALUES(?,?,?,?,?,?,?) ON CONFLICT(token_id) DO UPDATE SET "
                "revision=excluded.revision,mode=excluded.mode,server_policies_json=excluded.server_policies_json,tools_json=excluded.tools_json,"
                "rate_per_minute=excluded.rate_per_minute,concurrency=excluded.concurrency",
                (token_id, state["revision"] + 1, target["mode"], json.dumps(target["server_policies"]), json.dumps(target["tools"]), target["rate_per_minute"], target["concurrency"]))
            self.observability.emit_event("gate.auth.token_authorization_created" if secret else "gate.auth.token_authorization_updated",
                source="auth", subject_type="token", subject_id=token_id,
                payload={"actor_id": principal.id, "previous_revision": state["revision"], "revision": state["revision"] + 1,
                         "previous": state, "target": target}, connection=connection)
            token = connection.execute("SELECT * FROM api_tokens WHERE id=?", (token_id,)).fetchone()
            policy = connection.execute("SELECT * FROM api_token_authorizations WHERE token_id=?", (token_id,)).fetchone()
            result = {key: token[key] for key in ("id", "name", "token_prefix", "expires_at", "revoked_at", "last_used_at", "created_at")}
            result.update({"username": principal.username, "scopes": target["scopes"], **authorization_data(policy)})
            if secret:
                result["token"] = secret
            return result


class TokenServerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_id: str = Field(min_length=1, max_length=512)
    mode: Literal["continuous"] = "continuous"
    access: Literal["read", "write"]
    server_binding: str | None = None


class TokenAuthorizationChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    catalog_revision: str = Field(min_length=1, max_length=128)
    mode: Literal["account", "independent"]
    scopes: list[str] = Field(max_length=200)
    tool_ids: list[str] = Field(default_factory=list, max_length=5000)
    server_policies: list[TokenServerPolicy] = Field(default_factory=list, max_length=100)
    rate_per_minute: int = Field(default=6000, ge=1, le=10000, strict=True)
    concurrency: int = Field(default=100, ge=1, le=100, strict=True)
    name: str | None = Field(default=None, max_length=256)
    expires_at: str | None = Field(default=None, max_length=64)


class TokenAuthorizationPreview(TokenAuthorizationChange):
    csrf: str = Field(min_length=40, max_length=128)


class TokenAuthorizationSave(TokenAuthorizationChange):
    confirmation: str = Field(min_length=40, max_length=128)


def register_token_authorization_routes(app: FastAPI, store: TokenAuthorizationStore,
                                        require_viewer: Callable[[Request], AuthPrincipal]) -> None:
    """新编辑合同仅允许本人 Console 会话；旧 scopes PATCH 保留原合同。"""
    def owner(request: Request, principal: AuthPrincipal = Depends(require_viewer)) -> AuthPrincipal:
        if not console_origin_allowed(request, required=request.method not in {"GET", "HEAD"}):
            raise HTTPException(403, detail="invalid_origin")
        return store._owner(principal, request.cookies.get(store.auth.cookie_name, ""))

    def options(request: Request, principal: AuthPrincipal, token_id: str) -> JSONResponse:
        return JSONResponse(store.options(principal, request.cookies.get(store.auth.cookie_name, ""), token_id),
                            headers={"Cache-Control": "no-store"})

    def change(request: Request, principal: AuthPrincipal, token_id: str,
               body: TokenAuthorizationChange, *, save: bool) -> JSONResponse:
        try:
            result = store.change(principal, request.cookies.get(store.auth.cookie_name, ""), token_id,
                                  body.model_dump(exclude_none=True), save=save)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/v1/auth/tokens/authorization-options", tags=["auth"])
    def create_options(request: Request, principal: AuthPrincipal = Depends(owner)) -> JSONResponse:
        return options(request, principal, "new")

    @app.post("/v1/auth/tokens/authorization-preview", tags=["auth"])
    def create_preview(request: Request, body: TokenAuthorizationPreview, principal: AuthPrincipal = Depends(owner)) -> JSONResponse:
        return change(request, principal, "new", body, save=False)

    @app.post("/v1/auth/tokens/authorization", tags=["auth"])
    def create_save(request: Request, body: TokenAuthorizationSave, principal: AuthPrincipal = Depends(owner)) -> JSONResponse:
        return change(request, principal, "new", body, save=True)

    @app.get("/v1/auth/tokens/{token_id}/authorization-options", tags=["auth"])
    def edit_options(token_id: str, request: Request, principal: AuthPrincipal = Depends(owner)) -> JSONResponse:
        return options(request, principal, token_id)

    @app.post("/v1/auth/tokens/{token_id}/authorization-preview", tags=["auth"])
    def edit_preview(token_id: str, request: Request, body: TokenAuthorizationPreview,
                     principal: AuthPrincipal = Depends(owner)) -> JSONResponse:
        return change(request, principal, token_id, body, save=False)

    @app.post("/v1/auth/tokens/{token_id}/authorization", tags=["auth"])
    def edit_save(token_id: str, request: Request, body: TokenAuthorizationSave,
                  principal: AuthPrincipal = Depends(owner)) -> JSONResponse:
        return change(request, principal, token_id, body, save=True)

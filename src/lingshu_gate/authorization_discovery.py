"""授权级工具发现设置；不修改授权范围、配额或协议凭据。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from lingshu_gate.access_control import AccessControlStore
    from lingshu_gate.auth import AuthPrincipal, AuthStore
    from lingshu_gate.observability_store import ObservabilityStore

DiscoveryMode = Literal["on_demand", "direct"]
AuthorizationKind = Literal["api", "builtin", "external"]


class PinnedTool(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["tool", "group"]
    tool_ref: str = Field(min_length=1, max_length=256)


class ResultBudgetSetting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    enabled: bool = False
    max_characters: int = Field(default=8192, ge=1024, le=65536)


def discovery_setting(connection: sqlite3.Connection, kind: str, authorization_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT mode,revision FROM authorization_discovery WHERE kind=? AND authorization_id=?",
                             (kind, authorization_id)).fetchone()
    preferences = connection.execute("SELECT pinned_tools_json,result_budget_json FROM authorization_tool_preferences "
                                     "WHERE kind=? AND authorization_id=?", (kind, authorization_id)).fetchone()
    # 新旧授权使用相同缺省；不从 URL、浏览器缓存或其他授权继承设置。
    return {"tool_discovery_mode": row["mode"] if row else "on_demand",
            "discovery_revision": row["revision"] if row else 0,
            "pinned_tools": json.loads(preferences["pinned_tools_json"]) if preferences else [],
            "result_budget": json.loads(preferences["result_budget_json"]) if preferences else ResultBudgetSetting().model_dump()}


def principal_authorization(principal: AuthPrincipal) -> tuple[str, str] | None:
    if principal.token_id:
        return "api", principal.token_id
    if principal.external_grant_id:
        return "builtin" if principal.oauth_builtin else "external", principal.external_grant_id
    return None


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool_discovery_mode: DiscoveryMode
    expected_revision: int = Field(ge=0)
    csrf: str = Field(min_length=43, max_length=43)
    pinned_tools: list[PinnedTool] | None = Field(default=None, max_length=20)
    result_budget: ResultBudgetSetting | None = None

    @model_validator(mode="after")
    def preferences(self) -> DiscoveryRequest:
        for key in ("pinned_tools", "result_budget"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError("preference_must_not_be_null")
        pins = self.pinned_tools or []
        if len({(pin.kind, pin.tool_ref) for pin in pins}) != len(pins):
            raise ValueError("duplicate_pinned_tool")
        return self

    def target(self, current: dict[str, Any]) -> dict[str, Any]:
        return {"tool_discovery_mode": self.tool_discovery_mode,
                "pinned_tools": [p.model_dump() for p in self.pinned_tools] if self.pinned_tools is not None else current["pinned_tools"],
                "result_budget": self.result_budget.model_dump() if self.result_budget is not None else current["result_budget"]}


def register_authorization_discovery_routes(app: FastAPI, auth: AuthStore, access: AccessControlStore,
                                             observability: ObservabilityStore) -> None:
    from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf, live_console_session
    from lingshu_gate.auth import hash_secret
    from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed

    csrf = ConsoleSessionCsrf(auth)

    def owner(request: Request) -> tuple[AuthPrincipal, str]:
        principal = auth.authenticate_request(request)
        session = request.cookies.get(auth.cookie_name, "")
        current = live_console_session(auth, principal, session)
        if not auth.enabled or current is None:
            raise HTTPException(403, detail="session_required")
        access.require_control_permission(current, "credentials.manage.self")
        return current, session

    def state(connection: sqlite3.Connection, principal: AuthPrincipal, kind: str, authorization_id: str) -> dict[str, Any]:
        table = {"api": "api_tokens", "builtin": "gate_oauth_grants", "external": "user_external_grant_drafts"}[kind]
        row = connection.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (authorization_id, principal.id)).fetchone()
        if row is None:
            raise HTTPException(404, detail="authorization_not_found")
        record = dict(row)
        if kind == "builtin" and (auth.builtin_oauth is None or record["resource"] != auth.builtin_oauth.store.config()["resource"]):
            raise HTTPException(409, detail="management_discovery_fixed")
        expired = record.get("expires_at")
        if kind == "external":
            expired = json.loads(record["payload_json"]).get("expires_at")
        if isinstance(expired, str):
            expired = datetime.fromisoformat(expired).timestamp()
        if record.get("revoked_at") or record.get("state") == "revoked" or expired and expired <= time.time():
            raise HTTPException(409, detail="authorization_unavailable")
        setting = discovery_setting(connection, kind, authorization_id)
        # 绑定基础授权记录；预览后撤销或该记录变化都不能套用原确认。
        record.pop("last_used_at", None)
        if kind == "api":
            policy = connection.execute("SELECT * FROM api_token_authorizations WHERE token_id=?", (authorization_id,)).fetchone()
            record["independent_authorization"] = dict(policy) if policy else None
        record_digest = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
        return {**setting, "record_digest": record_digest}

    def binding(value: dict[str, Any]) -> str:
        return hash_secret(json.dumps(value, sort_keys=True))

    def consume(connection: sqlite3.Connection, principal: AuthPrincipal, session: str,
                token: str, target: str, value: dict[str, Any]) -> None:
        deleted = connection.execute("DELETE FROM console_csrf_tickets WHERE token_hash=? AND session_id=? AND user_id=? "
            "AND session_hash=? AND target=? AND request_digest=? AND expires_at>?",
            (hash_secret(token), principal.session_id, principal.id, hash_secret(session), target, binding(value), int(time.time())))
        if deleted.rowcount != 1:
            raise HTTPException(409, detail="discovery_confirmation_changed")

    def reply(value: dict[str, Any]) -> JSONResponse:
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    @app.get("/v1/auth/authorizations/{kind}/{authorization_id}/discovery", tags=["access"])
    def options(kind: AuthorizationKind, authorization_id: str,
                identity: tuple = Depends(owner)) -> JSONResponse:
        principal, session = identity
        with auth.database.session() as connection:
            current = state(connection, principal, kind, authorization_id)
        try:
            ticket = csrf.issue(principal, session, f"discovery:{kind}:{authorization_id}", binding(current))
        except ConsoleCsrfError as exc:
            raise HTTPException(exc.status, detail=exc.code) from exc
        return reply({key: value for key, value in {**current, **ticket}.items() if key != "record_digest"})

    def write(request: Request, body: DiscoveryRequest, kind: str, authorization_id: str,
              identity: tuple, *, save: bool) -> JSONResponse:
        if not console_origin_allowed(request):
            raise HTTPException(403, detail="origin_not_allowed")
        principal, session = identity
        target = f"discovery:{kind}:{authorization_id}"
        with auth.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # 写事务内重检本人会话、权限和记录，保证设置与审计一起提交。
            principal, session = owner(request)
            current = state(connection, principal, kind, authorization_id)
            if current["discovery_revision"] != body.expected_revision:
                raise HTTPException(409, detail="revision_conflict")
            preferences = body.target(current)
            confirmed = {**current, "target_settings": preferences}
            consume(connection, principal, session, body.csrf, target + (":confirm" if save else ""), confirmed if save else current)
            if save:
                connection.execute("INSERT INTO authorization_discovery(kind,authorization_id,mode,revision) VALUES(?,?,?,?) "
                    "ON CONFLICT(kind,authorization_id) DO UPDATE SET mode=excluded.mode,revision=excluded.revision",
                    (kind, authorization_id, body.tool_discovery_mode, body.expected_revision + 1))
                connection.execute("INSERT INTO authorization_tool_preferences VALUES(?,?,?,?) "
                    "ON CONFLICT(kind,authorization_id) DO UPDATE SET pinned_tools_json=excluded.pinned_tools_json,result_budget_json=excluded.result_budget_json",
                    (kind, authorization_id, json.dumps(preferences["pinned_tools"]), json.dumps(preferences["result_budget"])))
                observability.emit_event("gate.auth.discovery_updated", source="authorization_discovery",
                    subject_type=kind, subject_id=authorization_id,
                    payload={"actor_id": principal.id, "previous": current["tool_discovery_mode"],
                             "mode": body.tool_discovery_mode, "revision": body.expected_revision + 1,
                             "pinned_tools": preferences["pinned_tools"], "result_budget": preferences["result_budget"]}, connection=connection)
                return reply(discovery_setting(connection, kind, authorization_id))
        try:
            ticket = csrf.issue(principal, session, target + ":confirm", binding(confirmed))
        except ConsoleCsrfError as exc:
            raise HTTPException(exc.status, detail=exc.code) from exc
        return reply({**ticket, "previous": current["tool_discovery_mode"], **preferences,
                      "expected_revision": body.expected_revision})

    @app.post("/v1/auth/authorizations/{kind}/{authorization_id}/discovery-preview", tags=["access"])
    def preview(request: Request, kind: AuthorizationKind, authorization_id: str, body: DiscoveryRequest,
                identity: tuple = Depends(owner)) -> JSONResponse:
        return write(request, body, kind, authorization_id, identity, save=False)

    @app.post("/v1/auth/authorizations/{kind}/{authorization_id}/discovery", tags=["access"])
    def save(request: Request, kind: AuthorizationKind, authorization_id: str, body: DiscoveryRequest,
             identity: tuple = Depends(owner)) -> JSONResponse:
        return write(request, body, kind, authorization_id, identity, save=True)

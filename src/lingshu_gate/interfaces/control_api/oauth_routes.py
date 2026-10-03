"""Public OAuth endpoints and private, permission-checked management adapters."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from starlette.concurrency import run_in_threadpool

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, hash_secret
from lingshu_gate.oauth_server import (
    BROWSER_COOKIE, INTERACTION_TTL, MAX_INTERACTION_TICKET, MAX_TOOLS, SESSION_COOKIE, OAuthError, OAuthServer, callback, tool_scope_matches,
)
from lingshu_gate.observability_store import ObservabilityStore

SAFE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff"}
PUBLIC_HEADERS = {**SAFE_HEADERS, "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
                  "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                  "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                  "X-Frame-Options": "DENY"}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConfigRequest(StrictRequest):
    enabled: StrictBool = False
    issuer: str = Field(max_length=2048)
    resource: str = Field(max_length=2048)
    expected_revision: int = Field(ge=0)


class ClientRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=100)
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    scopes: list[str] = Field(min_length=1, max_length=2)


class ClientUpdate(ClientRequest):
    enabled: StrictBool
    expected_revision: int = Field(ge=1)
    rotate_secret: StrictBool = False


class InteractionRequest(StrictRequest):
    request_id: str = Field(min_length=40, max_length=MAX_INTERACTION_TICKET)
    csrf: str = Field(min_length=40, max_length=128)


class LoginRequest(InteractionRequest):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class ConsentRequest(InteractionRequest):
    tool_ids: list[str] = Field(default_factory=list, max_length=MAX_TOOLS)
    grant_days: int = Field(default=7, ge=1, le=30)
    rate_per_minute: int = Field(default=30, ge=1, le=10000)
    concurrency: int = Field(default=1, ge=1, le=100)
    deny: StrictBool = False


class NarrowRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    tool_ids: list[str] = Field(min_length=1, max_length=MAX_TOOLS)
    expires_at: int = Field(ge=1)
    rate_per_minute: int = Field(ge=1, le=10000)
    concurrency: int = Field(ge=1, le=100)


class RevokeRequest(StrictRequest):
    expected_revision: int = Field(ge=1)


class OAuthRateBoundary:
    """Bounded single-Core admission; never trusts arbitrary X-Forwarded-For."""
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.windows: dict[str, dict[tuple[str, str], deque[float]]] = {}
        self.global_windows: dict[str, deque[float]] = {}

    def check(self, request: Request, kind: str, limit: int = 60, principal: AuthPrincipal | None = None) -> None:
        if kind in {"token", "revoke"}:
            raise ValueError("protocol endpoints require separate ingress and authenticated-client admission")
        identity = principal.id if principal else request.client.host if request.client else "unknown"
        # Anonymous browser traffic cannot spend authenticated browser budgets.
        # Protocol budgets are charged separately, only after client validation.
        lane, ceiling = (("authenticated", 400) if principal else ("login", 120) if kind == "login"
                         else ("authorize", 150) if kind == "authorize"
                         else ("discovery", 240) if kind == "discovery"
                         else ("cancel", 60) if kind == "decision" else ("public-browser", 300))
        self._take(lane, identity, kind, limit, ceiling)

    def protocol_inbound(self, request: Request, endpoint: str) -> None:
        # Cheap per-source/endpoint admission before reading any body. No
        # unauthenticated global pool can block every legitimate client.
        source = request.client.host if request.client else "unknown"
        self._take("protocol-inbound-" + endpoint, source, endpoint, 60, None, evict_sources=True)

    def protocol_failed(self, request: Request, endpoint: str) -> None:
        # Unknown, disabled and wrong-secret clients share the same response.
        # Track the resolved source, never a spoofable client_id. Classification
        # still needs a cheap read-only credential check so valid credentials
        # are not rejected merely because prior failures named that client.
        source = request.client.host if request.client else "unknown"
        self._take("protocol-failure-" + endpoint, source, endpoint, 10, None, evict_sources=True)

    def protocol_client(self, client_id: str, operation: str) -> None:
        # Call only after current client credentials are validated. Keep the
        # total at 600/min, reserving capacity for each operation; one client's
        # own ceiling cannot spend an entire shared operation budget.
        limit, ceiling = {"exchange": (30, 180), "refresh": (60, 300), "revoke": (30, 120)}[operation]
        self._take("protocol-client-" + operation, client_id, operation, limit, ceiling)

    def _take(self, lane: str, identity: str, kind: str, limit: int,
              ceiling: int | None, *, evict_sources: bool = False) -> None:
        now = time.monotonic()
        with self.lock:
            windows = self.windows.setdefault(lane, {})
            global_window = self.global_windows.setdefault(lane, deque()) if ceiling is not None else None
            for key in list(windows):
                window = windows[key]
                while window and window[0] <= now - 60:
                    window.popleft()
                if not window:
                    del windows[key]
            while global_window and global_window[0] <= now - 60:
                global_window.popleft()
            if len(windows) >= 4096 and (identity, kind) not in windows:
                if not evict_sources:
                    raise OAuthError("rate_limit_exceeded", 429)
                # Bounded least-recently-used source tracking instead of a
                # reject-all gate when unauthenticated identities fill it.
                del windows[next(iter(windows))]
            key = (identity, kind)
            window = windows.pop(key, deque())
            windows[key] = window
            if len(window) >= limit or (global_window is not None and ceiling is not None and len(global_window) >= ceiling):
                raise OAuthError("rate_limit_exceeded", 429)
            window.append(now)
            if global_window is not None:
                global_window.append(now)


async def read_body(request: Request, maximum: int = 32768) -> bytes:
    try:
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > maximum):
            raise OAuthError("request_too_large", 413)
        body = bytearray()
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > maximum:
                    raise OAuthError("request_too_large", 413)
        return bytes(body)
    except TimeoutError as exc:
        raise OAuthError("request_timeout", 408) from exc


async def read_json(request: Request, model: type[BaseModel], maximum: int = 32768) -> Any:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise OAuthError("invalid_request")
    try:
        return model.model_validate(json.loads(await read_body(request, maximum)))
    except (ValidationError, ValueError, UnicodeError, RecursionError) as exc:
        raise OAuthError("invalid_request") from exc


def parse_fields(value: str, allowed: set[str], maximum_value: int = 2048) -> dict[str, str]:
    try:
        pairs = parse_qsl(value, keep_blank_values=True, strict_parsing=True, max_num_fields=20)
    except ValueError as exc:
        raise OAuthError("invalid_request") from exc
    if (len(pairs) != len(dict(pairs)) or any(key not in allowed or len(item) > maximum_value for key, item in pairs)):
        raise OAuthError("invalid_request")
    return dict(pairs)


def authorization_ui_locale(value: str) -> str | None:
    """Bounded, optional language hint; never part of the authorization envelope."""
    if len(value) > 128:
        raise OAuthError("invalid_request")
    supported = {"zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "zh-hans-cn": "zh-CN",
                 "en": "en-US", "en-us": "en-US"}
    for tag in value.split(" "):
        if locale := supported.get(tag.lower()):
            return locale
    # Unrecognized or malformed tags do not change the existing UI preference.
    return None


def client_auth(request: Request, fields: dict[str, str]) -> tuple[str, str]:
    header = request.headers.get("authorization")
    if header is not None:
        if fields.get("client_secret") or not header.startswith("Basic ") or len(header) > 2048:
            raise OAuthError("invalid_client", 401)
        try:
            value = base64.b64decode(header[6:], validate=True).decode("utf-8")
            client_id, secret = (unquote(part) for part in value.split(":", 1))
        except (binascii.Error, UnicodeError, ValueError) as exc:
            raise OAuthError("invalid_client", 401) from exc
        if fields.get("client_id") and fields["client_id"] != client_id:
            raise OAuthError("invalid_client", 401)
    else:
        client_id, secret = fields.get("client_id", ""), fields.get("client_secret", "")
    if len(client_id) > 256 or len(secret) > 256:
        raise OAuthError("invalid_client", 401)
    return client_id, secret


def register_oauth_routes(app: FastAPI, *, server: OAuthServer, observability: ObservabilityStore) -> None:
    rate = OAuthRateBoundary()
    static = Path(__file__).resolve().parents[2] / "static" / "oauth"

    def event(action: str, principal: AuthPrincipal | None = None, subject: str = "") -> None:
        observability.emit_event("gate.oauth." + action, source="oauth", subject_type="oauth",
                                 subject_id=subject, payload={"actor_id": principal.id if principal else None})

    @app.exception_handler(OAuthError)
    async def error_handler(_request: Request, error: OAuthError) -> JSONResponse:
        headers = dict(SAFE_HEADERS)
        if error.status == 429:
            headers["Retry-After"] = "60"
        if error.code == "invalid_client":
            headers["WWW-Authenticate"] = 'Basic realm="lingshu-gate-oauth"'
        return JSONResponse({"error": error.code}, status_code=error.status, headers=headers)

    def require_permission(request: Request, permission: str) -> AuthPrincipal:
        principal = server.auth.authenticate_request(request)
        # Management cannot be bootstrapped by an auth-disabled system principal.
        if not server.auth.enabled:
            raise OAuthError("authentication_required", 403)
        try:
            server.access.require_control_permission(principal, permission)
        except AccessDeniedError as exc:
            raise OAuthError("permission_denied", 403) from exc
        if request.method not in {"GET", "HEAD"} and principal.auth_type == "session":
            # Console uses its private origin. This header is browser-controlled;
            # no CORS is offered. It is not used to derive any issuer/resource URL.
            origin = request.headers.get("origin")
            if not origin or origin != f"{request.url.scheme}://{request.url.netloc}":
                raise OAuthError("invalid_origin", 403)
        return principal

    def admin(request: Request) -> AuthPrincipal:
        return require_permission(request, "external_connections.manage")

    def owner(request: Request) -> AuthPrincipal:
        return require_permission(request, "credentials.manage.self")

    def browser_post(request: Request) -> str:
        config = server.ready_config()
        if request.headers.get("origin") != config["issuer"]:
            raise OAuthError("invalid_origin", 403)
        if request.headers.get("sec-fetch-site") in {"cross-site", "none"}:
            raise OAuthError("invalid_origin", 403)
        return request.cookies.get(BROWSER_COOKIE, "")

    def safe_config() -> dict[str, Any]:
        config = server.store.config()
        issuer = config["issuer"]
        return {**config, "metadata_url": issuer + "/.well-known/oauth-authorization-server" if issuer else "",
                "authorization_endpoint": issuer + "/oauth/authorize" if issuer else "",
                "token_endpoint": issuer + "/oauth/token" if issuer else "",
                "jwks_uri": issuer + "/oauth/jwks" if issuer else "",
                "signing_keys": [{"kid": row["kid"], "active": bool(row["active"]), "retire_at": row["retire_at"]}
                                 for row in server.store.database.query_all("SELECT kid,active,retire_at FROM gate_oauth_keys")],
                "scopes_supported": ["tools.read", "tools.invoke"]}

    @app.get("/v1/auth/oauth/config", tags=["oauth-management"])
    def config(_principal: AuthPrincipal = Depends(admin)) -> dict[str, Any]:
        return safe_config()

    @app.put("/v1/auth/oauth/config", tags=["oauth-management"])
    async def save_config(request: Request, principal: AuthPrincipal = Depends(admin)) -> dict[str, Any]:
        body = await read_json(request, ConfigRequest)
        await run_in_threadpool(server.save_config, body.model_dump(exclude={"expected_revision"}), body.expected_revision)
        event("configuration_saved", principal)
        return safe_config()

    @app.post("/v1/auth/oauth/keys/rotate", tags=["oauth-management"])
    async def rotate_key(request: Request, principal: AuthPrincipal = Depends(admin)) -> dict[str, Any]:
        await read_json(request, StrictRequest)
        rate.check(request, "key-rotation", 5, principal)
        kid = await run_in_threadpool(server.rotate_key)
        event("signing_key_rotated", principal, kid)
        return safe_config()

    @app.get("/v1/auth/oauth/clients", tags=["oauth-management"])
    def clients(_principal: AuthPrincipal = Depends(admin)) -> dict[str, Any]:
        return {"clients": server.store.clients()}

    @app.post("/v1/auth/oauth/clients", tags=["oauth-management"], status_code=201)
    async def create_client(request: Request, principal: AuthPrincipal = Depends(admin)) -> JSONResponse:
        body = await read_json(request, ClientRequest)
        result = await run_in_threadpool(server.create_client, body.name, body.redirect_uris, body.scopes)
        event("client_created", principal, result["client"]["id"])
        return JSONResponse(result, status_code=201, headers=SAFE_HEADERS)

    @app.patch("/v1/auth/oauth/clients/{client_id}", tags=["oauth-management"])
    async def update_client(client_id: str, request: Request, principal: AuthPrincipal = Depends(admin)) -> JSONResponse:
        body = await read_json(request, ClientUpdate)
        result = await run_in_threadpool(server.update_client, client_id, body.expected_revision, enabled=body.enabled,
                                      name=body.name, redirects=body.redirect_uris, scopes=body.scopes,
                                      rotate=body.rotate_secret)
        event("client_updated", principal, client_id)
        return JSONResponse(result, headers=SAFE_HEADERS)

    def describe_grant(grant: dict[str, Any], current: dict[str, dict[str, Any]]) -> dict[str, Any]:
        client = server.store.database.query_one("SELECT name,enabled,scopes_json FROM gate_oauth_clients WHERE id=?", (grant["client_id"],))
        safe = {key: value for key, value in grant.items() if key not in {"tools_json", "scopes_json"}}
        state = ("revoked" if grant["revoked_at"] is not None else "expired" if grant["expires_at"] <= int(time.time())
                 else "disabled" if not client or not client["enabled"] or not server.store.config()["enabled"] else "active")
        scopes = set(json.loads(client["scopes_json"])) if client else set()
        tools = [{**value, "server_name": current[key]["server_name"] if key in current else value.get("server_name"),
                  "currently_authorized": key in current and tool_scope_matches(value, current[key])
                  and ("tools.read" if value["access"] == "read" else "tools.invoke") in scopes}
                 for key, value in grant["tools"].items()]
        return {**safe, "tools": tools, "client_name": client["name"] if client else grant["client_id"],
                "state": state, "effective_tool_count": sum(bool(item["currently_authorized"]) for item in tools),
                "scope_currently_authorized": all(item["currently_authorized"] for item in tools)}

    @app.get("/v1/auth/oauth/grants", tags=["oauth-management"])
    def grants(principal: AuthPrincipal = Depends(owner)) -> dict[str, Any]:
        current = server.catalog(principal, ["tools.read", "tools.invoke"])
        return {"grants": [describe_grant(grant, current) for grant in server.store.grants(principal.id)]}

    @app.patch("/v1/auth/oauth/grants/{grant_id}", tags=["oauth-management"])
    async def narrow_grant(grant_id: str, request: Request, principal: AuthPrincipal = Depends(owner)) -> dict[str, Any]:
        body = await read_json(request, NarrowRequest, 2 * 1024 * 1024)
        grant = await run_in_threadpool(server.narrow_grant, principal.id, grant_id, body.expected_revision, body.tool_ids,
                                   body.expires_at, body.rate_per_minute, body.concurrency)
        event("grant_narrowed", principal, grant_id)
        current = await run_in_threadpool(server.catalog, principal, ["tools.read", "tools.invoke"])
        return describe_grant(grant, current)

    @app.post("/v1/auth/oauth/grants/{grant_id}/revoke", tags=["oauth-management"])
    async def revoke_grant(grant_id: str, request: Request, principal: AuthPrincipal = Depends(owner)) -> dict[str, Any]:
        body = await read_json(request, RevokeRequest)
        grant = await run_in_threadpool(server.narrow_grant, principal.id, grant_id, body.expected_revision, [], 0, 0, 0, revoke=True)
        event("grant_revoked", principal, grant_id)
        current = await run_in_threadpool(server.catalog, principal, ["tools.read", "tools.invoke"])
        return describe_grant(grant, current)

    @app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    def metadata(request: Request) -> JSONResponse:
        rate.check(request, "discovery", 120)
        return JSONResponse(server.metadata(), headers=SAFE_HEADERS)

    @app.get("/oauth/jwks", include_in_schema=False)
    def jwks(request: Request) -> JSONResponse:
        rate.check(request, "discovery", 120)
        return JSONResponse(server.jwks(), headers=SAFE_HEADERS)

    @app.get("/oauth/authorize", include_in_schema=False)
    def authorize(request: Request) -> RedirectResponse:
        principal = server.session_principal(request.cookies.get(SESSION_COOKIE))
        rate.check(request, "authorize", 30, principal)
        config = server.ready_config()
        if len(request.scope.get("query_string", b"")) > 8192:
            raise OAuthError("request_too_large", 413)
        params = parse_fields(request.url.query, {"client_id", "redirect_uri", "response_type", "scope",
                                                "resource", "code_challenge", "code_challenge_method", "state", "ui_locales"})
        ui_locale = authorization_ui_locale(params.pop("ui_locales", ""))
        browser = request.cookies.get(BROWSER_COOKIE) or secrets.token_urlsafe(32)
        try:
            interaction = server.start_authorization(params, browser)
        except OAuthError as error:
            client = server.store.database.query_one("SELECT redirect_uris_json FROM gate_oauth_clients WHERE id=? AND enabled=1",
                                                      (params.get("client_id", ""),))
            if client and params.get("redirect_uri") in json.loads(client["redirect_uris_json"]):
                return RedirectResponse(callback(params, config["issuer"], error=error.code), status_code=303, headers=SAFE_HEADERS)
            raise
        fragment = urlencode({"request": interaction, **({"ui_locales": ui_locale} if ui_locale else {})})
        response = RedirectResponse(config["issuer"] + "/oauth/consent#" + fragment, status_code=303, headers=SAFE_HEADERS)
        response.set_cookie(BROWSER_COOKIE, browser, secure=True, httponly=True, samesite="lax",
                            path="/oauth", max_age=INTERACTION_TTL)
        return response

    @app.get("/oauth/consent", include_in_schema=False)
    def consent_page() -> FileResponse:
        server.ready_config()
        target = static / "oauth.html"
        if not target.is_file():
            raise OAuthError("authorization_ui_unavailable", 503)
        return FileResponse(target, headers=PUBLIC_HEADERS)

    @app.get("/oauth/assets/{asset_path:path}", include_in_schema=False)
    def asset(asset_path: str) -> FileResponse:
        server.ready_config()
        base = (static / "assets").resolve()
        target = (base / asset_path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise OAuthError("asset_not_found", 404)
        return FileResponse(target, headers=PUBLIC_HEADERS)

    @app.get("/oauth/context", include_in_schema=False)
    def context(request: Request) -> JSONResponse:
        principal = server.session_principal(request.cookies.get(SESSION_COOKIE))
        rate.check(request, "context", 60, principal)
        if len(request.scope.get("query_string", b"")) > 32768:
            raise OAuthError("request_too_large", 413)
        fields = parse_fields(request.url.query, {"request_id"}, MAX_INTERACTION_TICKET)
        result = server.consent_context(fields.get("request_id", ""), request.cookies.get(BROWSER_COOKIE, ""),
                                        request.cookies.get(SESSION_COOKIE))
        return JSONResponse(result, headers=SAFE_HEADERS)

    @app.post("/oauth/login", include_in_schema=False)
    async def login(request: Request) -> JSONResponse:
        rate.check(request, "login", 10)
        browser = browser_post(request)
        body = await read_json(request, LoginRequest)
        with server.store.transaction() as connection:
            row, _ = server.interaction(connection, body.request_id, browser, body.csrf)
            if row["completed"]:
                raise OAuthError("authorization_completed", 409)
        try:
            principal, token, _ = await run_in_threadpool(server.auth.login, username=body.username,
                                                       password=body.password, purpose="oauth_consent")
        except HTTPException as exc:
            event("login_failed")
            raise OAuthError("login_failed", 401) from exc
        if principal.must_change_password or not server.access.has_control_permission(principal, "credentials.manage.self"):
            server.auth.logout(token, purpose="oauth_consent")
            raise OAuthError("user_authorization_unavailable", 403)
        try:
            rate.check(request, "context", 60, principal)
            result = await run_in_threadpool(server.consent_context, body.request_id, browser, token)
        except BaseException:
            server.auth.logout(token, purpose="oauth_consent")
            raise
        response = JSONResponse(result, headers=SAFE_HEADERS)
        response.set_cookie(SESSION_COOKIE, token, secure=True, httponly=True, samesite="lax", path="/oauth", max_age=1800)
        event("login", principal)
        return response

    @app.post("/oauth/logout", include_in_schema=False)
    async def logout(request: Request) -> JSONResponse:
        principal = await run_in_threadpool(server.session_principal, request.cookies.get(SESSION_COOKIE))
        rate.check(request, "logout", 30, principal)
        browser = browser_post(request)
        body = await read_json(request, InteractionRequest)
        with server.store.transaction() as connection:
            server.interaction(connection, body.request_id, browser, body.csrf)
        await run_in_threadpool(server.release_interaction, body.request_id, browser, body.csrf)
        server.auth.logout(request.cookies.get(SESSION_COOKIE), purpose="oauth_consent")
        response = JSONResponse({"logged_out": True}, headers=SAFE_HEADERS)
        response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="lax", path="/oauth")
        event("logout", principal)
        return response

    @app.post("/oauth/decision", include_in_schema=False)
    async def decision(request: Request) -> JSONResponse:
        principal = await run_in_threadpool(server.session_principal, request.cookies.get(SESSION_COOKIE))
        rate.check(request, "decision", 30, principal)
        browser = browser_post(request)
        body = await read_json(request, ConsentRequest, 2 * 1024 * 1024)
        result = await run_in_threadpool(server.consent, body.request_id, browser, body.csrf, principal, body.tool_ids, body.grant_days,
                                body.rate_per_minute, body.concurrency, deny=body.deny)
        row = server.store.database.query_one("SELECT request_json FROM gate_oauth_interactions WHERE id_hash=?",
                                               (hash_secret(body.request_id),))
        grant_id = json.loads(row["request_json"]).get("grant_id", "") if row else ""
        event("consent_denied" if body.deny else "consent_granted", principal, grant_id)
        return JSONResponse({"redirect": result}, headers=SAFE_HEADERS)

    async def form(request: Request, allowed: set[str]) -> dict[str, str]:
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            raise OAuthError("invalid_request")
        try:
            return parse_fields((await read_body(request)).decode("utf-8"), allowed)
        except UnicodeError as exc:
            raise OAuthError("invalid_request") from exc

    async def admitted_client(request: Request, fields: dict[str, str], endpoint: str) -> tuple[str, str]:
        try:
            client_id, secret = client_auth(request, fields)
            await run_in_threadpool(server.validate_client_credentials, client_id, secret)
        except OAuthError as exc:
            if exc.code == "invalid_client":
                rate.protocol_failed(request, endpoint)
            raise
        operation = ("revoke" if endpoint == "revoke" else
                     "refresh" if fields.get("grant_type") == "refresh_token" else "exchange")
        rate.protocol_client(client_id, operation)
        return client_id, secret

    @app.post("/oauth/token", include_in_schema=False)
    async def token(request: Request) -> JSONResponse:
        rate.protocol_inbound(request, "token")
        fields = await form(request, {"grant_type", "client_id", "client_secret", "code", "redirect_uri", "resource",
                                      "code_verifier", "refresh_token", "scope"})
        try:
            client_id, secret = await admitted_client(request, fields, "token")
            result = await run_in_threadpool(server.token, fields, client_id, secret)
        except OAuthError:
            event("token_rejected")
            raise
        event("token_issued", subject=client_id)
        return JSONResponse(result, headers=SAFE_HEADERS)

    @app.post("/oauth/revoke", include_in_schema=False)
    async def revoke(request: Request) -> Response:
        rate.protocol_inbound(request, "revoke")
        fields = await form(request, {"token", "token_type_hint", "client_id", "client_secret"})
        client_id, secret = await admitted_client(request, fields, "revoke")
        await run_in_threadpool(server.revoke_token, fields.get("token", ""), client_id, secret)
        event("token_revoked", subject=client_id)
        return Response(status_code=200, headers=SAFE_HEADERS)

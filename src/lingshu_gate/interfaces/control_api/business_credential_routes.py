"""Secret-safe Console endpoints; credential values never enter an MCP schema."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any, Callable, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from lingshu_gate.access_routes import _require_secure_secret_transport
from lingshu_gate.application.business_credentials import BusinessCredentialService
from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.domain.business_credentials import (
    BusinessCredentialBindingCreate, BusinessCredentialBindingUpdate, BusinessCredentialCreate,
    BusinessCredentialError, BusinessCredentialUpdate,
)
from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed

BASE = "/v1/business-credentials"
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
Body = TypeVar("Body", bound=BaseModel)


class BindingCreate(BusinessCredentialBindingCreate):
    expected_version: int = Field(ge=1)


class BindingUpdate(BusinessCredentialBindingUpdate):
    # Accepted only to check the editor did not change immutable target fields.
    server_id: str | None = None
    adapter: Literal["agent_browser"] | None = None
    tool_prefix: Literal["agent_browser_", ""] | None = None


class SyncRequest(BusinessCredentialBindingUpdate):
    enabled: bool = True


def register_business_credential_routes(app: FastAPI, *, auth: AuthStore, service: BusinessCredentialService) -> None:
    csrf = ConsoleSessionCsrf(auth)

    def error(exc: BusinessCredentialError) -> HTTPException:
        return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}, headers=PRIVATE_HEADERS)

    def actor(request: Request, body: dict[str, Any] | None = None) -> AuthPrincipal:
        current = auth.authenticate_request(request)
        if current.auth_type not in {"session", "token"} or not auth.enabled:
            raise HTTPException(403, detail={"code": "credential_management_denied"}, headers=PRIVATE_HEADERS)
        if body is not None and current.auth_type == "session":
            if not console_origin_allowed(request):
                raise HTTPException(403, detail={"code": "cross_origin_denied"}, headers=PRIVATE_HEADERS)
            target = f"{request.method}:{request.url.path}" + (f"?{request.url.query}" if request.url.query else "")
            nonce = request.headers.get("x-csrf-nonce", "")
            if not re.fullmatch(r"[a-f0-9]{64}", nonce):
                raise HTTPException(403, detail={"code": "invalid_csrf"}, headers=PRIVATE_HEADERS)
            try:
                # The per-request random key never enters ticket storage or its
                # URL. A stored digest cannot serve as a password-guess verifier.
                encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                digest = hmac.new(bytes.fromhex(nonce), encoded, hashlib.sha256).hexdigest()
            except (ValueError, UnicodeError, RecursionError, TypeError):
                raise HTTPException(422, detail={"code": "invalid_business_credential_request"}, headers=PRIVATE_HEADERS) from None
            try:
                csrf.consume(current, request.cookies.get(auth.cookie_name, ""), request.headers.get("x-csrf-token", ""), target, digest)
            except ConsoleCsrfError as exc:
                raise HTTPException(exc.status, detail={"code": exc.code}, headers=PRIVATE_HEADERS) from None
        return current

    async def read_body(request: Request) -> dict[str, Any]:
        # Parse manually: FastAPI/Pydantic validation errors otherwise include
        # rejected inputs, including passwords and unknown secret-bearing keys.
        actor(request)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, detail={"code": "credential_json_required"}, headers=PRIVATE_HEADERS)
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > 131072:
                raise HTTPException(413, detail={"code": "credential_request_too_large"}, headers=PRIVATE_HEADERS)
            chunks.append(chunk)
        try:
            value = json.loads(b"".join(chunks) or b"{}")
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, detail={"code": "invalid_business_credential_request"}, headers=PRIVATE_HEADERS) from None

    def validated(model: type[Body], body: dict[str, Any]) -> Body:
        try:
            return model.model_validate(body)
        except (ValidationError, RecursionError):
            raise HTTPException(422, detail={"code": "invalid_business_credential_request",
                "message": "Check the declared fields, login URL, secret values, selected target and current versions."}, headers=PRIVATE_HEADERS) from None

    async def run(action: Callable[[], dict[str, Any]]) -> JSONResponse:
        try:
            result = await run_in_threadpool(action)
            return JSONResponse(result, headers=PRIVATE_HEADERS)
        except BusinessCredentialError as exc:
            raise error(exc) from None

    @app.post(BASE + "/csrf", tags=["business-credentials"])
    def ticket(request: Request, target: str = Query(max_length=500),
               request_digest: str = Query(pattern=r"^[a-f0-9]{64}$")) -> JSONResponse:
        current = actor(request)
        if current.auth_type != "session" or not console_origin_allowed(request):
            raise HTTPException(403, detail={"code": "session_origin_required"}, headers=PRIVATE_HEADERS)
        valid = re.fullmatch(r"(?:POST|PUT|DELETE):/v1/business-credentials(?:/[a-f0-9]{32})?"
            r"(?:/bindings(?:/[a-f0-9]{32})?(?:/(?:sync|delete-remote))?|/sessions/[A-Za-z0-9_]+/close)?"
            r"(?:\?expected_(?:version|revision)=[1-9][0-9]*)?", target)
        if not valid:
            raise HTTPException(422, detail={"code": "invalid_csrf_target"}, headers=PRIVATE_HEADERS)
        try:
            # A ticket is not authorization. Every mutation checks its exact scope.
            service._current(current)
            result = csrf.issue(current, request.cookies.get(auth.cookie_name, ""), target, request_digest)
            return JSONResponse(result, headers=PRIVATE_HEADERS)
        except ConsoleCsrfError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code}, headers=PRIVATE_HEADERS) from None
        except BusinessCredentialError as exc:
            raise error(exc) from None

    @app.get(BASE, tags=["business-credentials"])
    async def list_credentials(request: Request, scope: Literal["personal", "shared"] = "personal") -> JSONResponse:
        current = actor(request)
        return await run(lambda: service.list(current, scope))

    @app.get(BASE + "/targets", tags=["business-credentials"])
    async def targets(request: Request, scope: Literal["personal", "shared"] = "personal") -> JSONResponse:
        current = actor(request)
        return await run(lambda: service.targets(current, scope))

    @app.get(BASE + "/{credential_id}", tags=["business-credentials"])
    async def detail(credential_id: str, request: Request) -> JSONResponse:
        current = actor(request)
        return await run(lambda: service.detail(credential_id, current))

    @app.post(BASE, tags=["business-credentials"])
    async def create(request: Request) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        _require_secure_secret_transport(request)
        draft = validated(BusinessCredentialCreate, body)
        return await run(lambda: service.create(current, draft))

    @app.put(BASE + "/{credential_id}", tags=["business-credentials"])
    async def update(credential_id: str, request: Request) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        draft = validated(BusinessCredentialUpdate, body)
        if draft.username is not None or draft.password is not None:
            _require_secure_secret_transport(request)
        return await run(lambda: service.update(current, credential_id, draft))

    @app.delete(BASE + "/{credential_id}", tags=["business-credentials"])
    async def delete(credential_id: str, request: Request, expected_version: int = Query(ge=1)) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        if body:
            raise HTTPException(422, detail={"code": "invalid_business_credential_request"}, headers=PRIVATE_HEADERS)
        return await run(lambda: service.delete(current, credential_id, expected_version))

    @app.post(BASE + "/{credential_id}/bindings", tags=["business-credentials"])
    async def bind(credential_id: str, request: Request) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        draft = validated(BindingCreate, body)
        clean = BusinessCredentialBindingCreate.model_validate(draft.model_dump(exclude={"expected_version"}))
        return await run(lambda: service.bind(current, credential_id, clean, draft.expected_version))

    @app.put(BASE + "/{credential_id}/bindings/{binding_id}", tags=["business-credentials"])
    async def update_binding(credential_id: str, binding_id: str, request: Request) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        draft = validated(BindingUpdate, body)

        def perform() -> dict[str, Any]:
            _, binding = service.binding(current, credential_id, binding_id)
            if any(getattr(draft, field) is not None and getattr(draft, field) != binding[field]
                   for field in ("server_id", "adapter", "tool_prefix")):
                raise BusinessCredentialError("binding_target_immutable", "Create a separate binding for a different target.", 422)
            clean = BusinessCredentialBindingUpdate.model_validate(draft.model_dump(exclude={"server_id", "adapter", "tool_prefix"}))
            return service.update_binding(current, credential_id, binding_id, clean)
        return await run(perform)

    @app.delete(BASE + "/{credential_id}/bindings/{binding_id}", tags=["business-credentials"])
    async def delete_binding(credential_id: str, binding_id: str, request: Request,
                             expected_revision: int = Query(ge=1)) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        if body:
            raise HTTPException(422, detail={"code": "invalid_business_credential_request"}, headers=PRIVATE_HEADERS)
        return await run(lambda: service.delete_binding(current, credential_id, binding_id, expected_revision))

    async def remote(credential_id: str, binding_id: str, request: Request, *, delete_remote: bool) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        draft = validated(SyncRequest, body)
        return await run(lambda: service.synchronize(current, credential_id, binding_id,
            draft.expected_version, draft.expected_revision, delete_remote=delete_remote))

    @app.post(BASE + "/{credential_id}/bindings/{binding_id}/sync", tags=["business-credentials"])
    async def sync(credential_id: str, binding_id: str, request: Request) -> JSONResponse:
        return await remote(credential_id, binding_id, request, delete_remote=False)

    @app.post(BASE + "/{credential_id}/bindings/{binding_id}/delete-remote", tags=["business-credentials"])
    async def delete_remote(credential_id: str, binding_id: str, request: Request) -> JSONResponse:
        return await remote(credential_id, binding_id, request, delete_remote=True)

    @app.get(BASE + "/{credential_id}/sessions", tags=["business-credentials"])
    async def sessions(credential_id: str, request: Request) -> JSONResponse:
        current = actor(request)
        return await run(lambda: service.sessions(current, credential_id))

    @app.post(BASE + "/{credential_id}/sessions/{session_id}/close", tags=["business-credentials"])
    async def close(credential_id: str, session_id: str, request: Request) -> JSONResponse:
        body = await read_body(request)
        current = actor(request, body)
        if body:
            raise HTTPException(422, detail={"code": "invalid_business_credential_request"}, headers=PRIVATE_HEADERS)
        return await run(lambda: service.close_session(current, credential_id, session_id))

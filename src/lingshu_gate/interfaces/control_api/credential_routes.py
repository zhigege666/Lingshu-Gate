"""Secret-safe HTTP adapters for shared system credential management."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.application.shared_credentials import SharedCredentialService, credential_context
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.models import CredentialResponse, CredentialSaveRequest
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext

PRIVATE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def register_credential_routes(
    app: FastAPI, *, credential_store: CredentialStore, observability_store: ObservabilityStore,
    require_authenticated: AuthDependency, access_store: AccessControlStore,
    service: SharedCredentialService,
) -> None:
    """Keep the public route shapes while sharing CAS, policy and idempotency."""

    def require_system_credentials(request: Request) -> None:
        principal = require_authenticated(request)
        try:
            access_store.require_control_permission(principal, "credentials.manage.system")
        except AccessDeniedError:
            raise HTTPException(403, detail={"code": "credential_permission_denied"}, headers=PRIVATE_HEADERS) from None

    def context(request: Request, *, write: bool = False) -> ToolInvocationContext:
        principal = require_authenticated(request)
        if write and principal.auth_type == "session" and not console_origin_allowed(request, required=False):
            raise HTTPException(403, detail={"code": "cross_origin_denied"}, headers=PRIVATE_HEADERS)
        return credential_context(principal)

    async def read_body(request: Request) -> dict[str, Any]:
        # FastAPI validation otherwise reflects rejected input, including value.
        context(request, write=True)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(415, detail={"code": "credential_json_required"}, headers=PRIVATE_HEADERS)
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > 131072:
                raise HTTPException(413, detail={"code": "credential_request_too_large"}, headers=PRIVATE_HEADERS)
            chunks.append(chunk)
        try:
            value = json.loads(b"".join(chunks))
            if not isinstance(value, dict):
                raise ValueError
            parsed = CredentialSaveRequest.model_validate(value)
            result = parsed.model_dump(mode="json", exclude_none=True)
            # Retrying a legacy REST request without a key is a new request.
            # MCP always requires an explicit key.
            result.setdefault("idempotency_key", uuid4().hex)
            return result
        except (ValidationError, ValueError, UnicodeError, RecursionError, TypeError):
            raise HTTPException(422, detail={"code": "credential_request_invalid",
                "message": "Check the declared credential fields and current revision."}, headers=PRIVATE_HEADERS) from None

    async def invoke(action: Callable[[], Any]) -> JSONResponse:
        try:
            return JSONResponse(await run_in_threadpool(action), headers=PRIVATE_HEADERS)
        except ToolExecutionError as exc:
            status = {"credential_permission_denied": 403, "credential_unavailable": 404,
                "credential_request_invalid": 422, "credential_http_scope_invalid": 400}.get(exc.code, 409)
            raise HTTPException(status, detail=exc.to_payload()["error"], headers=PRIVATE_HEADERS) from None

    @app.get("/v1/credentials", response_model=list[CredentialResponse], tags=["credentials"],
             dependencies=[Depends(require_system_credentials)])
    async def list_credentials(request: Request) -> JSONResponse:
        actor = context(request)
        return await invoke(lambda: service.list({}, actor)["credentials"])

    @app.get("/v1/credentials/{credential_id}", response_model=CredentialResponse, tags=["credentials"],
             dependencies=[Depends(require_system_credentials)])
    async def get_credential(credential_id: str, request: Request) -> JSONResponse:
        actor = context(request)
        return await invoke(lambda: service.get({"credential_id": credential_id}, actor))

    @app.post("/v1/credentials", response_model=CredentialResponse, tags=["credentials"],
              dependencies=[Depends(require_system_credentials)])
    async def create_credential(request: Request) -> JSONResponse:
        body, actor = await read_body(request), context(request, write=True)
        return await invoke(lambda: service.create(body, actor))

    @app.put("/v1/credentials/{credential_id}", response_model=CredentialResponse, tags=["credentials"],
             dependencies=[Depends(require_system_credentials)])
    async def update_credential(credential_id: str, request: Request) -> JSONResponse:
        body, actor = await read_body(request), context(request, write=True)
        if body.get("credential_id", credential_id) != credential_id:
            raise HTTPException(422, detail={"code": "credential_request_invalid"}, headers=PRIVATE_HEADERS)
        return await invoke(lambda: service.update({**body, "credential_id": credential_id}, actor))

    @app.delete("/v1/credentials/{credential_id}", response_model=CredentialResponse, tags=["credentials"],
                dependencies=[Depends(require_system_credentials)])
    async def delete_credential(credential_id: str, request: Request) -> JSONResponse:
        actor = context(request, write=True)
        body = {"credential_id": credential_id, "expected_revision": request.query_params.get("expected_revision"),
                "idempotency_key": request.query_params.get("idempotency_key") or uuid4().hex}
        return await invoke(lambda: service.delete(body, actor))

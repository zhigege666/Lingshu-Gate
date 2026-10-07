"""HTTP adapters for the same plan/apply/status/cancel used by management MCP."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf
from lingshu_gate.application.external_mcp_configuration import ExternalMcpConfigurationService
from lingshu_gate.auth import AuthStore
from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext


def register_external_mcp_config_routes(app: FastAPI, *, auth: AuthStore, service: ExternalMcpConfigurationService) -> None:
    csrf = ConsoleSessionCsrf(auth)

    def context(request: Request, *, body: dict[str, Any] | None = None) -> ToolInvocationContext:
        principal = auth.authenticate_request(request)
        if body is not None and principal.auth_type == "session":
            if not console_origin_allowed(request):
                raise HTTPException(status_code=403, detail={"code": "cross_origin_denied", "message": "Cross-origin configuration mutations are denied."})
            request_digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            try:
                csrf.consume(principal, request.cookies.get(auth.cookie_name, ""), request.headers.get("x-csrf-token", ""),
                             request.url.path, request_digest)
            except ConsoleCsrfError as exc:
                raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": "Obtain a new Console request ticket."}) from None
        return ToolInvocationContext(actor_id=principal.id, username=principal.username, auth_type=principal.auth_type,
            token_id=principal.token_id, correlation_id=uuid4().hex, roles=principal.roles, permissions=principal.permissions,
            scopes=principal.scopes, delegated_scopes=principal.delegated_scopes, session_id=principal.session_id)

    def invoke(action: Any) -> dict[str, Any]:
        try:
            return dict(action())
        except ToolExecutionError as exc:
            code = exc.code
            status = 403 if code in {"external_config_admin_required", "external_config_token_invalid", "external_config_session_invalid", "external_config_permission_denied"} else 409
            raise HTTPException(status_code=status, detail=exc.to_payload()["error"]) from None

    @app.post("/v1/mcp/external-configs/csrf", tags=["mcp-configs"])
    def request_ticket(request: Request, action: Literal["plan", "apply", "cancel"],
                       request_digest: str = Query(pattern=r"^[a-f0-9]{64}$"),
                       operation_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$")) -> JSONResponse:
        principal = auth.authenticate_request(request)
        if principal.auth_type != "session":
            raise HTTPException(status_code=403, detail={"code": "session_required"})
        if not console_origin_allowed(request):
            raise HTTPException(status_code=403, detail={"code": "cross_origin_denied"})
        if (action == "cancel") != (operation_id is not None):
            raise HTTPException(status_code=422, detail={"code": "invalid_csrf_target"})
        def authorize() -> dict[str, Any]:
            service._authorize(context(request))
            return {}
        invoke(authorize)
        target = (f"/v1/mcp/external-configs/operations/{operation_id}/cancel" if action == "cancel"
                  else f"/v1/mcp/external-configs/{action}")
        try:
            result = csrf.issue(principal, request.cookies.get(auth.cookie_name, ""), target, request_digest)
        except ConsoleCsrfError as exc:
            raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None
        return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @app.post("/v1/mcp/external-configs/plan", tags=["mcp-configs"])
    def plan(body: dict[str, Any], request: Request) -> dict[str, Any]:
        return invoke(lambda: service.plan(body, context(request, body=body)))

    @app.post("/v1/mcp/external-configs/apply", tags=["mcp-configs"])
    def apply(body: dict[str, Any], request: Request) -> dict[str, Any]:
        return invoke(lambda: service.apply(body, context(request, body=body)))

    @app.get("/v1/mcp/external-configs/operations/{operation_id}", tags=["mcp-configs"])
    def status(operation_id: str, request: Request) -> dict[str, Any]:
        return invoke(lambda: service.status({"operation_id": operation_id}, context(request)))

    @app.get("/v1/mcp/external-configs/targets/{server_id}", tags=["mcp-configs"])
    def target_status(server_id: str, request: Request) -> dict[str, Any]:
        return invoke(lambda: service.status({"server_id": server_id}, context(request)))

    @app.post("/v1/mcp/external-configs/operations/{operation_id}/cancel", tags=["mcp-configs"])
    def cancel(operation_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        return invoke(lambda: service.cancel({**body, "operation_id": operation_id}, context(request, body=body)))

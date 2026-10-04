"""HTTP adapters for the same plan/apply/status/cancel used by management MCP."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from lingshu_gate.application.external_mcp_configuration import ExternalMcpConfigurationService
from lingshu_gate.auth import AuthStore
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext


def register_external_mcp_config_routes(app: FastAPI, *, auth: AuthStore, service: ExternalMcpConfigurationService) -> None:
    def context(request: Request, *, mutation: bool = False) -> ToolInvocationContext:
        principal = auth.authenticate_request(request)
        if mutation and principal.auth_type == "session":
            origin = request.headers.get("origin")
            try:
                supplied, target = urlsplit(origin or ""), urlsplit(str(request.base_url))
                same_origin = (
                    not supplied.username and not supplied.password and not supplied.path and not supplied.query and not supplied.fragment
                    and (supplied.scheme, supplied.hostname, supplied.port or (443 if supplied.scheme == "https" else 80))
                    == (target.scheme, target.hostname, target.port or (443 if target.scheme == "https" else 80))
                )
            except ValueError:
                same_origin = False
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin is not None and not same_origin):
                raise HTTPException(status_code=403, detail={"code": "cross_origin_denied", "message": "Cross-origin configuration mutations are denied."})
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

    @app.post("/v1/mcp/external-configs/plan", tags=["mcp-configs"])
    def plan(body: dict[str, Any], request: Request) -> dict[str, Any]:
        return invoke(lambda: service.plan(body, context(request, mutation=True)))

    @app.post("/v1/mcp/external-configs/apply", tags=["mcp-configs"])
    def apply(body: dict[str, Any], request: Request) -> dict[str, Any]:
        return invoke(lambda: service.apply(body, context(request, mutation=True)))

    @app.get("/v1/mcp/external-configs/operations/{operation_id}", tags=["mcp-configs"])
    def status(operation_id: str, request: Request) -> dict[str, Any]:
        return invoke(lambda: service.status({"operation_id": operation_id}, context(request)))

    @app.get("/v1/mcp/external-configs/targets/{server_id}", tags=["mcp-configs"])
    def target_status(server_id: str, request: Request) -> dict[str, Any]:
        return invoke(lambda: service.status({"server_id": server_id}, context(request)))

    @app.post("/v1/mcp/external-configs/operations/{operation_id}/cancel", tags=["mcp-configs"])
    def cancel(operation_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        return invoke(lambda: service.cancel({**body, "operation_id": operation_id}, context(request, mutation=True)))

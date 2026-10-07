"""HTTP adapters for bounded, on-demand tool discovery and invocation."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import ValidationError

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.tool_catalog import ToolCatalog


def register_catalog_routes(app: FastAPI, *, catalog: ToolCatalog, require_authenticated: AuthDependency) -> None:
    def call(name: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        try:
            response = catalog.call(name, body, require_authenticated(request),
                refresh_principal=lambda: require_authenticated(request),
                correlation_id=request.headers.get("x-correlation-id"))
            return response.model_dump() if name == "gate_tool_invoke" else response.output
        except ValidationError:
            raise HTTPException(400, detail={"code": "catalog_parameters_invalid"}) from None
        except AccessDeniedError:
            raise HTTPException(404, detail={"code": "catalog_tool_unavailable"}) from None
        except ToolExecutionError as exc:
            status = 404 if exc.code == "catalog_tool_unavailable" else 409 if exc.code in {
                "catalog_cursor_invalid", "catalog_changed", "catalog_schema_revision_conflict", "catalog_namespace_conflict"
            } else 400
            raise HTTPException(status, detail=exc.to_payload()["error"]) from None

    @app.post("/v1/catalog/search", tags=["tools"])
    def search(body: dict[str, Any], request: Request,
               principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        return call("gate_catalog_search", body, request)

    @app.post("/v1/catalog/describe", tags=["tools"])
    def describe(body: dict[str, Any], request: Request,
                 principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        return call("gate_tool_describe", body, request)

    @app.post("/v1/catalog/invoke", tags=["tools"])
    def invoke(body: dict[str, Any], request: Request,
               principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        return call("gate_tool_invoke", body, request)

    @app.post("/v1/catalog/instances", tags=["tools"])
    def instances(body: dict[str, Any], request: Request,
                  principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        return call("gate_instance_list", body, request)

    @app.post("/v1/catalog/sessions/open", tags=["tools"])
    def session_open(body: dict[str, Any], request: Request,
                     principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        return call("gate_instance_session_open", body, request)

    @app.post("/v1/catalog/sessions/close", tags=["tools"])
    def session_close(body: dict[str, Any], request: Request,
                      principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        return call("gate_instance_session_close", body, request)

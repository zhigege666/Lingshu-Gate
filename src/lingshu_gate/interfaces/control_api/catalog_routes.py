"""HTTP adapters for bounded, on-demand tool discovery and invocation."""
from __future__ import annotations

from lingshu_gate.telemetry_http import request_correlation

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.tool_catalog import CatalogSearch, ToolCatalog
from lingshu_gate.authorization_discovery import PinnedTool
from lingshu_gate.pinned_tools import project_pins


class PinPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pinned_tools: list[PinnedTool] = Field(max_length=20)


def register_catalog_routes(app: FastAPI, *, catalog: ToolCatalog, require_authenticated: AuthDependency) -> None:
    @app.post("/v1/catalog/groups", tags=["tools"])
    def visible_groups(body: CatalogSearch, request: Request,
                       principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        try:
            return catalog.visible_groups(require_authenticated(request), body)
        except (AccessDeniedError, ToolExecutionError):
            raise HTTPException(409, detail={"code": "catalog_unavailable_or_changed"}) from None

    @app.post("/v1/catalog/pins/preview", tags=["tools"])
    def pin_preview(body: PinPreview, request: Request,
                    principal: AuthPrincipal = Depends(require_authenticated)) -> dict[str, Any]:
        pins = project_pins(catalog, require_authenticated(request),
            {"tool_discovery_mode": "on_demand", "pinned_tools": [pin.model_dump() for pin in body.pinned_tools]})
        return {"available_to_current_user": [{"kind": pin.kind, "tool_ref": pin.tool_ref, "name": pin.payload["title"]} for pin in pins],
                "authorization_checked_at_invocation": True}

    def call(name: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        try:
            response = catalog.call(name, body, require_authenticated(request),
                refresh_principal=lambda: require_authenticated(request),
                correlation_id=request_correlation(request))
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

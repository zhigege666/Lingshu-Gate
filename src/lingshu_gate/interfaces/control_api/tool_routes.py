"""Tool discovery and invocation HTTP routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.models import (
    GateInvokeRequest,
    ToolDefinition,
    ToolInvokeRequest,
    ToolInvokeResponse,
)
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolNotFoundError, ToolRegistry


def register_tool_routes(
    app: FastAPI,
    *,
    registry: ToolRegistry,
    access_store: AccessControlStore,
    observability_store: ObservabilityStore,
    require_authenticated: AuthDependency,
) -> None:
    """Register authenticated tool catalog and invocation routes."""

    @app.get("/v1/tools", response_model=list[ToolDefinition], tags=["tools"])
    def list_tools(
        principal: AuthPrincipal = Depends(require_authenticated),
    ) -> list[ToolDefinition]:
        return access_store.visible_tools(principal, registry.list_definitions())

    @app.get(
        "/v1/tools/{tool_id}",
        response_model=ToolDefinition,
        tags=["tools"],
    )
    def get_tool(
        tool_id: str,
        principal: AuthPrincipal = Depends(require_authenticated),
    ) -> ToolDefinition:
        try:
            definition = registry.get_definition(tool_id)
            if not access_store.visible_tools(principal, [definition]):
                raise HTTPException(
                    status_code=404,
                    detail=f"Tool not found: {tool_id}",
                )
            return definition
        except ToolNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Tool not found: {tool_id}",
            ) from exc

    def invoke_for_principal(
        principal: AuthPrincipal,
        *,
        tool_id: str,
        arguments: dict[str, object],
        http_request: Request,
        add_log: bool,
    ) -> ToolInvokeResponse:
        try:
            response = access_store.invoke_tool(
                registry,
                principal,
                tool_id,
                arguments,
                correlation_id=http_request.headers.get("x-correlation-id"),
            )
        except AccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=exc.reason) from exc
        except ToolNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Tool not found: {tool_id}",
            ) from exc

        observability_store.emit_event(
            "gate.tool.invoked",
            source="tools",
            subject_type="tool",
            subject_id=tool_id,
            payload={"ok": response.ok},
        )
        if add_log:
            observability_store.add_log(
                "info" if response.ok else "error",
                f"Tool invoked: {tool_id}",
                source="tools",
                tool_id=tool_id,
                event_type="gate.tool.invoked",
                payload={"ok": response.ok, "error": response.error},
            )
        return response

    @app.post(
        "/v1/tools/{tool_id}/invoke",
        response_model=ToolInvokeResponse,
        tags=["tools"],
    )
    def invoke_tool(
        tool_id: str,
        request: ToolInvokeRequest,
        http_request: Request,
        principal: AuthPrincipal = Depends(require_authenticated),
    ) -> ToolInvokeResponse:
        return invoke_for_principal(
            principal,
            tool_id=tool_id,
            arguments=request.arguments,
            http_request=http_request,
            add_log=True,
        )

    @app.post("/v1/invoke", response_model=ToolInvokeResponse, tags=["tools"])
    def invoke(
        request: GateInvokeRequest,
        http_request: Request,
        principal: AuthPrincipal = Depends(require_authenticated),
    ) -> ToolInvokeResponse:
        return invoke_for_principal(
            principal,
            tool_id=request.tool_id,
            arguments=request.arguments,
            http_request=http_request,
            add_log=False,
        )

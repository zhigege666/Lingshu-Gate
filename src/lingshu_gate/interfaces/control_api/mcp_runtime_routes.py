"""MCP runtime server control-plane routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_server_detail import build_mcp_server_detail
from lingshu_gate.models import McpServerListResponse, McpServerStatusResponse
from lingshu_gate.observability_store import ObservabilityStore


def register_mcp_runtime_routes(
    app: FastAPI,
    *,
    settings: Settings,
    mcp_runtime: McpRuntimeManager,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register server inventory and lifecycle routes."""

    @app.get(
        "/v1/mcp/servers",
        response_model=McpServerListResponse,
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_mcp_servers() -> McpServerListResponse:
        return mcp_runtime.list_servers()

    @app.get(
        "/v1/mcp/servers/{server_id}",
        response_model=McpServerStatusResponse,
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def get_mcp_server(server_id: str) -> McpServerStatusResponse:
        try:
            return mcp_runtime.get_server(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/v1/mcp/servers/{server_id}/detail",
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def get_mcp_server_detail(server_id: str) -> dict[str, Any]:
        try:
            return build_mcp_server_detail(
                settings,
                mcp_runtime,
                observability_store,
                server_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/v1/mcp/servers/{server_id}/start",
        response_model=McpServerStatusResponse,
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def start_mcp_server(server_id: str) -> McpServerStatusResponse:
        try:
            server = mcp_runtime.request_start(server_id)
        except KeyError as exc:
            observability_store.add_log(
                "error",
                f"Server start failed: {server_id}",
                source="runtime",
                server_id=server_id,
                event_type="gate.server.failed",
                payload={"error": str(exc)},
            )
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        observability_store.emit_event(
            "gate.server.started",
            source="runtime",
            subject_type="server",
            subject_id=server_id,
        )
        return server

    @app.post(
        "/v1/mcp/servers/{server_id}/stop",
        response_model=McpServerStatusResponse,
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def stop_mcp_server(server_id: str) -> McpServerStatusResponse:
        try:
            server = mcp_runtime.request_stop(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        observability_store.emit_event(
            "gate.server.stopped",
            source="runtime",
            subject_type="server",
            subject_id=server_id,
        )
        return server

    @app.post(
        "/v1/mcp/servers/{server_id}/restart",
        response_model=McpServerStatusResponse,
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def restart_mcp_server(server_id: str) -> McpServerStatusResponse:
        try:
            server = mcp_runtime.request_restart(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        observability_store.emit_event(
            "gate.server.restarted",
            source="runtime",
            subject_type="server",
            subject_id=server_id,
        )
        return server

    @app.get(
        "/v1/mcp/servers/{server_id}/tools",
        tags=["mcp"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_mcp_server_tools(server_id: str) -> list[dict[str, object]]:
        try:
            return mcp_runtime.list_server_tools(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

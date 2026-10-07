"""Logs and events control-plane routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.observability_store import ObservabilityStore


def _sse(items: list[dict[str, Any]]) -> Iterator[str]:
    for item in items:
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"


def register_observability_routes(
    app: FastAPI,
    *,
    observability_store: ObservabilityStore,
    access_store: AccessControlStore,
    mcp_runtime: McpRuntimeManager,
    require_operations_manager: AuthDependency,
) -> None:
    """Register operational log and event query/stream routes."""

    def scope_options(principal: AuthPrincipal) -> tuple[list[dict[str, Any]], bool]:
        current = mcp_runtime.iter_manifests()
        candidates = set(current) | set(observability_store.historical_server_ids())
        permitted = access_store.observability_server_ids(principal, candidates)
        can_read_all = permitted is None
        visible = sorted(candidates) if permitted is None else permitted
        return [{"id": server_id, "name": current[server_id].name or server_id if server_id in current else server_id,
                 "availability": "current" if server_id in current else "historical"}
                for server_id in visible], can_read_all

    def query_scope(principal: AuthPrincipal, server_id: str | None) -> list[str] | None:
        # Global readers need no historical directory for an unfiltered query.
        # Keep the shared policy (including token ceilings) authoritative.
        if not server_id and access_store.observability_server_ids(principal, ()) is None:
            return None
        options, can_read_all = scope_options(principal)
        visible = [item["id"] for item in options]
        if server_id and server_id not in visible:
            raise HTTPException(404, detail="MCP log scope not found")
        return None if can_read_all else visible

    @app.get("/v1/observability/mcp-scopes", tags=["logs", "events"])
    def list_mcp_scopes(
        q: str = Query("", max_length=200),
        server_id: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        principal: AuthPrincipal = Depends(require_operations_manager),
    ) -> dict[str, Any]:
        options, can_read_all = scope_options(principal)
        if server_id:
            options = [item for item in options if item["id"] == server_id]
            if not options:
                raise HTTPException(404, detail="MCP log scope not found")
        needle = q.strip().casefold()
        filtered = [item for item in options if not needle or needle in item["id"].casefold()
                    or needle in item["name"].casefold()]
        return {"scopes": filtered[offset:offset + limit], "total": len(filtered),
                "offset": offset, "limit": limit,
                "capabilities": {"can_read_all": can_read_all,
                                 "all_scope": "global" if can_read_all else "authorized_services"}}

    @app.get("/v1/observability/tool-scopes", tags=["logs"])
    def list_tool_scopes(
        server_id: str = Query(..., min_length=1),
        q: str = Query("", max_length=200),
        tool_id: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        principal: AuthPrincipal = Depends(require_operations_manager),
    ) -> dict[str, Any]:
        # Log readers need a whole-service grant; discovery/invocation grants
        # neither confer nor enlarge operational log access.
        query_scope(principal, server_id)
        options = {item: {"id": item, "name": item, "availability": "historical"}
                   for item in observability_store.historical_tool_ids(server_id)}
        for definition in mcp_runtime.registry.list_definitions():
            if definition.source == "mcp" and definition.metadata.get("server_id") == server_id:
                options[definition.id] = {"id": definition.id, "name": definition.name,
                                          "availability": "current"}
        needle = q.strip().casefold()
        filtered = [item for key, item in sorted(options.items())
                    if (not tool_id or key == tool_id) and
                    (not needle or needle in key.casefold() or needle in item["name"].casefold())]
        return {"scopes": filtered[offset:offset + limit], "total": len(filtered),
                "offset": offset, "limit": limit}

    @app.get(
        "/v1/logs",
        tags=["logs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_logs(
        level: str | None = None,
        server_id: str | None = None,
        tool_id: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
        keyword: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        principal: AuthPrincipal = Depends(require_operations_manager),
    ) -> dict[str, Any]:
        return {
            "logs": observability_store.list_logs(
                allowed_server_ids=query_scope(principal, server_id),
                level=level,
                server_id=server_id,
                tool_id=tool_id,
                event_type=event_type,
                source=source,
                keyword=keyword,
                limit=limit,
            )
        }

    @app.get(
        "/v1/events",
        tags=["events"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_events(
        type: str | None = None,
        event_type: str | None = None,
        subject_id: str | None = None,
        server_id: str | None = None,
        source: str | None = None,
        keyword: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        principal: AuthPrincipal = Depends(require_operations_manager),
    ) -> dict[str, Any]:
        return {
            "events": observability_store.list_events(
                allowed_server_ids=query_scope(principal, server_id),
                server_id=server_id,
                event_type=event_type or type,
                subject_id=subject_id,
                source=source,
                keyword=keyword,
                limit=limit,
            )
        }

    @app.get(
        "/v1/logs/stream",
        tags=["logs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def stream_logs(server_id: str | None = None,
                    principal: AuthPrincipal = Depends(require_operations_manager)) -> StreamingResponse:
        return StreamingResponse(
            _sse(observability_store.list_logs(limit=100, server_id=server_id,
                                             allowed_server_ids=query_scope(principal, server_id))),
            media_type="text/event-stream",
        )

    @app.get(
        "/v1/events/stream",
        tags=["events"],
        dependencies=[Depends(require_operations_manager)],
    )
    def stream_events(server_id: str | None = None,
                      principal: AuthPrincipal = Depends(require_operations_manager)) -> StreamingResponse:
        return StreamingResponse(
            _sse(observability_store.list_events(limit=100, server_id=server_id,
                                               allowed_server_ids=query_scope(principal, server_id))),
            media_type="text/event-stream",
        )

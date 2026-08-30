"""Logs and events control-plane routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI, Query
from fastapi.responses import StreamingResponse

from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.observability_store import ObservabilityStore


def _sse(items: list[dict[str, Any]]) -> Iterator[str]:
    for item in items:
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"


def register_observability_routes(
    app: FastAPI,
    *,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register operational log and event query/stream routes."""

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
    ) -> dict[str, Any]:
        return {
            "logs": observability_store.list_logs(
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
        source: str | None = None,
        keyword: str | None = None,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict[str, Any]:
        return {
            "events": observability_store.list_events(
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
    def stream_logs() -> StreamingResponse:
        return StreamingResponse(
            _sse(observability_store.list_logs(limit=100)),
            media_type="text/event-stream",
        )

    @app.get(
        "/v1/events/stream",
        tags=["events"],
        dependencies=[Depends(require_operations_manager)],
    )
    def stream_events() -> StreamingResponse:
        return StreamingResponse(
            _sse(observability_store.list_events(limit=100)),
            media_type="text/event-stream",
        )

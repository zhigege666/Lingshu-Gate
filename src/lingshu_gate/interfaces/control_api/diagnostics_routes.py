"""Runtime diagnostics control-plane routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI

from lingshu_gate.config import Settings
from lingshu_gate.diagnostics import run_diagnostics
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.memory_diagnostics import collect_memory_snapshot
from lingshu_gate.models import DiagnosticsResponse
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRegistry

logger = logging.getLogger(__name__)


def register_diagnostics_routes(
    app: FastAPI,
    *,
    settings: Settings,
    registry: ToolRegistry,
    mcp_runtime: McpRuntimeManager,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register diagnostic report and memory-snapshot routes."""

    def collect_diagnostics(*, add_log: bool) -> DiagnosticsResponse:
        result = run_diagnostics(settings, registry, mcp_runtime)
        observability_store.emit_event(
            "gate.diagnostics.completed",
            source="diagnostics",
            payload={"ok": result.ok, "check_count": len(result.checks)},
        )
        if add_log:
            observability_store.add_log(
                "info",
                "Diagnostics completed",
                source="diagnostics",
                event_type="gate.diagnostics.completed",
                payload={"ok": result.ok},
            )
        return result

    @app.get(
        "/v1/diagnostics",
        response_model=DiagnosticsResponse,
        tags=["diagnostics"],
        dependencies=[Depends(require_operations_manager)],
    )
    def diagnostics() -> DiagnosticsResponse:
        return collect_diagnostics(add_log=True)

    @app.post(
        "/v1/diagnostics/run",
        response_model=DiagnosticsResponse,
        tags=["diagnostics"],
        dependencies=[Depends(require_operations_manager)],
    )
    def run_diagnostics_endpoint() -> DiagnosticsResponse:
        return collect_diagnostics(add_log=False)

    @app.get(
        "/v1/diagnostics/memory",
        tags=["diagnostics"],
        dependencies=[Depends(require_operations_manager)],
    )
    def memory_diagnostics() -> dict[str, Any]:
        snapshot = collect_memory_snapshot()
        log_event(
            logger,
            logging.INFO,
            "gate.diagnostics.memory_snapshot_requested",
            "Memory snapshot requested",
            memory=snapshot,
        )
        observability_store.emit_event(
            "gate.diagnostics.memory_snapshot",
            source="diagnostics",
            payload={"available": True},
        )
        return snapshot

"""Runtime environment and cache control-plane routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.runtime_cache_management import (
    clear_runtime_cache,
    runtime_cache_status,
)
from lingshu_gate.runtime_environment import detect_runtime_environment


def register_runtime_routes(
    app: FastAPI,
    *,
    settings: Settings,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register runtime inspection and cache-management routes."""

    @app.get(
        "/v1/runtime/cache",
        tags=["runtime"],
        dependencies=[Depends(require_operations_manager)],
    )
    def get_runtime_cache() -> dict[str, Any]:
        return runtime_cache_status(settings)

    @app.delete(
        "/v1/runtime/cache/{cache_name}",
        tags=["runtime"],
        dependencies=[Depends(require_operations_manager)],
    )
    def delete_runtime_cache(cache_name: str) -> dict[str, Any]:
        try:
            result = clear_runtime_cache(settings, cache_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        observability_store.emit_event(
            "gate.runtime.cache_cleared",
            source="runtime",
            subject_type="runtime_cache",
            subject_id=cache_name,
            payload={
                "removed": result.get("removed"),
                "before": result.get("before"),
                "after": result.get("after"),
            },
        )
        observability_store.add_log(
            "warning",
            f"Runtime cache cleared: {cache_name}",
            source="runtime",
            event_type="gate.runtime.cache_cleared",
            payload=result,
        )
        return result

    @app.get(
        "/v1/runtime/environment",
        tags=["runtime"],
        dependencies=[Depends(require_operations_manager)],
    )
    def runtime_environment() -> dict[str, Any]:
        report = detect_runtime_environment(settings)
        observability_store.emit_event(
            "gate.runtime.environment_probed",
            source="runtime",
            payload={
                "platform": report.get("platform"),
                "deployment": report.get("gate_deployment"),
                "docker_mode": report.get("docker", {}).get("mode"),
            },
        )
        return report

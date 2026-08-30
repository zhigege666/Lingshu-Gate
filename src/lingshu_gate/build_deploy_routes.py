"""FastAPI route registration for Build + Deploy Pipeline."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from lingshu_gate.build_deploy import (
    BuildBlocked,
    BuildDeployStore,
    LocalExecutionBlocked,
)
from lingshu_gate.models import (
    DeployBuildRequest,
    ResourceDeleteConflict,
    RollbackDeploymentRequest,
)

TERMINAL_BUILD_STATUSES = {"success", "failed", "unsupported", "cancelled"}


def register_build_deploy_routes(
    app: FastAPI,
    store: BuildDeployStore,
    require_operations_manager: Any,
) -> None:
    """Register build and deployment endpoints."""

    @app.get("/v1/builds", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def list_builds() -> dict[str, Any]:
        return {"builds": store.list_builds()}

    @app.post("/v1/builds/preflight", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def preflight_build(body: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(body.get("upload_id") or "").strip()
        if not upload_id:
            raise HTTPException(status_code=400, detail="upload_id is required")
        try:
            return store.preflight_upload(upload_id, runtime_override=_runtime_override(body), project_root=_optional_string(body.get("project_root")), refresh=_as_bool(body.get("refresh", False)))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/builds/plan", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def plan_build(body: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(body.get("upload_id") or "").strip()
        if not upload_id:
            raise HTTPException(status_code=400, detail="upload_id is required")
        try:
            _require_allowed_fields(
                body,
                {
                    "upload_id",
                    "runtime_override",
                    "project_root",
                    "run_install",
                    "run_build",
                    "refresh",
                },
            )
            return store.plan_upload(upload_id, runtime_override=_runtime_override(body), project_root=_optional_string(body.get("project_root")), run_install=_as_bool(body.get("run_install", True)), run_build=_as_bool(body.get("run_build", True)), refresh=_as_bool(body.get("refresh", False)))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/builds", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def create_build(body: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(body.get("upload_id") or "").strip()
        if not upload_id:
            raise HTTPException(status_code=400, detail="upload_id is required")
        try:
            _require_allowed_fields(
                body,
                {
                    "upload_id",
                    "runtime_override",
                    "project_root",
                    "run_install",
                    "run_build",
                    "timeout_seconds",
                },
            )
            return store.build_upload(
                upload_id,
                run_install=_as_bool(body.get("run_install", True)),
                run_build=_as_bool(body.get("run_build", True)),
                timeout_seconds=_as_int(body.get("timeout_seconds", 300), default=300),
                runtime_override=_runtime_override(body),
                project_root=_optional_string(body.get("project_root")),
            )
        except LocalExecutionBlocked as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
        except BuildBlocked as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message, "runtime": exc.preflight.get("runtime"), "preflight": exc.preflight}) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/builds/{build_id}", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def get_build(build_id: str) -> dict[str, Any]:
        try:
            return store.get_build(build_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/v1/builds/{build_id}", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def delete_build(build_id: str) -> dict[str, Any]:
        try:
            return store.delete_build(build_id)
        except ResourceDeleteConflict as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/builds/{build_id}/logs", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def list_build_logs(build_id: str, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
        try:
            return {"logs": store.list_build_logs(build_id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/builds/{build_id}/logs/stream", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def stream_build_logs(build_id: str, interval_seconds: float = Query(1.0, ge=0.5, le=10.0)) -> StreamingResponse:
        try:
            store.get_build(build_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        async def event_generator():
            last_sequence = -1
            while True:
                try:
                    build = store.get_build(build_id)
                    logs = store.list_build_logs(build_id, limit=1000)
                except KeyError:
                    yield _sse("error", {"detail": f"build not found: {build_id}"})
                    return
                new_logs = [log for log in logs if int(log.get("sequence") or 0) > last_sequence]
                for log in new_logs:
                    last_sequence = int(log.get("sequence") or last_sequence)
                    yield _sse("log", log)
                yield _sse("status", {"build_id": build_id, "status": build.get("status"), "updated_at": build.get("updated_at"), "log_count": len(logs)})
                if build.get("status") in TERMINAL_BUILD_STATUSES:
                    return
                await asyncio.sleep(interval_seconds)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/v1/builds/{build_id}/cancel", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def cancel_build(build_id: str) -> dict[str, Any]:
        try:
            return store.cancel_build(build_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/builds/{build_id}/deploy", tags=["deployments"], dependencies=[Depends(require_operations_manager)])
    def deploy_build(
        build_id: str,
        body: DeployBuildRequest = DeployBuildRequest(),
    ) -> dict[str, Any]:
        server_id_raw = body.server_id
        server_id = str(server_id_raw).strip() if server_id_raw else None
        try:
            return store.deploy_build(
                build_id,
                server_id=server_id,
                start=body.start,
                overwrite=body.overwrite,
            )
        except LocalExecutionBlocked as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/deployments", tags=["deployments"], dependencies=[Depends(require_operations_manager)])
    def list_deployments() -> dict[str, Any]:
        return {"deployments": store.list_deployments()}

    @app.get("/v1/deployments/{deployment_id}", tags=["deployments"], dependencies=[Depends(require_operations_manager)])
    def get_deployment(deployment_id: str) -> dict[str, Any]:
        try:
            return store.get_deployment(deployment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/v1/deployments/{deployment_id}", tags=["deployments"], dependencies=[Depends(require_operations_manager)])
    def delete_deployment(deployment_id: str) -> dict[str, Any]:
        try:
            return store.delete_deployment(deployment_id)
        except ResourceDeleteConflict as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/deployments/{deployment_id}/rollback", tags=["deployments"], dependencies=[Depends(require_operations_manager)])
    def rollback_deployment(
        deployment_id: str,
        body: RollbackDeploymentRequest = RollbackDeploymentRequest(),
    ) -> dict[str, Any]:
        try:
            return store.rollback_deployment(deployment_id, start=body.start)
        except LocalExecutionBlocked as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _runtime_override(body: dict[str, Any]) -> str | None:
    value = body.get("runtime_override", body.get("runtime"))
    return _optional_string(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value}") from exc


def _require_allowed_fields(body: dict[str, Any], allowed: set[str]) -> None:
    unexpected = sorted(set(body) - allowed)
    if unexpected:
        raise ValueError(f"unsupported build request fields: {', '.join(unexpected)}")

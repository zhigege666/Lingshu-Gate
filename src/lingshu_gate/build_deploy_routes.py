"""FastAPI route registration for Build + Deploy Pipeline."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from lingshu_gate.application.delivery_drafts import DeliveryDraftRequest
from lingshu_gate.build_deploy import (
    BuildBlocked,
    BuildDeployStore,
    DeploymentRollbackError,
    LocalExecutionBlocked,
)
from lingshu_gate.registry import ToolExecutionError
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

    @app.get("/v1/delivery-drafts/{upload_id}", tags=["deployments"])
    def get_delivery_draft(upload_id: str, request: Request, principal: Any = Depends(require_operations_manager)) -> dict[str, Any]:
        service = request.app.state.project_delivery_service
        try:
            service.uploads.get_upload(upload_id)
            return service.delivery_drafts.get(upload_id, principal.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/v1/delivery-drafts/{upload_id}", tags=["deployments"])
    def save_delivery_draft(upload_id: str, request: Request, body: DeliveryDraftRequest, principal: Any = Depends(require_operations_manager)) -> dict[str, Any]:
        service = request.app.state.project_delivery_service
        try:
            service.uploads.get_upload(upload_id)
            if body.build_id and service.builds.get_build(body.build_id)["upload_id"] != upload_id:
                raise ValueError("Draft build does not belong to the upload")
            if body.deployment_id:
                deployment = service.builds.get_deployment(body.deployment_id)
                if not body.build_id or deployment["build_id"] != body.build_id:
                    raise ValueError("Draft deployment does not belong to the build")
            saved = service.delivery_drafts.save(upload_id, principal.id, body)
            service.observability.emit_event("gate.delivery.draft_saved", source="deployments", subject_type="upload", subject_id=upload_id, payload={"actor_id": principal.id, "revision": saved["revision"]})
            return saved
        except ToolExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.to_payload()["error"]) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    def list_build_logs(build_id: str, limit: int = Query(200, ge=1, le=1000),
                        before_sequence: int | None = Query(None, ge=0),
                        after_sequence: int | None = Query(None, ge=-1),
                        tail: bool = False) -> dict[str, Any]:
        try:
            logs = store.list_build_logs(build_id, limit=limit,
                before_sequence=before_sequence, after_sequence=after_sequence, tail=tail)
            bounds = store.build_log_bounds(build_id)
            return {"logs": logs, "has_earlier": bool(logs and bounds["first"] is not None and bounds["first"] < logs[0]["sequence"]),
                    "has_later": bool(logs and bounds["last"] is not None and bounds["last"] > logs[-1]["sequence"])}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/builds/{build_id}/logs/stream", tags=["builds"], dependencies=[Depends(require_operations_manager)])
    def stream_build_logs(build_id: str, interval_seconds: float = Query(1.0, ge=0.5, le=10.0), tail: bool = False) -> StreamingResponse:
        try:
            store.get_build(build_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        async def event_generator():
            last_sequence = -1
            emitted_count = 0
            initial = True
            while True:
                try:
                    build = await run_in_threadpool(store.get_build, build_id)
                    if initial and tail:
                        logs = await run_in_threadpool(store.list_build_logs, build_id, limit=200, tail=True)
                    else:
                        logs = await run_in_threadpool(store.list_build_logs, build_id, limit=1000, after_sequence=last_sequence)
                    initial = False
                except KeyError:
                    yield _sse("error", {"detail": f"build not found: {build_id}"})
                    return
                for log in logs:
                    last_sequence = int(log["sequence"])
                    emitted_count += 1
                    yield _sse("log", log)
                # Drain a full page before publishing terminal status: clients
                # close on that status, and must not lose logs beyond row 1000.
                if len(logs) == 1000:
                    continue
                yield _sse("status", {"build_id": build_id, "status": build.get("status"), "updated_at": build.get("updated_at"), "log_count": emitted_count})
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

    @app.post("/v1/builds/{build_id}/deploy/preview", tags=["deployments"])
    def preview_deployment(
        build_id: str, request: Request, body: DeployBuildRequest,
        principal: Any = Depends(require_operations_manager),
    ) -> dict[str, Any]:
        try:
            return request.app.state.project_delivery_service.console_deployment(
                build_id, body, actor_id=principal.id, preview=True,
            )
        except ToolExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.to_payload()["error"]) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/builds/{build_id}/deploy", tags=["deployments"], dependencies=[Depends(require_operations_manager)])
    def deploy_build(
        build_id: str,
        request: Request,
        body: DeployBuildRequest = DeployBuildRequest(),
        principal: Any = Depends(require_operations_manager),
    ) -> dict[str, Any]:
        try:
            return request.app.state.project_delivery_service.console_deployment(
                build_id, body, actor_id=principal.id,
            )
        except ToolExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.to_payload()["error"]) from exc
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
        except DeploymentRollbackError as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
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

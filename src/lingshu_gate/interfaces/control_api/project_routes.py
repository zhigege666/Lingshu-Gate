"""Project upload control-plane routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.models import ResourceDeleteConflict
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.project_uploads import ProjectUploadStore, ProjectUploadTooLarge


def register_project_routes(
    app: FastAPI,
    *,
    project_upload_store: ProjectUploadStore,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register project archive upload and analysis routes."""

    @app.post(
        "/v1/projects/upload",
        tags=["projects"],
        dependencies=[Depends(require_operations_manager)],
    )
    def upload_project(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            record = project_upload_store.save_zip_stream(
                filename=file.filename or "upload.zip",
                source=file.file,
            )
        except ProjectUploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        observability_store.emit_event(
            "gate.project.uploaded",
            source="projects",
            subject_type="upload",
            subject_id=record["id"],
            payload={
                "filename": record["filename"],
                "runtime": record["detected_runtime"],
            },
        )
        return record

    @app.get(
        "/v1/projects/uploads",
        tags=["projects"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_project_uploads() -> dict[str, Any]:
        return {"uploads": project_upload_store.list_uploads()}

    @app.get(
        "/v1/projects/uploads/{upload_id}",
        tags=["projects"],
        dependencies=[Depends(require_operations_manager)],
    )
    def get_project_upload(upload_id: str) -> dict[str, Any]:
        try:
            return project_upload_store.get_upload(upload_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/uploads/{upload_id}/analyze",
        tags=["projects"],
        dependencies=[Depends(require_operations_manager)],
    )
    def analyze_project_upload(upload_id: str) -> dict[str, Any]:
        try:
            record = project_upload_store.analyze_upload(upload_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        observability_store.emit_event(
            "gate.project.analyzed",
            source="projects",
            subject_type="upload",
            subject_id=upload_id,
            payload={"runtime": record["detected_runtime"]},
        )
        return record

    @app.post(
        "/v1/projects/uploads/{upload_id}/draft-manifest",
        tags=["projects"],
        dependencies=[Depends(require_operations_manager)],
    )
    def draft_project_manifest(upload_id: str) -> dict[str, Any]:
        try:
            manifest = project_upload_store.draft_manifest(upload_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        observability_store.emit_event(
            "gate.project.manifest_drafted",
            source="projects",
            subject_type="upload",
            subject_id=upload_id,
            payload={"manifest_id": manifest.get("id")},
        )
        return {"upload_id": upload_id, "manifest": manifest}

    @app.delete(
        "/v1/projects/uploads/{upload_id}",
        tags=["projects"],
        dependencies=[Depends(require_operations_manager)],
    )
    def delete_project_upload(upload_id: str) -> dict[str, Any]:
        try:
            record = project_upload_store.delete_upload(upload_id)
        except ResourceDeleteConflict as exc:
            raise HTTPException(status_code=409, detail=exc.detail()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        observability_store.emit_event(
            "gate.project.deleted",
            source="projects",
            subject_type="upload",
            subject_id=upload_id,
        )
        return record

"""Explicit retention policy and confirmed cleanup control-plane contract."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.retention_store import RetentionConflict, RetentionStore


class RetentionPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    runtime_logs_retention_days: int = Field(ge=1, le=3650)
    events_retention_days: int = Field(ge=1, le=3650)
    call_records_retention_days: int = Field(ge=1, le=3650)
    payload_mode: Literal["metadata_only", "redacted"]


class RetentionSaveRequest(RetentionPolicyRequest):
    expected_revision: int = Field(ge=1)
    preview_id: str | None = None
    confirmed: StrictBool = False


class RetentionCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(ge=1)
    confirmed: StrictBool


POLICY_FIELDS = {
    "logs_days": "runtime_logs_retention_days",
    "events_days": "events_retention_days",
    "invocation_audits_days": "call_records_retention_days",
}


def public_policy(values: dict[str, Any]) -> dict[str, Any]:
    return {POLICY_FIELDS.get(key, key): value for key, value in values.items()}


def internal_policy(body: RetentionPolicyRequest) -> dict[str, Any]:
    values = body.model_dump(include={*POLICY_FIELDS.values(), "payload_mode"})
    reverse = {value: key for key, value in POLICY_FIELDS.items()}
    return {reverse.get(key, key): value for key, value in values.items()}


def register_retention_routes(app: FastAPI, *, store: RetentionStore, auth_store: AuthStore,
                              access_store: AccessControlStore, observability_store: ObservabilityStore,
                              worker_enabled: bool) -> None:
    def require_manager(request: Request) -> AuthPrincipal:
        principal = auth_store.authenticate_request(request)
        try:
            access_store.require_control_permission(principal, "retention.manage")
        except AccessDeniedError as exc:
            raise HTTPException(403, detail=exc.reason) from exc
        return principal

    def conflict(exc: RetentionConflict) -> HTTPException:
        return HTTPException(409, detail={"code": str(exc)})

    @app.get("/v1/retention/policy")
    def get_policy(_: AuthPrincipal = Depends(require_manager)) -> dict[str, Any]:
        return {**public_policy(store.policy()), "worker_enabled": worker_enabled}

    @app.put("/v1/retention/policy")
    def save_policy(body: RetentionSaveRequest, principal: AuthPrincipal = Depends(require_manager)) -> dict[str, Any]:
        try:
            result = store.save_policy(body.expected_revision, internal_policy(body),
                                       preview_id=body.preview_id, confirmed=body.confirmed)
        except RetentionConflict as exc:
            raise conflict(exc) from exc
        observability_store.emit_event("gate.retention.policy_saved", source="control_api",
                                       payload={"user_id": principal.id, "revision": result["revision"]})
        return {**public_policy(result), "worker_enabled": worker_enabled}

    @app.post("/v1/retention/preview")
    def preview(body: RetentionPolicyRequest | None = None, _: AuthPrincipal = Depends(require_manager)) -> dict[str, Any]:
        result = store.preview(internal_policy(body) if body else None)
        return {**result, "policy": public_policy(result["policy"])}

    @app.post("/v1/retention/jobs", status_code=202)
    def start_cleanup(body: RetentionCleanupRequest, principal: AuthPrincipal = Depends(require_manager)) -> dict[str, Any]:
        if not worker_enabled:
            raise HTTPException(409, detail={"code": "retention_worker_disabled"})
        if not body.confirmed:
            raise HTTPException(422, detail={"code": "explicit_confirmation_required"})
        try:
            result = store.enqueue(body.preview_id, body.expected_revision, principal.id)
        except RetentionConflict as exc:
            raise conflict(exc) from exc
        observability_store.emit_event("gate.retention.cleanup_requested", source="control_api",
                                       payload={"user_id": principal.id, "job_id": result["id"]})
        return result

    @app.get("/v1/retention/jobs/{job_id}")
    def get_job(job_id: str, _: AuthPrincipal = Depends(require_manager)) -> dict[str, Any]:
        try:
            return store.job(job_id)
        except KeyError as exc:
            raise HTTPException(404, detail="Retention job not found") from exc

    @app.post("/v1/retention/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, principal: AuthPrincipal = Depends(require_manager)) -> dict[str, Any]:
        try:
            result = store.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(404, detail="Retention job not found") from exc
        observability_store.emit_event("gate.retention.cleanup_cancelled", source="control_api",
                                       payload={"user_id": principal.id, "job_id": result["id"]})
        return result

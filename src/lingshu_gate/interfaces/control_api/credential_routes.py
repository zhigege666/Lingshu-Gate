"""Service credential control-plane routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.models import CredentialResponse, CredentialSaveRequest
from lingshu_gate.observability_store import ObservabilityStore


def register_credential_routes(
    app: FastAPI,
    *,
    credential_store: CredentialStore,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register encrypted service-credential CRUD routes."""

    @app.get(
        "/v1/credentials",
        response_model=list[CredentialResponse],
        tags=["credentials"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_credentials() -> list[CredentialResponse]:
        return credential_store.list_credentials()

    @app.get(
        "/v1/credentials/{credential_id}",
        response_model=CredentialResponse,
        tags=["credentials"],
        dependencies=[Depends(require_operations_manager)],
    )
    def get_credential(credential_id: str) -> CredentialResponse:
        try:
            return credential_store.get_credential(credential_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def save_credential(
        request: CredentialSaveRequest,
        *,
        credential_id: str | None = None,
    ) -> CredentialResponse:
        try:
            credential = credential_store.save_credential(
                name=request.name,
                value=request.value,
                description=request.description,
                credential_id=credential_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        observability_store.emit_event(
            "gate.credential.saved",
            source="credentials",
            subject_type="credential",
            subject_id=credential.id,
            payload={"name": credential.name},
        )
        return credential

    @app.post(
        "/v1/credentials",
        response_model=CredentialResponse,
        tags=["credentials"],
        dependencies=[Depends(require_operations_manager)],
    )
    def create_credential(request: CredentialSaveRequest) -> CredentialResponse:
        return save_credential(request)

    @app.put(
        "/v1/credentials/{credential_id}",
        response_model=CredentialResponse,
        tags=["credentials"],
        dependencies=[Depends(require_operations_manager)],
    )
    def update_credential(
        credential_id: str,
        request: CredentialSaveRequest,
    ) -> CredentialResponse:
        return save_credential(request, credential_id=credential_id)

    @app.delete(
        "/v1/credentials/{credential_id}",
        response_model=CredentialResponse,
        tags=["credentials"],
        dependencies=[Depends(require_operations_manager)],
    )
    def delete_credential(credential_id: str) -> CredentialResponse:
        try:
            credential = credential_store.delete_credential(credential_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        observability_store.emit_event(
            "gate.credential.deleted",
            source="credentials",
            subject_type="credential",
            subject_id=credential_id,
        )
        return credential

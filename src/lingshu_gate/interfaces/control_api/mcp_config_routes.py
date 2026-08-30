"""MCP configuration control-plane routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request

from lingshu_gate.application.mcp_configuration import (
    McpConfigurationService,
    PreparedUserCredentials,
)
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from lingshu_gate.models import (
    McpConfigApplyResponse,
    McpConfigListResponse,
    McpConfigResponse,
    McpConfigSaveRequest,
)
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.redaction import redact_text


def _safe_error_detail(error: Exception) -> str:
    return redact_text(str(error))


def _require_secure_credential_transport(request: Request) -> None:
    """Require HTTPS for remote personal-secret submissions."""

    host = request.client.host if request.client else ""
    if request.url.scheme.lower() != "https" and host not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise HTTPException(
            status_code=400,
            detail="HTTPS is required to submit user downstream credentials",
        )


def register_mcp_config_routes(
    app: FastAPI,
    *,
    settings: Settings,
    auth_store: AuthStore,
    mcp_config_store: McpConfigStore,
    configuration_service: McpConfigurationService,
    observability_store: ObservabilityStore,
    require_operations_manager: AuthDependency,
) -> None:
    """Register manifest validation and transactional configuration routes."""

    @app.get(
        "/v1/mcp/configs",
        response_model=McpConfigListResponse,
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def list_mcp_configs() -> McpConfigListResponse:
        return mcp_config_store.list_configs()

    @app.get(
        "/v1/mcp/configs/{server_id}",
        response_model=McpConfigResponse,
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def get_mcp_config(server_id: str) -> McpConfigResponse:
        try:
            return mcp_config_store.get_config(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_safe_error_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    def record_validation(result: dict[str, Any], fallback_id: str | None = None) -> None:
        observability_store.emit_event(
            "gate.config.validated",
            source="configs",
            subject_type="config",
            subject_id=result.get("manifest_id") or fallback_id,
            payload={"ok": result.get("ok"), "summary": result.get("summary")},
        )

    @app.post(
        "/v1/mcp/configs/validate",
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def validate_mcp_config(request: McpConfigSaveRequest) -> dict[str, Any]:
        result = validate_mcp_manifest(
            settings,
            mcp_config_store,
            request.manifest,
        )
        record_validation(result)
        return result

    @app.post(
        "/v1/mcp/configs/{server_id}/validate",
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def validate_existing_mcp_config(
        server_id: str,
        request: McpConfigSaveRequest,
    ) -> dict[str, Any]:
        result = validate_mcp_manifest(
            settings,
            mcp_config_store,
            request.manifest,
            expected_id=server_id,
        )
        record_validation(result, server_id)
        return result

    def prepare_user_credentials(
        request: McpConfigSaveRequest,
        http_request: Request,
        *,
        existing_server_id: str | None = None,
    ) -> PreparedUserCredentials:
        prepared = configuration_service.prepare_user_credentials(
            request,
            existing_server_id=existing_server_id,
        )
        if prepared.values:
            if not auth_store.enabled:
                raise HTTPException(
                    status_code=409,
                    detail="authentication is required for user credentials",
                )
            _require_secure_credential_transport(http_request)
        return prepared

    @app.post(
        "/v1/mcp/configs",
        response_model=McpConfigApplyResponse,
        tags=["mcp-configs"],
    )
    def create_mcp_config(
        request: McpConfigSaveRequest,
        http_request: Request,
        principal: AuthPrincipal = Depends(require_operations_manager),
    ) -> McpConfigApplyResponse:
        try:
            prepared = prepare_user_credentials(request, http_request)
            response = configuration_service.create(
                request,
                user_id=principal.id,
                prepared=prepared,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=_safe_error_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

        observability_store.emit_event(
            "gate.config.created",
            source="configs",
            subject_type="config",
            subject_id=response.config.id if response.config else None,
        )
        return response

    @app.put(
        "/v1/mcp/configs/{server_id}",
        response_model=McpConfigApplyResponse,
        tags=["mcp-configs"],
    )
    def update_mcp_config(
        server_id: str,
        request: McpConfigSaveRequest,
        http_request: Request,
        principal: AuthPrincipal = Depends(require_operations_manager),
    ) -> McpConfigApplyResponse:
        try:
            prepared = prepare_user_credentials(
                request,
                http_request,
                existing_server_id=server_id,
            )
            response = configuration_service.update(
                server_id,
                request,
                user_id=principal.id,
                prepared=prepared,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_safe_error_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

        observability_store.emit_event(
            "gate.config.updated",
            source="configs",
            subject_type="config",
            subject_id=response.config.id if response.config else server_id,
        )
        return response

    @app.delete(
        "/v1/mcp/configs/{server_id}",
        response_model=McpConfigApplyResponse,
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def delete_mcp_config(server_id: str) -> McpConfigApplyResponse:
        try:
            response, removed_user_credentials = configuration_service.delete(
                server_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_safe_error_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

        observability_store.emit_event(
            "gate.config.deleted",
            source="configs",
            subject_type="config",
            subject_id=server_id,
            payload={"removed_user_credentials": removed_user_credentials},
        )
        return response

    @app.post(
        "/v1/mcp/configs/reload",
        response_model=McpConfigApplyResponse,
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def reload_mcp_configs() -> McpConfigApplyResponse:
        response = configuration_service.reload()
        observability_store.emit_event("gate.config.reloaded", source="configs")
        return response

    @app.post(
        "/v1/mcp/configs/{server_id}/apply",
        response_model=McpConfigApplyResponse,
        tags=["mcp-configs"],
        dependencies=[Depends(require_operations_manager)],
    )
    def apply_mcp_config(server_id: str) -> McpConfigApplyResponse:
        try:
            response = configuration_service.apply(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=_safe_error_detail(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

        observability_store.emit_event(
            "gate.config.applied",
            source="configs",
            subject_type="config",
            subject_id=server_id,
        )
        return response

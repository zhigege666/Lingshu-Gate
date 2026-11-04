"""Authenticated GitHub release update configuration and checks."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.release_updates import ReleaseUpdateService
from lingshu_gate.registry import ToolExecutionError


class UpdateSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0)
    proxy_profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    proxy_profile_version: int | None = Field(default=None, ge=1)


def register_release_update_routes(
    app: FastAPI, *, service: ReleaseUpdateService, auth: AuthStore, access: AccessControlStore,
) -> None:
    def manage(request: Request) -> AuthPrincipal:
        principal = auth.authenticate_request(request)
        try:
            access.require_control_permission(principal, "system_settings.manage")
        except AccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=exc.reason) from exc
        return principal

    def invoke(action: Any) -> Any:
        try:
            return action()
        except ToolExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.to_payload()["error"]) from None
        except (ValueError, KeyError):
            raise HTTPException(status_code=400, detail={
                "code": "update_settings_invalid", "message": "Invalid update configuration",
            }) from None

    @app.get("/v1/system-settings/updates", tags=["settings"])
    def get_settings(_principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return {"current_version": service.current_version, **service.settings()}

    @app.put("/v1/system-settings/updates", tags=["settings"])
    def put_settings(body: dict[str, Any], _principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            parsed = UpdateSettingsWrite.model_validate(body)
            return service.save(
                expected_revision=parsed.expected_revision,
                proxy_profile_id=parsed.proxy_profile_id,
                proxy_profile_version=parsed.proxy_profile_version,
                actor_id=_principal.id,
            )
        return invoke(action)

    @app.post("/v1/system-settings/updates/check", tags=["settings"])
    def check_updates(_principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return invoke(lambda: service.check(_principal.id))

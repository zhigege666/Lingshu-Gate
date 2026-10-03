"""Network configuration vs invocation permissions, with secret-safe validation."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import Field

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.git_import_mcp import GitImportService, ProxyTest
from lingshu_gate.network_settings import NetworkDefaults, NetworkSettingsStore, ProfileWrite, StrictModel
from lingshu_gate.project_delivery_mcp import _parse_input
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext


class DefaultsWrite(StrictModel):
    defaults: NetworkDefaults
    expected_revision: int = Field(ge=0)


class DeleteProfile(StrictModel):
    expected_version: int = Field(ge=1)


def register_network_routes(app: FastAPI, *, network: NetworkSettingsStore, imports: GitImportService, auth: AuthStore, access: AccessControlStore) -> None:
    def dependency(*permissions: str):
        def require(request: Request) -> AuthPrincipal:
            principal = auth.authenticate_request(request)
            try:
                for permission in permissions:
                    access.require_control_permission(principal, permission)
            except AccessDeniedError as exc:
                raise HTTPException(status_code=403, detail=exc.reason) from exc
            return principal
        return require

    manage = dependency("system_settings.manage")
    use = dependency("operations.manage", "network.use")
    write = dependency("operations.manage", "network.use", "tools.invoke")

    def context(principal: AuthPrincipal) -> ToolInvocationContext:
        return ToolInvocationContext(actor_id=principal.id, username=principal.username, auth_type=principal.auth_type, token_id=principal.token_id, correlation_id=uuid4().hex, roles=principal.roles, permissions=principal.permissions, scopes=principal.scopes, delegated_scopes=principal.delegated_scopes)

    def invoke(action: Any) -> Any:
        try:
            return action()
        except ToolExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.to_payload()["error"]) from None
        except (ValueError, KeyError):
            # No exception/input echo: endpoint writes may contain secret material.
            raise HTTPException(status_code=400, detail={"code": "network_invalid_input", "message": "Invalid network configuration or reference"}) from None

    @app.get("/v1/system-settings/network", tags=["settings"])
    def get_settings(principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return {**network.settings(), "profiles": network.profiles()}

    @app.put("/v1/system-settings/network", tags=["settings"])
    def put_settings(body: dict[str, Any], principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        def action():
            parsed = _parse_input(DefaultsWrite, body)
            return network.save_defaults(parsed.defaults, parsed.expected_revision, principal.id)
        return invoke(action)

    @app.post("/v1/system-settings/network/profiles", tags=["settings"])
    def create_profile(body: dict[str, Any], principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return invoke(lambda: network.save_profile(_parse_input(ProfileWrite, body), principal.id))

    @app.put("/v1/system-settings/network/profiles/{profile_id}", tags=["settings"])
    def update_profile(profile_id: str, body: dict[str, Any], principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return invoke(lambda: network.save_profile(_parse_input(ProfileWrite, body), principal.id, profile_id))

    @app.get("/v1/system-settings/network/profiles/{profile_id}/references", tags=["settings"])
    def profile_references(profile_id: str, principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return invoke(lambda: {"references": network.references(profile_id)})

    @app.post("/v1/system-settings/network/profiles/{profile_id}/delete", tags=["settings"])
    def delete_profile(profile_id: str, body: dict[str, Any], principal: AuthPrincipal = Depends(manage)) -> dict[str, Any]:
        return invoke(lambda: network.delete_profile(profile_id, _parse_input(DeleteProfile, body).expected_version, principal.id))

    @app.get("/v1/network/options", tags=["projects"])
    def network_options(principal: AuthPrincipal = Depends(use)) -> dict[str, Any]:
        # Invocation users receive only redacted selection/status data.
        return {**network.settings(), "profiles": network.profiles()}

    @app.post("/v1/network/test", tags=["projects"])
    def network_test(body: dict[str, Any], principal: AuthPrincipal = Depends(write)) -> dict[str, Any]:
        return invoke(lambda: imports.test_proxy(_parse_input(ProxyTest, body), context(principal)))

    @app.post("/v1/projects/git/plan", tags=["projects"])
    def git_plan(body: dict[str, Any], principal: AuthPrincipal = Depends(use)) -> dict[str, Any]:
        return invoke(lambda: imports.plan(body, context(principal)))

    @app.post("/v1/projects/git/import", tags=["projects"])
    def git_import(body: dict[str, Any], principal: AuthPrincipal = Depends(write)) -> dict[str, Any]:
        return invoke(lambda: imports.create(body, context(principal)))

    @app.get("/v1/projects/git/imports/{import_id}", tags=["projects"])
    def git_status(import_id: str, principal: AuthPrincipal = Depends(use)) -> dict[str, Any]:
        return invoke(lambda: imports.status({"import_id": import_id}, context(principal)))

    @app.post("/v1/projects/git/imports/{import_id}/cancel", tags=["projects"])
    def git_cancel(import_id: str, body: dict[str, Any], principal: AuthPrincipal = Depends(write)) -> dict[str, Any]:
        return invoke(lambda: imports.cancel({**body, "import_id": import_id}, context(principal)))

    # HTTP adapter reuses exactly the existing MCP delivery application methods.
    @app.post("/v1/projects/git/build-plan", tags=["builds"])
    def git_build_plan(body: dict[str, Any], principal: AuthPrincipal = Depends(use)) -> dict[str, Any]:
        return invoke(lambda: imports.delivery.build_plan(body, context(principal)))

    @app.post("/v1/projects/git/build", tags=["builds"])
    def git_build(body: dict[str, Any], principal: AuthPrincipal = Depends(write)) -> dict[str, Any]:
        return invoke(lambda: imports.delivery.build_create(body, context(principal)))

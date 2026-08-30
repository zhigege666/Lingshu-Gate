"""Authentication and personal API-token control-plane routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request, Response

from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.dependencies import AuthDependency
from lingshu_gate.models import (
    AuthLoginRequest,
    AuthSessionResponse,
    AuthUserResponse,
)
from lingshu_gate.observability_store import ObservabilityStore

def register_auth_routes(
    app: FastAPI,
    *,
    settings: Settings,
    auth_store: AuthStore,
    observability_store: ObservabilityStore,
    require_viewer: AuthDependency,
) -> None:
    """Register session authentication routes."""

    @app.post("/v1/auth/login", response_model=AuthSessionResponse, tags=["auth"])
    def login(request: AuthLoginRequest, response: Response) -> AuthSessionResponse:
        principal, token, expires_at = auth_store.login(
            username=request.username,
            password=request.password,
        )
        response.set_cookie(
            settings.auth_session_cookie_name,
            token,
            httponly=True,
            samesite="lax",
            secure=settings.auth_cookie_secure,
            max_age=settings.auth_session_ttl_hours * 3600,
        )
        observability_store.emit_event(
            "gate.auth.login",
            source="auth",
            subject_type="user",
            subject_id=principal.id,
            payload={"username": principal.username},
        )
        return AuthSessionResponse(
            user=AuthUserResponse.model_validate(auth_store.me(principal)),
            expires_at=expires_at,
            message="logged_in",
        )

    @app.post(
        "/v1/auth/logout",
        response_model=dict[str, str],
        tags=["auth"],
        dependencies=[Depends(require_viewer)],
    )
    def logout(request: Request, response: Response) -> dict[str, str]:
        auth_store.logout(request.cookies.get(settings.auth_session_cookie_name))
        response.delete_cookie(
            settings.auth_session_cookie_name,
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        observability_store.emit_event("gate.auth.logout", source="auth")
        return {"message": "logged_out"}

    @app.get("/v1/auth/me", response_model=AuthUserResponse, tags=["auth"])
    def auth_me(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> AuthUserResponse:
        return AuthUserResponse.model_validate(auth_store.me(principal))

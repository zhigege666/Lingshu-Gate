"""Shared dependency types for control-plane route adapters."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, AuthStore

AuthDependency = Callable[[Request], AuthPrincipal]


def create_operations_manager_dependency(
    auth_store: AuthStore,
    access_store: AccessControlStore,
) -> AuthDependency:
    """Build the authenticated operations-manager HTTP dependency."""

    def require_operations_manager(request: Request) -> AuthPrincipal:
        principal = auth_store.authenticate_request(request)
        try:
            access_store.require_control_permission(principal, "operations.manage")
        except AccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=exc.reason) from exc
        return principal

    return require_operations_manager

"""Explicitly enabled, globally scoped aggregate telemetry endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthStore
from lingshu_gate.telemetry import TelemetryService


def register_telemetry_routes(app: FastAPI, *, service: TelemetryService, auth: AuthStore, access: AccessControlStore) -> None:
    def authorize(request: Request) -> None:
        if not auth.enabled:
            raise HTTPException(401, detail={"code": "authentication_required"}, headers={"WWW-Authenticate": "Bearer"})
        principal = auth.authenticate_request(request)
        if not all(access.has_control_permission(principal, permission)
                   for permission in ("operations.manage", "observability.read.all")):
            raise HTTPException(403, detail={"code": "telemetry_permission_required"})

    @app.get("/v1/observability/metrics", tags=["observability"], response_class=PlainTextResponse)
    def metrics(request: Request) -> PlainTextResponse:
        # A disabled feature remains absent even for an unauthenticated caller.
        if not service.config.metrics_enabled:
            raise HTTPException(404)
        authorize(request)
        return PlainTextResponse(service.prometheus_text(), media_type="text/plain; version=0.0.4; charset=utf-8",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/v1/observability/telemetry", tags=["observability"])
    def telemetry_status(request: Request) -> Any:
        if not service.config.metrics_enabled and not service.config.traces_enabled:
            raise HTTPException(404)
        authorize(request)
        return JSONResponse(service.status(), headers={"Cache-Control": "no-store"})

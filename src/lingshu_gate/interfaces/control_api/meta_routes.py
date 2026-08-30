"""Service metadata, console assets, and orchestrator health probes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from lingshu_gate.application.health import HealthService
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
CONSOLE_INDEX = STATIC_DIR / "console" / "index.html"
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def register_meta_routes(
    app: FastAPI,
    *,
    settings: Settings,
    auth_store: AuthStore,
    health_service: HealthService,
) -> None:
    """Register stable metadata routes and lifecycle health probes."""

    @app.get("/", tags=["meta"])
    def index() -> dict[str, Any]:
        return {
            "service": settings.service_name,
            "version": settings.version,
            "console": "/console",
            "docs": "/docs",
            "probes": {
                "healthz": "/healthz",
                "readyz": "/readyz",
                "startupz": "/startupz",
            },
            "mcp": "/mcp" if settings.mcp_gateway_enabled else None,
            "diagnostics": "/v1/diagnostics",
            "memory_diagnostics": "/v1/diagnostics/memory",
            "runtime_environment": "/v1/runtime/environment",
            "logs": "/v1/logs",
            "events": "/v1/events",
            "runtime_cache": "/v1/runtime/cache",
            "project_uploads": "/v1/projects/uploads",
            "builds": "/v1/builds",
            "deployments": "/v1/deployments",
            "tools": "/v1/tools",
            "mcp_servers": "/v1/mcp/servers",
            "mcp_configs": "/v1/mcp/configs",
            "mcp_config_validate": "/v1/mcp/configs/validate",
            "access": "/v1/access",
            "auth": {
                "enabled": settings.auth_enabled,
                "initialized": auth_store.has_users(),
                "register": "/v1/auth/register",
                "login": "/v1/auth/login",
                "me": "/v1/auth/me",
                "tokens": "/v1/auth/tokens",
            },
        }

    @app.get("/console", response_model=None, tags=["console"])
    def console() -> Response:
        if CONSOLE_INDEX.exists():
            return FileResponse(CONSOLE_INDEX, headers=NO_STORE_HEADERS)
        raise HTTPException(status_code=404, detail="Console asset not found")

    @app.get("/console/{asset_path:path}", response_model=None, tags=["console"])
    def console_asset(asset_path: str) -> Response:
        base = (STATIC_DIR / "console").resolve()
        if asset_path in {"", "index.html"} and CONSOLE_INDEX.exists():
            return FileResponse(CONSOLE_INDEX, headers=NO_STORE_HEADERS)
        target = (base / asset_path).resolve()
        if not target.is_relative_to(base) or not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Console asset not found")
        cache_control = (
            "public, max-age=31536000, immutable"
            if asset_path.startswith("assets/")
            else "public, max-age=3600"
        )
        return FileResponse(target, headers={"Cache-Control": cache_control})

    @app.get("/healthz", tags=["meta"])
    def health() -> JSONResponse:
        report = health_service.liveness()
        return JSONResponse(report.to_payload(), status_code=200)

    @app.get("/startupz", tags=["meta"])
    def startup() -> JSONResponse:
        report = health_service.startup()
        return JSONResponse(report.to_payload(), status_code=200 if report.ok else 503)

    @app.get("/readyz", tags=["meta"])
    def readiness() -> JSONResponse:
        report = health_service.readiness()
        return JSONResponse(report.to_payload(), status_code=200 if report.ok else 503)

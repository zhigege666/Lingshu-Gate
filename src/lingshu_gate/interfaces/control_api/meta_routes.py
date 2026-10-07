"""Service metadata, console assets, and orchestrator health probes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from lingshu_gate.application.health import HealthService
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}
ROOT_HEADERS = {**NO_STORE_HEADERS, "Vary": "Accept"}


def _accept_quality(accept: str, media_type: str) -> tuple[int, int]:
    """Return quality and specificity; an exact q=0 overrides a wildcard."""
    selected = (-1, 0)
    for item in accept.split(","):
        media_range, *parameters = item.strip().lower().split(";")
        media_range = media_range.strip()
        if media_range == media_type:
            specificity = 2
        elif media_range == media_type.split("/", 1)[0] + "/*":
            specificity = 1
        elif media_range == "*/*":
            specificity = 0
        else:
            continue
        quality = 1000
        weights = []
        for parameter in parameters:
            name, separator, value = parameter.strip().partition("=")
            if name.strip() == "q":
                weights.append(value.strip() if separator else "")
        if len(weights) > 1:
            quality = 0
        elif weights:
            weight = weights[0]
            if not re.fullmatch(r"(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)", weight):
                quality = 0
            else:
                whole, _, fraction = weight.partition(".")
                quality = int(whole) * 1000 + int(fraction.ljust(3, "0"))
        selected = max(selected, (specificity, quality))
    return selected[1], selected[0]


def _console_file(asset_path: str, *, entry_headers: dict[str, str] | None = None) -> FileResponse:
    """Serve only regular files inside the Console tree, including the entry."""
    rejected = HTTPException(status_code=404, detail="Console asset not found",
                             headers=entry_headers or NO_STORE_HEADERS)
    if (asset_path.startswith("/") or "\\" in asset_path or ":" in asset_path
            or any(ord(character) < 32 or ord(character) == 127 for character in asset_path)
            or any(part in {".", ".."} for part in asset_path.split("/"))):
        raise rejected
    try:
        static_root = STATIC_DIR.resolve()
        base = (static_root / "console").resolve()
        target = (base / asset_path).resolve()
        valid = base.is_relative_to(static_root) and target.is_relative_to(base) and target.is_file()
    except (OSError, RuntimeError):
        raise rejected from None
    if not valid:
        raise HTTPException(status_code=404, detail="Console asset not found",
                            headers=entry_headers or NO_STORE_HEADERS)
    if asset_path == "index.html":
        headers = entry_headers or NO_STORE_HEADERS
    else:
        hashed_asset = asset_path.startswith("assets/") and re.search(
            r"-[\w-]{8,}\.[\w.]+$", target.name, flags=re.ASCII
        )
        headers = {"Cache-Control": "public, max-age=31536000, immutable"
                   if hashed_asset else "public, max-age=3600"}
    return FileResponse(target, headers=headers)


def register_meta_routes(
    app: FastAPI,
    *,
    settings: Settings,
    auth_store: AuthStore,
    health_service: HealthService,
) -> None:
    """Register stable metadata routes and lifecycle health probes."""

    def service_metadata() -> dict[str, Any]:
        return {
            "service": settings.service_name,
            "version": settings.version,
            "console": "/",
            "meta": "/v1/meta",
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

    @app.get("/v1/meta", tags=["meta"])
    def metadata() -> JSONResponse:
        return JSONResponse(service_metadata(), headers=NO_STORE_HEADERS)

    @app.get("/", response_model=None, tags=["meta", "console"])
    def index(request: Request) -> Response:
        accept = ",".join(request.headers.getlist("accept")).strip() or "*/*"
        json_quality, json_specificity = _accept_quality(accept, "application/json")
        html_quality, html_specificity = _accept_quality(accept, "text/html")
        # Explicit acceptable JSON keeps programmatic root discovery stable,
        # even when that client also lists HTML. Browser navigation prefers HTML.
        if json_quality > 0 and json_specificity == 2:
            return JSONResponse(service_metadata(), headers=ROOT_HEADERS)
        if html_quality > 0 and (html_quality, html_specificity) > (json_quality, json_specificity):
            return _console_file("index.html", entry_headers=ROOT_HEADERS)
        if json_quality > 0:
            return JSONResponse(service_metadata(), headers=ROOT_HEADERS)
        raise HTTPException(status_code=406, detail="No acceptable root representation", headers=ROOT_HEADERS)

    @app.get("/console", response_model=None, tags=["console"])
    @app.get("/console/", response_model=None, include_in_schema=False)
    def console(request: Request) -> RedirectResponse:
        # A fragment is browser-only. Omitting it from Location preserves the
        # old bookmark fragment through standard browser redirect inheritance.
        location = "/" + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse(location, status_code=307, headers=NO_STORE_HEADERS)

    @app.get("/assets/{asset_path:path}", response_model=None, include_in_schema=False)
    def root_console_asset(asset_path: str) -> FileResponse:
        return _console_file("assets/" + asset_path)

    @app.get("/lingshu-gate-icon.svg", response_model=None, include_in_schema=False)
    @app.get("/lingshu-gate-app-icon.svg", response_model=None, include_in_schema=False)
    @app.get("/lingshu-gate-icon-512.png", response_model=None, include_in_schema=False)
    def console_icon(request: Request) -> FileResponse:
        return _console_file(request.url.path.lstrip("/"))

    @app.get("/console/{asset_path:path}", response_model=None, tags=["console"])
    def console_asset(asset_path: str, request: Request) -> Response:
        if asset_path == "index.html":
            return console(request)
        return _console_file(asset_path)

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

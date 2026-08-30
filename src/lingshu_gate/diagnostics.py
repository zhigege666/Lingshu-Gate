"""Runtime diagnostics for Lingshu Gate."""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lingshu_gate.config import Settings
from lingshu_gate.endpoint_security import redact_endpoint
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import DiagnosticsCheck, DiagnosticsResponse
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.redaction import redact_text

logger = logging.getLogger(__name__)


def run_diagnostics(settings: Settings, registry: ToolRegistry, runtime: McpRuntimeManager) -> DiagnosticsResponse:
    """Run a read-only diagnostic pass over Gate runtime state."""

    checks: list[DiagnosticsCheck] = []
    log_event(logger, logging.INFO, "gate.diagnostics.started", "Runtime diagnostics started")

    _check_path(checks, "allowed_root", settings.allowed_root, must_be_dir=True)
    _check_path(checks, "config_dir", settings.config_dir, must_be_dir=True)
    _check_path(checks, "data_dir", settings.data_dir, must_be_dir=True, require_writable=True)
    _check_path(
        checks,
        "runtime_cache",
        settings.data_dir / "runtime-cache",
        must_be_dir=True,
        allow_missing=True,
        require_parent_writable=True,
    )
    if settings.runtime_role == "local":
        _check_executable(
            checks,
            "python",
            _find_python_interpreter(),
            version_args=["--version"],
            required=False,
            missing_detail="Neither python3 nor python was found in PATH",
        )
        _check_executable(
            checks,
            "node",
            "node",
            version_args=["--version"],
            minimum_version=(22, 13, 0),
            required=False,
        )
        _check_executable(checks, "npm", "npm", version_args=["--version"], required=False)
        _check_executable(checks, "npx", "npx", version_args=["--version"], required=False)

    server_list = runtime.list_servers()
    tools = registry.list_definitions()
    mcp_tools = [tool for tool in tools if tool.source == "mcp"]

    checks.append(
        DiagnosticsCheck(
            name="manifest_load_errors",
            ok=not server_list.load_errors,
            severity="error" if server_list.load_errors else "info",
            detail="No manifest load errors" if not server_list.load_errors else "Manifest load errors detected",
            metadata={"errors": server_list.load_errors},
        )
    )
    checks.append(
        DiagnosticsCheck(
            name="mcp_server_count",
            ok=True,
            severity="info",
            detail=f"Configured MCP servers: {len(server_list.servers)}",
            metadata={"server_count": len(server_list.servers)},
        )
    )

    for server in server_list.servers:
        ok = server.status in {"running", "external", "stopped"}
        severity = "error" if server.status == "failed" else "warning" if server.status == "unsupported" else "info"
        checks.append(
            DiagnosticsCheck(
                name=f"mcp_server.{server.id}.status",
                ok=ok,
                severity=severity,
                detail=f"{server.id} status={server.status}",
                metadata=server.model_dump(mode="json"),
            )
        )
        if server.last_error:
            checks.append(
                DiagnosticsCheck(
                    name=f"mcp_server.{server.id}.last_error",
                    ok=False,
                    severity="error" if server.status == "failed" else "warning",
                    detail=redact_text(server.last_error),
                    metadata={"server_id": server.id},
                )
            )

    for server_id, manifest in runtime.iter_manifests().items():
        if manifest.launch.type == "managed_process":
            command = manifest.launch.command or ""
            _check_executable(checks, f"mcp_server.{server_id}.command", command)
            if manifest.launch.package:
                checks.append(
                    DiagnosticsCheck(
                        name=f"mcp_server.{server_id}.package_cache",
                        ok=True,
                        severity="info",
                        detail=f"Dynamic package cache enabled for {manifest.launch.package.manager}:{manifest.launch.package.name}",
                        metadata=manifest.launch.package.model_dump(mode="json"),
                    )
                )
        if manifest.transport.type == "streamable_http":
            checks.append(
                DiagnosticsCheck(
                    name=f"mcp_server.{server_id}.streamable_http_endpoint",
                    ok=bool(manifest.transport.endpoint),
                    severity="info" if manifest.transport.endpoint else "error",
                    detail=redact_endpoint(manifest.transport.endpoint) or "Missing endpoint",
                    metadata={"server_id": server_id, "implemented": True},
                )
            )

    checks.append(
        DiagnosticsCheck(
            name="registered_tools",
            ok=len(tools) > 0,
            severity="info" if tools else "warning",
            detail=f"Registered tools: {len(tools)}",
            metadata={"total": len(tools), "mcp": len(mcp_tools)},
        )
    )

    response = DiagnosticsResponse(
        ok=not any(not check.ok and check.severity == "error" for check in checks),
        checks=checks,
        summary={
            "service": settings.service_name,
            "version": settings.version,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "allowed_root": str(settings.allowed_root),
            "config_dir": str(settings.config_dir),
            "data_dir": str(settings.data_dir),
            "runtime_cache_dir": str(settings.data_dir / "runtime-cache"),
            "mcp_server_count": len(server_list.servers),
            "tool_count": len(tools),
            "mcp_tool_count": len(mcp_tools),
        },
    )
    log_event(
        logger,
        logging.INFO,
        "gate.diagnostics.completed",
        "Runtime diagnostics completed",
        ok=response.ok,
        check_count=len(checks),
        summary=response.summary,
    )
    return response


def _check_path(
    checks: list[DiagnosticsCheck],
    name: str,
    path: Path,
    *,
    must_be_dir: bool,
    allow_missing: bool = False,
    require_writable: bool = False,
    require_parent_writable: bool = False,
) -> None:
    exists = path.exists()
    is_expected_type = path.is_dir() if must_be_dir else path.is_file()
    readable = os.access(path, os.R_OK) if exists else False
    writable = os.access(path, os.W_OK) if exists else False
    parent_writable = os.access(path.parent, os.W_OK) if path.parent.exists() else False
    ok = (exists and is_expected_type and readable) or (allow_missing and parent_writable)
    if require_writable and exists:
        ok = ok and writable
    if require_parent_writable:
        ok = ok and parent_writable
    checks.append(
        DiagnosticsCheck(
            name=f"path.{name}",
            ok=ok,
            severity="error" if not ok else "info",
            detail=f"{path} exists={exists} expected_type={is_expected_type} readable={readable} writable={writable} parent_writable={parent_writable}",
            metadata={
                "path": str(path),
                "exists": exists,
                "readable": readable,
                "writable": writable,
                "parent_writable": parent_writable,
            },
        )
    )


def _check_executable(
    checks: list[DiagnosticsCheck],
    name: str,
    command: str | None,
    *,
    version_args: list[str] | None = None,
    minimum_version: tuple[int, int, int] | None = None,
    required: bool = True,
    missing_detail: str | None = None,
) -> None:
    if not command:
        checks.append(
            DiagnosticsCheck(
                name=f"executable.{name}",
                ok=False,
                severity="error" if required else "warning",
                detail=missing_detail or "Missing command",
                metadata={"command": None, "resolved": None, "required": required},
            )
        )
        return
    resolved = command if Path(command).is_absolute() and Path(command).exists() else shutil.which(command)
    if not resolved:
        checks.append(
            DiagnosticsCheck(
                name=f"executable.{name}",
                ok=False,
                severity="error" if required else "warning",
                detail=f"{command} not found in PATH",
                metadata={"command": command, "resolved": None, "required": required},
            )
        )
        return

    version_output = _read_version(str(resolved), version_args or []) if version_args else None
    parsed_version = _parse_semver(version_output or "")
    version_ok = True
    min_text = None
    if minimum_version:
        min_text = ".".join(str(part) for part in minimum_version)
        version_ok = bool(parsed_version and parsed_version >= minimum_version)

    checks.append(
        DiagnosticsCheck(
            name=f"executable.{name}",
            ok=version_ok,
            severity="error" if required and not version_ok else "warning" if not version_ok else "info",
            detail=(
                f"{command} -> {resolved}; version={version_output}; required>={min_text}"
                if minimum_version
                else f"{command} -> {resolved}; version={version_output}"
            ),
            metadata={
                "command": command,
                "resolved": str(resolved),
                "version": version_output,
                "parsed_version": list(parsed_version) if parsed_version else None,
                "minimum_version": list(minimum_version) if minimum_version else None,
                "required": required,
            },
        )
    )


def _find_python_interpreter() -> str | None:
    """Find a real Python interpreter without recursing into a frozen Gate binary."""

    for command in ("python3", "python"):
        resolved = shutil.which(command)
        if resolved:
            return resolved

    if getattr(sys, "frozen", False):
        return None

    executable = Path(sys.executable)
    if executable.exists() and executable.name.lower().startswith("python"):
        return str(executable)
    return None


def _read_version(command: str, args: list[str]) -> str | None:
    try:
        completed = subprocess.run([command, *args], check=False, capture_output=True, text=True, timeout=5)
    except Exception as exc:  # noqa: BLE001 - diagnostics must keep running
        return f"version check failed: {exc}"
    output = (completed.stdout or completed.stderr or "").strip()
    return output.splitlines()[0] if output else None


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))

"""Runtime capability detection for Lingshu Gate.

Detects what the current runtime (this machine + this Gate deployment) can do:
platform, whether Gate runs inside a container, Docker availability and mode
(native vs Docker-out-of-Docker), toolchain presence, and which MCP launch types
are usable here. This makes multi-platform deployment explicit and lets the
Console degrade gracefully instead of failing when e.g. Docker is absent.

The heavy probing (subprocess/filesystem) is separated from the pure derivation
(`derive_launch_capabilities`) so the latter can be unit-tested without a host.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from lingshu_gate.config import Settings

TOOLCHAIN = ["node", "npm", "npx", "python", "python3", "pip", "pip3"]
DOCKER_SOCKET = "/var/run/docker.sock"


def detect_runtime_environment(settings: Settings) -> dict[str, Any]:
    """Probe the current runtime and return a capability report."""

    deployment = "container" if _in_container() else "host"
    docker = _detect_docker(settings.docker_bin, deployment)
    toolchain = {name: bool(shutil.which(name)) for name in TOOLCHAIN}
    return {
        "platform": _platform_key(),
        "python_version": platform.python_version(),
        "gate_deployment": deployment,
        "docker": docker,
        "toolchain": toolchain,
        "launch_capabilities": derive_launch_capabilities(docker["mode"], settings.runtime_role),
    }


def derive_launch_capabilities(
    docker_mode: str,
    runtime_role: str = "local",
) -> dict[str, dict[str, Any]]:
    """Map the deployment role and Docker mode to usable launch types."""

    if runtime_role == "core":
        core_reason = "The Core runtime role only connects to external HTTP MCP servers."
        return {
            "managed_process": {"available": False, "reason": core_reason},
            "managed_container": {"available": False, "reason": core_reason},
            "external": {"available": True, "reason": "Connects to an already-running MCP server."},
        }
    if runtime_role != "local":
        raise ValueError("runtime_role must be local or core")

    container_available = docker_mode != "unavailable"
    return {
        "managed_process": {"available": True, "reason": "Runs natively on Windows, macOS, and Linux without Docker."},
        "managed_container": {
            "available": container_available,
            "reason": f"Docker mode: {docker_mode}." if container_available else "Docker CLI or daemon not available; install Docker or mount the Docker socket to enable.",
        },
        "external": {"available": True, "reason": "Connects to an already-running MCP server."},
    }


def _detect_docker(docker_bin: str, deployment: str) -> dict[str, Any]:
    binary = shutil.which(docker_bin)
    socket_present = Path(DOCKER_SOCKET).exists()
    if not binary:
        return {"cli_available": False, "binary": docker_bin, "version": "", "daemon_reachable": False, "socket_present": socket_present, "mode": "unavailable"}
    version, daemon_reachable = _docker_daemon_probe(docker_bin)
    if not daemon_reachable:
        mode = "unavailable"
    elif deployment == "container" and socket_present:
        mode = "dood"
    else:
        mode = "native"
    return {"cli_available": True, "binary": binary, "version": version, "daemon_reachable": daemon_reachable, "socket_present": socket_present, "mode": mode}


def _docker_daemon_probe(docker_bin: str) -> tuple[str, bool]:
    try:
        completed = subprocess.run([docker_bin, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=5, check=False)
    except Exception:  # noqa: BLE001 - probe must never raise
        return "", False
    output = (completed.stdout or "").strip()
    if completed.returncode == 0 and output:
        return f"Docker Engine {output}", True
    # CLI present but daemon not reachable (e.g. Desktop stopped): capture stderr hint.
    return (completed.stderr or "").strip()[:200], False


def _in_container() -> bool:
    if os.getenv("LINGSHU_GATE_IN_CONTAINER", "").lower() in {"1", "true", "yes", "on"}:
        return True
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


def _platform_key() -> str:
    name = sys.platform
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    if name.startswith("linux"):
        return "linux"
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    return system or "linux"

"""Docker helpers for managed_container MCP servers.

A ``managed_container`` + ``stdio`` MCP server is run as ``docker run -i --rm``,
so the container's stdin/stdout becomes the JSON-RPC channel and the existing
stdio client mechanism is reused unchanged. Only the Docker CLI is used so the
runtime stays dependency-free.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

from lingshu_gate.mcp_manifest import (
    ContainerMount,
    ContainerResources,
    McpServerManifest,
    require_digest_pinned_container_image,
)
from lingshu_gate.subprocess_environment import validate_docker_child_environment_names

DOCKER_BINARY = "docker"
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CONTAINER_TMPFS = (
    "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
    "/run:rw,noexec,nosuid,nodev,size=16m,mode=755",
)


def resolve_docker_binary(configured_binary: str) -> str:
    """Resolve the operator-configured Docker command before Manifest env exists."""

    configured = configured_binary.strip()
    if not configured:
        raise ValueError("Docker binary setting cannot be empty")
    candidate = configured if Path(configured).is_absolute() else shutil.which(configured)
    if not candidate:
        raise FileNotFoundError(f"Docker binary is not available: {configured!r}")
    resolved = Path(candidate).resolve()
    if not resolved.is_file() or not (resolved.stat().st_mode & 0o111):
        raise FileNotFoundError(f"Docker binary is not executable: {resolved}")
    return str(resolved)


def docker_available(configured_binary: str = DOCKER_BINARY) -> bool:
    """Return True when a docker CLI is discoverable on PATH."""

    try:
        resolve_docker_binary(configured_binary)
    except (OSError, ValueError):
        return False
    return True


def build_docker_command(
    manifest: McpServerManifest,
    environment: dict[str, str] | None = None,
    *,
    docker_binary: str = DOCKER_BINARY,
    allowed_root: Path,
) -> list[str]:
    """Build the ``docker run`` command for a managed_container stdio server.

    ``environment`` overrides/extends the manifest environment (already resolved
    for credential refs). Only variable names enter argv; the Docker CLI reads
    values from its minimal subprocess environment so secrets never appear in
    process listings or command logs.
    """

    launch = manifest.launch
    if launch.type != "managed_container":
        raise ValueError("build_docker_command requires launch.type=managed_container")
    if not launch.image:
        raise ValueError("launch.image is required for managed_container")
    image = require_digest_pinned_container_image(launch.image)

    resources = ContainerResources.model_validate(
        launch.resources.model_dump() if launch.resources is not None else {}
    )
    command: list[str] = [
        docker_binary,
        "run",
        "-i",
        "--rm",
        "--name",
        _container_name(manifest.id),
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        resources.memory,
        "--cpus",
        str(resources.cpus),
        "--pids-limit",
        str(resources.pids_limit),
    ]
    for tmpfs in CONTAINER_TMPFS:
        command.extend(["--tmpfs", tmpfs])

    env: dict[str, str] = dict(launch.environment or {})
    if environment:
        env.update(environment)
    validate_docker_child_environment_names(env)
    for key in sorted(env):
        if not ENVIRONMENT_NAME.fullmatch(key):
            raise ValueError(f"invalid managed_container environment name: {key!r}")
        command.extend(["-e", key])

    for configured_mount in launch.mounts:
        mount = ContainerMount.model_validate(configured_mount.model_dump())
        source = resolve_container_mount_source(mount.source, allowed_root)
        command.extend(
            [
                "--mount",
                f"type=bind,src={source},dst={mount.target},readonly",
            ]
        )

    command.append(image)
    command.extend(str(arg) for arg in (launch.args or []))
    return command


def resolve_container_mount_source(source: str, allowed_root: Path) -> Path:
    """Resolve one bind source and enforce the allowed-root boundary."""

    root = allowed_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"allowed_root must be a directory: {root}")
    candidate = Path(source)
    if not candidate.is_absolute():
        raise ValueError("managed_container mount source must be absolute")
    resolved = candidate.resolve(strict=True)
    if "," in str(resolved) or any(ord(character) < 32 for character in str(resolved)):
        raise ValueError(
            f"managed_container mount source resolves to an unsupported path: {resolved}"
        )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"managed_container mount source {resolved} is outside allowed_root {root}"
        ) from exc
    if not resolved.is_file() and not resolved.is_dir():
        raise ValueError(
            f"managed_container mount source must be a regular file or directory: {resolved}"
        )
    if not os.access(resolved, os.R_OK):
        raise PermissionError(f"managed_container mount source is not readable: {resolved}")
    return resolved


def _container_name(server_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in server_id).strip("-._")
    return f"lingshu-gate-{safe or 'server'}"


def container_command_preview(
    manifest: McpServerManifest,
    *,
    allowed_root: Path,
) -> dict[str, Any]:
    """Return a log-safe preview of the docker command (env values masked)."""

    preview = build_docker_command(manifest, allowed_root=allowed_root)
    for index, argument in enumerate(preview):
        if index > 0 and preview[index - 1] == "--mount":
            preview[index] = re.sub(r"(?<=src=)[^,]+", "***", argument)
    return {"command": preview, "image": manifest.launch.image, "container_name": _container_name(manifest.id)}

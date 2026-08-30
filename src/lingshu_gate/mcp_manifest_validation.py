"""MCP manifest validation and preflight checks."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from lingshu_gate.config import Settings
from lingshu_gate.credential_refs import extract_credential_refs, scan_env_credential_refs
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.endpoint_security import REDACTED_ENDPOINT, redact_endpoint
from lingshu_gate.mcp_container import (
    resolve_container_mount_source,
    resolve_docker_binary,
)
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime_cache import McpRuntimeCacheResolver
from lingshu_gate.redaction import redact_validation_errors

CheckSeverity = Literal["error", "warning", "info", "ok"]
SENSITIVE_ENV_PATTERN = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "CREDENTIAL", "AUTH", "COOKIE")


def validate_mcp_manifest(settings: Settings, config_store: McpConfigStore, manifest_data: dict[str, Any], *, expected_id: str | None = None) -> dict[str, Any]:
    """Validate a manifest and run read-only runtime preflight checks."""

    checks: list[dict[str, Any]] = []
    manifest: McpServerManifest | None = None

    if not isinstance(manifest_data, dict):
        checks.append(_check("manifest.root", "error", "Manifest root must be an object"))
        return _response(None, checks)

    manifest_id = str(manifest_data.get("id") or "").strip()
    if not manifest_id:
        checks.append(_check("manifest.id", "error", "id is required"))
    elif expected_id and manifest_id != expected_id:
        checks.append(_check("manifest.id_mismatch", "error", f"Manifest id mismatch: expected {expected_id}, got {manifest_id}", {"expected_id": expected_id, "actual_id": manifest_id}))

    validation_data = _restore_existing_endpoint_mask(
        config_store,
        manifest_data,
        expected_id,
    )
    try:
        manifest = McpServerManifest.model_validate(validation_data)
        checks.append(_check("manifest.schema", "ok", "Manifest schema is valid"))
    except ValidationError as exc:
        checks.append(
            _check(
                "manifest.schema",
                "error",
                "Manifest schema validation failed",
                {"errors": redact_validation_errors(exc.errors())},
            )
        )
        return _response(manifest_id or None, checks)

    credential_store = CredentialStore(settings.data_dir)
    _check_duplicate(config_store, manifest, expected_id, checks)
    _check_launch(settings, manifest, checks)
    _check_transport(manifest, checks)
    _check_paths(settings, manifest, checks)
    _check_runtime_cache(settings, manifest, checks)
    _check_timeout(manifest, checks)
    _check_permissions(manifest, checks)
    _check_env(manifest, credential_store, checks)
    _check_auto_start(manifest, checks)
    _check_restart_policy(manifest, checks)

    return _response(manifest.id, checks)


def _check_duplicate(config_store: McpConfigStore, manifest: McpServerManifest, expected_id: str | None, checks: list[dict[str, Any]]) -> None:
    try:
        existing = config_store.get_config(manifest.id)
    except KeyError:
        checks.append(_check("manifest.duplicate", "ok", "id is available", {"id": manifest.id}))
        return
    except Exception as exc:  # noqa: BLE001 - keep validation available even if one config is broken
        checks.append(_check("manifest.duplicate", "warning", f"Could not check duplicate id: {exc}", {"id": manifest.id}))
        return
    if expected_id and expected_id == manifest.id:
        checks.append(_check("manifest.duplicate", "ok", "editing existing config", {"id": manifest.id, "path": existing.path}))
        return
    checks.append(_check("manifest.duplicate", "warning", "A config with this id already exists; saving as new will fail unless overwrite is intended", {"id": manifest.id, "path": existing.path}))


def _check_launch(
    settings: Settings,
    manifest: McpServerManifest,
    checks: list[dict[str, Any]],
) -> None:
    launch = manifest.launch
    checks.append(_check("launch.type", "ok", f"launch.type={launch.type}"))
    if launch.type == "managed_process":
        command = launch.command or ""
        if not command:
            checks.append(_check("launch.command", "error", "managed_process requires launch.command"))
        else:
            resolved = shutil.which(command)
            severity: CheckSeverity = "ok" if resolved else "warning"
            checks.append(_check("launch.command", severity, f"command={command}" + (f" -> {resolved}" if resolved else " not found in current PATH"), {"command": command, "resolved": resolved}))
        if launch.command in {"npx", "npm"}:
            package_name = _first_npx_package(launch.args)
            if launch.package and launch.package.name:
                package_name = launch.package.name
            if package_name:
                checks.append(_check("launch.package", "info", f"dynamic npm package detected: {package_name}", {"package_name": package_name, "package": launch.package.model_dump(mode="json") if launch.package else None}))
            else:
                checks.append(_check("launch.package", "warning", "npx/npm launch detected but package name could not be inferred; consider adding launch.package.name"))
    elif launch.type == "external":
        checks.append(_check("launch.external", "info", "external server will not be started by Gate"))
    elif launch.type == "managed_container":
        try:
            resolved = resolve_docker_binary(settings.docker_bin)
        except (OSError, ValueError):
            resolved = None
        available = resolved is not None
        checks.append(
            _check(
                "launch.managed_container",
                "ok" if available else "warning",
                (
                    f"managed_container runtime is available through {resolved}"
                    if available
                    else f"managed_container is supported, but Docker CLI {settings.docker_bin!r} is unavailable"
                ),
                {
                    "docker_binary": settings.docker_bin,
                    "resolved": resolved,
                    "available": available,
                },
            )
        )


def _check_transport(manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    transport = manifest.transport
    if transport.type == "stdio":
        checks.append(
            _check(
                "transport.stdio",
                "ok",
                f"stdio transport is supported for {manifest.launch.type}",
            )
        )
    elif transport.type == "streamable_http":
        severity: CheckSeverity = "info" if transport.endpoint else "error"
        checks.append(
            _check(
                "transport.streamable_http",
                severity,
                "streamable_http endpoint is configured"
                if transport.endpoint
                else "streamable_http requires endpoint",
                {"endpoint": redact_endpoint(transport.endpoint)},
            )
        )
        if manifest.launch.type == "managed_process":
            checks.append(_check("transport.managed_http", "ok", "managed_process + streamable_http is supported"))


def _check_paths(settings: Settings, manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    allowed_root = settings.allowed_root.resolve()
    launch = manifest.launch
    if launch.cwd:
        _check_user_path("launch.cwd", Path(launch.cwd), allowed_root, checks)
    for index, mount in enumerate(launch.mounts):
        name = f"launch.mounts.{index}.source"
        try:
            resolved = resolve_container_mount_source(mount.source, allowed_root)
        except (OSError, RuntimeError, ValueError) as exc:
            checks.append(
                _check(
                    name,
                    "error",
                    str(exc),
                    {
                        "source": mount.source,
                        "target": mount.target,
                        "allowed_root": str(allowed_root),
                    },
                )
            )
        else:
            checks.append(
                _check(
                    name,
                    "ok",
                    f"read-only mount source is allowed: {resolved}",
                    {
                        "source": str(resolved),
                        "target": mount.target,
                        "read_only": True,
                    },
                )
            )
    for index, root in enumerate(manifest.roots):
        _check_user_path(f"roots.{index}", Path(root), allowed_root, checks)


def _check_user_path(name: str, path: Path, allowed_root: Path, checks: list[dict[str, Any]]) -> None:
    resolved = path.resolve() if path.is_absolute() else (allowed_root / path).resolve()
    exists = resolved.exists()
    inside_allowed = _is_inside(resolved, allowed_root)
    if not inside_allowed:
        checks.append(_check(name, "warning", f"{resolved} is outside allowed_root {allowed_root}", {"path": str(resolved), "allowed_root": str(allowed_root)}))
    if exists:
        checks.append(_check(name, "ok", f"path exists: {resolved}", {"path": str(resolved), "readable": os.access(resolved, os.R_OK), "writable": os.access(resolved, os.W_OK)}))
    else:
        checks.append(_check(name, "warning", f"path does not exist in current Gate container: {resolved}", {"path": str(resolved)}))


def _check_runtime_cache(settings: Settings, manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    plan = McpRuntimeCacheResolver(settings.data_dir).resolve(manifest)
    if not plan.enabled:
        checks.append(_check("runtime_cache", "info", "runtime cache is not required for this launch", plan.safe_dict()))
        return
    cache_dir = plan.cache_dir
    parent = cache_dir.parent if cache_dir else None
    exists = cache_dir.exists() if cache_dir else False
    writable = os.access(cache_dir, os.W_OK) if cache_dir and exists else False
    parent_writable = os.access(parent, os.W_OK) if parent and parent.exists() else False
    severity: CheckSeverity = "ok" if writable or parent_writable else "error"
    checks.append(_check("runtime_cache", severity, f"runtime cache dir: {cache_dir}", {**plan.safe_dict(), "exists": exists, "writable": writable, "parent_writable": parent_writable}))


def _check_timeout(manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    timeout = manifest.timeout_seconds
    launch = manifest.launch
    if timeout <= 0:
        checks.append(_check("timeout_seconds", "error", "timeout_seconds must be greater than 0"))
    elif launch.command in {"npx", "npm"} and timeout < 120:
        checks.append(_check("timeout_seconds", "warning", "dynamic npm/npx MCP servers should usually use timeout_seconds >= 120", {"timeout_seconds": timeout}))
    elif timeout < 30:
        checks.append(_check("timeout_seconds", "warning", "timeout_seconds is low; startup may fail on slow machines", {"timeout_seconds": timeout}))
    else:
        checks.append(_check("timeout_seconds", "ok", f"timeout_seconds={timeout}"))


def _check_permissions(manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    permissions = manifest.permissions or {}
    if not permissions:
        checks.append(_check("permissions", "warning", "permissions is empty; consider declaring intended access scope"))
        return
    text = str(permissions).lower()
    if "write" in text or "admin" in text or "*" in text:
        checks.append(_check("permissions", "warning", "permissions include write/admin/wildcard; confirm this server really needs elevated access", {"permissions": permissions}))
    else:
        checks.append(_check("permissions", "ok", "permissions declared", {"permissions": permissions}))


def _check_env(manifest: McpServerManifest, credential_store: CredentialStore, checks: list[dict[str, Any]]) -> None:
    container_environment = manifest.launch.type == "managed_container"
    env = (
        manifest.launch.environment
        if container_environment
        else manifest.launch.env
    ) or {}
    field_name = "launch.environment" if container_environment else "launch.env"
    if not env:
        checks.append(_check(field_name, "info", f"no {field_name} configured"))
        return
    sensitive = [key for key in env if any(token in key.upper() for token in SENSITIVE_ENV_PATTERN)]
    masked_empty = [key for key, value in env.items() if str(value).strip() in {"", "***", "changeme", "CHANGE_ME"}]
    credential_scan = scan_env_credential_refs(env, credential_store)
    credential_keys = sorted({key for keys in credential_scan.references.values() for key in keys})
    if credential_scan.has_references:
        checks.append(_check(f"{field_name}.credential_refs", "info", f"credential refs detected: {', '.join(sorted(credential_scan.references))}", {"references": credential_scan.references}))
    if credential_scan.has_missing:
        checks.append(_check(f"{field_name}.credential_missing", "error", f"missing credential refs: {', '.join(sorted(credential_scan.missing))}", {"missing": credential_scan.missing}))
    else:
        for ref, keys in sorted(credential_scan.references.items()):
            checks.append(_check(f"{field_name}.credential_exists", "ok", f"credential exists: {ref}", {"credential_id": ref, "env_keys": keys}))
    if sensitive:
        plain_sensitive = [key for key in sensitive if key not in credential_keys and not extract_credential_refs(str(env.get(key, "")))]
        checks.append(_check(f"{field_name}.sensitive", "info", f"sensitive env keys detected: {', '.join(sensitive)}", {"keys": sensitive, "credential_backed_keys": credential_keys}))
        if plain_sensitive:
            checks.append(_check(f"{field_name}.plain_sensitive", "warning", f"sensitive env keys are plain text, consider credential refs: {', '.join(plain_sensitive)}", {"keys": plain_sensitive}))
    if masked_empty:
        checks.append(_check(f"{field_name}.empty", "warning", f"env values may be empty or placeholders: {', '.join(masked_empty)}", {"keys": masked_empty}))


def _check_auto_start(manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    if manifest.launch.type == "external" and manifest.auto_start:
        checks.append(_check("auto_start", "warning", "external servers cannot be auto-started by Gate"))
    elif manifest.auto_start and manifest.launch.command in {"npx", "npm"}:
        checks.append(_check("auto_start", "info", "auto_start is enabled for dynamic npm/npx server; first startup may be slower"))
    else:
        checks.append(_check("auto_start", "ok", f"auto_start={manifest.auto_start}"))


def _check_restart_policy(manifest: McpServerManifest, checks: list[dict[str, Any]]) -> None:
    policy = manifest.restart_policy
    metadata = policy.model_dump(mode="json")
    if not policy.enabled:
        checks.append(_check("restart_policy", "info", "restart policy is disabled", metadata))
        return
    restart_supported = (
        manifest.launch.type == "managed_process"
        and manifest.transport.type in {"stdio", "streamable_http"}
    ) or (
        manifest.launch.type == "managed_container"
        and manifest.transport.type == "stdio"
    )
    if not restart_supported:
        checks.append(_check("restart_policy", "warning", "restart policy only applies to managed_process + stdio/streamable_http or managed_container + stdio", metadata))
        return
    if policy.max_attempts <= 0:
        checks.append(_check("restart_policy.max_attempts", "warning", "restart policy is enabled but max_attempts is 0", metadata))
    elif policy.delay_seconds <= 0:
        checks.append(_check("restart_policy.delay_seconds", "warning", "restart delay is 0; repeated failures may restart too aggressively", metadata))
    else:
        checks.append(_check("restart_policy", "ok", f"restart policy enabled: max_attempts={policy.max_attempts}, delay_seconds={policy.delay_seconds}", metadata))
    if policy.reset_after_seconds == 0:
        checks.append(_check("restart_policy.reset_after_seconds", "info", "restart attempts will not reset automatically", metadata))
    elif policy.reset_after_seconds < 60:
        checks.append(_check("restart_policy.reset_after_seconds", "warning", "reset_after_seconds is low; unstable servers may never exhaust attempts", metadata))
    health = policy.health_check
    if health.enabled:
        if health.interval_seconds < health.timeout_seconds:
            checks.append(_check("restart_policy.health_check", "warning", "health_check.interval_seconds should usually be >= timeout_seconds", metadata))
        else:
            checks.append(_check("restart_policy.health_check", "ok", f"health check enabled: {health.method} every {health.interval_seconds}s", metadata))
    else:
        checks.append(_check("restart_policy.health_check", "info", "health check is disabled", metadata))


def _first_npx_package(args: list[str]) -> str | None:
    skip_next = False
    expect_package = False
    for arg in args:
        if expect_package:
            return arg
        if skip_next:
            skip_next = False
            continue
        if arg in {"-y", "--yes", "--no", "--quiet", "--silent"}:
            continue
        if arg in {"--cache", "--userconfig", "--prefix", "--registry"}:
            skip_next = True
            continue
        if arg in {"--package", "-p"}:
            expect_package = True
            continue
        if arg.startswith("--"):
            if arg.startswith("--package="):
                return arg.split("=", 1)[1]
            continue
        return arg
    return None


def _response(manifest_id: str | None, checks: list[dict[str, Any]]) -> dict[str, Any]:
    error_count = sum(1 for check in checks if check["severity"] == "error")
    warning_count = sum(1 for check in checks if check["severity"] == "warning")
    ok = error_count == 0
    can_apply = error_count == 0
    return {
        "ok": ok,
        "can_apply": can_apply,
        "manifest_id": manifest_id,
        "summary": {
            "errors": error_count,
            "warnings": warning_count,
            "info": sum(1 for check in checks if check["severity"] == "info"),
            "ok": sum(1 for check in checks if check["severity"] == "ok"),
        },
        "checks": checks,
    }


def _restore_existing_endpoint_mask(
    config_store: McpConfigStore,
    manifest_data: dict[str, Any],
    expected_id: str | None,
) -> dict[str, Any]:
    restored = dict(manifest_data)
    transport = dict(restored.get("transport") or {})
    if transport.get("endpoint") != REDACTED_ENDPOINT or not expected_id:
        return restored
    try:
        existing = config_store.load_manifest(expected_id)
    except (KeyError, ValueError):
        return restored
    transport["endpoint"] = existing.transport.endpoint
    restored["transport"] = transport
    return restored


def _check(name: str, severity: CheckSeverity, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "severity": severity, "message": message, "metadata": metadata or {}}


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

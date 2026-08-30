"""Dynamic MCP runtime cache helpers.

The cache layer keeps user MCP servers dynamic while avoiding repeated cold-start
work from package managers such as npm/npx. It does not bake user MCP packages
into the Gate image; it only injects persistent cache directories under data_dir.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lingshu_gate.mcp_manifest import McpServerManifest


@dataclass(frozen=True)
class RuntimeCachePlan:
    """Resolved cache behavior for one MCP process launch."""

    enabled: bool
    manager: str | None = None
    cache_dir: Path | None = None
    package_name: str | None = None
    package_version: str | None = None
    install_hint: str | None = None
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "manager": self.manager,
            "cache_dir": str(self.cache_dir) if self.cache_dir else None,
            "package_name": self.package_name,
            "package_version": self.package_version,
            "install_hint": self.install_hint,
            "command": self.command,
            "metadata": self.metadata,
        }


class McpRuntimeCacheResolver:
    """Resolve persistent cache settings for dynamic MCP process launches."""

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "runtime-cache"
        self.npm_cache_dir = self.root / "npm-cache"

    def resolve(self, manifest: McpServerManifest) -> RuntimeCachePlan:
        launch = manifest.launch
        command = [launch.command or "", *launch.args]
        if not command[0]:
            return RuntimeCachePlan(enabled=False, command=command)

        explicit_package = launch.package
        manager = explicit_package.manager if explicit_package else self._detect_manager(command[0])
        if manager not in {"npm", "npx"}:
            return RuntimeCachePlan(enabled=False, command=command, metadata={"reason": "unsupported_manager", "manager": manager})

        package_name = explicit_package.name if explicit_package else (self._extract_npx_package(command) if manager == "npx" else None)
        package_version = explicit_package.version if explicit_package else None
        if not explicit_package and package_name and "@" in package_name[1:]:
            package_name, package_version = package_name.rsplit("@", 1)

        if explicit_package and explicit_package.cache is False:
            return RuntimeCachePlan(enabled=False, manager=manager, package_name=package_name, package_version=package_version, command=command, metadata={"reason": "package_cache_disabled"})

        env = {
            "NPM_CONFIG_CACHE": str(self.npm_cache_dir),
            "npm_config_cache": str(self.npm_cache_dir),
            "npm_config_update_notifier": "false",
            "NO_UPDATE_NOTIFIER": "1",
        }
        install_hint = None
        if package_name:
            install_hint = f"dynamic npm package via {manager}: {package_name}{('@' + package_version) if package_version else ''}"

        return RuntimeCachePlan(
            enabled=True,
            manager=manager,
            cache_dir=self.npm_cache_dir,
            package_name=package_name,
            package_version=package_version,
            install_hint=install_hint,
            command=command,
            env=env,
            metadata={"cache_scope": "npm", "strategy": "persistent_npm_cache", "explicit_package": bool(explicit_package)},
        )

    def prepare(self, plan: RuntimeCachePlan) -> None:
        if plan.cache_dir:
            plan.cache_dir.mkdir(parents=True, exist_ok=True)

    def _detect_manager(self, command: str) -> str | None:
        name = Path(command).name.lower()
        if name in {"npx", "npx.cmd"}:
            return "npx"
        if name in {"npm", "npm.cmd"}:
            return "npm"
        return None

    def _extract_npx_package(self, command: list[str]) -> str | None:
        """Best-effort package extraction from common `npx -y package` commands."""

        args = command[1:]
        expect_package_value = False
        skip_value = False
        options_with_value = {"--cache", "--userconfig", "--prefix", "--registry"}
        package_candidate: str | None = None
        for arg in args:
            if expect_package_value:
                package_candidate = arg
                expect_package_value = False
                continue
            if skip_value:
                skip_value = False
                continue
            if arg in {"-y", "--yes", "--no", "--quiet", "--silent"}:
                continue
            if arg in {"--package", "-p"}:
                expect_package_value = True
                continue
            if arg in options_with_value:
                skip_value = True
                continue
            if arg.startswith("--"):
                key, sep, value = arg.partition("=")
                if key in {"--package", "-p"} and sep:
                    package_candidate = value
                continue
            if arg == "--":
                continue
            package_candidate = arg
            break
        if package_candidate:
            return shlex.split(package_candidate)[0] if any(ch.isspace() for ch in package_candidate) else package_candidate
        return None

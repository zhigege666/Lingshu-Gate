"""Bounded Node inspection and explicit tool preparation specifications; no download."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

LOCKS = {"package-lock.json": "npm", "npm-shrinkwrap.json": "npm", "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn"}
SUPPORTED_MAJORS = {"npm": {9, 10, 11}, "pnpm": {8, 9, 10, 11}, "yarn": {1}}
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DECLARATION = re.compile(r"^(npm|pnpm|yarn)@(\d+\.\d+\.\d+)(?:\+sha(?:224|256|384|512)\.[A-Za-z0-9+/=]+)?$")
# Policy pins displayed in the confirmed plan; never resolve a moving latest tag.
DEFAULT_VERSIONS = {"npm": "11.6.0", "pnpm": "9.15.4", "yarn": "1.22.22"}
INSTALL_COMMANDS = {"npm": ["npm", "ci"], "pnpm": ["pnpm", "install", "--frozen-lockfile"], "yarn": ["yarn", "install", "--frozen-lockfile"]}


def supported_version(name: str, version: str) -> bool:
    match = VERSION.fullmatch(version)
    if not match or int(match[1]) not in SUPPORTED_MAJORS.get(name, set()):
        return False
    return name != "yarn" or int(match[2]) == 22


def node_requirement(name: str, version: str) -> str:
    return ">=22.13" if name == "pnpm" and VERSION.fullmatch(version) and version.startswith("11.") else "verify_official_engines"


def node_version_supported(name: str, version: str, node_version: str) -> bool:
    if node_requirement(name, version) != ">=22.13":
        return True
    match = VERSION.fullmatch(node_version.removeprefix("v"))
    return bool(match and tuple(int(part) for part in match.groups()) >= (22, 13, 0))


class NodeToolchainOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Literal["npm", "pnpm", "yarn"]
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=32)
    lockfile: Literal["package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"] | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> NodeToolchainOverride:
        if not supported_version(self.name, self.version):
            raise ValueError("Requested package manager version is unsupported")
        if self.lockfile and LOCKS[self.lockfile] != self.name:
            raise ValueError("Selected lockfile belongs to another package manager")
        return self


def tool_preparation(name: str, version: str, declared_integrity: str | None = None) -> dict[str, Any]:
    if not supported_version(name, version):
        raise ValueError("Unsupported package manager preparation")
    if declared_integrity:
        matched = re.fullmatch(r"sha(224|256|384|512)\.([a-fA-F0-9]+)", declared_integrity)
        if not matched or len(matched[2]) != int(matched[1]) // 4:
            raise ValueError("Unsupported packageManager integrity pin")
    return {
        "name": name, "version": version, "method": "official_distribution",
        "official_metadata_url": f"https://registry.npmjs.org/{name}/{version}",
        "integrity_policy": "verify_official_sha512_before_extract",
        "declared_integrity": declared_integrity,
        "cache_key_fields": ["name", "version", "source_integrity"],
        "node_engine_policy": "verify_official_engines",
        "node_requirement": node_requirement(name, version),
        "unplanned_tool_downloads": False,
        "corepack_required": False, "execute_lifecycle": False,
        "limits": {"timeout_seconds": 120, "metadata_bytes": 1024 * 1024, "archive_bytes": 50 * 1024 * 1024, "expanded_bytes": 200 * 1024 * 1024, "files": 4000, "retries": 0},
    }


def node_bin_entrypoint(package: dict[str, Any]) -> str:
    raw = package.get("bin")
    values = [raw] if isinstance(raw, str) else list(raw.values()) if isinstance(raw, dict) else []
    if not values or any(not isinstance(value, str) for value in values) or len(set(values)) != 1:
        return ""
    value = values[0].removeprefix("./")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("-") or path.as_posix() != value or ".." in path.parts or ".git" in path.parts or ":" in value or "\\" in value or any(ord(ch) < 32 for ch in value):
        return ""
    return value if path.suffix in {".js", ".cjs", ".mjs"} else ""


def inspect_node_toolchain(root: Path, package: dict[str, Any], files: set[str], tools: dict[str, Any], override: NodeToolchainOverride | None = None, *, isolated_toolchain: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    # Only files immediately inside the selected project root participate.
    detected = sorted(set(LOCKS) & files)
    declaration = package.get("packageManager")
    matched = DECLARATION.fullmatch(str(declaration)) if declaration is not None else None
    declared_integrity = str(declaration).split("+", 1)[1] if matched and "+" in str(declaration) and not override else None
    if declared_integrity:
        integrity_match = re.fullmatch(r"sha(224|256|384|512)\.([a-fA-F0-9]+)", declared_integrity)
        if not integrity_match or len(integrity_match[2]) != int(integrity_match[1]) // 4:
            errors.append("packageManager integrity must be a supported exact hexadecimal digest")
    managers = {LOCKS[lock] for lock in detected}
    name = override.name if override else matched[1] if matched else next(iter(managers)) if len(managers) == 1 else "npm"
    selected_by = "project_override" if override else "packageManager" if matched else "lockfile" if detected else "default_policy"
    if declaration is not None and not matched:
        (warnings if override else errors).append("packageManager is not an exact supported declaration; an explicit project override is required")
    if override and matched and (override.name, override.version) != (matched[1], matched[2]):
        warnings.append("Explicit saved project override takes precedence over packageManager")
    if override and matched and "+" in str(declaration):
        warnings.append("Explicit project override replaces the declared integrity pin; official distribution verification remains required")
    if not override and not matched and len(managers) > 1:
        errors.append("Ambiguous dependency lockfiles: select a recommended project override")
    matching = [lock for lock in detected if LOCKS[lock] == name]
    lockfile = override.lockfile if override and override.lockfile else "npm-shrinkwrap.json" if "npm-shrinkwrap.json" in matching else matching[0] if matching else ""
    if lockfile and lockfile not in detected:
        errors.append("Selected dependency lockfile does not exist in this project root")
    if name == "npm" and lockfile == "package-lock.json" and "npm-shrinkwrap.json" in matching:
        errors.append("npm uses npm-shrinkwrap.json when present; select its native precedence")
    if detected and not matching:
        errors.append("packageManager conflicts with the dependency lockfile; select an explicit project override")
    if len(detected) > 1 and not errors:
        warnings.append(f"Selected {lockfile}; other lockfiles are preserved and are not consumed by this build")
    tool = tools.get(name) or {}
    observed = "" if isolated_toolchain else str(tool.get("version") or "").strip().removeprefix("v")
    version = override.version if override else matched[2] if matched else observed if supported_version(name, observed) else DEFAULT_VERSIONS[name]
    if not supported_version(name, version):
        errors.append("Requested packageManager version is unknown or outside the supported range; no replacement is permitted")
    elif not override and not matched and version != observed:
        warnings.append(f"No exact packageManager version is declared; the confirmed plan pins policy version {name}@{version}")
    requires_prepare = isolated_toolchain or bool(declared_integrity) or not tool.get("available") or observed != version
    requirement = node_requirement(name, version)
    if requirement == ">=22.13":
        warnings.append("pnpm 11 requires actual executor Node >=22.13; Node is not automatically upgraded")
        if not isolated_toolchain and not requires_prepare and not node_version_supported(name, version, str((tools.get("node") or {}).get("version") or "")):
            errors.append("pnpm 11 requires Node >=22.13; provision a reviewed execution environment or explicitly select a compatible project override")
    if requires_prepare and not errors:
        warnings.append(f"Prepare {name}@{version} from its verified official distribution in the isolated executor; no host installation")
    lock_digest, lock_version = "", ""
    if lockfile and lockfile in detected:
        try:
            lock_digest, lock_version = _read_lockfile(root, lockfile, name, version)
        except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError, RecursionError):
            errors.append("Dependency lockfile format is invalid or unsupported for this manager version")
    choices = []
    for lock in detected:
        choice_name = LOCKS[lock]
        if lock == "package-lock.json" and "npm-shrinkwrap.json" in detected:
            continue
        installed = "" if isolated_toolchain else str((tools.get(choice_name) or {}).get("version") or "").strip().removeprefix("v")
        candidates = [installed, DEFAULT_VERSIONS[choice_name]]
        if choice_name == "pnpm":
            candidates.append("8.15.9")
        for candidate in dict.fromkeys(candidates):
            if not supported_version(choice_name, candidate):
                continue
            try:
                _read_lockfile(root, lock, choice_name, candidate)
            except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError, RecursionError):
                continue
            choices.append({"name": choice_name, "version": candidate, "lockfile": lock})
            break
    return {
        "name": name, "version": version, "expected_version": matched[2] if matched else "",
        "observed_version": observed if VERSION.fullmatch(observed) else "", "selected_by": selected_by,
        "observation_scope": "executor_cache_pending" if isolated_toolchain else "local_host",
        "node_requirement": requirement,
        "project_override": override.model_dump() if override else None, "requires_prepare": requires_prepare,
        "declared_integrity": declared_integrity,
        "preparation": tool_preparation(name, version, declared_integrity) if requires_prepare and not errors else None,
        "lockfile": lockfile, "lockfile_version": lock_version, "lockfile_sha256": lock_digest,
        "detected_lockfiles": detected, "errors": errors, "warnings": warnings,
        "recommended_choices": choices if errors else [], "supported": not errors,
        "recommended_actions": (["Provision actual Node >=22.13 in the reviewed executor; do not automatically change the pnpm 11 pin"] if errors and requirement == ">=22.13" else ["Select a supported exact manager and a matching committed lockfile; unsupported Yarn Berry is never converted to Classic"] if errors else []),
    }


def _read_lockfile(root: Path, lockfile: str, name: str, version: str) -> tuple[str, str]:
    path = root / lockfile
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Unsupported lockfile")
    content = path.read_bytes()
    if name == "npm":
        lock_version = str(json.loads(content).get("lockfileVersion", ""))
        if lock_version not in {"2", "3"}:
            raise ValueError("Unsupported npm lockfile")
    elif name == "pnpm":
        lock_version = str(yaml.safe_load(content).get("lockfileVersion", ""))
        major = int(version.split(".")[0])
        if (major == 8 and lock_version not in {"6", "6.0"}) or (major in {9, 10, 11} and lock_version not in {"9", "9.0"}) or major not in {8, 9, 10, 11}:
            raise ValueError("Unsupported pnpm lockfile")
    else:
        lock_version = "1" if b"# yarn lockfile v1" in content[:2048] and b"__metadata:" not in content else ""
        if lock_version != "1":
            raise ValueError("Yarn Berry is unsupported; no Classic conversion or fallback")
    return hashlib.sha256(content).hexdigest(), lock_version

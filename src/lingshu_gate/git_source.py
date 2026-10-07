"""Pure Git source/input/snapshot policy; never runs Git on the Core host."""

from __future__ import annotations

import hashlib
import base64
import io
import ipaddress
import json
import re
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from pydantic import Field, model_validator

from lingshu_gate.network_settings import GitHostRule, NetworkSelection, PROFILE_ID, StrictModel, validate_endpoint
from lingshu_gate.project_uploads import MAX_EXTRACTED_BYTES, MAX_FILES, MAX_ZIP_BYTES, _validated_zip_member
from lingshu_gate.registry import ToolExecutionError

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SENSITIVE_PARTS = {".env", ".netrc", ".git-credentials", "id_rsa", "id_ed25519", "credentials.json", "credential.key", ".ssh", ".aws", ".git", ".npmrc", ".yarnrc", ".yarnrc.yml", "pip.conf", ".pypirc"}
SECRET_TEXT = re.compile(rb"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})")
GIT_POLICY = {
    "protocol.allow": "never", "protocol.https.allow": "always",
    "core.hooksPath": "/dev/null", "credential.helper": "",
    "core.fsmonitor": "false", "init.templateDir": "", "http.sslVerify": "true",
    "http.followRedirects": "false", "submodule.recurse": "false",
    "fetch.recurseSubmodules": "false", "filter.lfs.required": "false",
    "filter.lfs.smudge": "", "filter.lfs.process": "",
}
GIT_ENVIRONMENT_POLICY = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_ALLOW_PROTOCOL": "https", "GIT_OPTIONAL_LOCKS": "0"}
SNAPSHOT_CHUNK_BYTES = 64 * 1024
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def network_secret_values(material: dict[str, Any]) -> list[str]:
    """Derive actual Basic/proxy password components, never usernames alone.

    This uses the same first-colon split as trusted Git/proxy authentication.
    Preserve every original material value and add its secret component so
    reflected bare tokens and their existing URL/base64 forms are also scanned.
    Short components remain active; conservative rejection is intentional.
    """
    values = [value for value in material.values() if isinstance(value, str)]
    for key, value in material.items():
        if key.rsplit(".", 1)[-1] in {"git_credential", "proxy_credential"} and isinstance(value, str) and ":" in value:
            _, secret = value.split(":", 1)
            if not secret:
                raise ValueError("Network credential secret component is empty")
            values.append(secret)
    return list(dict.fromkeys(values))


def snapshot_forbidden_values(values: list[str]) -> frozenset[bytes]:
    """Bound scanner state; do not retain arbitrarily large network material."""
    if len(values) > 32 or any(len(value) > 64 * 1024 for value in values):
        raise ValueError("Git snapshot network scan material exceeds limit")
    forbidden: set[bytes] = set()
    total = 0
    for value in values:
        if value:
            raw = value.encode()
            total += len(raw)
            if len(raw) > 64 * 1024 or total > 256 * 1024:
                raise ValueError("Git snapshot network scan material exceeds limit")
            forbidden.update({raw, quote(value, safe="").encode(), base64.b64encode(raw)})
    return frozenset(forbidden)


def validate_snapshot_path(entry: zipfile.ZipInfo, forbidden: frozenset[bytes]) -> tuple[str, str]:
    """Shared raw-object/ZIP path policy, including every unselected subtree."""
    parts, key = _validated_zip_member(entry)
    relative = "/".join(parts)
    if any(value in relative.encode() for value in forbidden):
        raise ValueError("Git snapshot path contains network material")
    if any(part.lower() in SENSITIVE_PARTS or part.lower().startswith(".env") or part.lower().endswith((".pem", ".key", ".p12", ".pfx")) for part in parts):
        raise ValueError("Git snapshot contains sensitive/configuration paths")
    if any(part.lower().endswith(".gitmodules") for part in parts):
        raise ValueError("Git submodules are unsupported; remove submodules before import")
    return relative, key


class SnapshotContentScanner:
    """Incremental content/hash scan; neither decoder nor scanner loads a blob."""

    def __init__(self, forbidden: frozenset[bytes], max_bytes: int) -> None:
        self.forbidden = forbidden
        self.max_bytes = max_bytes
        self.size = 0
        self.digest = hashlib.sha256()
        self._overlap = max(128, *(len(value) for value in forbidden)) if forbidden else 128
        self._tail = b""
        self._prefix = b""

    def update(self, chunk: bytes) -> None:
        if len(chunk) > SNAPSHOT_CHUNK_BYTES or self.size + len(chunk) > self.max_bytes:
            raise ValueError("Git snapshot exceeds expanded size or chunk limit")
        window = self._tail + chunk
        if any(value in window for value in self.forbidden):
            raise ValueError("Git snapshot contains network material")
        if SECRET_TEXT.search(window):
            raise ValueError("Git snapshot contains possible credentials; review source")
        self._prefix = (self._prefix + chunk)[:len(LFS_PREFIX)]
        if self._prefix == LFS_PREFIX:
            raise ValueError("Git LFS is unsupported; materialize and review regular source files before import")
        self._tail = window[-self._overlap:]
        self.size += len(chunk)
        self.digest.update(chunk)


class GitSourceInput(StrictModel):
    repository_url: str = Field(min_length=1, max_length=2048)
    ref_type: Literal["branch", "tag", "commit"] = "branch"
    ref: str = Field(default="main", min_length=1, max_length=200)
    project_root: str = Field(default=".", min_length=1, max_length=500)
    credential_ref: str | None = Field(default=None, pattern=PROFILE_ID)
    git_network: NetworkSelection = Field(default_factory=NetworkSelection)
    install_network: NetworkSelection = Field(default_factory=NetworkSelection)
    runtime_template: Literal["node", "python"] = "node"

    @model_validator(mode="after")
    def safe_input(self) -> GitSourceInput:
        if self.repository_url.startswith(("ssh:", "git@")):
            raise ValueError("Git SSH requires a separate reviewed SSH executor; HTTP proxies do not provide SSH support")
        validate_endpoint(self.repository_url, {"https"})
        parsed = urlsplit(self.repository_url)
        if not parsed.path or parsed.path == "/" or any(part in {".", "..", ""} for part in parsed.path[1:].split("/")):
            raise ValueError("repository URL requires an unambiguous repository path")
        validate_project_subdirectory(self.project_root)
        if self.ref_type == "commit":
            if not COMMIT_RE.fullmatch(self.ref):
                raise ValueError("commit must be a full lowercase 40-character SHA")
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.ref) or any(value in self.ref for value in ("..", "//", "@{", "\\")) or self.ref.endswith((".", "/", ".lock")) or any(part.startswith(".") or part.endswith(".lock") for part in self.ref.split("/")):
            raise ValueError("ref must be a safe branch/tag name, not an option or revision expression")
        return self


def validate_project_subdirectory(value: str) -> None:
    path = PurePosixPath(value)
    if value != "." and (path.is_absolute() or path.as_posix() != value or any(part in {"..", ".git"} for part in path.parts) or ":" in value or "\\" in value or any(ord(ch) < 32 for ch in value)):
        raise ValueError("project_root must be a safe relative directory")


def repository_rule(repository_url: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = urlsplit(repository_url)
    for raw in rules:
        rule = GitHostRule.model_validate(raw)
        if parsed.hostname == rule.host and (parsed.port or 443) == rule.port:
            return rule.model_dump()
    raise ToolExecutionError("git_host_not_allowed", "Repository host/port is not allowed", next_action="An administrator must add the exact Git host policy before import.")


def validate_resolved_addresses(rule: dict[str, Any], addresses: list[str]) -> None:
    """Executor must use these validated IPs for every connect, including proxy egress."""
    if not addresses:
        raise ValueError("DNS resolution returned no addresses")
    cidrs = [ipaddress.ip_network(cidr) for cidr in rule.get("private_cidrs", [])]
    for value in addresses:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or str(address) == "100.100.100.200":
            raise ValueError("resolved address is forbidden")
        if not address.is_global and not any(address in cidr for cidr in cidrs):
            raise ValueError("non-public address requires an explicit administrator CIDR")


def digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_git_snapshot(upload: dict[str, Any]) -> None:
    """Detect file edits/additions/removals before planning or queuing a Git build."""
    analysis = upload.get("analysis") or {}
    source = analysis.get("git_source")
    if not source:
        return
    entries = analysis.get("included_files") or []
    if not entries or digest_json(entries) != analysis.get("file_list_sha256"):
        raise ToolExecutionError("git_snapshot_changed", "Source inventory digest is invalid", next_action="Import and confirm a new exact commit snapshot.")
    prefix = "" if source["project_root"] == "." else source["project_root"] + "/"
    expected = {entry["path"].removeprefix(prefix): entry for entry in entries if not prefix or entry["path"].startswith(prefix)}
    root = Path(upload["root_dir"])
    deadline = time.monotonic() + 30
    actual: set[str] = set()
    total = 0
    try:
        for path in root.rglob("*"):
            if time.monotonic() > deadline or path.is_symlink():
                raise ValueError
            if path.is_dir():
                continue
            relative = path.relative_to(root).as_posix()
            entry = expected.get(relative)
            if not path.is_file() or entry is None or path.stat().st_size != entry["size_bytes"]:
                raise ValueError
            actual.add(relative)
            total += entry["size_bytes"]
            if len(actual) > MAX_FILES or total > MAX_EXTRACTED_BYTES:
                raise ValueError
            digest = hashlib.sha256()
            with path.open("rb") as reader:
                while chunk := reader.read(1024 * 1024):
                    if time.monotonic() > deadline:
                        raise ValueError
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError
        if actual != set(expected):
            raise ValueError
    except (OSError, ValueError):
        raise ToolExecutionError("git_snapshot_changed", "Imported source snapshot changed or exceeded verification bounds", next_action="Import and confirm a fresh exact commit; do not reuse this plan.") from None


def snapshot_inventory(content: bytes, project_root: str, *, forbidden_values: list[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Inspect every entry, including outside the selected project, before importing."""
    validate_project_subdirectory(project_root)
    if len(content) > MAX_ZIP_BYTES:
        raise ValueError("Git snapshot exceeds compressed size limit")
    files: list[dict[str, Any]] = []
    expanded = 0
    seen: set[str] = set()
    forbidden = snapshot_forbidden_values(forbidden_values or [])
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise ValueError("Git snapshot exceeds file count limit")
        for entry in archive.infolist():
            relative, key = validate_snapshot_path(entry, forbidden)
            if key in seen:
                raise ValueError("Git snapshot contains duplicate/ambiguous paths")
            seen.add(key)
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Git snapshot cannot contain links")
            if entry.is_dir():
                continue
            expanded += entry.file_size
            if expanded > MAX_EXTRACTED_BYTES:
                raise ValueError("Git snapshot exceeds expanded size limit")
            scanner = SnapshotContentScanner(forbidden, entry.file_size)
            with archive.open(entry) as reader:
                while chunk := reader.read(SNAPSHOT_CHUNK_BYTES):
                    scanner.update(chunk)
            if scanner.size != entry.file_size:
                raise ValueError("Git snapshot entry size does not match its declared size")
            files.append({"path": relative, "size_bytes": scanner.size, "sha256": scanner.digest.hexdigest()})
    if not files or (project_root != "." and not any(item["path"].startswith(project_root + "/") for item in files)):
        raise ValueError("selected project directory has no files")
    inventory = sorted(files, key=lambda item: item["path"])
    return digest_json(inventory), inventory

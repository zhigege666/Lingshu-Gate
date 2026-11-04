"""GitHub release checks with an optional, version-pinned managed proxy."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
import re

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.network_settings import NetworkSettingsStore
from lingshu_gate.registry import ToolExecutionError

RELEASE_API = "https://api.github.com/repos/zhigege666/Lingshu-Gate/releases/latest"
MAX_RELEASE_BYTES = 1024 * 1024
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")

def _version_parts(value: str) -> tuple[tuple[int, int, int], tuple[tuple[int, int | str], ...] | None]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ValueError("invalid semantic version")
    core = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    prerelease = match.group(4)
    if prerelease is None:
        return core, None
    identifiers: list[tuple[int, int | str]] = []
    for item in prerelease.split("."):
        if not item or (item.isdigit() and len(item) > 1 and item.startswith("0")):
            raise ValueError("invalid semantic version prerelease")
        identifiers.append((0, int(item)) if item.isdigit() else (1, item))
    return core, tuple(identifiers)


def _is_newer(candidate: str, current: str) -> bool:
    candidate_core, candidate_pre = _version_parts(candidate)
    current_core, current_pre = _version_parts(current)
    if candidate_core != current_core:
        return candidate_core > current_core
    if candidate_pre is None:
        return current_pre is not None
    if current_pre is None:
        return False
    for left, right in zip(candidate_pre, current_pre):
        if left != right:
            return left > right
    return len(candidate_pre) > len(current_pre)

class ReleaseUpdateService:
    def __init__(self, database: SQLiteDatabase, network: NetworkSettingsStore, current_version: str, audit: Any) -> None:
        self.database = database
        self.network = network
        self.current_version = current_version
        self.audit = audit

    def settings(self) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM release_update_settings WHERE id=1")
        profile_id = str(row["proxy_profile_id"]) if row and row["proxy_profile_id"] else None
        profile_version = int(row["proxy_profile_version"]) if row and row["proxy_profile_version"] else None
        profile = None
        if profile_id and profile_version:
            try:
                selected = self.network._version(profile_id, profile_version)
                profile = {"id": profile_id, "version": profile_version, "name": str(selected["name"]), "enabled": bool(selected["enabled"])}
            except ToolExecutionError:
                profile = {"id": profile_id, "version": profile_version, "name": "Unavailable", "enabled": False}
        return {"revision": int(row["revision"]) if row else 0, "proxy_profile": profile}

    def save(self, *, expected_revision: int, proxy_profile_id: str | None, proxy_profile_version: int | None, actor_id: str) -> dict[str, Any]:
        if (proxy_profile_id is None) != (proxy_profile_version is None):
            raise ValueError("proxy profile ID and version must be supplied together")
        if proxy_profile_id is not None:
            row = self.network._version(proxy_profile_id, proxy_profile_version)
            current = self.network._version(proxy_profile_id, None)
            if not row["enabled"] or not current["enabled"]:
                raise ToolExecutionError("update_proxy_disabled", "Selected proxy profile is disabled", next_action="Enable the proxy profile or select direct access.")
            if self.network._credential_revision(row["credential_ref"]) != row["credential_revision"]:
                raise ToolExecutionError("update_proxy_credential_changed", "Proxy credential revision changed", next_action="Save a new proxy profile revision and select it again.")
            if row["scheme"] not in {"http", "https"}:
                raise ValueError("GitHub release checks support HTTP and HTTPS proxy profiles only")
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT revision FROM release_update_settings WHERE id=1").fetchone()
            actual = int(current["revision"]) if current else 0
            if actual != expected_revision:
                raise ToolExecutionError("update_settings_conflict", "Update settings changed", next_action="Reload settings before saving.")
            connection.execute("""INSERT INTO release_update_settings(id,revision,proxy_profile_id,proxy_profile_version)
                VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,
                proxy_profile_id=excluded.proxy_profile_id,proxy_profile_version=excluded.proxy_profile_version""",
                (actual + 1, proxy_profile_id, proxy_profile_version))
            connection.execute("DELETE FROM network_profile_references WHERE resource_type='release_update' AND resource_id='github'")
            if proxy_profile_id is not None and proxy_profile_version is not None:
                connection.execute("INSERT INTO network_profile_references VALUES(?,?,?,?)",
                    (proxy_profile_id, proxy_profile_version, "release_update", "github"))
        self.audit.emit_event("gate.release_update.proxy_saved", source="system_settings", payload={
            "proxy_profile_id": proxy_profile_id, "proxy_profile_version": proxy_profile_version,
            "actor_id": actor_id,
        })
        return self.settings()

    def check(self, actor_id: str | None = None) -> dict[str, Any]:
        state = self.settings()
        selected = state["proxy_profile"]
        handlers: list[Any] = [urllib.request.ProxyHandler({})]
        if selected:
            row = self.network._version(selected["id"], selected["version"])
            current = self.network._version(selected["id"], None)
            if not row["enabled"] or not current["enabled"]:
                raise ToolExecutionError("update_proxy_disabled", "Selected proxy profile is disabled", next_action="Enable the proxy profile or select direct access.")
            if self.network._credential_revision(row["credential_ref"]) != row["credential_revision"]:
                raise ToolExecutionError("update_proxy_credential_changed", "Proxy credential revision changed", next_action="Save a new proxy profile revision and select it again.")
            endpoint = self.network.endpoints.resolve_value(str(row["endpoint_ref"]))
            if not endpoint:
                raise ToolExecutionError("update_proxy_unavailable", "Selected proxy endpoint is unavailable", next_action="Review the selected network profile.")
            if row["scheme"] not in {"http", "https"}:
                raise ToolExecutionError("update_proxy_unsupported", "Selected proxy protocol is unsupported for GitHub release checks", next_action="Use an HTTP or HTTPS proxy profile.")
            credential = self.network.credentials.resolve_value(row["credential_ref"])
            handlers[0] = urllib.request.ProxyHandler({"http": endpoint, "https": endpoint})
            if credential:
                username, separator, password = credential.partition(":")
                if not separator or not username or not password:
                    raise ToolExecutionError("update_proxy_credential_invalid", "Proxy credential format is invalid", next_action="Use username:password in the referenced credential.")
                manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
                manager.add_password(None, endpoint, username, password)
                handlers.append(urllib.request.ProxyBasicAuthHandler(manager))
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(RELEASE_API, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Lingshu-Gate-Update-Checker",
        })
        try:
            with opener.open(request, timeout=12) as response:
                raw = response.read(MAX_RELEASE_BYTES + 1)
            if len(raw) > MAX_RELEASE_BYTES:
                raise ToolExecutionError("update_response_too_large", "GitHub release response exceeded the size limit", next_action="Retry later.")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("invalid release payload")
            tag = payload.get("tag_name")
            if not isinstance(tag, str) or len(tag) > 96:
                raise ValueError("invalid release tag")
            latest = tag[1:] if tag.startswith("v") else tag
            is_newer = _is_newer(latest, self.current_version)
            self.audit.emit_event("gate.release_update.checked", source="system_settings", payload={
                "actor_id": actor_id, "result": "update_available" if is_newer else "up_to_date",
                "latest_version": latest, "proxy": "configured" if selected else "direct",
            })
            release_url = payload.get("html_url")
            if not isinstance(release_url, str) or not release_url.startswith("https://github.com/zhigege666/Lingshu-Gate/releases/tag/"):
                release_url = ""
            return {"current_version": self.current_version, "latest_version": latest,
                "update_available": is_newer,
                "release_name": str(payload.get("name") or tag)[:200],
                "release_url": release_url[:500],
                "published_at": str(payload.get("published_at") or "")[:40],
                "release_notes": str(payload.get("body") or "")[:30000],
                "proxy": "configured" if selected else "direct"}
        except ToolExecutionError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise ToolExecutionError("github_release_check_failed", "GitHub release check failed", next_action="Check network access, the selected proxy profile, and GitHub API availability; secrets are not included in diagnostics.") from None
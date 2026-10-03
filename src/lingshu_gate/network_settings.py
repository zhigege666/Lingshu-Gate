"""Versioned delivery network policy. No plaintext proxy values in SQLite/API/audit."""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolExecutionError

PROFILE_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
EXPIRED_PLAN_PRUNE_BATCH = 100


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class NetworkSelection(StrictModel):
    mode: Literal["inherit", "direct", "profile"] = "inherit"
    profile_id: str | None = Field(default=None, pattern=PROFILE_ID)
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def consistent(self) -> NetworkSelection:
        if (self.mode == "profile") != bool(self.profile_id):
            raise ValueError("profile mode requires profile_id; other modes forbid it")
        if self.mode != "profile" and self.version is not None:
            raise ValueError("version is only valid for profile mode")
        return self


class GitHostRule(StrictModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    private_cidrs: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def valid(self) -> GitHostRule:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", self.host) or ".." in self.host:
            raise ValueError("host must be an exact lowercase DNS name or IPv4 address")
        for cidr in self.private_cidrs:
            network = ipaddress.ip_network(cidr, strict=True)
            if not network.is_private or network.is_loopback or network.is_link_local or network.is_unspecified:
                raise ValueError("internal Git requires a specific private CIDR")
        return self


class NetworkDefaults(StrictModel):
    git: NetworkSelection = Field(default_factory=lambda: NetworkSelection(mode="direct"))
    install: NetworkSelection = Field(default_factory=lambda: NetworkSelection(mode="direct"))
    npm_registry: str = "https://registry.npmjs.org/"
    python_index: str = "https://pypi.org/simple/"
    npm_credential_ref: str | None = Field(default=None, pattern=PROFILE_ID)
    python_credential_ref: str | None = Field(default=None, pattern=PROFILE_ID)
    git_hosts: list[GitHostRule] = Field(default_factory=lambda: [GitHostRule(host="github.com")], min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_defaults(self) -> NetworkDefaults:
        if self.git.mode == "inherit" or self.install.mode == "inherit":
            raise ValueError("system defaults cannot inherit themselves")
        validate_endpoint(self.npm_registry, {"https"})
        validate_endpoint(self.python_index, {"https"})
        if len({(rule.host, rule.port) for rule in self.git_hosts}) != len(self.git_hosts):
            raise ValueError("duplicate Git host rules")
        return self


class ProfileWrite(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    endpoint: str | None = Field(default=None, max_length=2048)
    credential_ref: str | None = Field(default=None, pattern=PROFILE_ID)
    enabled: bool = True
    expected_version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid(self) -> ProfileWrite:
        if any(ord(ch) < 32 for ch in self.name) or "://" in self.name or "@" in self.name:
            raise ValueError("use a display name without endpoints or credentials")
        if self.endpoint is not None:
            validate_endpoint(self.endpoint, {"http", "https", "socks5", "socks5h"}, proxy=True)
        return self


def validate_endpoint(value: str, schemes: set[str], *, proxy: bool = False) -> str:
    """Reject ambiguous URL and credential/config injection without echoing input."""
    try:
        if any(ord(ch) <= 32 or ord(ch) == 127 for ch in value) or "\\" in value or "%" in value:
            raise ValueError
        parsed = urlsplit(value)
        if parsed.scheme not in schemes or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.query or parsed.fragment or not parsed.port and value.endswith(":"):
            raise ValueError
        if proxy and (parsed.path not in {"", "/"} or parsed.port is None):
            raise ValueError
        _ = parsed.port
        if parsed.hostname.endswith("."):
            raise ValueError
        parsed.hostname.encode("ascii")
    except (ValueError, UnicodeError):
        raise ValueError("invalid endpoint: use an explicit supported URL without userinfo, query, fragment or escapes") from None
    return parsed.scheme


def require_network_permission(permissions: tuple[str, ...] | list[str], permission: str = "network.use") -> None:
    if permission not in permissions and "*" not in permissions:
        raise ToolExecutionError("network_permission_denied", f"{permission} is required", next_action="Ask an administrator for the explicit control permission.")


class NetworkSettingsStore:
    def __init__(self, database: SQLiteDatabase, data_dir: Path, credentials: CredentialStore, audit: ObservabilityStore) -> None:
        self.database = database
        self.credentials = credentials
        self.audit = audit
        # Same encryption implementation, separate namespace from user credentials.
        self.endpoints = CredentialStore(data_dir / "private-network-profiles")

    def _credential_revision(self, ref: str | None) -> str | None:
        if ref is None:
            return None
        try:
            return self.credentials.get_credential(ref).updated_at
        except (KeyError, ValueError, RuntimeError):
            raise ToolExecutionError("network_credential_missing", "Credential reference is unavailable", next_action="Repair the reference in shared credentials.") from None

    def settings(self) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM delivery_network_settings WHERE id=1")
        return {"revision": int(row["revision"]) if row else 0, "defaults": json.loads(row["settings_json"]) if row else NetworkDefaults().model_dump(), "executor": {"available": False, "code": "safe_executor_unavailable"}}

    def profiles(self) -> list[dict[str, Any]]:
        rows = self.database.query_all("""SELECT v.* FROM network_profiles p JOIN network_profile_versions v
            ON p.id=v.profile_id AND p.revision=v.version WHERE p.deleted=0 ORDER BY v.name""")
        return [self._public(row) for row in rows]

    def _public(self, row: Any) -> dict[str, Any]:
        configured = row["credential_ref"] is None
        if row["credential_ref"]:
            try:
                configured = self._credential_revision(row["credential_ref"]) == row["credential_revision"]
            except ToolExecutionError:
                configured = False
        return {"id": row["profile_id"], "version": row["version"], "name": row["name"], "enabled": bool(row["enabled"]), "scheme": row["scheme"], "endpoint_masked": "***", "credential_ref": row["credential_ref"], "credential_configured": configured, "created_at": row["created_at"]}

    def _version(self, profile_id: str, version: int | None) -> Any:
        row = self.database.query_one("""SELECT v.* FROM network_profiles p JOIN network_profile_versions v ON p.id=v.profile_id
            WHERE p.id=? AND p.deleted=0 AND v.version=COALESCE(?, p.revision)""", (profile_id, version))
        if row is None:
            raise ToolExecutionError("network_profile_missing", "Network profile or revision is unavailable", next_action="Select an existing profile.")
        return row

    def save_profile(self, body: ProfileWrite, actor_id: str, profile_id: str | None = None) -> dict[str, Any]:
        profile_id = profile_id or uuid4().hex
        if not re.fullmatch(PROFILE_ID, profile_id):
            raise ValueError("invalid profile ID")
        revision = self._credential_revision(body.credential_ref)
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM network_profiles WHERE id=?", (profile_id,)).fetchone()
            actual = int(current["revision"]) if current else 0
            if (current and current["deleted"]) or actual != body.expected_version:
                raise ToolExecutionError("network_version_conflict", "Network configuration changed", next_action="Reload and review the current version before saving.")
            version = actual + 1
            endpoint = body.endpoint
            if endpoint is None:
                if not actual:
                    raise ValueError("endpoint is required for a new profile")
                previous = connection.execute("SELECT endpoint_ref FROM network_profile_versions WHERE profile_id=? AND version=?", (profile_id, actual)).fetchone()
                endpoint = self.endpoints.resolve_value(previous["endpoint_ref"])
            if not endpoint:
                raise ValueError("endpoint unavailable")
            scheme = validate_endpoint(endpoint, {"http", "https", "socks5", "socks5h"}, proxy=True)
            endpoint_ref = f"network-{profile_id}-{version}"
            self.endpoints.save_credential(name=endpoint_ref, value=endpoint, credential_id=endpoint_ref)
            if not current:
                connection.execute("INSERT INTO network_profiles(id, revision) VALUES(?,?)", (profile_id, version))
            else:
                connection.execute("UPDATE network_profiles SET revision=? WHERE id=?", (version, profile_id))
            connection.execute("INSERT INTO network_profile_versions VALUES(?,?,?,?,?,?,?,?,?)", (profile_id, version, body.name, int(body.enabled), scheme, endpoint_ref, body.credential_ref, revision, now()))
        self._audit("profile_saved", actor_id, {"profile_id": profile_id, "version": version, "enabled": body.enabled})
        return self._public(self._version(profile_id, version))

    def references(self, profile_id: str) -> list[dict[str, Any]]:
        self._version(profile_id, None)
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_references(connection)
            return [dict(row) for row in connection.execute("SELECT version, resource_type, resource_id FROM network_profile_references WHERE profile_id=?", (profile_id,))]

    @staticmethod
    def _prune_references(connection: Any) -> None:
        # Import-referenced plans remain immutable provenance, including
        # interrupted/unknown work. Expired unused plans have a bounded sweep;
        # their secret-safe plan-created audit records remain independently.
        connection.execute("""DELETE FROM git_import_plans WHERE id IN (
            SELECT p.id FROM git_import_plans p
            WHERE julianday(p.expires_at)<=julianday(?) AND NOT EXISTS (
                SELECT 1 FROM git_imports i WHERE i.plan_id=p.id)
            ORDER BY p.expires_at,p.id LIMIT ?)""", (now(), EXPIRED_PLAN_PRUNE_BATCH))
        connection.execute("""DELETE FROM network_profile_references AS ref WHERE
            (resource_type='git_plan' AND NOT EXISTS (
                SELECT 1 FROM git_import_plans p WHERE p.id=ref.resource_id
                AND julianday(p.expires_at)>julianday(?)))
            OR (resource_type='upload' AND NOT EXISTS (
                SELECT 1 FROM project_uploads u WHERE u.id=ref.resource_id))
            OR (resource_type='build' AND NOT EXISTS (
                SELECT 1 FROM builds b WHERE b.id=ref.resource_id))
            OR (resource_type='git_import' AND NOT EXISTS (
                SELECT 1 FROM git_imports i WHERE i.id=ref.resource_id
                AND i.status IN ('queued','running','cancel_requested','interrupted','unknown')))
            """, (now(),))

    @staticmethod
    def _release(connection: Any, resource_type: str, resource_id: str) -> None:
        connection.execute("DELETE FROM network_profile_references WHERE resource_type=? AND resource_id=?", (resource_type, resource_id))

    def delete_profile(self, profile_id: str, expected_version: int, actor_id: str) -> dict[str, Any]:
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM network_profiles WHERE id=? AND deleted=0", (profile_id,)).fetchone()
            if row is None or int(row["revision"]) != expected_version:
                raise ToolExecutionError("network_version_conflict", "Network configuration changed", next_action="Reload before deleting.")
            self._prune_references(connection)
            if connection.execute("SELECT 1 FROM network_profile_references WHERE profile_id=? LIMIT 1", (profile_id,)).fetchone():
                raise ToolExecutionError("network_profile_in_use", "Referenced configuration cannot be deleted", next_action="Inspect references or disable the profile; pinned tasks retain their version.")
            connection.execute("UPDATE network_profiles SET deleted=1 WHERE id=?", (profile_id,))
        self._audit("profile_deleted", actor_id, {"profile_id": profile_id, "version": expected_version})
        return {"deleted": True, "id": profile_id}

    def save_defaults(self, body: NetworkDefaults, expected_revision: int, actor_id: str) -> dict[str, Any]:
        # Resolve and reference the exact current profile version, never float defaults.
        values = body.model_dump()
        for phase in ("git", "install"):
            values[phase] = self.resolve(body.model_dump()[phase], phase, defaults=values)
        for name in ("npm_credential_ref", "python_credential_ref"):
            self._credential_revision(values[name])
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT revision FROM delivery_network_settings WHERE id=1").fetchone()
            if (int(current[0]) if current else 0) != expected_revision:
                raise ToolExecutionError("network_version_conflict", "Network defaults changed", next_action="Reload before saving defaults.")
            connection.execute("INSERT INTO delivery_network_settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,settings_json=excluded.settings_json", (expected_revision + 1, json.dumps(values)))
            connection.execute("DELETE FROM network_profile_references WHERE resource_type='defaults'")
            self._retain(connection, {"git": values["git"], "install": values["install"]}, "defaults", "system")
        self._audit("defaults_saved", actor_id, {"revision": expected_revision + 1})
        return self.settings()

    def resolve(self, selection: dict[str, Any], phase: str, *, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = NetworkSelection.model_validate(selection)
        if selected.mode == "inherit":
            selected = NetworkSelection.model_validate((defaults or self.settings()["defaults"])[phase])
        if selected.mode == "direct":
            return {"mode": "direct", "profile_id": None, "version": None}
        row = self._version(str(selected.profile_id), selected.version)
        # Current disable blocks new selection of even an older enabled revision.
        if not row["enabled"] or not self._version(str(selected.profile_id), None)["enabled"]:
            raise ToolExecutionError("network_profile_disabled", "Network profile is disabled", next_action="Select direct or an enabled profile explicitly.")
        if self._credential_revision(row["credential_ref"]) != row["credential_revision"]:
            raise ToolExecutionError("network_credential_changed", "Credential changed since profile revision", next_action="Save a new profile revision, then review the plan again.")
        return {"mode": "profile", "profile_id": row["profile_id"], "version": row["version"]}

    def freeze(self, git: NetworkSelection, install: NetworkSelection) -> dict[str, Any]:
        settings = self.settings()
        values = settings["defaults"]
        return {"settings_revision": settings["revision"], "git": self.resolve(git.model_dump(), "git", defaults=values), "install": self.resolve(install.model_dump(), "install", defaults=values), "npm_registry": values["npm_registry"], "python_index": values["python_index"], "npm_credential_ref": values["npm_credential_ref"], "python_credential_ref": values["python_credential_ref"], "npm_credential_revision": self._credential_revision(values["npm_credential_ref"]), "python_credential_revision": self._credential_revision(values["python_credential_ref"]), "git_hosts": values["git_hosts"]}

    def validate_frozen(self, frozen: dict[str, Any]) -> None:
        # Pinned enabled revisions continue after subsequent edits/disable. No fallback.
        for phase in ("git", "install"):
            selected = frozen[phase]
            if selected["mode"] == "profile":
                row = self._version(selected["profile_id"], selected["version"])
                if self._credential_revision(row["credential_ref"]) != row["credential_revision"]:
                    raise ToolExecutionError("network_credential_changed", "Pinned credential revision is unavailable", next_action="Re-plan and confirm; do not replay this write automatically.")
        for prefix in ("npm", "python"):
            if self._credential_revision(frozen.get(f"{prefix}_credential_ref")) != frozen.get(f"{prefix}_credential_revision"):
                raise ToolExecutionError("network_credential_changed", "Pinned registry credential changed", next_action="Re-plan and confirm.")

    def retain(self, frozen: dict[str, Any], resource_type: str, resource_id: str) -> None:
        with self.database.session() as connection:
            self._retain(connection, frozen, resource_type, resource_id)

    @staticmethod
    def _retain(connection: Any, frozen: dict[str, Any], resource_type: str, resource_id: str) -> None:
        for phase in ("git", "install"):
            selection = frozen[phase]
            if selection["mode"] == "profile":
                connection.execute("INSERT OR IGNORE INTO network_profile_references VALUES(?,?,?,?)", (selection["profile_id"], selection["version"], resource_type, resource_id))

    def execution_material(self, frozen: dict[str, Any], phase: str) -> dict[str, Any]:
        """Only a trusted executor may consume this ephemeral, never-log value."""
        self.validate_frozen(frozen)
        selected = frozen[phase]
        if selected["mode"] == "direct":
            return {"proxy": None, "proxy_credential": None}
        row = self._version(selected["profile_id"], selected["version"])
        return {"proxy": self.endpoints.resolve_value(row["endpoint_ref"]), "proxy_credential": self.credentials.resolve_value(row["credential_ref"])}

    def _audit(self, action: str, actor_id: str, payload: dict[str, Any]) -> None:
        self.audit.emit_event(f"gate.network.{action}", source="network", payload={"actor_id": actor_id, **payload})

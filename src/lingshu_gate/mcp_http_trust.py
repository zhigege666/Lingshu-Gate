"""Server-owned exact-origin authorization for downstream private HTTP MCP."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.endpoint_security import is_canonical_rfc1918_ipv4, private_http_origin
from lingshu_gate.mcp_authorization_policy import server_binding
from lingshu_gate.persistence.migrations import Migration, MigrationRunner


class TrustedHttpOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ip: str
    port: int = Field(ge=1, le=65535)

    @field_validator("ip")
    @classmethod
    def canonical_private_ip(cls, value: str) -> str:
        if not is_canonical_rfc1918_ipv4(value):
            raise ValueError("HTTP trust requires a canonical RFC1918 IPv4 literal")
        return value


class McpHttpTrustUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    origins: list[TrustedHttpOrigin] = Field(max_length=32)
    expected_revision: int = Field(ge=0)
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("HTTP trust changes require confirmed=true")
        return value

    @field_validator("origins")
    @classmethod
    def unique_origins(cls, value: list[TrustedHttpOrigin]) -> list[TrustedHttpOrigin]:
        if len({(item.ip, item.port) for item in value}) != len(value):
            raise ValueError("duplicate HTTP trust origins")
        return value


class McpHttpTrustConflict(ValueError):
    """The administrator must reload a changed trust policy before replacing it."""


class McpHttpTrustDenied(PermissionError):
    """The live actor lacks the administrator boundary for changing trust."""


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE gate_mcp_http_trust (server_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, origins_json TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL)")


def _identity_schema(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE gate_mcp_http_trust ADD COLUMN server_binding TEXT")
    # Only rows present during this migration are eligible for the bounded
    # configuration-startup migration. Reads and later creates never migrate.
    connection.execute("ALTER TABLE gate_mcp_http_trust ADD COLUMN state TEXT NOT NULL DEFAULT 'legacy'")


class McpHttpTrustStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        MigrationRunner(database.connect, (Migration("0009_mcp_http_trust", _schema),
                                           Migration("0025_mcp_http_trust_identity", _identity_schema))).run()

    @staticmethod
    def _current_binding(connection: sqlite3.Connection, server_id: str) -> str | None:
        try:
            return server_binding(connection, server_id)
        except ValueError:
            return None

    @staticmethod
    def _require_admin(connection: sqlite3.Connection, actor_id: str) -> None:
        active_admin = connection.execute("SELECT 1 FROM users JOIN user_roles ON user_roles.user_id=users.id JOIN roles ON roles.id=user_roles.role_id WHERE users.id=? AND users.status='active' AND users.must_change_password=0 AND roles.code='admin' AND roles.enabled=1", (actor_id,)).fetchone()
        manager = connection.execute("SELECT 1 FROM user_roles JOIN roles ON roles.id=user_roles.role_id AND roles.enabled=1 JOIN role_permissions ON role_permissions.role_id=roles.id JOIN control_permissions ON control_permissions.id=role_permissions.permission_id WHERE user_roles.user_id=? AND control_permissions.code='operations.manage'", (actor_id,)).fetchone()
        if not active_admin or not manager:
            raise McpHttpTrustDenied("An active Gate administrator with operations.manage is required")

    def require_admin(self, actor_id: str) -> None:
        with closing(self.database.connect()) as connection:
            self._require_admin(connection, actor_id)

    def _get(self, connection: sqlite3.Connection, server_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM gate_mcp_http_trust WHERE server_id=?", (server_id,)).fetchone()
        if not row:
            return {"server_id": server_id, "revision": 0, "origins": [], "state": "unconfigured",
                    "server_binding": None, "revoked": False, "needs_review": False}
        origins = [TrustedHttpOrigin.model_validate(item).model_dump() for item in json.loads(row["origins_json"])]
        state = str(row["state"])
        if state == "legacy" or (state == "active" and (not row["server_binding"] or row["server_binding"] != self._current_binding(connection, server_id))):
            state = "needs_review"
        return {"server_id": server_id, "revision": int(row["revision"]), "origins": origins,
                "state": state, "server_binding": row["server_binding"],
                "revoked": state == "revoked", "needs_review": state == "needs_review"}

    def get(self, server_id: str) -> dict[str, Any]:
        self._validate_server_id(server_id)
        with closing(self.database.connect()) as connection:
            return self._get(connection, server_id)

    def require_endpoint(self, server_id: str, endpoint: str, *, allow_pending: bool = False,
                         expected_binding: str | None = None) -> str | None:
        origin = private_http_origin(endpoint)
        if origin is None:
            return None
        try:
            policy = self.get(server_id)
        except Exception as exc:
            raise ValueError("Private HTTP MCP trust could not be read; connection is denied") from exc
        if (policy["state"] not in ({"active", "pending"} if allow_pending else {"active"})
                or expected_binding is not None and policy["server_binding"] != expected_binding
                or not any((item["ip"], item["port"]) == origin for item in policy["origins"])):
            raise ValueError("Private HTTP MCP endpoint requires administrator-approved trust for this service, exact IP and port")
        return policy["server_binding"] if isinstance(policy["server_binding"], str) else None

    @staticmethod
    def _write(connection: sqlite3.Connection, server_id: str, *, revision: int, origins: list[dict[str, Any]],
               binding: str | None, state: str, actor_id: str) -> None:
        connection.execute("INSERT INTO gate_mcp_http_trust(server_id,revision,origins_json,updated_by,updated_at,server_binding,state) "
                           "VALUES(?,?,?,?,?,?,?) ON CONFLICT(server_id) DO UPDATE SET revision=excluded.revision,"
                           "origins_json=excluded.origins_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at,"
                           "server_binding=excluded.server_binding,state=excluded.state",
                           (server_id, revision, json.dumps(origins), actor_id, datetime.now(timezone.utc).isoformat(), binding, state))

    def migrate_saved_configs(self, endpoints: dict[str, str]) -> None:
        """Adopt only old rows matching an existing saved target, exactly once."""
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for row in connection.execute("SELECT * FROM gate_mcp_http_trust WHERE state='legacy'").fetchall():
                target_id = str(row["server_id"])
                origin = private_http_origin(endpoints[target_id]) if target_id in endpoints else None
                binding = self._current_binding(connection, target_id)
                matches = [item for item in json.loads(row["origins_json"]) if origin and (item.get("ip"), item.get("port")) == origin]
                state = "active" if binding and matches else "revoked" if not json.loads(row["origins_json"]) else "needs_review"
                connection.execute("UPDATE gate_mcp_http_trust SET server_binding=?,state=?,origins_json=? WHERE server_id=? AND state='legacy'",
                                   (binding, state, json.dumps(matches if state == "active" else json.loads(row["origins_json"])), target_id))

    def bind_pending(self, server_id: str, endpoint: str | None) -> None:
        """Consume an explicit pre-save approval on its first matching save."""
        origin = private_http_origin(endpoint) if endpoint else None
        if origin is None:
            return
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM gate_mcp_http_trust WHERE server_id=? AND state='pending'", (server_id,)).fetchone()
            binding = self._current_binding(connection, server_id)
            if row and binding and any((item["ip"], item["port"]) == origin for item in json.loads(row["origins_json"])):
                # Only the origin actually saved becomes usable by this
                # incarnation, even if the older request listed several.
                connection.execute("UPDATE gate_mcp_http_trust SET server_binding=?,state='active',origins_json=? WHERE server_id=? AND state='pending' AND revision=?",
                                   (binding, json.dumps([{"ip": origin[0], "port": origin[1]}]), server_id, row["revision"]))

    def plan_configuration(self, server_id: str, endpoint: str | None, *, action: str = "auto",
                           previous_endpoint: str | None = None, creating: bool = False,
                           expected_revision: int | None = None) -> dict[str, Any]:
        """Pure policy preview. No approval, DNS lookup or downstream traffic."""
        self._validate_server_id(server_id)
        if action not in {"auto", "preserve", "restore"}:
            raise ValueError("Unsupported HTTP trust action")
        policy = self.get(server_id)
        if expected_revision is not None and expected_revision != policy["revision"]:
            raise McpHttpTrustConflict("HTTP trust changed; reload the current revision before updating")
        origin = private_http_origin(endpoint) if endpoint else None
        allowed = bool(origin and policy["state"] in {"active", "pending"}
                       and any((item["ip"], item["port"]) == origin for item in policy["origins"]))
        change = "none"
        if origin:
            if action == "restore":
                change = "authorize"
            elif action == "auto":
                # A new incarnation is a new explicit create. Existing revoked
                # or unassociated records require a deliberate restore action.
                if creating and policy["state"] == "pending" and allowed:
                    change = "none"
                elif creating and policy["state"] != "needs_review":
                    change = "authorize"
                elif policy["state"] in {"revoked", "needs_review"}:
                    change = "preserve_denied"
                elif not allowed or endpoint != previous_endpoint:
                    change = "authorize"
            elif not allowed or not creating and endpoint != previous_endpoint:
                raise ValueError("Private HTTP MCP endpoint requires administrator-approved trust for this service, exact IP and port")
        elif policy["state"] in {"active", "pending"} and previous_endpoint != endpoint:
            change = "retire"
        with closing(self.database.connect()) as connection:
            binding = self._current_binding(connection, server_id)
        return {"server_id": server_id, "expected_revision": policy["revision"], "expected_binding": binding,
                "policy_state": policy["state"], "action": action, "change": change,
                "origin": {"ip": origin[0], "port": origin[1]} if origin else None,
                "endpoint": endpoint, "creating": creating,
                "connection_allowed": not origin or allowed or change == "authorize"}

    def check_plan(self, plan: dict[str, Any]) -> None:
        policy = self.get(plan["server_id"])
        with closing(self.database.connect()) as connection:
            binding = self._current_binding(connection, plan["server_id"])
        if policy["revision"] != plan["expected_revision"] or binding != plan["expected_binding"]:
            raise McpHttpTrustConflict("HTTP trust or service identity changed after planning")

    def apply_saved_configuration(self, plan: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        """Finalize a reviewed target after its new file identity exists.

        The file and SQLite are separate stores. Until this step commits, the
        new binding has no usable permission. A crash therefore fails closed.
        """
        target_id = str(plan["server_id"])
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            policy = self._get(connection, target_id)
            if policy["revision"] != plan["expected_revision"]:
                raise McpHttpTrustConflict("HTTP trust changed while saving configuration")
            binding = self._current_binding(connection, target_id)
            if binding is None:
                raise McpHttpTrustConflict("Saved service identity is unavailable")
            change = plan["change"]
            if change in {"authorize", "retire"}:
                self._require_admin(connection, actor_id)
                self._write(connection, target_id, revision=policy["revision"] + 1,
                            origins=[plan["origin"]] if change == "authorize" else [], binding=binding,
                            state="active" if change == "authorize" else "revoked", actor_id=actor_id)
            elif policy["state"] == "active" and policy["server_binding"] != binding:
                # Metadata writes keep the identity. A changed identity without
                # an approved network change must never inherit old permission.
                raise McpHttpTrustConflict("Service identity changed without a reviewed HTTP permission")
            return self._get(connection, target_id)

    def retire_deleted(self, server_id: str) -> None:
        """Retain the revision but remove every reusable network permission."""
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT revision FROM gate_mcp_http_trust WHERE server_id=?", (server_id,)).fetchone()
            if row:
                self._write(connection, server_id, revision=int(row["revision"]) + 1, origins=[], binding=None,
                            state="revoked", actor_id="config_deleted")

    def update(self, server_id: str, request: McpHttpTrustUpdate, *, actor_id: str) -> dict[str, Any]:
        """CAS replacement with live role/permission checks in the write transaction."""
        self._validate_server_id(server_id)
        origins = sorted((item.model_dump() for item in request.origins), key=lambda item: (item["ip"], item["port"]))
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_admin(connection, actor_id)
            row = connection.execute("SELECT revision FROM gate_mcp_http_trust WHERE server_id=?", (server_id,)).fetchone()
            revision = int(row["revision"]) if row else 0
            if revision != request.expected_revision:
                raise McpHttpTrustConflict("HTTP trust changed; reload the current revision before updating")
            binding = self._current_binding(connection, server_id)
            self._write(connection, server_id, revision=revision + 1, origins=origins, binding=binding,
                        state=("active" if binding else "pending") if origins else "revoked", actor_id=actor_id)
            return self._get(connection, server_id)

    @staticmethod
    def _validate_server_id(server_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", server_id):
            raise ValueError("Invalid MCP server ID")


def require_mcp_http_endpoint(server_id: str, endpoint: str, trust_store: McpHttpTrustStore | None = None, *,
                              settings: Settings | None = None, allow_pending: bool = False,
                              expected_binding: str | None = None) -> str | None:
    """Default deny; only live, service-owned policy authorizes private HTTP."""
    if private_http_origin(endpoint) is None:
        return None
    if trust_store is None and settings is not None:
        try:
            trust_store = McpHttpTrustStore(SQLiteDatabase(settings.db_url, settings.data_dir))
        except Exception as exc:
            raise ValueError("Private HTTP MCP trust could not be read; connection is denied") from exc
    if trust_store is None:
        raise ValueError("Private HTTP MCP endpoint requires administrator-approved trust for this service, exact IP and port")
    return trust_store.require_endpoint(server_id, endpoint, allow_pending=allow_pending, expected_binding=expected_binding)

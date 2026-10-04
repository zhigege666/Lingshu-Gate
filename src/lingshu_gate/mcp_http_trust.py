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


class McpHttpTrustStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        MigrationRunner(database.connect, (Migration("0009_mcp_http_trust", _schema),)).run()

    def get(self, server_id: str) -> dict[str, Any]:
        self._validate_server_id(server_id)
        row = self.database.query_one("SELECT * FROM gate_mcp_http_trust WHERE server_id=?", (server_id,))
        if not row:
            return {"server_id": server_id, "revision": 0, "origins": []}
        origins = [TrustedHttpOrigin.model_validate(item).model_dump() for item in json.loads(row["origins_json"])]
        return {"server_id": server_id, "revision": int(row["revision"]), "origins": origins}

    def require_endpoint(self, server_id: str, endpoint: str) -> None:
        origin = private_http_origin(endpoint)
        if origin is None:
            return
        try:
            policy = self.get(server_id)
        except Exception as exc:
            raise ValueError("Private HTTP MCP trust could not be read; connection is denied") from exc
        if not any((item["ip"], item["port"]) == origin for item in policy["origins"]):
            raise ValueError("Private HTTP MCP endpoint requires administrator-approved trust for this service, exact IP and port")

    def update(self, server_id: str, request: McpHttpTrustUpdate, *, actor_id: str) -> dict[str, Any]:
        """CAS replacement with live role/permission checks in the write transaction."""
        self._validate_server_id(server_id)
        origins = sorted((item.model_dump() for item in request.origins), key=lambda item: (item["ip"], item["port"]))
        with closing(self.database.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            active_admin = connection.execute("SELECT 1 FROM users JOIN user_roles ON user_roles.user_id=users.id JOIN roles ON roles.id=user_roles.role_id WHERE users.id=? AND users.status='active' AND roles.code='admin' AND roles.enabled=1", (actor_id,)).fetchone()
            manager = connection.execute("SELECT 1 FROM user_roles JOIN roles ON roles.id=user_roles.role_id AND roles.enabled=1 JOIN role_permissions ON role_permissions.role_id=roles.id JOIN control_permissions ON control_permissions.id=role_permissions.permission_id WHERE user_roles.user_id=? AND control_permissions.code='operations.manage'", (actor_id,)).fetchone()
            if not active_admin or not manager:
                raise McpHttpTrustDenied("An active Gate administrator with operations.manage is required")
            row = connection.execute("SELECT revision FROM gate_mcp_http_trust WHERE server_id=?", (server_id,)).fetchone()
            revision = int(row["revision"]) if row else 0
            if revision != request.expected_revision:
                raise McpHttpTrustConflict("HTTP trust changed; reload the current revision before updating")
            connection.execute("INSERT INTO gate_mcp_http_trust VALUES (?, ?, ?, ?, ?) ON CONFLICT(server_id) DO UPDATE SET revision=excluded.revision, origins_json=excluded.origins_json, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                               (server_id, revision + 1, json.dumps(origins), actor_id, datetime.now(timezone.utc).isoformat()))
        return {"server_id": server_id, "revision": revision + 1, "origins": origins}

    @staticmethod
    def _validate_server_id(server_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", server_id):
            raise ValueError("Invalid MCP server ID")


def require_mcp_http_endpoint(server_id: str, endpoint: str, trust_store: McpHttpTrustStore | None = None, *, settings: Settings | None = None) -> None:
    """Default deny; only live, service-owned policy authorizes private HTTP."""
    if private_http_origin(endpoint) is None:
        return
    if trust_store is None and settings is not None:
        try:
            trust_store = McpHttpTrustStore(SQLiteDatabase(settings.db_url, settings.data_dir))
        except Exception as exc:
            raise ValueError("Private HTTP MCP trust could not be read; connection is denied") from exc
    if trust_store is None:
        raise ValueError("Private HTTP MCP endpoint requires administrator-approved trust for this service, exact IP and port")
    trust_store.require_endpoint(server_id, endpoint)

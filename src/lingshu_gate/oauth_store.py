"""Transactional persistence for the opt-in, single-Core OAuth authorization server.

Opaque secrets are SHA-256 digests. Only encrypted signing keys are persisted.
No initializer generates keys, clients or credentials.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from typing import Any

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.oauth_management import management_resource
from lingshu_gate.persistence.migrations import Migration, MigrationRunner, execute_sql_script


def _schema(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
CREATE TABLE gate_oauth_config (
    id INTEGER PRIMARY KEY CHECK(id=1), payload_json TEXT NOT NULL, revision INTEGER NOT NULL
);
CREATE TABLE gate_oauth_clients (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, redirect_uris_json TEXT NOT NULL,
    scopes_json TEXT NOT NULL, secret_hash TEXT NOT NULL, enabled INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
);
CREATE TABLE gate_oauth_keys (
    kid TEXT PRIMARY KEY, encrypted_private TEXT NOT NULL, public_json TEXT NOT NULL,
    active INTEGER NOT NULL, retire_at INTEGER, created_at INTEGER NOT NULL
);
CREATE TABLE gate_oauth_interactions (
    id_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, csrf_hash TEXT NOT NULL DEFAULT '',
    request_json TEXT NOT NULL, catalog_json TEXT NOT NULL DEFAULT '{}',
    expires_at INTEGER NOT NULL, completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX gate_oauth_interactions_expiry ON gate_oauth_interactions(expires_at);
CREATE TABLE gate_oauth_grants (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL REFERENCES gate_oauth_clients(id), resource TEXT NOT NULL,
    scopes_json TEXT NOT NULL, tools_json TEXT NOT NULL, expires_at INTEGER NOT NULL,
    rate_per_minute INTEGER NOT NULL, concurrency INTEGER NOT NULL,
    revoked_at INTEGER, revision INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
);
CREATE INDEX gate_oauth_grants_owner ON gate_oauth_grants(user_id, created_at);
CREATE TABLE gate_oauth_codes (
    code_hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES gate_oauth_grants(id) ON DELETE CASCADE,
    client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL, resource TEXT NOT NULL,
    challenge TEXT NOT NULL, expires_at INTEGER NOT NULL, consumed_at INTEGER
);
CREATE INDEX gate_oauth_codes_expiry ON gate_oauth_codes(expires_at);
CREATE TABLE gate_oauth_families (
    id TEXT PRIMARY KEY, grant_id TEXT NOT NULL REFERENCES gate_oauth_grants(id) ON DELETE CASCADE,
    scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER
);
CREATE TABLE gate_oauth_refresh (
    token_hash TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES gate_oauth_families(id) ON DELETE CASCADE,
    consumed_at INTEGER, created_at INTEGER NOT NULL
);
CREATE INDEX gate_oauth_refresh_family ON gate_oauth_refresh(family_id);
""")


def _interaction_capacity_schema(connection: sqlite3.Connection) -> None:
    # Old opaque requests have no stateless ticket or authenticated owner.
    # They are short-lived and must be restarted rather than promoted blindly.
    connection.execute("DELETE FROM gate_oauth_interactions")
    connection.execute("ALTER TABLE gate_oauth_interactions ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE")
    connection.execute("ALTER TABLE gate_oauth_interactions ADD COLUMN client_id TEXT NOT NULL DEFAULT ''")
    connection.execute("CREATE INDEX gate_oauth_interactions_owner ON gate_oauth_interactions(completed,user_id)")
    connection.execute("CREATE INDEX gate_oauth_interactions_client ON gate_oauth_interactions(completed,client_id)")


def _scope_confirmation_schema(connection: sqlite3.Connection) -> None:
    # Only a digest of the latest short-lived confirmation is persisted. This
    # is not a user draft, and contains no tools, tokens or client credentials.
    execute_sql_script(connection, """
CREATE TABLE gate_oauth_scope_confirmations (
    grant_id TEXT PRIMARY KEY REFERENCES gate_oauth_grants(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_hash TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL
);
CREATE INDEX gate_oauth_scope_confirmation_expiry ON gate_oauth_scope_confirmations(expires_at);
""")


def _management_resource_schema(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
CREATE TABLE gate_oauth_management_config (
    id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    revision INTEGER NOT NULL
);
ALTER TABLE gate_oauth_clients ADD COLUMN resources_json TEXT NOT NULL DEFAULT '["business"]';
ALTER TABLE gate_oauth_grants ADD COLUMN management_targets_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE gate_oauth_grants ADD COLUMN target_revision INTEGER NOT NULL DEFAULT 0;
""")


class OAuthStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        MigrationRunner(database.connect, (Migration("0006_builtin_oauth", _schema),
                                           Migration("0008_oauth_interaction_capacity", _interaction_capacity_schema),
                                           Migration("0009_oauth_scope_confirmations", _scope_confirmation_schema),
                                           Migration("0012_oauth_management_resource", _management_resource_schema))).run()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        # Close as well as commit: sqlite Connection.__exit__ alone doesn't close.
        with closing(self.database.connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection

    def config(self, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = (connection.execute("SELECT * FROM gate_oauth_config WHERE id=1").fetchone()
               if connection else self.database.query_one("SELECT * FROM gate_oauth_config WHERE id=1"))
        return ({**json.loads(row["payload_json"]), "revision": row["revision"]} if row else
                {"enabled": False, "issuer": "", "resource": "", "revision": 0})

    def management_config(self, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = (connection.execute("SELECT * FROM gate_oauth_management_config WHERE id=1").fetchone()
               if connection else self.database.query_one("SELECT * FROM gate_oauth_management_config WHERE id=1"))
        config = self.config(connection)
        return {"enabled": bool(row and row["enabled"]), "revision": row["revision"] if row else 0,
                "active": bool(row and row["enabled"] and config["enabled"]),
                "resource": management_resource(config["resource"])}

    @staticmethod
    def client(row: Any) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"],
                "redirect_uris": json.loads(row["redirect_uris_json"]),
                "scopes": json.loads(row["scopes_json"]), "enabled": bool(row["enabled"]),
                "resources": json.loads(row["resources_json"]),
                "revision": row["revision"], "created_at": row["created_at"]}

    def clients(self) -> list[dict[str, Any]]:
        return [self.client(row) for row in self.database.query_all(
            "SELECT * FROM gate_oauth_clients ORDER BY created_at DESC,id")]

    @staticmethod
    def grant(row: Any) -> dict[str, Any]:
        return {**dict(row), "scopes": json.loads(row["scopes_json"]),
                "tools": json.loads(row["tools_json"]), "management_targets": json.loads(row["management_targets_json"])}

    def grants(self, user_id: str) -> list[dict[str, Any]]:
        return [self.grant(row) for row in self.database.query_all(
            "SELECT * FROM gate_oauth_grants WHERE user_id=? ORDER BY created_at DESC,id", (user_id,))]

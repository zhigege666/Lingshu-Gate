"""Business accounts, pinned adapters and durable remote-copy state."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

BUSINESS_CREDENTIALS_MIGRATION_ID = "0024_business_credentials"


def apply_business_credentials_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
        CREATE TABLE IF NOT EXISTS business_credentials (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            scope TEXT NOT NULL CHECK(scope IN ('personal','shared')),
            metadata_json TEXT NOT NULL,
            encrypted_secret TEXT NOT NULL,
            enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            version INTEGER NOT NULL CHECK(version > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_business_credentials_owner ON business_credentials(owner_id);
        CREATE TABLE IF NOT EXISTS business_credential_targets (
            server_id TEXT PRIMARY KEY,
            adapter TEXT NOT NULL CHECK(adapter = 'agent_browser'),
            tool_prefix TEXT NOT NULL CHECK(tool_prefix IN ('agent_browser_','')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS business_credential_bindings (
            id TEXT PRIMARY KEY,
            credential_id TEXT NOT NULL REFERENCES business_credentials(id) ON DELETE RESTRICT,
            server_id TEXT NOT NULL REFERENCES business_credential_targets(server_id) ON DELETE RESTRICT,
            adapter TEXT NOT NULL CHECK(adapter = 'agent_browser'),
            tool_prefix TEXT NOT NULL CHECK(tool_prefix IN ('agent_browser_','')),
            profile_name TEXT NOT NULL UNIQUE,
            manifest_digest TEXT NOT NULL,
            tool_revisions_json TEXT NOT NULL,
            enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
            revision INTEGER NOT NULL CHECK(revision > 0),
            synced_version INTEGER,
            sync_status TEXT NOT NULL CHECK(sync_status IN ('pending','synced','failed','unknown','deleted')),
            remote_copy_possible INTEGER NOT NULL CHECK(remote_copy_possible IN (0,1)),
            last_sync_at TEXT,
            last_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(credential_id, server_id)
        );
        CREATE INDEX IF NOT EXISTS idx_business_bindings_server ON business_credential_bindings(server_id);
        CREATE TABLE IF NOT EXISTS business_credential_sessions (
            id TEXT PRIMARY KEY,
            connection_key TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            server_id TEXT NOT NULL,
            logical_session TEXT NOT NULL,
            credential_id TEXT NOT NULL,
            binding_id TEXT NOT NULL,
            credential_version INTEGER NOT NULL,
            binding_revision INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active','unknown','closed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(connection_key,server_id,logical_session)
        );
        CREATE INDEX IF NOT EXISTS idx_business_sessions_credential ON business_credential_sessions(credential_id,status);
    """)

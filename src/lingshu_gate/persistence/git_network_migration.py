"""Additive delivery-network schema; deliberately independent of OAuth migrations."""

from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

GIT_NETWORK_MIGRATION_ID = "0004_gate_git_network"


def apply_git_network_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE network_profiles (
        id TEXT PRIMARY KEY, revision INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE network_profile_versions (
        profile_id TEXT NOT NULL, version INTEGER NOT NULL, name TEXT NOT NULL,
        enabled INTEGER NOT NULL, scheme TEXT NOT NULL, endpoint_ref TEXT NOT NULL,
        credential_ref TEXT, credential_revision TEXT, created_at TEXT NOT NULL,
        PRIMARY KEY(profile_id, version), FOREIGN KEY(profile_id) REFERENCES network_profiles(id)
    );
    CREATE TABLE delivery_network_settings (
        id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL, settings_json TEXT NOT NULL
    );
    CREATE TABLE network_profile_references (
        profile_id TEXT NOT NULL, version INTEGER NOT NULL, resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL, PRIMARY KEY(profile_id, version, resource_type, resource_id),
        FOREIGN KEY(profile_id, version) REFERENCES network_profile_versions(profile_id, version)
    );
    CREATE TABLE git_import_plans (
        id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, digest TEXT NOT NULL,
        plan_json TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE git_imports (
        id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, actor_id TEXT NOT NULL,
        status TEXT NOT NULL, upload_id TEXT, error_code TEXT, progress_json TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(plan_id) REFERENCES git_import_plans(id)
    );
    CREATE INDEX idx_git_imports_actor ON git_imports(actor_id, created_at DESC);
    CREATE INDEX idx_git_imports_plan ON git_imports(plan_id);
    CREATE INDEX idx_git_plans_expiry ON git_import_plans(expires_at, id);
    CREATE INDEX idx_network_references_resource ON network_profile_references(resource_type, resource_id);
    """)

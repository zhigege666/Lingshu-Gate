"""Additive group metadata; server IDs reference file manifests, not a fake SQL table."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

MCP_GROUPS_MIGRATION_ID = "0013_gate_mcp_groups"


def apply_mcp_groups_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE mcp_groups (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','archived')),
        revision INTEGER NOT NULL CHECK(revision >= 1), search_text TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE mcp_group_members (
        group_id TEXT NOT NULL, server_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','missing')),
        PRIMARY KEY(group_id,server_id),
        FOREIGN KEY(group_id) REFERENCES mcp_groups(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_mcp_group_members_instance ON mcp_group_members(server_id,status,group_id);
    CREATE INDEX idx_mcp_groups_state ON mcp_groups(status,id);
    """)

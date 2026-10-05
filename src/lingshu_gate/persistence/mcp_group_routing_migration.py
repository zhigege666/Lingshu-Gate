"""Add a suggested default and connection-bound routing sessions, without grants."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

MCP_GROUP_ROUTING_MIGRATION_ID = "0015_gate_mcp_group_routing"


def apply_mcp_group_routing_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    ALTER TABLE mcp_groups ADD COLUMN default_instance_id TEXT;
    CREATE TABLE mcp_group_route_sessions (
        id TEXT PRIMARY KEY,
        actor_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        connection_binding TEXT NOT NULL,
        group_id TEXT NOT NULL REFERENCES mcp_groups(id) ON DELETE CASCADE,
        group_revision INTEGER NOT NULL,
        instance_id TEXT NOT NULL,
        config_digest TEXT NOT NULL,
        runtime_generation TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        closed_at TEXT
    );
    CREATE INDEX idx_mcp_group_route_sessions_owner
        ON mcp_group_route_sessions(actor_id,connection_binding,group_id,expires_at);
    """)

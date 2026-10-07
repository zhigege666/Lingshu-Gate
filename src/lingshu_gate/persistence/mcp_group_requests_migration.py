"""Actor-bound create receipts survive group deletion, preventing resurrection."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

MCP_GROUP_REQUESTS_MIGRATION_ID = "0014_gate_mcp_group_requests"


def apply_mcp_group_requests_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE mcp_group_requests (
        actor_id TEXT NOT NULL, request_key TEXT NOT NULL, request_digest TEXT NOT NULL,
        group_id TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(actor_id,request_key),
        FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

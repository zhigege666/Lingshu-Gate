"""Additive, actor-bound external MCP plans and operation progress."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

EXTERNAL_MCP_CONFIG_MIGRATION_ID = "0010_gate_external_mcp_config"


def apply_external_mcp_config_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE external_mcp_config_plans (
        id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, principal_digest TEXT NOT NULL,
        digest TEXT NOT NULL, plan_json TEXT NOT NULL, expires_at TEXT NOT NULL,
        consumed_by TEXT, created_at TEXT NOT NULL
    );
    CREATE INDEX idx_external_config_plans_expiry ON external_mcp_config_plans(expires_at, id);
    CREATE TABLE external_mcp_config_operations (
        id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, actor_id TEXT NOT NULL,
        status TEXT NOT NULL, result_json TEXT NOT NULL,
        cancel_requested INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
        FOREIGN KEY(id) REFERENCES mcp_idempotent_operations(id) ON DELETE CASCADE,
        FOREIGN KEY(plan_id) REFERENCES external_mcp_config_plans(id)
    );
    CREATE INDEX idx_external_config_operations_actor ON external_mcp_config_operations(actor_id, updated_at);
    CREATE INDEX idx_external_config_operations_plan ON external_mcp_config_operations(plan_id);
    """)

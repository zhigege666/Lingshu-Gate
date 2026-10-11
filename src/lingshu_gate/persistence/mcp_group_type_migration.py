"""增加组用途；既有组保留未指定状态，不根据工具合同推断业务用途。"""
from __future__ import annotations

import sqlite3

MCP_GROUP_TYPE_MIGRATION_ID = "0017_gate_mcp_group_type"


def apply_mcp_group_type_migration(connection: sqlite3.Connection) -> None:
    connection.execute("""ALTER TABLE mcp_groups ADD COLUMN group_type TEXT NOT NULL
        DEFAULT 'unspecified' CHECK(group_type IN ('execution','data_source','unspecified'))""")

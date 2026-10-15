"""为持续授权保存不可复用的服务生命周期身份，不迁移既有授权范围。"""

from __future__ import annotations

import sqlite3

MCP_AUTHORIZATION_IDENTITY_MIGRATION_ID = "0018_mcp_authorization_identities"


def apply_mcp_authorization_identity_migration(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE gate_mcp_authorization_identities (
        server_id TEXT PRIMARY KEY, binding TEXT NOT NULL, target_digest TEXT NOT NULL DEFAULT '',
        file_path TEXT NOT NULL DEFAULT '', file_marker TEXT NOT NULL DEFAULT ''
    )""")

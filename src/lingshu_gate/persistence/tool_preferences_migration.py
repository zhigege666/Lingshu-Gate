"""Authorization-owned discovery preferences share the existing revision."""
from __future__ import annotations

import sqlite3

TOOL_PREFERENCES_MIGRATION_ID = "0022_tool_preferences"


def apply_tool_preferences_migration(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE authorization_tool_preferences (
        kind TEXT NOT NULL,
        authorization_id TEXT NOT NULL,
        pinned_tools_json TEXT NOT NULL,
        result_budget_json TEXT NOT NULL,
        PRIMARY KEY(kind, authorization_id),
        FOREIGN KEY(kind, authorization_id) REFERENCES authorization_discovery(kind, authorization_id) ON DELETE CASCADE
    )""")

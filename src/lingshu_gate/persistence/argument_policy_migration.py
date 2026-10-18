"""Persist restrictions independently of transient tool discovery records."""
from __future__ import annotations

import sqlite3

ARGUMENT_POLICY_MIGRATION_ID = "0023_tool_argument_policy"


def apply_argument_policy_migration(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS tool_argument_policies (tool_id TEXT PRIMARY KEY, "
        "enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), revision INTEGER NOT NULL CHECK(revision>0), rules_json TEXT NOT NULL)")

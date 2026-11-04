"""Release update settings migration."""
from __future__ import annotations
import sqlite3
from lingshu_gate.persistence.migrations import execute_sql_script

RELEASE_UPDATES_MIGRATION_ID = "0025_gate_release_updates"

def apply_release_updates_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE release_update_settings (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        revision INTEGER NOT NULL,
        proxy_profile_id TEXT,
        proxy_profile_version INTEGER
    );
    """)
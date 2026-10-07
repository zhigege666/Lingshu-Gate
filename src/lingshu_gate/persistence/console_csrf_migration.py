"""Add bounded, session-bound single-use Console request tickets."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

CONSOLE_CSRF_MIGRATION_ID = "0011_gate_console_csrf"


def apply_console_csrf_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE console_csrf_tickets (
        token_hash TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_id TEXT NOT NULL,
        session_hash TEXT NOT NULL, target TEXT NOT NULL, request_digest TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        FOREIGN KEY(session_id) REFERENCES auth_sessions(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_console_csrf_expiry ON console_csrf_tickets(expires_at);
    CREATE INDEX idx_console_csrf_session ON console_csrf_tickets(session_id);
    """)

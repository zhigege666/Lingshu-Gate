"""Keep Console and public OAuth consent sessions separate in persistence."""

import sqlite3

SESSION_PURPOSE_MIGRATION_ID = "0007_auth_session_purpose"


def apply_session_purpose_migration(connection: sqlite3.Connection) -> None:
    # Published Gate versions only issued Console sessions. Preserve their
    # expiry and digest while assigning the explicit Console purpose.
    connection.execute("ALTER TABLE auth_sessions ADD COLUMN purpose TEXT NOT NULL DEFAULT 'console' "
                       "CHECK(purpose IN ('console','oauth_consent'))")
    connection.execute("CREATE INDEX auth_sessions_purpose_expiry ON auth_sessions(purpose,expires_at)")

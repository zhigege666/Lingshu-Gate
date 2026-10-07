"""Index latest audit snapshots without rescanning a user's entire history."""

import sqlite3

AUDIT_LOOKUP_MIGRATION_ID = "0003_audit_user_latest_lookup"


def apply_audit_lookup_migration(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX idx_invocation_audits_user_latest "
        "ON invocation_audits(user_id, created_at DESC, id DESC)"
    )

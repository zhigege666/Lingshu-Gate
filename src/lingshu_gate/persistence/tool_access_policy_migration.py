"""Separate effective access from optional classification/review evidence."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

TOOL_ACCESS_POLICY_MIGRATION_ID = "0025_tool_access_policy"
TOOL_ACCESS_POLICY_REVISION_MIGRATION_ID = "0026_tool_access_policy_revision"


def apply_tool_access_policy_migration(connection: sqlite3.Connection) -> None:
    # Existing reviews are adopted only after the runtime checks their exact
    # fingerprint. Merely having an old published row must not authorize a new
    # contract during upgrade. No grants, tokens or reviewed safety are changed.
    execute_sql_script(connection, """
        ALTER TABLE mcp_tool_classifications ADD COLUMN required_access TEXT NOT NULL
            DEFAULT 'write' CHECK(required_access IN ('none','read','write'));
        ALTER TABLE mcp_tool_classifications ADD COLUMN access_policy_source TEXT NOT NULL DEFAULT 'unresolved';
        ALTER TABLE mcp_tool_classifications ADD COLUMN access_policy_binding TEXT NOT NULL DEFAULT '';
        ALTER TABLE mcp_tool_classifications ADD COLUMN legacy_authorization_snapshot TEXT NOT NULL DEFAULT '';
        CREATE TRIGGER gate_tool_policy_identity_changed AFTER UPDATE OF binding
            ON gate_mcp_authorization_identities WHEN old.binding != new.binding BEGIN
            UPDATE mcp_tool_classifications SET required_access='write',
                access_policy_source='default_write', access_policy_binding=new.binding,
                legacy_authorization_snapshot='',status='stale',effective_access='unknown',reviewed_at=NULL
                WHERE server_id=new.server_id;
        END;
        CREATE TRIGGER gate_tool_policy_identity_deleted AFTER DELETE
            ON gate_mcp_authorization_identities BEGIN
            UPDATE mcp_tool_classifications SET required_access='none',
                access_policy_source='unavailable', access_policy_binding='',
                legacy_authorization_snapshot='',status='stale',effective_access='unknown',reviewed_at=NULL
                WHERE server_id=old.server_id;
        END;
    """)


def apply_tool_access_policy_revision_migration(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(mcp_tool_classifications)")}
    if "access_policy_revision" not in columns:
        connection.execute("ALTER TABLE mcp_tool_classifications ADD COLUMN access_policy_revision INTEGER NOT NULL DEFAULT 1")
    execute_sql_script(connection, """
        DROP TRIGGER gate_tool_policy_identity_changed;
        DROP TRIGGER gate_tool_policy_identity_deleted;
        CREATE TRIGGER gate_tool_policy_identity_changed AFTER UPDATE OF binding
            ON gate_mcp_authorization_identities WHEN old.binding != new.binding BEGIN
            UPDATE mcp_tool_classifications SET required_access='write',
                access_policy_source='default_write', access_policy_binding=new.binding,
                access_policy_revision=access_policy_revision+1,
                legacy_authorization_snapshot='',status='stale',effective_access='unknown',reviewed_at=NULL
                WHERE server_id=new.server_id;
        END;
        CREATE TRIGGER gate_tool_policy_identity_deleted AFTER DELETE
            ON gate_mcp_authorization_identities BEGIN
            UPDATE mcp_tool_classifications SET required_access='none',
                access_policy_source='unavailable', access_policy_binding='',
                access_policy_revision=access_policy_revision+1,
                legacy_authorization_snapshot='',status='stale',effective_access='unknown',reviewed_at=NULL
                WHERE server_id=old.server_id;
        END;
        UPDATE mcp_tool_classifications SET status='stale',effective_access='unknown',reviewed_at=NULL
            WHERE access_policy_source='default_write' AND status='published';
    """)

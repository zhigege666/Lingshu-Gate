"""Incremental schema-free search directory and authorization invalidation."""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

TOOL_CATALOG_MIGRATION_ID = "0012_gate_tool_catalog"


def apply_tool_catalog_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE TABLE gate_tool_catalog (
        tool_ref TEXT PRIMARY KEY, instance_id TEXT NOT NULL, name TEXT NOT NULL,
        description TEXT NOT NULL, source TEXT NOT NULL, permission TEXT NOT NULL,
        policy_json TEXT NOT NULL, schema_revision TEXT NOT NULL
    );
    CREATE INDEX idx_gate_catalog_instance ON gate_tool_catalog(instance_id, tool_ref);
    CREATE VIRTUAL TABLE gate_tool_catalog_fts USING fts5(
        tool_ref, name, description, content='gate_tool_catalog', content_rowid='rowid',
        tokenize='unicode61'
    );
    CREATE TRIGGER gate_catalog_insert AFTER INSERT ON gate_tool_catalog BEGIN
        INSERT INTO gate_tool_catalog_fts(rowid,tool_ref,name,description)
        VALUES(new.rowid,new.tool_ref,new.name,new.description);
    END;
    CREATE TRIGGER gate_catalog_delete AFTER DELETE ON gate_tool_catalog BEGIN
        INSERT INTO gate_tool_catalog_fts(gate_tool_catalog_fts,rowid,tool_ref,name,description)
        VALUES('delete',old.rowid,old.tool_ref,old.name,old.description);
    END;
    CREATE TRIGGER gate_catalog_update AFTER UPDATE ON gate_tool_catalog BEGIN
        INSERT INTO gate_tool_catalog_fts(gate_tool_catalog_fts,rowid,tool_ref,name,description)
        VALUES('delete',old.rowid,old.tool_ref,old.name,old.description);
        INSERT INTO gate_tool_catalog_fts(rowid,tool_ref,name,description)
        VALUES(new.rowid,new.tool_ref,new.name,new.description);
    END;
    CREATE TABLE gate_catalog_epochs (
        id INTEGER PRIMARY KEY CHECK(id=1), policy INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO gate_catalog_epochs(id) VALUES(1);
    """)
    for table in (
        "mcp_resource_grants", "mcp_tool_classifications", "permission_types",
        "users", "user_roles", "roles", "role_permissions",
    ):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            connection.execute(f"""CREATE TRIGGER gate_catalog_{table}_{operation.lower()}
                AFTER {operation} ON {table} BEGIN
                UPDATE gate_catalog_epochs SET policy=policy+1 WHERE id=1; END""")

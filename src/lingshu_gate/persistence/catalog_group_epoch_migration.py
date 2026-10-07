"""Invalidate public directory cursors on logical group and membership writes."""
from __future__ import annotations

import sqlite3

CATALOG_GROUP_EPOCH_MIGRATION_ID = "0016_gate_catalog_group_epoch"


def apply_catalog_group_epoch_migration(connection: sqlite3.Connection) -> None:
    for table in ("mcp_groups", "mcp_group_members"):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            connection.execute(f"""CREATE TRIGGER gate_catalog_{table}_{operation.lower()}
                AFTER {operation} ON {table} BEGIN
                UPDATE gate_catalog_epochs SET policy=policy+1 WHERE id=1; END""")

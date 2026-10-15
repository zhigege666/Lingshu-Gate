"""按凭据独立保存工具发现方式，历史授权缺省为按需。"""
from __future__ import annotations

import sqlite3

AUTHORIZATION_DISCOVERY_MIGRATION_ID = "0021_authorization_discovery"


def apply_authorization_discovery_migration(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS authorization_discovery (
        kind TEXT NOT NULL CHECK(kind IN ('api','builtin','external')),
        authorization_id TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('on_demand','direct')),
        revision INTEGER NOT NULL CHECK(revision > 0),
        PRIMARY KEY(kind, authorization_id)
    )""")

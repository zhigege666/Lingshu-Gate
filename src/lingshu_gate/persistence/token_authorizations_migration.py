"""个人 API 令牌范围与单次授权确认；旧令牌不自动生成策略。"""
from __future__ import annotations

import sqlite3

from lingshu_gate.persistence.migrations import execute_sql_script

TOKEN_AUTHORIZATIONS_MIGRATION_ID = "0020_gate_token_authorizations"


def apply_token_authorizations_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
CREATE TABLE api_token_authorizations (
    token_id TEXT PRIMARY KEY REFERENCES api_tokens(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision > 0),
    mode TEXT NOT NULL CHECK(mode IN ('account','independent')),
    server_policies_json TEXT NOT NULL,
    tools_json TEXT NOT NULL,
    rate_per_minute INTEGER NOT NULL CHECK(rate_per_minute BETWEEN 1 AND 10000),
    concurrency INTEGER NOT NULL CHECK(concurrency BETWEEN 1 AND 100)
);
CREATE TABLE api_token_authorization_tickets (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_hash TEXT NOT NULL,
    target_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    binding_digest TEXT NOT NULL,
    target_digest TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX idx_token_authorization_ticket_expiry ON api_token_authorization_tickets(expires_at);
""")

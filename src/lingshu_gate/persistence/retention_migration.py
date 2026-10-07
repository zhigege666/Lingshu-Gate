"""Retention policy, resumable cleanup and optional invocation payload storage."""
import sqlite3
from lingshu_gate.persistence.migrations import execute_sql_script

RETENTION_MIGRATION_ID = "0002_retention_and_invocation_payloads"


def apply_retention_migration(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
    CREATE INDEX idx_logs_retention_utc ON logs(julianday(created_at), id);
    CREATE INDEX idx_events_retention_utc ON events(julianday(created_at), id);
    CREATE INDEX idx_audits_retention_utc ON invocation_audits(julianday(created_at), id);
    CREATE TABLE retention_policy (
      id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
      logs_days INTEGER NOT NULL CHECK(logs_days BETWEEN 1 AND 3650),
      events_days INTEGER NOT NULL CHECK(events_days BETWEEN 1 AND 3650),
      invocation_audits_days INTEGER NOT NULL CHECK(invocation_audits_days BETWEEN 1 AND 3650),
      payload_mode TEXT NOT NULL CHECK(payload_mode IN ('metadata_only','redacted'))
    );
    INSERT INTO retention_policy VALUES (1, 1, 7, 7, 7, 'metadata_only');
    CREATE TABLE retention_jobs (
      id TEXT PRIMARY KEY, policy_revision INTEGER NOT NULL, cutoffs_json TEXT NOT NULL,
      state TEXT NOT NULL, counts_json TEXT NOT NULL, created_at TEXT NOT NULL,
      cancel_requested INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
      retry_at REAL NOT NULL DEFAULT 0, error_code TEXT, actor_id TEXT NOT NULL
    );
    CREATE INDEX idx_retention_jobs_state ON retention_jobs(state, retry_at, created_at);
    CREATE TABLE retention_lease (
      id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, expires_at REAL NOT NULL DEFAULT 0
    );
    INSERT INTO retention_lease(id) VALUES (1);
    CREATE TABLE invocation_payloads (
      audit_id TEXT PRIMARY KEY REFERENCES invocation_audits(id) ON DELETE CASCADE,
      user_id TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL
    );
    CREATE INDEX idx_invocation_payloads_user ON invocation_payloads(user_id);
    """)

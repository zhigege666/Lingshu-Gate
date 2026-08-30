"""SQLite database helpers for Lingshu Gate."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from lingshu_gate.persistence.migrations import (
    Migration,
    MigrationRunner,
    execute_sql_script,
)

BASELINE_MIGRATION_ID = "0001_gate_baseline"
SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_LOCK_RETRY_MAX_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1_000


class SQLiteDatabase:
    """Small SQLite wrapper used by control-plane stores.

    The implementation intentionally stays dependency-free so containerized and
    supported local runs can share the same lightweight storage.
    """

    def __init__(self, db_url: str, data_dir: Path) -> None:
        self.path = _resolve_sqlite_path(db_url, data_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=SQLITE_LOCK_RETRY_MAX_SECONDS,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            _enable_wal_mode(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            return connection
        except BaseException:
            # A failed connection bootstrap must not leave an open handle that
            # prolongs the same schema/journal lock for competing initializers.
            connection.close()
            raise

    def initialize(self) -> None:
        MigrationRunner(
            self.connect,
            (Migration(BASELINE_MIGRATION_ID, self._apply_baseline_migration),),
        ).run()

    def _apply_baseline_migration(self, connection: sqlite3.Connection) -> None:
        """Create the complete Gate baseline schema."""

        execute_sql_script(
            connection,
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('pending', 'active', 'disabled')),
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_prefix TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS user_downstream_credentials (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    UNIQUE(user_id, server_id, slot_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_user_downstream_credentials_user
                    ON user_downstream_credentials(user_id);
                CREATE INDEX IF NOT EXISTS idx_user_downstream_credentials_resource
                    ON user_downstream_credentials(server_id, slot_id);

                CREATE TABLE IF NOT EXISTS roles (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    is_system INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS control_permissions (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    is_system INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS role_permissions (
                    role_id TEXT NOT NULL,
                    permission_id TEXT NOT NULL,
                    PRIMARY KEY(role_id, permission_id),
                    FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE,
                    FOREIGN KEY(permission_id) REFERENCES control_permissions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    PRIMARY KEY(user_id, role_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS permission_types (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    base_level TEXT NOT NULL CHECK(base_level IN ('none', 'read', 'write')),
                    description TEXT NOT NULL DEFAULT '',
                    is_system INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mcp_resource_grants (
                    id TEXT PRIMARY KEY,
                    subject_type TEXT NOT NULL CHECK(subject_type IN ('user', 'role')),
                    subject_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL DEFAULT '',
                    permission_type_id TEXT NOT NULL,
                    expires_at TEXT,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(subject_type, subject_id, server_id, tool_id),
                    FOREIGN KEY(permission_type_id) REFERENCES permission_types(id)
                );

                CREATE INDEX IF NOT EXISTS idx_mcp_grants_subject ON mcp_resource_grants(subject_type, subject_id);
                CREATE INDEX IF NOT EXISTS idx_mcp_grants_resource ON mcp_resource_grants(server_id, tool_id);

                CREATE TABLE IF NOT EXISTS mcp_tool_classifications (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    suggested_access TEXT NOT NULL CHECK(suggested_access IN ('read', 'write', 'unknown')),
                    effective_access TEXT NOT NULL CHECK(effective_access IN ('read', 'write', 'unknown')),
                    status TEXT NOT NULL CHECK(status IN ('pending', 'published', 'stale')),
                    confidence REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'rule',
                    destructive INTEGER NOT NULL DEFAULT 0,
                    idempotent INTEGER NOT NULL DEFAULT 0,
                    open_world INTEGER NOT NULL DEFAULT 1,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(server_id, tool_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tool_classifications_server ON mcp_tool_classifications(server_id);
                CREATE INDEX IF NOT EXISTS idx_tool_classifications_status ON mcp_tool_classifications(status);

                CREATE TABLE IF NOT EXISTS invocation_audits (
                    id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    auth_type TEXT NOT NULL,
                    api_token_id TEXT,
                    server_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    tool_access TEXT NOT NULL,
                    required_access TEXT NOT NULL,
                    granted_access TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow', 'deny')),
                    reason TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('success', 'error', 'not_invoked')),
                    duration_ms INTEGER,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_invocation_audits_created_at ON invocation_audits(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_invocation_audits_user ON invocation_audits(user_id);
                CREATE INDEX IF NOT EXISTS idx_invocation_audits_resource ON invocation_audits(server_id, tool_id);
                CREATE INDEX IF NOT EXISTS idx_invocation_audits_decision ON invocation_audits(decision);

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    subject_type TEXT,
                    subject_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
                CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_type, subject_id);

                CREATE TABLE IF NOT EXISTS logs (
                    id TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    server_id TEXT,
                    tool_id TEXT,
                    event_type TEXT,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
                CREATE INDEX IF NOT EXISTS idx_logs_server_id ON logs(server_id);
                CREATE INDEX IF NOT EXISTS idx_logs_tool_id ON logs(tool_id);

                CREATE TABLE IF NOT EXISTS project_uploads (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    root_dir TEXT NOT NULL,
                    detected_runtime TEXT NOT NULL DEFAULT 'unknown',
                    analysis_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_project_uploads_created_at ON project_uploads(created_at DESC);

                CREATE TABLE IF NOT EXISTS project_upload_transfers (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    expected_size_bytes INTEGER NOT NULL,
                    expected_sha256 TEXT NOT NULL,
                    received_size_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    temp_path TEXT NOT NULL,
                    upload_id TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_project_upload_transfers_actor
                    ON project_upload_transfers(actor_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_project_upload_transfers_expiry
                    ON project_upload_transfers(status, expires_at);

                CREATE TABLE IF NOT EXISTS project_upload_transfer_chunks (
                    transfer_id TEXT NOT NULL,
                    offset_bytes INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(transfer_id, offset_bytes),
                    FOREIGN KEY(transfer_id) REFERENCES project_upload_transfers(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mcp_idempotent_operations (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(actor_id, tool_id, idempotency_key)
                );

                CREATE INDEX IF NOT EXISTS idx_mcp_idempotent_operations_resource
                    ON mcp_idempotent_operations(resource_type, resource_id);
                CREATE INDEX IF NOT EXISTS idx_mcp_idempotent_operations_status
                    ON mcp_idempotent_operations(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS project_delivery_resource_owners (
                    resource_type TEXT NOT NULL CHECK(resource_type IN ('upload', 'build', 'deployment', 'mcp_server')),
                    resource_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(resource_type, resource_id)
                );

                CREATE INDEX IF NOT EXISTS idx_project_delivery_resource_owners_actor
                    ON project_delivery_resource_owners(owner_id, resource_type, updated_at DESC);

                CREATE TABLE IF NOT EXISTS builds (
                    id TEXT PRIMARY KEY,
                    upload_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    runtime TEXT NOT NULL DEFAULT 'unknown',
                    source_sha256 TEXT NOT NULL DEFAULT '',
                    plan_fingerprint TEXT NOT NULL DEFAULT '',
                    operation_id TEXT NOT NULL DEFAULT '',
                    source_dir TEXT NOT NULL,
                    artifact_dir TEXT NOT NULL,
                    entrypoint TEXT,
                    command_json TEXT NOT NULL DEFAULT '[]',
                    logs_json TEXT NOT NULL DEFAULT '[]',
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_builds_created_at ON builds(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_builds_upload_id ON builds(upload_id);
                CREATE INDEX IF NOT EXISTS idx_builds_status ON builds(status);

                CREATE TABLE IF NOT EXISTS build_logs (
                    id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL DEFAULT '',
                    command_json TEXT NOT NULL DEFAULT '[]',
                    returncode INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_build_logs_build_id_sequence ON build_logs(build_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_build_logs_created_at ON build_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_build_logs_level ON build_logs(level);

                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    previous_manifest_json TEXT,
                    config_path TEXT,
                    started INTEGER NOT NULL DEFAULT 0,
                    config_applied INTEGER NOT NULL DEFAULT 0,
                    runtime_started INTEGER NOT NULL DEFAULT 0,
                    rollback_attempted INTEGER NOT NULL DEFAULT 0,
                    rollback_succeeded INTEGER,
                    rollback_error TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_deployments_created_at ON deployments(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deployments_build_id ON deployments(build_id);
                CREATE INDEX IF NOT EXISTS idx_deployments_server_id ON deployments(server_id);
                CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);

                CREATE TABLE IF NOT EXISTS mcp_runtime_intents (
                    server_id TEXT PRIMARY KEY,
                    desired_state TEXT NOT NULL CHECK(desired_state IN ('running', 'stopped')),
                    revision INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_mcp_runtime_intents_updated_at ON mcp_runtime_intents(updated_at DESC);

                CREATE TABLE IF NOT EXISTS preflight_cache (
                    cache_key TEXT PRIMARY KEY,
                    upload_id TEXT NOT NULL,
                    scope_key TEXT,
                    fingerprint_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_preflight_cache_upload_id ON preflight_cache(upload_id);
                CREATE INDEX IF NOT EXISTS idx_preflight_cache_updated_at ON preflight_cache(updated_at DESC);
                """,
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_preflight_cache_scope_key ON preflight_cache(scope_key)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id)")

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> None:
        with self.connect() as connection:
            connection.execute(sql, parameters)
            connection.commit()

    def query_one(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(sql, parameters).fetchone()

    def query_all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(sql, parameters).fetchall())


def _enable_wal_mode(
    connection: sqlite3.Connection,
    *,
    max_wait_seconds: float = SQLITE_LOCK_RETRY_MAX_SECONDS,
) -> None:
    """Enable WAL despite the transient lock race between first connections.

    ``PRAGMA journal_mode=WAL`` is outside the migration transaction and can
    return ``SQLITE_BUSY`` immediately while another process is creating the
    database, even after ``busy_timeout`` has been configured. Re-checking the
    persistent journal mode lets losing initializers observe the winner's WAL
    change without attempting another write-like PRAGMA.
    """

    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    retry_delay = 0.01
    while True:
        try:
            current = connection.execute("PRAGMA journal_mode").fetchone()
            if current is not None and str(current[0]).lower() == "wal":
                return
            # Filesystems may decline WAL without raising. SQLite remains usable
            # in its returned
            # journal mode, while lock errors are retried below.
            connection.execute("PRAGMA journal_mode=WAL").fetchone()
            return
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_lock_error(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(retry_delay, remaining))
            retry_delay = min(retry_delay * 2, 0.25)


def _is_sqlite_lock_error(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int):
        primary_code = code & 0xFF
        return primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _resolve_sqlite_path(db_url: str, data_dir: Path) -> Path:
    if not db_url:
        return data_dir / "gate.db"
    if not db_url.startswith("sqlite:///") or db_url == "sqlite:///" or any(
        marker in db_url for marker in ("?", "#")
    ):
        raise ValueError("db_url must be a SQLite file URL")
    return Path(db_url.removeprefix("sqlite:///")).expanduser().resolve()

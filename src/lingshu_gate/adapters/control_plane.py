"""Thin wrappers around current stores; no business behavior is duplicated here."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import BASELINE_MIGRATION_ID, SQLiteDatabase
from lingshu_gate.domain.health import ComponentStatus
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.observability_store import ObservabilityStore


class SQLiteStateStoreAdapter:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def readiness(self) -> ComponentStatus:
        row = self.database.query_one("SELECT 1 AS value")
        migration = self.database.query_one(
            "SELECT applied_at FROM schema_migrations WHERE id = ?",
            (BASELINE_MIGRATION_ID,),
        )
        ok = row is not None and int(row["value"]) == 1 and migration is not None
        return ComponentStatus(
            "database",
            ok,
            "SQLite is reachable and baseline migration is applied"
            if ok
            else "SQLite baseline migration is missing",
            {"backend": "sqlite"},
        )


class FileConfigurationSourceAdapter:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir

    def readiness(self) -> ComponentStatus:
        if self.config_dir.exists():
            ok = self.config_dir.is_dir() and os.access(
                self.config_dir,
                os.R_OK | os.W_OK | os.X_OK,
            )
            detail = (
                "configuration directory is readable and writable"
                if ok
                else "configuration path is not a readable and writable directory"
            )
        else:
            parent = self.config_dir.parent
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            ok = parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
            detail = (
                "configuration directory can be created"
                if ok
                else "configuration directory is missing and its parent is not writable"
            )
        return ComponentStatus(
            "configuration",
            ok,
            detail,
            {"source": "filesystem"},
        )


class McpRuntimeDriverAdapter:
    def __init__(self, runtime: McpRuntimeManager) -> None:
        self.runtime = runtime

    def readiness(self) -> ComponentStatus:
        response = self.runtime.list_servers()
        errors = tuple(response.load_errors)
        return ComponentStatus(
            "runtime",
            not errors,
            "runtime catalog loaded"
            if not errors
            else "one or more MCP manifests failed to load",
            {"server_count": len(response.servers), "load_error_count": len(errors)},
        )


class CredentialSecretStoreAdapter:
    def __init__(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store

    def resolve(self, secret_id: str | None) -> str | None:
        return self.credential_store.resolve_value(secret_id)


class ObservabilityEventSinkAdapter:
    def __init__(self, observability_store: ObservabilityStore) -> None:
        self.observability_store = observability_store

    def emit(
        self,
        event_type: str,
        *,
        source: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.observability_store.emit_event(
            event_type,
            source=source,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=dict(payload or {}),
        )

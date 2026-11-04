"""Thin wrappers around current stores; no business behavior is duplicated here."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.health import ComponentStatus
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.path_diagnostics import inspect_directory


class SQLiteStateStoreAdapter:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def readiness(self) -> ComponentStatus:
        ok = self.database.probe_baseline_migration()
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
        status = inspect_directory(self.config_dir, allow_missing=True, require_writable=True)
        return ComponentStatus(
            "configuration",
            status.ok,
            status.detail,
            {"source": "filesystem", "reason_code": status.code},
        )


class McpRuntimeDriverAdapter:
    def __init__(self, runtime: McpRuntimeManager) -> None:
        self.runtime = runtime

    def readiness(self) -> ComponentStatus:
        scan_status, server_count, error_count = self.runtime.configuration_scan_snapshot()
        ok = scan_status in {"missing", "loaded"} and error_count == 0
        if error_count or scan_status == "failed":
            detail = "MCP configuration scan or manifest loading failed"
        elif scan_status == "not_scanned":
            detail = "MCP configuration directory has not been scanned"
        elif scan_status == "missing":
            detail = "last MCP configuration scan was skipped because the directory was missing"
        else:
            detail = "runtime catalog loaded"
        return ComponentStatus(
            "runtime",
            ok,
            detail,
            {"server_count": server_count, "load_error_count": error_count, "scan_status": scan_status},
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

"""Focused filesystem failure diagnostics without changing startup error semantics."""

from __future__ import annotations

import errno
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.logging import JsonFormatter
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.path_diagnostics import inspect_directory


def _startup_event(caplog: pytest.LogCaptureFixture) -> dict:
    records = [record for record in caplog.records if getattr(record, "gate_event", None) == "gate.startup.path_failed"]
    assert len(records) == 1
    return json.loads(JsonFormatter().format(records[0]))


def test_database_parent_file_reports_its_type_without_reading_contents(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    data_path = tmp_path / "data"
    data_path.write_text("private-file-contents")
    with pytest.raises(FileExistsError):
        SQLiteDatabase("", data_path)

    event = _startup_event(caplog)
    assert event["component"] == "database"
    assert event["phase"] == "database_directory"
    assert event["path"] == str(data_path / "gate.db")
    assert event["parent"]["path_type"] == "file"
    assert event["parent"]["reason_code"] == "path_not_directory"
    assert "private-file-contents" not in json.dumps(event)


@pytest.mark.parametrize(
    ("error_number", "reason"),
    [(errno.EACCES, "permission_denied"), (errno.EROFS, "read_only_filesystem")],
)
def test_mkdir_failure_keeps_the_original_error_and_safe_diagnostic_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    error_number: int, reason: str,
) -> None:
    data_path = tmp_path / "data"
    error = OSError(error_number, "do-not-log-this-message")
    original_mkdir = Path.mkdir

    def denied(path: Path, *args, **kwargs):
        if path == data_path:
            raise error
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(OSError) as captured:
        SQLiteDatabase("", data_path)
    assert captured.value is error

    event = _startup_event(caplog)
    assert event["phase"] == "database_directory"
    assert event["reason_code"] == reason
    assert event["errno"] == error_number
    assert event["sqlite_errorcode"] is None
    assert event["effective_uid"] == (os.geteuid() if hasattr(os, "geteuid") else None)
    assert event["effective_gid"] == (os.getegid() if hasattr(os, "getegid") else None)
    assert event["parent"]["observed_path"] == str(tmp_path)
    assert "do-not-log-this-message" not in json.dumps(event)
    assert not data_path.exists()


@pytest.mark.parametrize(
    ("sqlite_code", "reason"),
    [
        (sqlite3.SQLITE_CANTOPEN, "database_open_failed"),
        (sqlite3.SQLITE_READONLY, "database_read_only"),
        (sqlite3.SQLITE_ERROR, "database_initialization_failed"),
    ],
)
def test_sqlite_failure_keeps_code_without_inventing_a_permission_cause_or_logging_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    sqlite_code: int, reason: str,
) -> None:
    database_path = tmp_path / "gate.db"
    database_path.write_bytes(b"private-database-contents")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", "private-environment-value")
    error = sqlite3.OperationalError("private-sql-and-exception-message")
    error.sqlite_errorcode = sqlite_code
    connect = Mock(side_effect=error)
    monkeypatch.setattr("lingshu_gate.database.sqlite3.connect", connect)

    with pytest.raises(sqlite3.OperationalError) as captured:
        SQLiteDatabase("", tmp_path)
    assert captured.value is error

    event = _startup_event(caplog)
    assert event["phase"] == "database_initialize"
    assert event["reason_code"] == reason
    assert event["sqlite_errorcode"] == sqlite_code
    assert event["parent"]["writable"] is True
    assert event["target"]["path_type"] == "file"
    encoded = json.dumps(event)
    for value in ("private-database-contents", "private-environment-value", "private-sql-and-exception-message"):
        assert value not in encoded
    assert "exception" not in event
    assert "db_url" not in event


def test_real_sqlite_rejects_database_path_that_is_a_directory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / "gate.db").mkdir()
    with pytest.raises(sqlite3.OperationalError):
        SQLiteDatabase("", tmp_path)

    event = _startup_event(caplog)
    assert event["reason_code"] == "database_open_failed"
    assert event["target"]["path_type"] == "directory"
    assert event["parent"]["path_type"] == "directory"


def test_startup_config_enumeration_failure_remains_fatal_and_is_diagnosed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "mcp.d"
    config_path.write_text("private-config-contents")
    trust = Mock()
    with pytest.raises(NotADirectoryError):
        McpConfigStore(config_path, http_trust_store=trust)
    trust.migrate_saved_configs.assert_not_called()

    event = _startup_event(caplog)
    assert event["component"] == "configuration"
    assert event["phase"] == "configuration_scan"
    assert event["reason_code"] == "path_type_mismatch"
    assert event["target"]["reason_code"] == "path_not_directory"
    assert "private-config-contents" not in json.dumps(event)


@pytest.mark.skipif(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0, reason="requires a real non-root POSIX user")
def test_inaccessible_config_parent_is_not_mistaken_for_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    parent = tmp_path / "config"
    config_path = parent / "mcp.d"
    config_path.mkdir(parents=True)
    trust = Mock()
    parent.chmod(0o600)
    try:
        with pytest.raises(PermissionError):
            McpConfigStore(config_path, http_trust_store=trust)
        event = _startup_event(caplog)
        assert event["reason_code"] == "permission_denied"
        assert event["target"]["reason_code"] == "path_inspection_failed"
        assert event["target"]["inspection_errno"] == errno.EACCES
        trust.migrate_saved_configs.assert_not_called()
    finally:
        parent.chmod(0o700)


def test_directory_inspection_errors_are_unavailable_without_public_path_or_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = PermissionError(errno.EACCES, "private-os-error")
    monkeypatch.setattr(Path, "stat", Mock(side_effect=error))
    status = inspect_directory(tmp_path, allow_missing=True)
    assert status.ok is False
    assert status.code == "path_inspection_failed"
    assert status.metadata()["inspection_errno"] == errno.EACCES
    assert status.metadata()["inspection_error_type"] == "PermissionError"
    assert str(tmp_path) not in status.detail
    assert "private-os-error" not in status.detail


def test_dangling_directory_symlink_is_not_claimed_to_be_creatable(tmp_path: Path) -> None:
    linked = tmp_path / "mcp.d"
    try:
        linked.symlink_to(tmp_path / "absent", target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")
    status = inspect_directory(linked, allow_missing=True)
    assert status.ok is False
    assert status.code == "path_not_directory"
    assert status.metadata()["path_type"] == "symlink"
    assert not (tmp_path / "absent").exists()

"""Read-only filesystem observations for readiness and startup failure logs."""

from __future__ import annotations

import errno
import logging
import os
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lingshu_gate.logging import log_event


@dataclass(frozen=True)
class DirectoryStatus:
    """Public status text and separate operator-only filesystem observations."""

    ok: bool
    code: str
    detail: str
    _facts: dict[str, Any] = field(repr=False)

    def metadata(self) -> dict[str, Any]:
        """Return path and identity details only to trusted diagnostics/logs."""
        return dict(self._facts)


def _effective_identity() -> dict[str, int | None]:
    return {
        "effective_uid": os.geteuid() if hasattr(os, "geteuid") else None,
        "effective_gid": os.getegid() if hasattr(os, "getegid") else None,
    }


def _can_access(path: Path, mode: int) -> bool:
    if os.access in os.supports_effective_ids:
        return os.access(path, mode, effective_ids=True)
    return os.access(path, mode)


def _path_snapshot(path: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "path": str(path), "exists": False, "path_type": "missing",
        "owner_uid": None, "owner_gid": None, "mode": None,
        "readable": None, "writable": None, "searchable": None,
        "inspection_errno": None, "inspection_error_type": None,
    }
    try:
        try:
            info = path.stat()
        except FileNotFoundError:
            # A dangling link is an existing invalid path, not a creatable directory.
            try:
                info = path.lstat()
            except FileNotFoundError:
                return facts
        is_directory = stat.S_ISDIR(info.st_mode)
        facts.update(
            exists=True,
            path_type=("directory" if is_directory else "file" if stat.S_ISREG(info.st_mode)
                       else "symlink" if stat.S_ISLNK(info.st_mode) else "other"),
            owner_uid=info.st_uid, owner_gid=info.st_gid,
            mode=format(stat.S_IMODE(info.st_mode), "04o"),
        )
        facts.update(
            readable=_can_access(path, os.R_OK),
            writable=_can_access(path, os.W_OK),
            searchable=_can_access(path, os.X_OK) if is_directory else None,
        )
    except OSError as error:
        if facts["exists"] is False:
            facts.update(exists=None, path_type="unknown")
        facts.update(inspection_errno=error.errno, inspection_error_type=type(error).__name__)
    return facts


def inspect_directory(
    path: Path, *, allow_missing: bool = False, require_writable: bool = True,
) -> DirectoryStatus:
    """Observe permissions without creating files or claiming a later operation will succeed.

    A missing directory is creatable only when its nearest existing ancestor is
    a directory with write and search access. Real filesystem operations remain
    authoritative: access checks cannot exclude races, quotas or filesystem errors.
    """
    path = Path(path)
    observed = path
    identity = _effective_identity()
    while True:
        snapshot = _path_snapshot(observed)
        facts = {**snapshot, **identity, "path": str(path), "observed_path": str(observed)}
        facts["exists"] = snapshot["exists"] if observed == path else False

        def result(ok: bool, code: str, detail: str) -> DirectoryStatus:
            return DirectoryStatus(ok, code, detail, facts)

        if snapshot["inspection_error_type"] is not None:
            if snapshot["inspection_errno"] == errno.ENOTDIR:
                return result(False, "path_not_directory", "path is not a directory")
            return result(False, "path_inspection_failed", "directory access could not be inspected")
        if snapshot["exists"] is False:
            if not allow_missing or observed.parent == observed:
                return result(False, "path_missing", "directory does not exist")
            observed = observed.parent
            continue
        if snapshot["path_type"] != "directory":
            return result(False, "path_not_directory", "path is not a directory")
        if not snapshot["searchable"]:
            return result(False, "directory_not_searchable", "directory cannot be entered")
        if observed != path:
            if not snapshot["writable"]:
                return result(False, "directory_not_writable", "directory cannot be created in its parent")
            return result(True, "directory_creatable", "directory is missing and can be created")
        if not snapshot["readable"]:
            return result(False, "directory_not_readable", "directory is not readable")
        if require_writable and not snapshot["writable"]:
            return result(False, "directory_not_writable", "directory is not writable")
        detail = "directory is readable, writable and searchable" if require_writable else "directory is readable and searchable"
        return result(True, "directory_ready", detail)


def _failure_reason(error: OSError | sqlite3.Error) -> str:
    error_number = getattr(error, "errno", None)
    if error_number in (errno.EACCES, errno.EPERM):
        return "permission_denied"
    if error_number == errno.EROFS:
        return "read_only_filesystem"
    if error_number == errno.ENOENT:
        return "path_missing"
    if error_number in (errno.ENOTDIR, errno.EISDIR):
        return "path_type_mismatch"
    if error_number == errno.ENOSPC:
        return "storage_full"
    sqlite_code = getattr(error, "sqlite_errorcode", None)
    if isinstance(sqlite_code, int):
        if sqlite_code & 0xFF == sqlite3.SQLITE_CANTOPEN:
            return "database_open_failed"
        if sqlite_code & 0xFF == sqlite3.SQLITE_READONLY:
            return "database_read_only"
    return "database_initialization_failed" if isinstance(error, sqlite3.Error) else "path_operation_failed"


def log_path_failure(
    logger: logging.Logger, *, component: str, phase: str, path: Path,
    error: OSError | sqlite3.Error, directory: bool = False,
) -> None:
    """Record filesystem facts without copying exception messages, URLs, SQL or contents."""
    parent = inspect_directory(path.parent, allow_missing=True)
    parent_facts = parent.metadata()
    parent_facts["reason_code"] = parent.code
    target = _path_snapshot(path)
    if directory:
        status = inspect_directory(path, allow_missing=True, require_writable=False)
        target = status.metadata()
        target["reason_code"] = status.code
    log_event(
        logger, logging.ERROR, "gate.startup.path_failed", "Gate storage initialization failed",
        component=component, phase=phase, reason_code=_failure_reason(error), path=str(path),
        **_effective_identity(), error_type=type(error).__name__, errno=getattr(error, "errno", None),
        sqlite_errorcode=getattr(error, "sqlite_errorcode", None), parent=parent_facts, target=target,
    )

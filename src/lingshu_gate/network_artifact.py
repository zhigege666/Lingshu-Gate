"""Bounded export defense for an executor's quiescent workspace, not isolation."""

from __future__ import annotations

import base64
import os
import stat
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from lingshu_gate.git_source import SECRET_TEXT
from lingshu_gate.safe_files import open_regular_file

NETWORK_ARTIFACT_LIMITS = {"files": 30000, "bytes": 500 * 1024 * 1024, "seconds": 30}


def export_network_artifact(source: Path, target: Path, *, ignored: set[str], forbidden_values: list[str], cancelled: Callable[[], bool], limits: dict[str, int] | None = None) -> dict[str, Any]:
    """Preserve only contained relative links; copy regular files with bounded scans.

    A reviewed executor must stop all writers and freeze its output before this
    export. Host path checks cannot isolate a running hostile process.
    """
    bounds = limits or NETWORK_ARTIFACT_LIMITS
    deadline = time.monotonic() + bounds["seconds"]
    forbidden: set[bytes] = set()
    for value in forbidden_values:
        if value:
            if len(value.encode()) > 64 * 1024:
                raise ValueError("network_artifact_material_limit")
            forbidden.update({value.encode(), quote(value, safe="").encode(), base64.b64encode(value.encode())})
    overlap = max([256, *(len(value) for value in forbidden)])
    root = source.resolve()
    count, total = 0, 0

    def checkpoint() -> None:
        if cancelled():
            raise InterruptedError("network_artifact_cancelled")
        if time.monotonic() > deadline:
            raise TimeoutError("network_artifact_timeout")

    def destination(path: Path) -> Path:
        nonlocal count
        checkpoint()
        count += 1
        if count > bounds["files"]:
            raise ValueError("network_artifact_file_limit")
        relative = path.relative_to(root)
        if any(value in relative.as_posix().encode() for value in forbidden):
            raise ValueError("network_artifact_secret_rejected")
        return target / relative

    def copy_link(path: Path, output: Path) -> None:
        link = os.readlink(path)
        try:
            resolved = path.resolve(strict=True)
            contained = resolved.relative_to(root)
        except (ValueError, OSError, RuntimeError):
            raise ValueError("network_artifact_link_rejected") from None
        if Path(link).is_absolute() or any(part in ignored for part in contained.parts):
            raise ValueError("network_artifact_link_rejected")
        output.symlink_to(link, target_is_directory=resolved.is_dir())

    for directory, folders, filenames in os.walk(root, followlinks=False):
        checkpoint()
        folders[:] = sorted(folder for folder in folders if folder not in ignored)
        parent = Path(directory)
        for folder in list(folders):
            path = parent / folder
            output = destination(path)
            if path.is_symlink():
                copy_link(path, output)
                folders.remove(folder)
            else:
                output.mkdir()
        for name in sorted(filenames):
            if name in ignored:
                continue
            path = parent / name
            output = destination(path)
            if path.is_symlink():
                copy_link(path, output)
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("network_artifact_type_rejected")
            tail = b""
            with output.open("xb") as writer, open_regular_file(path, maximum=NETWORK_ARTIFACT_LIMITS["bytes"]) as (reader, info):
                if info.st_size > bounds["bytes"] - total:
                    raise ValueError("network_artifact_size_limit")
                while True:
                    checkpoint()
                    chunk = reader.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > bounds["bytes"]:
                        raise ValueError("network_artifact_size_limit")
                    window = tail + chunk
                    if SECRET_TEXT.search(window) or any(value in window for value in forbidden):
                        raise ValueError("network_artifact_secret_rejected")
                    writer.write(chunk)
                    tail = window[-overlap:]
            output.chmod(info.st_mode & 0o777)
    return {"files": count, "bytes": total}

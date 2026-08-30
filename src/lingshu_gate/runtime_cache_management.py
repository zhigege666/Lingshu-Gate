"""Runtime cache management APIs for dynamic MCP packages."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lingshu_gate.config import Settings


def runtime_cache_status(settings: Settings) -> dict[str, Any]:
    root = settings.data_dir / "runtime-cache"
    npm_cache = root / "npm-cache"
    caches = [_cache_info("npm", npm_cache)]
    return {
        "root": _path_info(root),
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in caches),
        "caches": caches,
    }


def clear_runtime_cache(settings: Settings, cache_name: str) -> dict[str, Any]:
    root = (settings.data_dir / "runtime-cache").resolve()
    cache_map = {
        "npm": root / "npm-cache",
    }
    if cache_name not in cache_map:
        raise ValueError(f"Unsupported cache name: {cache_name}")
    target = cache_map[cache_name].resolve()
    if not _is_inside(target, root):
        raise ValueError("Refusing to clear cache outside runtime-cache root")

    before = _cache_info(cache_name, target)
    removed = bool(target.exists())
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    after = _cache_info(cache_name, target)
    return {
        "cache": cache_name,
        "removed": removed,
        "before": before,
        "after": after,
    }


def _cache_info(name: str, path: Path) -> dict[str, Any]:
    info = _path_info(path)
    info.update({
        "name": name,
        "size_bytes": _dir_size(path),
        "file_count": _file_count(path),
        "last_modified_at": _last_modified(path),
    })
    return info


def _path_info(path: Path) -> dict[str, Any]:
    exists = path.exists()
    parent = path.parent
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": path.is_dir() if exists else False,
        "readable": os.access(path, os.R_OK) if exists else False,
        "writable": os.access(path, os.W_OK) if exists else False,
        "parent_writable": os.access(parent, os.W_OK) if parent.exists() else False,
    }


def _dir_size(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _file_count(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    count = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                count += 1
        except OSError:
            continue
    return count


def _last_modified(path: Path) -> str | None:
    if not path.exists():
        return None
    latest = 0.0
    items = path.rglob("*") if path.is_dir() else [path]
    for item in items:
        try:
            latest = max(latest, item.stat().st_mtime)
        except OSError:
            continue
    if latest <= 0:
        try:
            latest = path.stat().st_mtime
        except OSError:
            return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

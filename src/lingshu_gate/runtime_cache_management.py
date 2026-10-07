"""Runtime cache management APIs for dynamic MCP packages."""

from __future__ import annotations

import os
import shutil
import stat
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
    info.update({"name": name, **_tree_summary(path)})
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


def _tree_summary(path: Path) -> dict[str, Any]:
    """Compute all directory metrics in one walk and one stat per entry."""
    size = count = 0
    latest = 0.0
    if path.exists():
        directory = path.is_dir()
        items = path.rglob("*") if directory else [path]
        for item in items:
            try:
                metadata = item.stat()
            except OSError:
                continue  # Package installers may remove a file during this read.
            if directory and stat.S_ISREG(metadata.st_mode):
                size += metadata.st_size
                count += 1
            latest = max(latest, metadata.st_mtime)
        if latest <= 0:
            try:
                latest = path.stat().st_mtime
            except OSError:
                pass
    return {
        "size_bytes": size,
        "file_count": count,
        "last_modified_at": datetime.fromtimestamp(latest, tz=timezone.utc).isoformat() if latest > 0 else None,
    }


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

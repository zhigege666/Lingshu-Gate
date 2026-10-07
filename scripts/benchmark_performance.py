"""Opt-in synthetic SQLite benchmark; never opens the deployment database.

Run with: uv run python scripts/benchmark_performance.py --rows 30000
Results are local warm-cache timings, not production capacity promises.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.runtime_cache_management import _cache_info


def measure(action: Callable[[], Any], repeats: int = 3) -> dict[str, Any]:
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        action()
        timings.append(round((time.perf_counter() - started) * 1000, 3))
    return {"runs_ms": timings, "median_ms": statistics.median(timings)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--cache-files", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.rows <= 1000000 or not 0 <= args.cache_files <= 100000:
        parser.error("rows must be 1..1000000; cache-files must be 0..100000")
    with tempfile.TemporaryDirectory(prefix="gate-perf-") as temporary:
        root = Path(temporary)
        database = SQLiteDatabase("", root)
        store = AccessControlStore(database)
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with database.session() as connection:
            connection.executemany(
                "INSERT INTO invocation_audits(id,correlation_id,user_id,username,auth_type,server_id,"
                "tool_id,tool_access,required_access,granted_access,decision,reason,outcome,payload_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ((str(i), str(i), f"user-{i % 100}", f"User {i % 100}", "session", f"server-{i % 100}",
                  f"mcp.server-{i % 100}.tool-{i % 3000}", "read", "read", "read", "allow", "benchmark", "success", "{}",
                  (now - timedelta(seconds=args.rows - i)).isoformat()) for i in range(args.rows)),
            )
        result = {"synthetic": True, "rows": args.rows, "users": 100,
                  "filter_options": measure(store.list_invocation_audit_filter_options),
                  "statistics": measure(lambda: store.invocation_statistics(now=now))}
        cache = root / "cache"
        cache.mkdir()
        for index in range(args.cache_files):
            folder = cache / str(index // 100)
            folder.mkdir(exist_ok=True)
            (folder / str(index)).write_bytes(b"x" * 128)
        result["cache_files"] = args.cache_files
        result["cache_status"] = measure(lambda: _cache_info("npm", cache))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

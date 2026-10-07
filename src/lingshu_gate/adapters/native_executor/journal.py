"""Durable single-owner phase journal. Unknown work is never dispatched again."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any
from contextlib import contextmanager
from collections.abc import Iterator

from lingshu_gate.git_source import digest_json
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.ports.safe_network_executor import SafeExecutionCancelled
from lingshu_gate.adapters.native_executor.pending import PendingDNS


class JobJournal:
    def __init__(self, root: Path) -> None:
        import fcntl
        self._mutex = threading.RLock()
        self._active_trusted: set[str] = set()
        self._pending_dns: dict[str, threading.Thread] = {}
        self._lease = (root / "owner.lock").open("a+b")
        try:
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lease.close()
            raise ToolExecutionError("executor_owner_busy", "Executor journal already has a live owner") from None
        self.connection = sqlite3.connect(root / "jobs.sqlite3", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, digest TEXT NOT NULL, name TEXT NOT NULL UNIQUE, phase TEXT NOT NULL, state TEXT NOT NULL, container_id TEXT, cgroup TEXT, result TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        if "cleanup_state" not in {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN cleanup_state TEXT NOT NULL DEFAULT 'pending'")
        self.connection.commit()

    def reserve(self, key: str, descriptor: dict[str, Any], phase: str) -> dict[str, Any]:
        digest = digest_json(descriptor)
        name = "gate-job-" + digest_json(key)[:32]
        with self._mutex, self.connection:
            row = self.connection.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if row:
                if row["digest"] != digest:
                    raise ToolExecutionError("executor_idempotency_conflict", "Phase key is already bound to different content")
                raise InterruptedError("executor_phase_already_recorded")
            self.connection.execute("INSERT INTO jobs(key,digest,name,phase,state) VALUES(?,?,?,?,?)", (key, digest, name, phase, "reserved"))
        return {"key": key, "name": name, "digest": digest, "phase": phase}

    def update(self, key: str, state: str, *, container_id: str | None = None, cgroup: str | None = None, result: dict[str, Any] | None = None) -> None:
        with self._mutex, self.connection:
            self.connection.execute("UPDATE jobs SET state=?,container_id=COALESCE(?,container_id),cgroup=COALESCE(?,cgroup),result=COALESCE(?,result),updated_at=CURRENT_TIMESTAMP WHERE key=?", (state, container_id, cgroup, json.dumps(result) if result is not None else None, key))
            if state in {"completed", "failed", "cancelled", "interrupted_terminated"}:
                self._pending_dns.pop(key, None)

    def reconciliation_required(self) -> bool:
        with self._mutex:
            return self.connection.execute("SELECT 1 FROM jobs WHERE state='unknown' LIMIT 1").fetchone() is not None

    def trusted_work_stopped(self) -> bool:
        with self._mutex:
            return not self._active_trusted and all(not worker.is_alive() for worker in self._pending_dns.values())

    def dns_recovery_ready(self) -> bool:
        """Only live-process DNS evidence permits recovery without a restart."""
        with self._mutex:
            rows = self.unfinished()
            return bool(rows) and not self._active_trusted and all(row["state"] == "unknown" and row["phase"] in {"git_acquisition", "tool_acquisition", "dependency_acquisition"} and not row["container_id"] and not row["cgroup"] and row["key"] in self._pending_dns and not self._pending_dns[row["key"]].is_alive() for row in rows)

    def unfinished(self) -> list[dict[str, Any]]:
        with self._mutex:
            return [dict(row) for row in self.connection.execute("SELECT * FROM jobs WHERE state NOT IN ('completed','failed','cancelled','interrupted_terminated')")]

    def lookup(self, key: str) -> dict[str, Any] | None:
        with self._mutex:
            row = self.connection.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            return dict(row) if row else None

    def lookup_name(self, name: str) -> dict[str, Any] | None:
        with self._mutex:
            row = self.connection.execute("SELECT * FROM jobs WHERE name=?", (name,)).fetchone()
            return dict(row) if row else None

    def cleanup_pending(self) -> list[dict[str, Any]]:
        with self._mutex:
            return [dict(row) for row in self.connection.execute("SELECT * FROM jobs WHERE cleanup_state='pending' AND state IN ('completed','failed','cancelled','interrupted_terminated')")]

    def mark_cleaned(self, key: str) -> None:
        with self._mutex, self.connection:
            self.connection.execute("UPDATE jobs SET cleanup_state='cleaned',updated_at=CURRENT_TIMESTAMP WHERE key=? AND state IN ('completed','failed','cancelled','interrupted_terminated')", (key,))

    @contextmanager
    def trusted_phase(self, key: str, descriptor: dict[str, Any], phase: str) -> Iterator[None]:
        with self._mutex:
            self.reserve(key, descriptor, phase)
            self.update(key, "running")
            self._active_trusted.add(key)
        try:
            yield
        except SafeExecutionCancelled:
            self.update(key, "cancelled")
            raise
        except InterruptedError as error:
            with self._mutex:
                if isinstance(error, PendingDNS):
                    # Retain only the worker, never the request traceback/material.
                    self._pending_dns[key] = error.worker
                    self.update(key, "unknown", result={"reconciliation_reason": "trusted_dns_termination_unknown"})
                else:
                    self.update(key, "unknown")
            raise
        except BaseException:
            self.update(key, "failed")
            raise
        else:
            self.update(key, "completed")
        finally:
            with self._mutex:
                self._active_trusted.discard(key)

    def close(self) -> None:
        import fcntl
        self.connection.close()
        fcntl.flock(self._lease, fcntl.LOCK_UN)
        self._lease.close()

"""CAS retention policy and bounded, leased deletion; no implicit background work."""
from __future__ import annotations

import json
from copy import deepcopy
from threading import Lock
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from lingshu_gate.database import SQLiteDatabase

TABLES = ("logs", "events", "invocation_audits")


class RetentionConflict(ValueError):
    """The preview, revision or lease is no longer valid."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone required")
    return value.astimezone(timezone.utc)


class RetentionStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        # Preview never writes the DB. Restart invalidates outstanding confirmations.
        self._previews: dict[str, dict[str, Any]] = {}
        self._preview_lock = Lock()

    def policy(self) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM retention_policy WHERE id=1")
        assert row is not None
        return {key: row[key] for key in row.keys() if key != "id"}

    @staticmethod
    def validate(values: dict[str, Any]) -> None:
        if set(values) != {"logs_days", "events_days", "invocation_audits_days", "payload_mode"}:
            raise ValueError("complete retention policy required")
        for table in TABLES:
            value = values[f"{table}_days"]
            if type(value) is not int or not 1 <= value <= 3650:
                raise ValueError("retention days must be 1..3650")
        if values["payload_mode"] not in ("metadata_only", "redacted"):
            raise ValueError("invalid payload mode")

    def save_policy(self, expected_revision: int, values: dict[str, Any], *,
                    preview_id: str | None = None, confirmed: bool = False) -> dict[str, Any]:
        self.validate(values)
        with self.database.session() as db:
            db.execute("BEGIN IMMEDIATE")
            current = dict(db.execute("SELECT * FROM retention_policy WHERE id=1").fetchone())
            if current["revision"] != expected_revision:
                raise RetentionConflict("policy_revision_changed")
            if any(values[f"{table}_days"] < current[f"{table}_days"] for table in TABLES):
                with self._preview_lock:
                    preview = deepcopy(self._previews.get(preview_id or ""))
                if (not confirmed or not preview or preview["revision"] != expected_revision
                        or preview["policy"] != values or preview["expires_at"] <= utc_now().isoformat()):
                    raise RetentionConflict("shortening_confirmation_required")
            cursor = db.execute(
                "UPDATE retention_policy SET revision=revision+1, logs_days=?, events_days=?, "
                "invocation_audits_days=?, payload_mode=? WHERE id=1 AND revision=?",
                (values["logs_days"], values["events_days"], values["invocation_audits_days"],
                 values["payload_mode"], expected_revision),
            )
            if cursor.rowcount != 1:
                raise RetentionConflict("policy_revision_changed")
            result = dict(db.execute("SELECT * FROM retention_policy WHERE id=1").fetchone())
            result.pop("id")
            return result

    def preview(self, values: dict[str, Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
        instant = utc(now or utc_now())
        policy = self.policy()
        selected = dict(values) if values is not None else {k: v for k, v in policy.items() if k != "revision"}
        self.validate(selected)
        cutoffs = {table: (instant - timedelta(days=selected[f"{table}_days"])).isoformat()
                   for table in TABLES}
        counts = {}
        for table in TABLES:
            row = self.database.query_one(f"SELECT COUNT(*) AS count FROM {table} WHERE julianday(created_at) < julianday(?)", (cutoffs[table],))
            assert row is not None
            counts[table] = row["count"]
        result = {"preview_id": uuid4().hex, "revision": policy["revision"], "policy": selected,
                  "cutoffs": cutoffs, "counts": counts, "expires_at": (instant + timedelta(minutes=5)).isoformat(),
                  "shortened": [table for table in TABLES if selected[f"{table}_days"] < policy[f"{table}_days"]]}
        with self._preview_lock:
            self._previews = {key: value for key, value in self._previews.items() if value["expires_at"] > instant.isoformat()}
            if len(self._previews) >= 256:
                self._previews.pop(next(iter(self._previews)))
            self._previews[result["preview_id"]] = deepcopy(result)
        return result

    def enqueue(self, preview_id: str, revision: int, actor_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        instant = utc(now or utc_now())
        with self._preview_lock:
            preview = deepcopy(self._previews.get(preview_id))
        if not preview or preview["expires_at"] <= instant.isoformat() or preview["revision"] != revision:
            raise RetentionConflict("preview_expired_or_changed")
        with self.database.session() as db:
            db.execute("BEGIN IMMEDIATE")
            current = dict(db.execute("SELECT * FROM retention_policy WHERE id=1").fetchone())
            if current.pop("revision") != revision:
                raise RetentionConflict("policy_revision_changed")
            current.pop("id")
            if current != preview["policy"]:
                raise RetentionConflict("save_policy_then_preview_again")
            if db.execute("SELECT 1 FROM retention_jobs WHERE state IN ('queued','running','retry')").fetchone():
                raise RetentionConflict("cleanup_already_active")
            job_id = uuid4().hex
            db.execute("INSERT INTO retention_jobs(id,policy_revision,cutoffs_json,state,counts_json,created_at,actor_id) "
                       "VALUES (?,?,?,'queued',?,?,?)", (job_id, revision, json.dumps(preview["cutoffs"]),
                       json.dumps(dict.fromkeys(TABLES, 0)), instant.isoformat(), actor_id))
        with self._preview_lock:
            self._previews.pop(preview_id, None)
        return self.job(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM retention_jobs WHERE id=?", (job_id,))
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result["cutoffs"] = json.loads(result.pop("cutoffs_json"))
        result["counts"] = json.loads(result.pop("counts_json"))
        result["cancel_requested"] = bool(result["cancel_requested"])
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE retention_jobs SET cancel_requested=1,state='cancelled' "
                       "WHERE id=? AND state IN ('queued','running','retry')", (job_id,))
        return self.job(job_id)

    def run_batch(self, owner: str, *, batch_size: int = 200, now: datetime | None = None) -> str | None:
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be 1..1000")
        instant = utc(now or utc_now())
        timestamp = instant.timestamp()
        with self.database.session() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT * FROM retention_lease WHERE id=1").fetchone()
            if lease["owner"] not in (None, owner) and lease["expires_at"] > timestamp:
                return None
            job = db.execute("SELECT * FROM retention_jobs WHERE state IN ('queued','running','retry') "
                             "AND retry_at<=? ORDER BY created_at,id LIMIT 1", (timestamp,)).fetchone()
            if job is None:
                db.execute("UPDATE retention_lease SET owner=NULL,expires_at=0 WHERE id=1 AND owner=?", (owner,))
                return None
            policy = db.execute("SELECT revision FROM retention_policy WHERE id=1").fetchone()
            if job["cancel_requested"] or policy["revision"] != job["policy_revision"]:
                db.execute("UPDATE retention_jobs SET state='cancelled',error_code='policy_changed_or_cancelled' WHERE id=?", (job["id"],))
                db.execute("UPDATE retention_lease SET owner=NULL,expires_at=0 WHERE id=1")
                return job["id"]
            db.execute("UPDATE retention_lease SET owner=?,expires_at=? WHERE id=1", (owner, timestamp + 30))
            db.execute("UPDATE retention_jobs SET state='running',error_code=NULL WHERE id=?", (job["id"],))
            cutoffs, counts = json.loads(job["cutoffs_json"]), json.loads(job["counts_json"])
            for table in TABLES:
                # created_at's existing index bounds the SELECT; one batch per transaction.
                cursor = db.execute(f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} "
                                    "WHERE julianday(created_at) < julianday(?) ORDER BY julianday(created_at),id LIMIT ?)", (cutoffs[table], batch_size))
                if cursor.rowcount:
                    counts[table] += cursor.rowcount
                    db.execute("UPDATE retention_jobs SET counts_json=? WHERE id=?", (json.dumps(counts), job["id"]))
                    return str(job["id"])
            db.execute("UPDATE retention_jobs SET state='succeeded' WHERE id=?", (job["id"],))
            db.execute("UPDATE retention_lease SET owner=NULL,expires_at=0 WHERE id=1")
            return str(job["id"])

    def retry_failure(self, owner: str, *, now: datetime | None = None) -> None:
        instant = utc(now or utc_now()).timestamp()
        with self.database.session() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT * FROM retention_lease WHERE id=1").fetchone()
            if lease["owner"] not in (None, owner) and lease["expires_at"] > instant:
                return
            job = db.execute("SELECT id FROM retention_jobs WHERE state IN ('queued','running','retry') "
                             "AND retry_at<=? ORDER BY created_at,id LIMIT 1", (instant,)).fetchone()
            if job is not None:
                db.execute("UPDATE retention_jobs SET attempts=attempts+1, "
                           "state=CASE WHEN attempts>=2 THEN 'failed' ELSE 'retry' END, "
                           "retry_at=?,error_code='cleanup_batch_failed' WHERE id=?", (instant + 5, job["id"]))
            db.execute("UPDATE retention_lease SET owner=NULL,expires_at=0 WHERE id=1")

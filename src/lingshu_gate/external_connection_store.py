"""Persist default-disabled trust, subject links and delegation; never OAuth tokens."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.external_connection import ExternalConnectionConfig
from lingshu_gate.persistence.migrations import Migration, MigrationRunner, execute_sql_script


def _schema(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
CREATE TABLE IF NOT EXISTS external_connection_drafts (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_external_grant_drafts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS user_external_grant_drafts_owner
    ON user_external_grant_drafts(user_id, created_at);
""")


def _subject_schema(connection: sqlite3.Connection) -> None:
    execute_sql_script(connection, """
CREATE TABLE IF NOT EXISTS external_oauth_subject_links (
    id TEXT PRIMARY KEY,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(issuer, subject)
);
""")


class ExternalIdentityNotFound(PermissionError):
    pass


class DraftRevisionConflict(ValueError):
    pass


class ExternalConnectionStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        MigrationRunner(database.connect, (Migration("0002_external_connection_drafts", _schema),
                                           Migration("0003_external_oauth_subjects", _subject_schema))).run()

    def config(self) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM external_connection_drafts WHERE id = 1")
        return ({**json.loads(row["payload_json"]), "revision": row["revision"], "updated_at": row["updated_at"]}
                if row else {"enabled": False, "mode": "disabled", "revision": 0})

    def configuration(self) -> ExternalConnectionConfig:
        return ExternalConnectionConfig(**{key: value for key, value in self.config().items()
                                           if key not in {"revision", "updated_at"}})

    def save_config(self, payload: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT revision FROM external_connection_drafts WHERE id = 1").fetchone()
            revision = row["revision"] if row else 0
            if revision != expected_revision:
                raise DraftRevisionConflict("configuration changed; reload before saving")
            connection.execute("""INSERT INTO external_connection_drafts(id,payload_json,revision,updated_at)
                VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,
                revision=excluded.revision,updated_at=excluded.updated_at""",
                               (json.dumps(payload), revision + 1, now))
        return {**payload, "revision": revision + 1, "updated_at": now}

    def list_grants(self, user_id: str) -> list[dict[str, Any]]:
        return [self._grant(row) for row in self.database.query_all(
            "SELECT * FROM user_external_grant_drafts WHERE user_id = ? ORDER BY created_at DESC", (user_id,))]

    def get_grant(self, user_id: str, grant_id: str) -> dict[str, Any]:
        row = self.database.query_one(
            "SELECT * FROM user_external_grant_drafts WHERE id = ? AND user_id = ?", (grant_id, user_id))
        if not row:
            raise KeyError("grant not found")
        return self._grant(row)

    def create_grant(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        grant_id, now = uuid4().hex, datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._check_unique_active_grant(connection, user_id, payload)
            connection.execute("""INSERT INTO user_external_grant_drafts
                (id,user_id,payload_json,created_at,updated_at) VALUES(?,?,?,?,?)""",
                               (grant_id, user_id, json.dumps(payload), now, now))
        return self.get_grant(user_id, grant_id)

    def update_grant(self, user_id: str, grant_id: str, payload: dict[str, Any],
                     expected_revision: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM user_external_grant_drafts WHERE id=? AND user_id=?",
                                     (grant_id, user_id)).fetchone()
            if not row:
                raise KeyError("grant not found")
            if row["revoked_at"]:
                raise DraftRevisionConflict("revoked draft cannot be changed")
            if row["revision"] != expected_revision:
                raise DraftRevisionConflict("grant changed; reload before saving")
            self._check_unique_active_grant(connection, user_id, payload, exclude_id=grant_id)
            connection.execute("""UPDATE user_external_grant_drafts SET payload_json=?, revision=revision+1,
                updated_at=? WHERE id=? AND user_id=?""",
                               (json.dumps(payload), datetime.now(timezone.utc).isoformat(), grant_id, user_id))
        return self.get_grant(user_id, grant_id)

    def revoke_grant(self, user_id: str, grant_id: str) -> dict[str, Any]:
        self.get_grant(user_id, grant_id)
        now = datetime.now(timezone.utc).isoformat()
        self.database.execute("""UPDATE user_external_grant_drafts SET revoked_at=?, updated_at=?, revision=revision+1
            WHERE id=? AND user_id=? AND revoked_at IS NULL""", (now, now, grant_id, user_id))
        return self.get_grant(user_id, grant_id)

    @staticmethod
    def _grant(row: Any) -> dict[str, Any]:
        return {**json.loads(row["payload_json"]), "id": row["id"], "user_id": row["user_id"],
                "revision": row["revision"], "revoked_at": row["revoked_at"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}


    @staticmethod
    def _check_unique_active_grant(connection: sqlite3.Connection, user_id: str, payload: dict[str, Any],
                                   exclude_id: str = "") -> None:
        if not payload.get("enabled"):
            return
        now = datetime.now(timezone.utc)
        for row in connection.execute("SELECT * FROM user_external_grant_drafts WHERE user_id=? AND revoked_at IS NULL AND id != ?",
                                      (user_id, exclude_id)):
            previous = json.loads(row["payload_json"])
            if (previous.get("enabled") and previous.get("client_id") == payload.get("client_id")
                    and datetime.fromisoformat(previous["expires_at"]) > now):
                raise DraftRevisionConflict("an active grant already exists for this client")

    def get_active_grant(self, user_id: str, client_id: str, now: datetime) -> dict[str, Any]:
        matches = [grant for grant in self.list_grants(user_id) if grant.get("enabled")
                   and not grant["revoked_at"] and grant["client_id"] == client_id
                   and datetime.fromisoformat(grant["expires_at"]) > now]
        if len(matches) != 1:
            raise ExternalIdentityNotFound("external grant unavailable or ambiguous")
        return matches[0]

    def list_subject_links(self, *, q: str = "", offset: int = 0,
                           limit: int | None = None, link_id: str | None = None) -> list[dict[str, Any]]:
        where, params = self._subject_search(q, link_id)
        sql = """SELECT links.*, users.id AS resolved_user_id, users.username,
                 users.display_name, users.status AS user_status
                 FROM external_oauth_subject_links AS links LEFT JOIN users ON users.id=links.user_id"""
        sql += where + " ORDER BY links.created_at DESC, links.id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += (limit, offset)
        result = []
        for row in self.database.query_all(sql, params):
            item = dict(row)
            user = {"id": item.pop("resolved_user_id"), "username": item.pop("username"),
                    "display_name": item.pop("display_name"), "status": item.pop("user_status")}
            result.append(item | {"enabled": bool(item["enabled"]), "user": user if user["id"] else None})
        return result

    @staticmethod
    def _subject_search(q: str, link_id: str | None = None) -> tuple[str, tuple[Any, ...]]:
        if link_id:
            return " WHERE links.id=?", (link_id,)
        if q.strip():
            return (" WHERE " + " OR ".join(f"instr(lower(COALESCE({column},'')), lower(?)) > 0"
                    for column in ("links.issuer", "links.subject", "links.user_id", "users.username", "users.display_name")),
                    (q.strip(),) * 5)
        return "", ()

    def count_subject_links(self, q: str = "") -> int:
        where, params = self._subject_search(q)
        row = self.database.query_one("SELECT COUNT(*) AS total FROM external_oauth_subject_links AS links "
                                      "LEFT JOIN users ON users.id=links.user_id" + where, params)
        return int(row["total"]) if row else 0

    def subject_user_options(self, *, q: str = "", offset: int = 0, limit: int = 40) -> dict[str, Any]:
        where = " WHERE status='active'"
        params: tuple[Any, ...] = ()
        if q.strip():
            where += " AND (" + " OR ".join(f"instr(lower({column}), lower(?)) > 0"
                                             for column in ("id", "username", "display_name")) + ")"
            params = (q.strip(),) * 3
        count = self.database.query_one("SELECT COUNT(*) AS total FROM users" + where, params)
        rows = self.database.query_all("SELECT id,username,display_name,status FROM users" + where +
                                       " ORDER BY username,id LIMIT ? OFFSET ?", params + (limit, offset))
        return {"users": [dict(row) for row in rows], "total": int(count["total"]) if count else 0,
                "offset": offset, "limit": limit}

    def create_subject_link(self, payload: dict[str, Any]) -> dict[str, Any]:
        link_id, now = uuid4().hex, datetime.now(timezone.utc).isoformat()
        try:
            self.database.execute("""INSERT INTO external_oauth_subject_links
                (id,issuer,subject,user_id,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
                                  (link_id, payload["issuer"], payload["subject"], payload["user_id"],
                                   int(payload.get("enabled", False)), now, now))
        except sqlite3.IntegrityError as exc:
            raise DraftRevisionConflict("subject already linked or user unavailable") from exc
        return self.list_subject_links(link_id=link_id)[0]

    def update_subject_link(self, link_id: str, *, enabled: bool, expected_revision: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM external_oauth_subject_links WHERE id=?", (link_id,)).fetchone()
            if not row:
                raise KeyError("subject link not found")
            if row["revision"] != expected_revision:
                raise DraftRevisionConflict("subject link changed; reload before saving")
            connection.execute("UPDATE external_oauth_subject_links SET enabled=?,revision=revision+1,updated_at=? WHERE id=?",
                               (int(enabled), datetime.now(timezone.utc).isoformat(), link_id))
        return self.list_subject_links(link_id=link_id)[0]

    def resolve_subject(self, issuer: str, subject: str) -> str:
        row = self.database.query_one("""SELECT links.user_id FROM external_oauth_subject_links AS links
            JOIN users ON users.id=links.user_id WHERE links.issuer=? AND links.subject=?
            AND links.enabled=1 AND users.status='active'""", (issuer, subject))
        if not row:
            raise ExternalIdentityNotFound("external subject is not linked to an active user")
        return str(row["user_id"])

    def has_active_subject(self, user_id: str) -> bool:
        issuers = set(self.configuration().trusted_issuers)
        return any(link["enabled"] and link["user_id"] == user_id and link["issuer"] in issuers
                   for link in self.list_subject_links())

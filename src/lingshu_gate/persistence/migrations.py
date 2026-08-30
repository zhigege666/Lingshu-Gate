"""Dependency-free, transactional SQLite schema migration runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

MigrationAction = Callable[[sqlite3.Connection], None]
ConnectionFactory = Callable[[], sqlite3.Connection]


@dataclass(frozen=True)
class Migration:
    """One ordered, immutable database migration."""

    id: str
    apply: MigrationAction


class MigrationRunner:
    """Apply missing migrations under one SQLite write transaction."""

    def __init__(
        self,
        connect: ConnectionFactory,
        migrations: Sequence[Migration],
    ) -> None:
        self._connect = connect
        self._migrations = tuple(migrations)
        migration_ids = [migration.id for migration in self._migrations]
        if any(not migration_id.strip() for migration_id in migration_ids):
            raise ValueError("migration id must not be empty")
        if len(migration_ids) != len(set(migration_ids)):
            raise ValueError("migration ids must be unique")

    def run(self) -> tuple[str, ...]:
        connection = self._connect()
        applied_now: list[str] = []
        try:
            # BEGIN IMMEDIATE serializes competing initializers before either can
            # inspect schema_migrations, avoiding check-then-apply races.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                str(row[0])
                for row in connection.execute("SELECT id FROM schema_migrations")
            }
            for migration in self._migrations:
                if migration.id in applied:
                    continue
                migration.apply(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                    (migration.id, datetime.now(timezone.utc).isoformat()),
                )
                applied_now.append(migration.id)
            connection.commit()
            return tuple(applied_now)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script statement-by-statement inside the caller transaction.

    sqlite3.Connection.executescript commits an active transaction implicitly,
    which would make a partially failed migration durable. This parser relies on
    sqlite3.complete_statement and keeps every statement in the runner's explicit
    transaction instead.
    """

    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if not sqlite3.complete_statement(statement):
            continue
        sql = statement.strip()
        statement = ""
        if sql:
            connection.execute(sql)
    if statement.strip():
        raise ValueError("incomplete SQL statement in migration script")

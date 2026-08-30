"""SQLite migration runner regression tests."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from lingshu_gate.database import (
    BASELINE_MIGRATION_ID,
    SQLiteDatabase,
    _enable_wal_mode,
    _resolve_sqlite_path,
)
from lingshu_gate.persistence.migrations import Migration, MigrationRunner


class _FlakyWalConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        failures: int,
        *,
        error_code: int = sqlite3.SQLITE_BUSY,
    ) -> None:
        self.connection = connection
        self.remaining_failures = failures
        self.error_code = error_code
        self.wal_attempts = 0

    def execute(self, sql: str) -> sqlite3.Cursor:
        if sql.strip().lower() == "pragma journal_mode=wal":
            self.wal_attempts += 1
            if self.remaining_failures:
                self.remaining_failures -= 1
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = self.error_code
                raise error
        return self.connection.execute(sql)


class DatabaseMigrationTest(unittest.TestCase):
    def test_database_path_rejects_non_sqlite_and_ambiguous_urls(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            for value in (
                "https://user:secret@example.invalid/gate",
                "sqlite://relative.db",
                "sqlite:///",
                "sqlite:////tmp/gate.db?token=secret",
            ):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _resolve_sqlite_path(value, root)

    def test_fresh_database_records_baseline_once(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            database = SQLiteDatabase("", root)
            database.initialize()

            rows = database.query_all(
                "SELECT id FROM schema_migrations WHERE id = ?",
                (BASELINE_MIGRATION_ID,),
            )
            self.assertEqual([str(row["id"]) for row in rows], [BASELINE_MIGRATION_ID])

    def test_fresh_database_materializes_the_complete_gate_schema(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            database = SQLiteDatabase("", root)

            user_columns = {
                str(row["name"])
                for row in database.query_all("PRAGMA table_info(users)")
            }
            token_columns = {
                str(row["name"])
                for row in database.query_all("PRAGMA table_info(api_tokens)")
            }

            self.assertEqual(
                user_columns,
                {
                    "id",
                    "username",
                    "password_hash",
                    "display_name",
                    "status",
                    "must_change_password",
                    "created_at",
                    "updated_at",
                },
            )
            self.assertIn("token_prefix", token_columns)
            self.assertIn("last_used_at", token_columns)

    def test_failed_migration_rolls_back_schema_and_marker(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            path = Path(temp_dir) / "failure.db"

            def connect() -> sqlite3.Connection:
                connection = sqlite3.connect(path)
                connection.row_factory = sqlite3.Row
                return connection

            def fail_after_ddl(connection: sqlite3.Connection) -> None:
                connection.execute("CREATE TABLE should_rollback (id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO table_that_does_not_exist VALUES (1)")

            with self.assertRaises(sqlite3.OperationalError):
                MigrationRunner(connect, (Migration("broken", fail_after_ddl),)).run()

            with sqlite3.connect(path) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertNotIn("should_rollback", tables)
            self.assertNotIn("schema_migrations", tables)

    def test_concurrent_initializers_apply_one_baseline(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            errors: list[BaseException] = []
            roots: list[Path] = []
            for round_index in range(5):
                root = Path(temp_dir) / f"round-{round_index}"
                roots.append(root)
                start = threading.Barrier(9)

                def initialize() -> None:
                    try:
                        start.wait()
                        SQLiteDatabase("", root)
                    except BaseException as exc:  # pragma: no cover - asserted below
                        errors.append(exc)

                threads = [threading.Thread(target=initialize) for _ in range(8)]
                for thread in threads:
                    thread.start()
                start.wait()
                for thread in threads:
                    thread.join(timeout=10)

                self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            for root in roots:
                database = SQLiteDatabase("", root)
                count = database.query_one(
                    "SELECT COUNT(*) AS total FROM schema_migrations WHERE id = ?",
                    (BASELINE_MIGRATION_ID,),
                )
                self.assertEqual(int(count["total"]), 1)  # type: ignore[index]

    def test_wal_bootstrap_retries_transient_sqlite_busy(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            flaky = _FlakyWalConnection(connection, failures=2)
            with patch("lingshu_gate.database.time.sleep") as sleep:
                _enable_wal_mode(flaky, max_wait_seconds=1)  # type: ignore[arg-type]

        self.assertEqual(flaky.wal_attempts, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_wal_bootstrap_does_not_retry_known_non_lock_error(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            flaky = _FlakyWalConnection(
                connection,
                failures=1,
                error_code=sqlite3.SQLITE_READONLY,
            )
            with (
                patch("lingshu_gate.database.time.sleep") as sleep,
                self.assertRaisesRegex(sqlite3.OperationalError, "locked"),
            ):
                _enable_wal_mode(flaky, max_wait_seconds=1)  # type: ignore[arg-type]

        self.assertEqual(flaky.wal_attempts, 1)
        sleep.assert_not_called()

    def test_failed_connection_bootstrap_closes_sqlite_handle(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            path = Path(temp_dir) / "closed.db"
            raw_connection = sqlite3.connect(path)
            database = object.__new__(SQLiteDatabase)
            database.path = path

            with (
                patch(
                    "lingshu_gate.database.sqlite3.connect",
                    return_value=raw_connection,
                ),
                patch(
                    "lingshu_gate.database._enable_wal_mode",
                    side_effect=sqlite3.OperationalError("disk I/O error"),
                ),
                self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"),
            ):
                database.connect()

            with self.assertRaises(sqlite3.ProgrammingError):
                raw_connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()

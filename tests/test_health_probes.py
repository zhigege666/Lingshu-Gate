"""Health, readiness, and startup probe tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate.database import BASELINE_MIGRATION_ID


class HealthProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        # A literal percent escape must stay part of the directory name in SQLite's file URI.
        self.db_path = self.root / "db %23" / "gate.db"
        self.environment = patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": str(self.root / "data"),
                "LINGSHU_GATE_DB_URL": f"sqlite:///{self.db_path}",
                "LINGSHU_GATE_RETENTION_WORKER_ENABLED": "false",
                "LINGSHU_GATE_CONFIG_DIR": str(self.root / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": str(self.root),
                "LINGSHU_GATE_AUTH_ENABLED": "true",
                "LINGSHU_GATE_ADMIN_USERNAME": "probe-admin",
                "LINGSHU_GATE_ADMIN_PASSWORD": "ProbeAdmin123!",
            },
        )
        self.environment.start()

        from lingshu_gate.main import create_app

        self.app = create_app()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def test_startup_probe_is_503_before_lifespan_and_ready_after_startup(self) -> None:
        endpoint = next(
            route.endpoint
            for route in self.app.routes
            if getattr(route, "path", None) == "/startupz"
        )
        before = endpoint()
        self.assertEqual(before.status_code, 503)

        with TestClient(self.app) as client:
            removed = client.get("/health")
            removed_livez = client.get("/livez")
            health = client.get("/healthz")
            startup = client.get("/startupz")
            ready = client.get("/readyz")
            metadata = client.get("/").json()

        self.assertEqual(removed.status_code, 404)
        self.assertEqual(removed_livez.status_code, 404)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(
            metadata["probes"],
            {
                "healthz": "/healthz",
                "readyz": "/readyz",
                "startupz": "/startupz",
            },
        )
        self.assertNotIn("health", metadata)
        self.assertEqual(startup.status_code, 200)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ok")
        self.assertEqual(
            set(ready.json()["checks"]),
            {"startup", "database", "configuration", "runtime"},
        )

    def test_missing_configuration_is_ready_without_initialization_or_public_paths(self) -> None:
        config_dir = self.root / "mcp.d"
        self.assertFalse(config_dir.exists())
        with TestClient(self.app) as client:
            ready = client.get("/readyz")
        self.assertEqual(ready.status_code, 200)
        self.assertFalse(config_dir.exists())
        checks = ready.json()["checks"]
        self.assertEqual(checks["configuration"]["metadata"]["reason_code"], "directory_creatable")
        self.assertEqual(checks["runtime"]["metadata"]["scan_status"], "missing")
        self.assertEqual(checks["runtime"]["metadata"]["server_count"], 0)
        self.assertIn("skipped", checks["runtime"]["detail"])
        for sensitive in (str(self.root), "effective_uid", "effective_gid", "owner_uid", "owner_gid"):
            self.assertNotIn(sensitive, ready.text)

    def test_existing_empty_directory_is_reported_as_a_completed_scan(self) -> None:
        (self.root / "mcp.d").mkdir()
        with TestClient(self.app) as client:
            ready = client.get("/readyz")
        self.assertEqual(ready.status_code, 200)
        checks = ready.json()["checks"]
        self.assertEqual(checks["configuration"]["metadata"]["reason_code"], "directory_ready")
        self.assertEqual(checks["runtime"]["metadata"]["scan_status"], "loaded")
        self.assertEqual(checks["runtime"]["metadata"]["server_count"], 0)

    def test_readiness_does_not_rescan_after_directory_is_created(self) -> None:
        with TestClient(self.app) as client:
            before = client.get("/readyz")
            (self.root / "mcp.d").mkdir()
            after = client.get("/readyz")
        self.assertEqual(before.status_code, 200)
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json()["checks"]["configuration"]["metadata"]["reason_code"], "directory_ready")
        self.assertEqual(after.json()["checks"]["runtime"]["metadata"]["scan_status"], "missing")

    def test_readiness_does_not_recreate_a_missing_database(self) -> None:
        directory = self.db_path.parent
        original = self.root / "original-store"
        with TestClient(self.app) as client:
            self.assertEqual(client.get("/readyz").status_code, 200)
            # Move the isolated store and its WAL sidecars together; the mount remains writable.
            directory.rename(original)
            directory.mkdir()
            try:
                for _ in range(2):
                    response = client.get("/readyz")
                    self.assertEqual(response.status_code, 503)
                    check = response.json()["checks"]["database"]
                    self.assertFalse(check["ok"])
                    self.assertEqual(check["detail"], "component probe failed")
                    self.assertEqual(check["metadata"], {"error_type": "OperationalError"})
                    self.assertNotIn(str(self.root), response.text)
                    self.assertFalse(self.db_path.exists())
            finally:
                directory.rename(self.root / "probed-store")
                original.rename(directory)
            self.assertEqual(client.get("/readyz").status_code, 200)

    def test_readiness_preserves_existing_journal_mode(self) -> None:
        with TestClient(self.app) as client:
            with closing(sqlite3.connect(self.db_path)) as setup:
                self.assertEqual(setup.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
            self.assertEqual(client.get("/readyz").status_code, 200)
            with closing(sqlite3.connect(self.db_path)) as observer:
                self.assertEqual(observer.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_readiness_sees_a_committed_change_in_the_active_wal(self) -> None:
        with TestClient(self.app) as client, closing(sqlite3.connect(self.db_path)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            deleted = writer.execute("DELETE FROM schema_migrations WHERE id = ?", (BASELINE_MIGRATION_ID,))
            self.assertEqual(deleted.rowcount, 1)
            writer.commit()
            response = client.get("/readyz")
            self.assertEqual(response.status_code, 503)
            check = response.json()["checks"]["database"]
            self.assertFalse(check["ok"])
            self.assertEqual(check["detail"], "SQLite baseline migration is missing")
            self.assertEqual(check["metadata"], {"backend": "sqlite"})

    def test_runtime_manifest_load_errors_make_readiness_fail(self) -> None:
        with TestClient(self.app) as client:
            self.app.state.mcp_runtime.load_errors = ["invalid.yaml: broken manifest"]
            response = client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["checks"]["runtime"]["ok"])
        self.assertEqual(
            response.json()["checks"]["runtime"]["metadata"]["load_error_count"],
            1,
        )
        self.assertNotIn(
            "broken manifest",
            response.text,
        )


if __name__ == "__main__":
    unittest.main()

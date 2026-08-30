"""Health, readiness, and startup probe tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class HealthProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": str(self.root / "data"),
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

    def test_readiness_reports_database_failure_as_503(self) -> None:
        with TestClient(self.app) as client, patch.object(
            self.app.state.database,
            "query_one",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        payload = json.loads(response.text)
        self.assertFalse(payload["checks"]["database"]["ok"])
        self.assertEqual(
            payload["checks"]["database"]["detail"],
            "component probe failed",
        )
        self.assertEqual(
            payload["checks"]["database"]["metadata"]["error_type"],
            "RuntimeError",
        )

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

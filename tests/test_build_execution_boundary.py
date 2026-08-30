"""Core role integration tests for the build/deploy execution boundary."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext


NOW = "2026-08-29T00:00:00+00:00"


class CoreBuildExecutionBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.temp.name)
        self.environment = patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": str(self.data_dir),
                "LINGSHU_GATE_CONFIG_DIR": str(self.data_dir / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": str(self.data_dir),
                "LINGSHU_GATE_AUTH_ENABLED": "false",
                "LINGSHU_GATE_RUNTIME_ROLE": "core",
            },
        )
        self.environment.start()

        from lingshu_gate.main import create_app

        self.app = create_app()
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.store = self.app.state.build_deploy_store
        self.service = self.app.state.project_delivery_service

        self.upload_id = "upload-core-boundary-001"
        self.source_sha256 = "a" * 64
        self.project_root = self.data_dir / "uploads" / self.upload_id / "extracted"
        self.project_root.mkdir(parents=True)
        (self.project_root / "package.json").write_text(
            json.dumps({"name": "core-boundary", "scripts": {"start": "node index.js"}}),
            encoding="utf-8",
        )
        (self.project_root / "index.js").write_text("export {};\n", encoding="utf-8")
        self.app.state.database.execute(
            """
            INSERT INTO project_uploads (
                id, filename, status, root_dir, detected_runtime,
                analysis_json, created_at, updated_at
            ) VALUES (?, ?, 'analyzed', ?, 'node', ?, ?, ?)
            """,
            (
                self.upload_id,
                "core-boundary.zip",
                str(self.project_root),
                json.dumps({"source_sha256": self.source_sha256}),
                NOW,
                NOW,
            ),
        )
        self.context = ToolInvocationContext(
            actor_id="core-boundary-operator",
            username="operator",
            auth_type="session",
            token_id=None,
            correlation_id="core-boundary-correlation",
            roles=("admin",),
        )

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.environment.stop()
        self.temp.cleanup()

    def test_rest_and_mcp_share_fail_closed_core_store(self) -> None:
        self.assertEqual(self.store.runtime_role, "core")
        self.assertIs(self.service.builds, self.store)

        with (
            patch.object(self.store.executor, "submit") as submit,
            patch("lingshu_gate.build_deploy._run_command") as run_command,
            patch("lingshu_gate.build_preflight.subprocess.run") as preflight_process,
        ):
            response = self.client.post(
                "/v1/builds",
                json={
                    "upload_id": self.upload_id,
                    "run_install": False,
                    "run_build": False,
                },
            )
            plan = self.service.build_plan(
                {
                    "upload_id": self.upload_id,
                    "run_install": False,
                    "run_build": False,
                    "refresh": True,
                },
                self.context,
            )
            with self.assertRaises(ToolExecutionError) as captured:
                self.service.build_create(
                    {
                        "upload_id": self.upload_id,
                        "run_install": False,
                        "run_build": False,
                        "source_sha256": plan["source_sha256"],
                        "plan_fingerprint": plan["plan_fingerprint"],
                        "idempotency_key": "core-build-boundary-001",
                        "confirmed": True,
                    },
                    self.context,
                )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "runtime_role_execution_blocked",
        )
        self.assertEqual(captured.exception.code, "runtime_role_execution_blocked")
        submit.assert_not_called()
        run_command.assert_not_called()
        preflight_process.assert_not_called()
        self.assertIsNone(
            self.app.state.database.query_one("SELECT id FROM builds LIMIT 1")
        )

    def test_rest_deploy_and_rollback_block_before_resource_lookup(self) -> None:
        deploy = self.client.post("/v1/builds/missing-build/deploy", json={})
        rollback = self.client.post(
            "/v1/deployments/missing-deployment/rollback",
            json={},
        )

        self.assertEqual(deploy.status_code, 409, deploy.text)
        self.assertEqual(rollback.status_code, 409, rollback.text)
        self.assertEqual(
            deploy.json()["detail"]["code"],
            "runtime_role_execution_blocked",
        )
        self.assertEqual(
            rollback.json()["detail"]["code"],
            "runtime_role_execution_blocked",
        )
        self.assertIsNone(
            self.app.state.database.query_one("SELECT id FROM deployments LIMIT 1")
        )


if __name__ == "__main__":
    unittest.main()

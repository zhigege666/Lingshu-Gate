"""项目上传、构建和部署历史安全删除集成测试。"""

from __future__ import annotations

import gc
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


NOW = "2026-07-17T00:00:00+00:00"


class BuildDeleteRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": str(self.data_dir),
                "LINGSHU_GATE_CONFIG_DIR": str(self.data_dir / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": str(self.data_dir),
                "LINGSHU_GATE_AUTH_ENABLED": "false",
            },
        )
        self.env.start()
        from lingshu_gate.main import create_app

        self.app = create_app()
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.database = self.app.state.database

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.env.stop()
        gc.collect()
        self.temp.cleanup()

    def _add_upload(self, upload_id: str) -> Path:
        # 使用嵌套项目根，覆盖旧实现 root_dir.parent 无法清理完整上传目录的问题。
        upload_dir = self.data_dir / "uploads" / upload_id
        project_root = upload_dir / "extracted" / "workspace" / "project"
        project_root.mkdir(parents=True)
        self.database.execute(
            "INSERT INTO project_uploads (id, filename, status, root_dir, detected_runtime, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (upload_id, f"{upload_id}.zip", "analyzed", str(project_root), "node", NOW, NOW),
        )
        self.database.execute(
            "INSERT INTO preflight_cache (cache_key, upload_id, fingerprint_json, result_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"cache-{upload_id}", upload_id, "{}", "{}", NOW, NOW),
        )
        return upload_dir

    def _add_build(self, upload_id: str, build_id: str, status: str = "success") -> Path:
        build_dir = self.data_dir / "builds" / build_id
        source_dir = build_dir / "source"
        artifact_dir = build_dir / "artifact"
        source_dir.mkdir(parents=True)
        artifact_dir.mkdir()
        self.database.execute(
            "INSERT INTO builds (id, upload_id, status, runtime, source_dir, artifact_dir, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (build_id, upload_id, status, "node", str(source_dir), str(artifact_dir), NOW, NOW),
        )
        return build_dir

    def _add_deployment(self, build_id: str, deployment_id: str, status: str = "success", server_id: str = "demo") -> None:
        self.database.execute(
            "INSERT INTO deployments (id, build_id, server_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (deployment_id, build_id, server_id, status, NOW, NOW),
        )

    def test_upload_conflict_then_build_and_upload_cleanup(self) -> None:
        upload_dir = self._add_upload("upload-cleanup")
        build_dir = self._add_build("upload-cleanup", "build-cleanup")
        self.database.execute(
            "INSERT INTO build_logs (id, build_id, sequence, phase, message, started_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("log-cleanup", "build-cleanup", 1, "build", "done", NOW, NOW),
        )

        conflict = self.client.delete("/v1/projects/uploads/upload-cleanup")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "project_upload_has_builds")

        deleted_build = self.client.delete("/v1/builds/build-cleanup")
        self.assertEqual(deleted_build.status_code, 200, deleted_build.text)
        self.assertEqual(deleted_build.json()["deleted_log_count"], 1)
        self.assertFalse(build_dir.exists())
        self.assertIsNone(self.database.query_one("SELECT id FROM build_logs WHERE build_id = ?", ("build-cleanup",)))

        deleted_upload = self.client.delete("/v1/projects/uploads/upload-cleanup")
        self.assertEqual(deleted_upload.status_code, 200, deleted_upload.text)
        self.assertFalse(upload_dir.exists())
        self.assertIsNone(self.database.query_one("SELECT cache_key FROM preflight_cache WHERE upload_id = ?", ("upload-cleanup",)))

    def test_active_build_cannot_be_deleted(self) -> None:
        self._add_upload("upload-active")
        self._add_build("upload-active", "build-active", status="running")
        response = self.client.delete("/v1/builds/build-active")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "build_active")

    def test_deployment_history_must_be_deleted_before_build(self) -> None:
        self._add_upload("upload-deployed")
        self._add_build("upload-deployed", "build-deployed")
        self._add_deployment("build-deployed", "deployment-history")

        conflict = self.client.delete("/v1/builds/build-deployed")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "build_has_deployments")

        deleted = self.client.delete("/v1/deployments/deployment-history")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(deleted.json()["runtime_unchanged"])
        self.assertEqual(deleted.json()["message"], "deployment_history_deleted")

    def test_build_referenced_by_config_cannot_be_deleted(self) -> None:
        self._add_upload("upload-config")
        build_dir = self._add_build("upload-config", "build-config")
        self.app.state.mcp_config_store.save_config(
            {
                "id": "config-server",
                "enabled": True,
                "launch": {"type": "managed_process", "command": "node", "args": ["index.js"], "cwd": str(build_dir / "artifact")},
                "transport": {"type": "stdio"},
                "analysis": {"build_id": "build-config"},
            }
        )
        response = self.client.delete("/v1/builds/build-config")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "build_in_use")
        self.assertEqual(response.json()["detail"]["dependencies"]["server_ids"], ["config-server"])

    def test_running_deployment_history_cannot_be_deleted(self) -> None:
        self._add_upload("upload-deploying")
        self._add_build("upload-deploying", "build-deploying")
        self._add_deployment("build-deploying", "deployment-running", status="running")
        response = self.client.delete("/v1/deployments/deployment-running")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "deployment_active")


if __name__ == "__main__":
    unittest.main()

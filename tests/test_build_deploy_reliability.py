"""构建来源持久化与部署补偿状态的轻量可靠性测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from lingshu_gate.build_deploy import (
    BuildDeployStore,
    DeploymentRollbackError,
    LocalExecutionBlocked,
)
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_runtime import McpTargetApplyError


NOW = "2026-08-12T00:00:00+00:00"


class SimulatedProcessCrash(BaseException):
    """模拟常规 Exception 边界无法捕获的进程中断。"""


class FakeManifest:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = dict(value)

    def safe_dict(self) -> dict[str, Any]:
        data = json.loads(json.dumps(self.value))
        launch = data.get("launch")
        if isinstance(launch, dict):
            for field in ("env", "environment"):
                values = launch.get(field)
                if isinstance(values, dict) and values:
                    launch[field] = {key: "***" for key in values}
        transport = data.get("transport")
        if isinstance(transport, dict) and isinstance(transport.get("headers"), dict):
            transport["headers"] = {key: "***" for key in transport["headers"]}
        return data

    def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.value)


class FakeUploads:
    def __init__(self, upload: dict[str, Any]) -> None:
        self.upload = upload

    def get_upload(self, upload_id: str) -> dict[str, Any]:
        if upload_id != self.upload["id"]:
            raise KeyError(upload_id)
        return dict(self.upload)


class FakeConfigs:
    def __init__(self) -> None:
        self.manifests: dict[str, FakeManifest] = {}
        self.fail_save = False
        self.fail_delete = False
        self.crash_delete = False

    def load_manifest(self, server_id: str) -> FakeManifest:
        if server_id not in self.manifests:
            raise KeyError(server_id)
        return self.manifests[server_id]

    def save_config(
        self,
        manifest: dict[str, Any],
        *,
        expected_id: str | None = None,
        overwrite: bool = False,
    ) -> SimpleNamespace:
        del expected_id, overwrite
        if self.fail_save:
            raise RuntimeError("injected config save failure")
        server_id = str(manifest["id"])
        self.manifests[server_id] = FakeManifest(manifest)
        return SimpleNamespace(path=f"/fake/{server_id}.yaml")

    def delete_config(self, server_id: str) -> None:
        if self.crash_delete:
            raise SimulatedProcessCrash("injected process crash")
        if self.fail_delete:
            raise RuntimeError("injected config rollback failure")
        self.manifests.pop(server_id, None)


class FakeRuntime:
    def __init__(self, *, error: str | Exception | None = None, status: str = "running") -> None:
        self.error = error
        self.status = status
        self.manifests: dict[str, Any] = {}
        self.desired_states: dict[str, str] = {}
        self.apply_calls: list[dict[str, Any]] = []
        self.remove_calls: list[str] = []

    def seed(self, manifest: Any, *, desired_state: str) -> None:
        server_id = str(manifest.model_dump()["id"])
        self.manifests[server_id] = manifest
        self.desired_states[server_id] = desired_state

    def iter_manifests(self) -> dict[str, Any]:
        return dict(self.manifests)

    def get_server(self, server_id: str) -> SimpleNamespace:
        if server_id not in self.manifests:
            raise KeyError(server_id)
        desired_state = self.desired_states[server_id]
        status = "running" if desired_state == "running" else "stopped"
        return SimpleNamespace(status=status, desired_state=desired_state)

    def apply_manifest(
        self,
        _manifest: Any,
        *,
        start: bool,
        source: str,
    ) -> SimpleNamespace:
        if self.error:
            if isinstance(self.error, Exception):
                raise self.error
            raise RuntimeError(self.error)
        manifest = _manifest.model_dump(mode="json", exclude={"manifest_path"})
        server_id = str(manifest["id"])
        response_status = self.status if start else "stopped"
        self.manifests[server_id] = _manifest
        self.desired_states[server_id] = "running" if start else "stopped"
        self.apply_calls.append(
            {"server_id": server_id, "manifest": manifest, "start": start, "source": source}
        )
        return SimpleNamespace(
            status=response_status,
            desired_state=self.desired_states[server_id],
            model_dump=lambda **_kwargs: {
                "id": server_id,
                "status": response_status,
                "desired_state": self.desired_states[server_id],
            },
        )

    def remove_manifest(self, server_id: str) -> None:
        self.manifests.pop(server_id, None)
        self.desired_states.pop(server_id, None)
        self.remove_calls.append(server_id)


class FakeObservability:
    def emit_event(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def add_log(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class CapturingExecutor:
    """只捕获 worker 提交瞬间的数据库状态，不执行任何构建命令。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.snapshots: list[dict[str, Any]] = []

    def submit(self, _function: Any, build_id: str, *_args: Any) -> SimpleNamespace:
        row = self.database.query_one("SELECT * FROM builds WHERE id = ?", (build_id,))
        if row is None:
            raise AssertionError("worker 提交前必须已存在 build 记录")
        owner = self.database.query_one(
            """
            SELECT owner_id FROM project_delivery_resource_owners
            WHERE resource_type = 'build' AND resource_id = ?
            """,
            (build_id,),
        )
        snapshot = dict(row)
        snapshot["_owner_id"] = None if owner is None else owner["owner_id"]
        self.snapshots.append(snapshot)
        return SimpleNamespace()

    def shutdown(self, **_kwargs: Any) -> None:
        return None


class BuildDeployReliabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.temp.name)
        self.database = SQLiteDatabase("", self.data_dir)
        self.project_root = self.data_dir / "project"
        self.project_root.mkdir()
        self.upload = {
            "id": "upload-reliability",
            "filename": "reliability.zip",
            "root_dir": str(self.project_root),
            "detected_runtime": "node",
            "analysis": {},
        }
        self.configs = FakeConfigs()
        self.runtime = FakeRuntime()
        self.store = BuildDeployStore(
            self.database,
            self.data_dir,
            FakeUploads(self.upload),
            self.configs,
            self.runtime,
            FakeObservability(),
        )

    def tearDown(self) -> None:
        self.store.executor.shutdown(wait=False, cancel_futures=True)
        self.temp.cleanup()

    def _replace_store(self, runtime_role: str) -> None:
        self.store.executor.shutdown(wait=False, cancel_futures=True)
        self.store = BuildDeployStore(
            self.database,
            self.data_dir,
            FakeUploads(self.upload),
            self.configs,
            self.runtime,
            FakeObservability(),
            runtime_role=runtime_role,
        )

    def _add_success_build(
        self,
        build_id: str = "build-deploy-reliability",
        *,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        build_dir = self.data_dir / "builds" / build_id
        source_dir = build_dir / "source"
        artifact_dir = build_dir / "artifact"
        source_dir.mkdir(parents=True)
        artifact_dir.mkdir()
        manifest = manifest or {
            "id": "reliability-server",
            "enabled": True,
            "launch": {"type": "managed_process", "command": "node"},
            "transport": {"type": "stdio"},
        }
        self.database.execute(
            """
            INSERT INTO builds (
                id, upload_id, status, runtime, source_dir, artifact_dir,
                manifest_json, created_at, updated_at
            ) VALUES (?, ?, 'success', 'node', ?, ?, ?, ?, ?)
            """,
            (
                build_id,
                self.upload["id"],
                str(source_dir),
                str(artifact_dir),
                json.dumps(manifest),
                NOW,
                NOW,
            ),
        )

    @staticmethod
    def _manifest_with_secret(secret: str) -> dict[str, Any]:
        return {
            "id": "reliability-server",
            "enabled": True,
            "launch": {
                "type": "managed_process",
                "command": "node",
                "env": {"API_TOKEN": secret},
            },
            "transport": {"type": "stdio"},
        }

    def _seed_existing_server(self, secret: str, *, desired_state: str) -> FakeManifest:
        manifest = FakeManifest(self._manifest_with_secret(secret))
        self.configs.manifests["reliability-server"] = manifest
        self.runtime.seed(manifest, desired_state=desired_state)
        return manifest

    def _inject_database_execute_failure(self, predicate: Any) -> dict[str, bool]:
        original_execute = self.database.execute
        state = {"triggered": False}

        def execute(sql: str, parameters: tuple[Any, ...] = ()) -> None:
            if not state["triggered"] and predicate(sql, parameters):
                state["triggered"] = True
                raise RuntimeError("injected deployment persistence failure")
            original_execute(sql, parameters)

        self.database.execute = execute  # type: ignore[method-assign]
        return state

    def test_build_provenance_is_persisted_before_worker_submit(self) -> None:
        self.store.executor.shutdown(wait=False, cancel_futures=True)
        executor = CapturingExecutor(self.database)
        self.store.executor = executor  # type: ignore[assignment]
        preflight = {
            "status": "ok",
            "runtime": "node",
            "project_root_dir": str(self.project_root),
            "metadata": {"package_scripts": []},
        }
        result = self.store.build_upload(
            self.upload["id"],
            run_install=False,
            run_build=False,
            prepared_preflight=preflight,
            source_sha256="a" * 64,
            plan_fingerprint="b" * 64,
            operation_id="operation-provenance-001",
            owner_id="actor-provenance-001",
        )

        self.assertEqual(len(executor.snapshots), 1)
        snapshot = executor.snapshots[0]
        self.assertEqual(snapshot["status"], "queued")
        self.assertEqual(snapshot["source_sha256"], "a" * 64)
        self.assertEqual(snapshot["plan_fingerprint"], "b" * 64)
        self.assertEqual(snapshot["operation_id"], "operation-provenance-001")
        self.assertEqual(snapshot["_owner_id"], "actor-provenance-001")
        self.assertEqual(result["operation_id"], "operation-provenance-001")

    def test_core_role_blocks_build_before_preflight_record_or_worker_submit(self) -> None:
        self._replace_store("core")
        with (
            patch.object(self.store.executor, "submit") as submit,
            patch("lingshu_gate.build_deploy.run_build_preflight") as preflight,
            patch("lingshu_gate.build_deploy._run_command") as run_command,
            self.assertRaises(LocalExecutionBlocked) as captured,
        ):
            self.store.build_upload(self.upload["id"])

        self.assertEqual(captured.exception.code, "runtime_role_execution_blocked")
        self.assertEqual(captured.exception.operation, "build")
        self.assertEqual(captured.exception.runtime_role, "core")
        preflight.assert_not_called()
        submit.assert_not_called()
        run_command.assert_not_called()
        self.assertIsNone(self.database.query_one("SELECT id FROM builds LIMIT 1"))

    def test_core_role_preflight_keeps_analysis_without_spawning_processes(self) -> None:
        self._replace_store("core")
        (self.project_root / "package.json").write_text(
            json.dumps({"name": "core-analysis", "scripts": {"start": "node index.js"}}),
            encoding="utf-8",
        )
        (self.project_root / "index.js").write_text("export {};\n", encoding="utf-8")

        with patch("lingshu_gate.build_preflight.subprocess.run") as run:
            result = self.store.preflight_upload(self.upload["id"], refresh=True)

        run.assert_not_called()
        self.assertEqual(result["runtime"], "node")
        self.assertIn(result["status"], {"ok", "warning"})

    def test_core_role_blocks_deploy_and_rollback_before_config_side_effects(self) -> None:
        self._add_success_build()
        self._replace_store("core")
        with (
            patch.object(self.configs, "save_config") as save_config,
            patch.object(self.runtime, "apply_manifest") as apply_manifest,
        ):
            with self.assertRaises(LocalExecutionBlocked) as deploy_blocked:
                self.store.deploy_build("build-deploy-reliability")
            with self.assertRaises(LocalExecutionBlocked) as rollback_blocked:
                self.store.rollback_deployment("missing-deployment")

        self.assertEqual(deploy_blocked.exception.operation, "deploy")
        self.assertEqual(
            rollback_blocked.exception.operation,
            "deployment_rollback",
        )
        save_config.assert_not_called()
        apply_manifest.assert_not_called()
        self.assertIsNone(
            self.database.query_one("SELECT id FROM deployments LIMIT 1")
        )

    def test_runtime_failure_persists_successful_config_rollback(self) -> None:
        self._add_success_build()
        self.store.runtime = FakeRuntime(error="injected runtime failure")

        deployment = self.store.deploy_build(
            "build-deploy-reliability",
            start=True,
            overwrite=False,
        )

        self.assertEqual(deployment["status"], "failed")
        self.assertTrue(deployment["config_applied"])
        self.assertFalse(deployment["runtime_started"])
        self.assertTrue(deployment["rollback_attempted"])
        self.assertTrue(deployment["rollback_succeeded"])
        self.assertIsNone(deployment["rollback_error"])
        self.assertNotIn("reliability-server", self.configs.manifests)

    def test_runtime_internal_rollback_failure_marks_overall_compensation_failed(self) -> None:
        self._add_success_build()
        self.store.runtime = FakeRuntime(
            error=McpTargetApplyError(
                "reliability-server",
                "startup failed; target rollback failed: restore target runtime",
                status="failed",
            )
        )

        deployment = self.store.deploy_build(
            "build-deploy-reliability",
            start=True,
            overwrite=False,
        )

        self.assertTrue(deployment["rollback_attempted"])
        self.assertFalse(deployment["rollback_succeeded"])
        self.assertIn("runtime compensation failed", deployment["rollback_error"])

    def test_rollback_failure_is_distinct_from_unknown_rollback(self) -> None:
        self._add_success_build()
        self.store.runtime = FakeRuntime(error="injected runtime failure")
        self.configs.fail_delete = True

        deployment = self.store.deploy_build(
            "build-deploy-reliability",
            start=True,
            overwrite=False,
        )

        self.assertTrue(deployment["rollback_attempted"])
        self.assertFalse(deployment["rollback_succeeded"])
        self.assertEqual(
            deployment["rollback_error"],
            "config compensation failed: injected config rollback failure",
        )

        self.configs.fail_delete = False
        self.configs.fail_save = True
        self._add_success_build("build-config-failure")
        deployment_without_rollback = self.store.deploy_build(
            "build-config-failure",
            server_id="other-reliability-server",
            start=False,
            overwrite=False,
        )
        self.assertFalse(deployment_without_rollback["config_applied"])
        self.assertFalse(deployment_without_rollback["rollback_attempted"])
        self.assertIsNone(deployment_without_rollback["rollback_succeeded"])
        self.assertIsNone(deployment_without_rollback["rollback_error"])

    def test_interrupted_rollback_remains_persisted_as_unknown(self) -> None:
        self._add_success_build()
        self.store.runtime = FakeRuntime(error="injected runtime failure")
        self.configs.crash_delete = True

        with self.assertRaises(SimulatedProcessCrash):
            self.store.deploy_build(
                "build-deploy-reliability",
                start=True,
                overwrite=False,
            )

        row = self.database.query_one(
            "SELECT id FROM deployments ORDER BY created_at DESC LIMIT 1"
        )
        self.assertIsNotNone(row)
        deployment = self.store.get_deployment(str(row["id"]))
        self.assertTrue(deployment["config_applied"])
        self.assertFalse(deployment["runtime_started"])
        self.assertTrue(deployment["rollback_attempted"])
        self.assertIsNone(deployment["rollback_succeeded"])
        self.assertIsNone(deployment["rollback_error"])

    def test_post_runtime_persistence_failure_restores_config_runtime_and_intent(self) -> None:
        old_manifest = self._seed_existing_server("old-secret", desired_state="running")
        self._add_success_build(
            manifest=self._manifest_with_secret("new-secret"),
        )
        failure = self._inject_database_execute_failure(
            lambda sql, parameters: (
                "SET status = ?" in sql
                and bool(parameters)
                and parameters[0] == "success"
            )
        )

        deployment = self.store.deploy_build(
            "build-deploy-reliability",
            start=True,
            overwrite=True,
        )

        self.assertTrue(failure["triggered"])
        self.assertEqual(deployment["status"], "failed")
        self.assertTrue(deployment["config_applied"])
        self.assertTrue(deployment["runtime_started"])
        self.assertTrue(deployment["rollback_attempted"])
        self.assertTrue(deployment["rollback_succeeded"])
        self.assertEqual(
            self.configs.manifests["reliability-server"].model_dump()["launch"]["env"]["API_TOKEN"],
            "old-secret",
        )
        self.assertIs(self.runtime.manifests["reliability-server"], old_manifest)
        self.assertEqual(self.runtime.desired_states["reliability-server"], "running")
        self.assertEqual(self.runtime.apply_calls[-1]["source"], "deploy_compensation")
        self.assertEqual(
            self.runtime.apply_calls[-1]["manifest"]["launch"]["env"]["API_TOKEN"],
            "old-secret",
        )

    def test_manual_rollback_restores_old_secret_from_encrypted_snapshot(self) -> None:
        self._seed_existing_server("old-secret", desired_state="stopped")
        self._add_success_build(
            manifest=self._manifest_with_secret("new-secret"),
        )

        deployment = self.store.deploy_build(
            "build-deploy-reliability",
            start=False,
            overwrite=True,
        )
        self.assertEqual(deployment["status"], "success")
        self.assertEqual(
            deployment["previous_manifest"]["launch"]["env"]["API_TOKEN"],
            "***",
        )
        self.assertEqual(
            self.configs.manifests["reliability-server"].model_dump()["launch"]["env"]["API_TOKEN"],
            "new-secret",
        )

        result = self.store.rollback_deployment(deployment["id"], start=False)

        self.assertEqual(result["message"], "rolled_back")
        self.assertEqual(
            self.configs.manifests["reliability-server"].model_dump()["launch"]["env"]["API_TOKEN"],
            "old-secret",
        )
        self.assertEqual(
            self.runtime.apply_calls[-1]["manifest"]["launch"]["env"]["API_TOKEN"],
            "old-secret",
        )
        snapshot_path = self.data_dir / "deployment-rollback-snapshots" / "credentials.json"
        self.assertTrue(snapshot_path.exists())
        self.assertNotIn("old-secret", snapshot_path.read_text(encoding="utf-8"))

        self.store.delete_deployment(deployment["id"])
        with self.assertRaises(KeyError):
            self.store.rollback_snapshots.resolve_value(
                self.store._rollback_snapshot_id(deployment["id"])
            )

    def test_masked_snapshot_without_secure_record_rejects_manual_rollback(self) -> None:
        self._add_success_build()
        deployment_id = "masked-deployment"
        safe_previous = self._manifest_with_secret("***")
        self.database.execute(
            """
            INSERT INTO deployments (
                id, build_id, server_id, status, manifest_json,
                previous_manifest_json, started, created_at, updated_at
            ) VALUES (?, ?, ?, 'success', ?, ?, 0, ?, ?)
            """,
            (
                deployment_id,
                "build-deploy-reliability",
                "reliability-server",
                json.dumps(self._manifest_with_secret("new-secret")),
                json.dumps(safe_previous),
                NOW,
                NOW,
            ),
        )

        with self.assertRaises(DeploymentRollbackError) as captured:
            self.store.rollback_deployment(deployment_id, start=False)

        self.assertEqual(captured.exception.code, "rollback_snapshot_unavailable")
        self.assertNotIn("reliability-server", self.configs.manifests)
        self.assertEqual(self.runtime.apply_calls, [])

    def test_deployment_owner_is_persisted_before_config_side_effect(self) -> None:
        self._add_success_build()
        self.configs.fail_save = True

        deployment = self.store.deploy_build(
            "build-deploy-reliability",
            start=False,
            overwrite=False,
            owner_id="actor-deployment-001",
        )

        owner = self.database.query_one(
            """
            SELECT owner_id FROM project_delivery_resource_owners
            WHERE resource_type = 'deployment' AND resource_id = ?
            """,
            (deployment["id"],),
        )
        self.assertIsNotNone(owner)
        self.assertEqual(owner["owner_id"], "actor-deployment-001")
        self.assertEqual(deployment["status"], "failed")


if __name__ == "__main__":
    unittest.main()

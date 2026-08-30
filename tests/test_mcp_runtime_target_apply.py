"""目标粒度 MCP Manifest 应用的隔离和补偿测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import (
    McpManifestDigestConflict,
    McpRuntimeManager,
    McpServerState,
    McpTargetApplyError,
)
from lingshu_gate.models import ToolDefinition
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.registry import ToolRegistry


class _FakeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.stop_count = 0
        self.pid = None
        self.listed_tools: list[dict[str, object]] = []

    def stop(self) -> None:
        self.stop_count += 1

    def list_tools(self) -> list[dict[str, object]]:
        return self.listed_tools


class McpRuntimeTargetApplyTest(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            config_dir=root / "mcp.d",
            data_dir=root / "data",
            allowed_root=root,
            db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
        )

    @staticmethod
    def _manifest(server_id: str, command_marker: str) -> McpServerManifest:
        return McpServerManifest.model_validate(
            {
                "id": server_id,
                "enabled": True,
                "launch": {
                    "type": "managed_process",
                    "command": "node",
                    "args": [command_marker],
                },
                "transport": {"type": "stdio"},
                "auto_start": False,
            }
        )

    def _manager(self, root: Path) -> McpRuntimeManager:
        settings = self._settings(root)
        database = SQLiteDatabase(settings.db_url, settings.data_dir)
        return McpRuntimeManager(
            settings,
            ToolRegistry(),
            state_store=McpRuntimeStateStore(database),
        )

    def _install_running(self, manager: McpRuntimeManager, server_id: str, marker: str) -> _FakeClient:
        intent = manager.state_store.set(server_id, "running", source="test")
        runtime = manager._new_runtime(self._manifest(server_id, marker), intent)
        runtime.state = McpServerState.RUNNING
        client = _FakeClient(marker)
        runtime.client = client  # type: ignore[assignment]
        runtime.tools = [{"name": f"{server_id}_tool"}]
        manager._servers[server_id] = runtime
        return client

    @staticmethod
    def _fake_start(manager: McpRuntimeManager, server_id: str, **_: object):
        runtime = manager._servers[server_id]
        marker = runtime.manifest.launch.args[0]
        if marker == "fail-new-a":
            runtime.state = McpServerState.FAILED
            runtime.last_error = "simulated start failure"
            return runtime.to_response()
        runtime.state = McpServerState.RUNNING
        runtime.client = _FakeClient(marker)  # type: ignore[assignment]
        runtime.tools = [{"name": f"{server_id}_tool"}]
        return runtime.to_response()

    def test_apply_a_does_not_stop_or_replace_b(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            old_a_client = self._install_running(manager, "a", "old-a")
            b_client = self._install_running(manager, "b", "old-b")
            b_runtime = manager._servers["b"]

            with patch.object(
                manager,
                "start_server",
                side_effect=lambda server_id, **kwargs: self._fake_start(
                    manager,
                    server_id,
                    **kwargs,
                ),
            ):
                response = manager.apply_manifest(
                    self._manifest("a", "new-a"),
                    start=True,
                    source="test_apply",
                )

            self.assertEqual(response.status, "running")
            self.assertEqual(old_a_client.stop_count, 1)
            self.assertIs(manager._servers["b"], b_runtime)
            self.assertIs(manager._servers["b"].client, b_client)
            self.assertEqual(b_client.stop_count, 0)
            self.assertEqual(manager.get_server("b").status, "running")

    def test_failed_apply_restores_old_a_without_touching_b(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            self._install_running(manager, "a", "old-a")
            b_client = self._install_running(manager, "b", "old-b")
            b_runtime = manager._servers["b"]

            with patch.object(
                manager,
                "start_server",
                side_effect=lambda server_id, **kwargs: self._fake_start(
                    manager,
                    server_id,
                    **kwargs,
                ),
            ):
                with self.assertRaises(McpTargetApplyError):
                    manager.apply_manifest(
                        self._manifest("a", "fail-new-a"),
                        start=True,
                        source="test_apply",
                    )

            restored_a = manager._servers["a"]
            self.assertEqual(restored_a.manifest.launch.args, ["old-a"])
            self.assertEqual(restored_a.state, McpServerState.RUNNING)
            self.assertEqual(restored_a.desired_intent.desired_state, "running")
            self.assertIs(manager._servers["b"], b_runtime)
            self.assertIs(manager._servers["b"].client, b_client)
            self.assertEqual(b_client.stop_count, 0)

    def test_stop_failure_enters_target_rollback_without_touching_b(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            self._install_running(manager, "a", "old-a")
            b_client = self._install_running(manager, "b", "old-b")
            b_runtime = manager._servers["b"]
            original_stop = manager._stop_runtime_locked
            stop_attempts = 0

            def fail_first_target_stop(
                server_id: str,
                runtime: object,
                *,
                clear_error: bool,
            ) -> None:
                nonlocal stop_attempts
                if server_id == "a" and stop_attempts == 0:
                    stop_attempts += 1
                    raise RuntimeError("simulated stop failure")
                original_stop(server_id, runtime, clear_error=clear_error)  # type: ignore[arg-type]

            with (
                patch.object(
                    manager,
                    "_stop_runtime_locked",
                    side_effect=fail_first_target_stop,
                ),
                patch.object(
                    manager,
                    "start_server",
                    side_effect=lambda server_id, **kwargs: self._fake_start(
                        manager,
                        server_id,
                        **kwargs,
                    ),
                ),
            ):
                with self.assertRaisesRegex(McpTargetApplyError, "simulated stop failure"):
                    manager.apply_manifest(
                        self._manifest("a", "new-a"),
                        start=True,
                        source="test_stop_failure",
                    )

            self.assertEqual(manager._servers["a"].manifest.launch.args, ["old-a"])
            self.assertEqual(manager._servers["a"].state, McpServerState.RUNNING)
            self.assertIs(manager._servers["b"], b_runtime)
            self.assertIs(manager._servers["b"].client, b_client)
            self.assertEqual(b_client.stop_count, 0)

    def test_intent_write_failure_restores_old_a_without_touching_b(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            self._install_running(manager, "a", "old-a")
            b_client = self._install_running(manager, "b", "old-b")
            b_runtime = manager._servers["b"]
            original_set = manager.state_store.set

            def fail_candidate_intent(
                server_id: str,
                desired_state: str,
                *,
                source: str,
                reason: str | None = None,
            ):
                if source == "test_intent_failure":
                    raise RuntimeError("simulated intent write failure")
                return original_set(
                    server_id,
                    desired_state,  # type: ignore[arg-type]
                    source=source,
                    reason=reason,
                )

            with (
                patch.object(
                    manager.state_store,
                    "set",
                    side_effect=fail_candidate_intent,
                ),
                patch.object(
                    manager,
                    "start_server",
                    side_effect=lambda server_id, **kwargs: self._fake_start(
                        manager,
                        server_id,
                        **kwargs,
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    McpTargetApplyError,
                    "simulated intent write failure",
                ):
                    manager.apply_manifest(
                        self._manifest("a", "new-a"),
                        start=True,
                        source="test_intent_failure",
                    )

            self.assertEqual(manager._servers["a"].manifest.launch.args, ["old-a"])
            self.assertEqual(manager._servers["a"].state, McpServerState.RUNNING)
            self.assertEqual(manager.state_store.get("a").desired_state, "running")  # type: ignore[union-attr]
            self.assertIs(manager._servers["b"], b_runtime)
            self.assertIs(manager._servers["b"].client, b_client)
            self.assertEqual(b_client.stop_count, 0)

    def test_runtime_registration_failure_restores_old_a_without_touching_b(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            self._install_running(manager, "a", "old-a")
            b_client = self._install_running(manager, "b", "old-b")
            b_runtime = manager._servers["b"]
            original_new_runtime = manager._new_runtime

            def fail_candidate_registration(manifest, intent):  # noqa: ANN001 - 测试替身
                if manifest.launch.args == ["new-a"]:
                    raise RuntimeError("simulated runtime registration failure")
                return original_new_runtime(manifest, intent)

            with (
                patch.object(
                    manager,
                    "_new_runtime",
                    side_effect=fail_candidate_registration,
                ),
                patch.object(
                    manager,
                    "start_server",
                    side_effect=lambda server_id, **kwargs: self._fake_start(
                        manager,
                        server_id,
                        **kwargs,
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    McpTargetApplyError,
                    "simulated runtime registration failure",
                ):
                    manager.apply_manifest(
                        self._manifest("a", "new-a"),
                        start=True,
                        source="test_registration_failure",
                    )

            self.assertEqual(manager._servers["a"].manifest.launch.args, ["old-a"])
            self.assertEqual(manager._servers["a"].state, McpServerState.RUNNING)
            self.assertIs(manager._servers["b"], b_runtime)
            self.assertIs(manager._servers["b"].client, b_client)
            self.assertEqual(b_client.stop_count, 0)

    def test_remove_a_does_not_touch_b(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            a_client = self._install_running(manager, "a", "old-a")
            b_client = self._install_running(manager, "b", "old-b")
            b_runtime = manager._servers["b"]

            removed = manager.remove_manifest("a")

            self.assertIsNotNone(removed)
            self.assertFalse(manager.has_server("a"))
            self.assertIsNone(manager.state_store.get("a"))
            self.assertEqual(a_client.stop_count, 1)
            self.assertIs(manager._servers["b"], b_runtime)
            self.assertIs(manager._servers["b"].client, b_client)
            self.assertEqual(b_client.stop_count, 0)

    def test_removing_delivery_server_only_unregisters_dynamic_mcp_tools(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            self._install_running(manager, "gate-delivery", "delivery")
            manager.registry.register(
                ToolDefinition(
                    id="gate_server_status",
                    name="Gate server status",
                    description="Builtin delivery control tool",
                    source="builtin",
                    metadata={"server_id": "gate-delivery"},
                ),
                lambda _: {"status": "ok"},
            )
            manager.registry.register(
                ToolDefinition(
                    id="mcp.gate-delivery.dynamic_tool",
                    name="Dynamic tool",
                    description="Dynamically discovered MCP tool",
                    source="mcp",
                    metadata={"server_id": "gate-delivery"},
                ),
                lambda _: {"status": "ok"},
            )

            manager.remove_manifest("gate-delivery")

            self.assertEqual(
                manager.registry.get_definition("gate_server_status").source,
                "builtin",
            )
            with self.assertRaises(KeyError):
                manager.registry.get_definition("mcp.gate-delivery.dynamic_tool")

    def test_start_with_digest_checks_runtime_manifest_before_start(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            self._install_running(manager, "a", "runtime-a")
            expected_digest = manager.get_manifest_digest("a")

            with patch.object(manager, "start_server", wraps=manager.start_server) as start:
                response = manager.request_start_if_manifest_digest("a", expected_digest)

            self.assertEqual(response.status, "running")
            self.assertEqual(start.call_count, 1)

            with patch.object(manager, "start_server") as start:
                with self.assertRaises(McpManifestDigestConflict) as conflict:
                    manager.request_start_if_manifest_digest("a", "f" * 64)

            self.assertEqual(conflict.exception.actual_digest, expected_digest)
            start.assert_not_called()

    def test_refresh_tools_atomically_keeps_previous_snapshot_when_discovery_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            client = self._install_running(manager, "a", "runtime-a")
            runtime = manager._servers["a"]
            manager._register_mcp_tools(runtime)
            old_tool_id = "mcp.a.a_tool"
            self.assertEqual(manager.registry.get_definition(old_tool_id).source, "mcp")

            client.listed_tools = [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "inputSchema": {"type": "object"},
                    "annotations": {"readOnlyHint": True},
                }
            ]
            with self.assertRaisesRegex(RuntimeError, "classification gate failed"):
                manager.refresh_server_tools(
                    "a",
                    before_replace=lambda _: (_ for _ in ()).throw(
                        RuntimeError("classification gate failed")
                    ),
                )
            self.assertEqual(manager.registry.get_definition(old_tool_id).source, "mcp")
            with self.assertRaises(KeyError):
                manager.registry.get_definition("mcp.a.read_file")

            refreshed = manager.refresh_server_tools("a")
            self.assertEqual(refreshed["tool_count"], 1)
            self.assertEqual(
                manager.registry.get_definition("mcp.a.read_file").name,
                "read_file",
            )
            with self.assertRaises(KeyError):
                manager.registry.get_definition(old_tool_id)

            client.listed_tools = [
                {"name": "duplicate", "inputSchema": {"type": "object"}},
                {"name": "duplicate", "inputSchema": {"type": "object"}},
            ]
            with self.assertRaisesRegex(ValueError, "duplicate tool name"):
                manager.refresh_server_tools("a")

            self.assertEqual(
                manager.registry.get_definition("mcp.a.read_file").name,
                "read_file",
            )
            with self.assertRaises(KeyError):
                manager.registry.get_definition("mcp.a.duplicate")


if __name__ == "__main__":
    unittest.main()

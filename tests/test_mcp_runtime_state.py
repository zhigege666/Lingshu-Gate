"""MCP 期望运行状态的持久化与恢复测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.registry import ToolRegistry


class McpRuntimeStateTest(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            config_dir=root / "mcp.d",
            data_dir=root / "data",
            allowed_root=root,
            db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
        )

    def _write_manifest(self, settings: Settings, *, auto_start: bool) -> None:
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        (settings.config_dir / "demo.yaml").write_text(
            "\n".join([
                "id: demo",
                "enabled: true",
                "launch:",
                "  type: managed_process",
                "  command: node",
                "transport:",
                "  type: stdio",
                f"auto_start: {'true' if auto_start else 'false'}",
            ]),
            encoding="utf-8",
        )

    def _manager(self, settings: Settings) -> McpRuntimeManager:
        database = SQLiteDatabase(settings.db_url, settings.data_dir)
        return McpRuntimeManager(settings, ToolRegistry(), state_store=McpRuntimeStateStore(database))

    def test_manual_start_is_restored_by_new_runtime_manager(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            settings = self._settings(Path(temp_dir))
            self._write_manifest(settings, auto_start=False)
            manager = self._manager(settings)
            manager.load_manifests()
            with patch.object(manager, "start_server", side_effect=lambda server_id, **_: manager.get_server(server_id)):
                manager.request_start("demo")

            restored = self._manager(settings)
            restored.load_manifests()
            self.assertEqual(restored.get_server("demo").desired_state, "running")
            with patch.object(restored, "start_server", side_effect=lambda server_id, **_: restored.get_server(server_id)) as start:
                restored.reconcile_desired_states()
            start.assert_called_once_with("demo")

    def test_manual_stop_overrides_manifest_auto_start(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            settings = self._settings(Path(temp_dir))
            self._write_manifest(settings, auto_start=True)
            manager = self._manager(settings)
            manager.load_manifests()
            with patch.object(manager, "stop_server", side_effect=lambda server_id: manager.get_server(server_id)):
                manager.request_stop("demo")

            restored = self._manager(settings)
            restored.load_manifests()
            self.assertEqual(restored.get_server("demo").desired_state, "stopped")
            with patch.object(restored, "start_server") as start:
                restored.reconcile_desired_states()
            start.assert_not_called()

    def test_no_override_uses_manifest_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            settings = self._settings(Path(temp_dir))
            self._write_manifest(settings, auto_start=True)
            manager = self._manager(settings)
            manager.load_manifests()
            server = manager.get_server("demo")
            self.assertEqual(server.desired_state, "running")
            self.assertEqual(server.desired_state_source, "manifest_default")


if __name__ == "__main__":
    unittest.main()

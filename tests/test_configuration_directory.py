"""Configuration directory policy and last-scan reporting regressions."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lingshu_gate.adapters.control_plane import FileConfigurationSourceAdapter, McpRuntimeDriverAdapter
from lingshu_gate.config import Settings
from lingshu_gate.diagnostics import run_diagnostics
from lingshu_gate.mcp_config_loader import McpConfigLoader
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import McpServerListResponse
from lingshu_gate.registry import ToolRegistry


class _EmptyRuntime:
    def list_servers(self) -> McpServerListResponse:
        return McpServerListResponse(servers=[], load_errors=[])

    def iter_manifests(self) -> dict[str, object]:
        return {}


class ConfigurationDirectoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_dir = self.root / "config" / "mcp.d"
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        self.settings = Settings(
            config_dir=self.config_dir,
            data_dir=self.data_dir,
            db_url=f"sqlite:///{self.data_dir / 'gate.db'}",
            allowed_root=self.root,
            runtime_role="core",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_configuration_policy(self, expected_ok: bool, reason_code: str) -> None:
        readiness = FileConfigurationSourceAdapter(self.config_dir).readiness()
        diagnostics = run_diagnostics(
            self.settings, ToolRegistry(), _EmptyRuntime(),  # type: ignore[arg-type]
        )
        check = next(item for item in diagnostics.checks if item.name == "path.config_dir")
        self.assertEqual(readiness.ok, expected_ok)
        self.assertEqual(check.ok, expected_ok)
        self.assertEqual(diagnostics.ok, expected_ok)
        self.assertEqual(check.severity, "info" if expected_ok else "error")
        self.assertEqual(readiness.metadata["reason_code"], reason_code)
        self.assertEqual(check.metadata["reason_code"], reason_code)
        self.assertNotIn(str(self.root), readiness.detail)
        self.assertEqual(set(readiness.metadata), {"source", "reason_code"})
        self.assertEqual(check.metadata["path"], str(self.config_dir))

    def test_missing_creatable_and_existing_empty_configuration_are_usable(self) -> None:
        self.assert_configuration_policy(True, "directory_creatable")
        self.assertFalse(self.config_dir.exists())
        missing = McpConfigLoader(self.config_dir).load()
        self.assertEqual(missing.scan_status, "missing")
        self.assertEqual(missing.errors, [])
        self.assertFalse(self.config_dir.exists())

        self.config_dir.mkdir(parents=True)
        self.assert_configuration_policy(True, "directory_ready")
        empty = McpConfigLoader(self.config_dir).load()
        self.assertEqual(empty.scan_status, "loaded")
        self.assertEqual(empty.manifests, [])
        self.assertEqual(empty.errors, [])

    def test_configuration_path_file_is_rejected_consistently(self) -> None:
        self.config_dir.parent.mkdir()
        self.config_dir.write_text("not a directory", encoding="utf-8")
        self.assert_configuration_policy(False, "path_not_directory")
        result = McpConfigLoader(self.config_dir).load()
        self.assertEqual(result.scan_status, "failed")
        self.assertEqual(len(result.errors), 1)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0,
                         "requires actual non-root POSIX directory permissions")
    def test_directory_permission_failures_agree_without_requiring_scan_write_access(self) -> None:
        self.config_dir.mkdir(parents=True)
        cases = (
            (0o500, "directory_not_writable", "loaded"),
            (0o300, "directory_not_readable", "failed"),
            (0o600, "directory_not_searchable", "failed"),
        )
        for mode, reason_code, scan_status in cases:
            with self.subTest(mode=oct(mode)):
                try:
                    self.config_dir.chmod(mode)
                    self.assert_configuration_policy(False, reason_code)
                    self.assertEqual(McpConfigLoader(self.config_dir).load().scan_status, scan_status)
                finally:
                    self.config_dir.chmod(0o700)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0,
                         "requires actual non-root POSIX directory permissions")
    def test_missing_configuration_requires_a_creatable_parent(self) -> None:
        self.config_dir.parent.mkdir()
        try:
            self.config_dir.parent.chmod(0o500)
            self.assert_configuration_policy(False, "directory_not_writable")
            result = McpConfigLoader(self.config_dir).load()
            self.assertEqual(result.scan_status, "failed")
            self.assertFalse(self.config_dir.exists())
        finally:
            self.config_dir.parent.chmod(0o700)

    def test_directory_enumeration_race_becomes_a_bounded_scan_error(self) -> None:
        self.config_dir.mkdir(parents=True)
        with patch.object(Path, "iterdir", side_effect=PermissionError("sensitive failure payload")):
            result = McpConfigLoader(self.config_dir).load()
        self.assertEqual(result.scan_status, "failed")
        self.assertEqual(result.manifests, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("PermissionError", result.errors[0])
        self.assertNotIn("sensitive failure payload", result.errors[0])

    def test_runtime_snapshot_tracks_full_scans_not_directory_changes(self) -> None:
        runtime = McpRuntimeManager(self.settings, ToolRegistry())
        adapter = McpRuntimeDriverAdapter(runtime)
        initial = adapter.readiness()
        self.assertFalse(initial.ok)
        self.assertEqual(initial.metadata["scan_status"], "not_scanned")

        runtime.load_manifests()
        missing = adapter.readiness()
        self.assertTrue(missing.ok)
        self.assertEqual(missing.metadata["scan_status"], "missing")
        self.assertIn("skipped", missing.detail)

        self.config_dir.mkdir(parents=True)
        self.assertEqual(adapter.readiness().metadata["scan_status"], "missing")
        runtime.load_manifests()
        loaded = adapter.readiness()
        self.assertTrue(loaded.ok)
        self.assertEqual(loaded.metadata, {"scan_status": "loaded", "server_count": 0, "load_error_count": 0})

        (self.config_dir / "invalid.json").write_text("{", encoding="utf-8")
        runtime.load_manifests()
        failed = adapter.readiness()
        self.assertFalse(failed.ok)
        self.assertEqual(failed.metadata["scan_status"], "failed")
        self.assertEqual(failed.metadata["load_error_count"], 1)
        self.assertNotIn(str(self.root), failed.detail)
        self.assertNotIn("invalid.json", failed.detail)


if __name__ == "__main__":
    unittest.main()

"""Focused tests for runtime diagnostics."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from lingshu_gate.config import Settings
from lingshu_gate.diagnostics import _find_python_interpreter, run_diagnostics
from lingshu_gate.models import McpServerListResponse, ToolDefinition
from lingshu_gate.registry import ToolRegistry


class _Runtime:
    def __init__(self, manifests: dict[str, object] | None = None) -> None:
        self._manifests = manifests or {}

    def list_servers(self) -> McpServerListResponse:
        return McpServerListResponse(servers=[], load_errors=[])

    def iter_manifests(self) -> dict[str, object]:
        return self._manifests


class DiagnosticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        self.config_dir = root / "config"
        self.data_dir = root / "data"
        for path in (self.workspace, self.config_dir, self.data_dir):
            path.mkdir()

        self.registry = ToolRegistry()
        self.registry.register(
            ToolDefinition(
                id="mcp.test.status",
                name="Status",
                description="Return test status.",
                source="mcp",
            ),
            lambda _: {"ok": True},
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _settings(self, runtime_role: str) -> Settings:
        return Settings(
            allowed_root=self.workspace,
            config_dir=self.config_dir,
            data_dir=self.data_dir,
            runtime_role=runtime_role,
        )

    def test_frozen_binary_uses_path_python_instead_of_sys_executable(self) -> None:
        interpreter = Path(self.temp_dir.name) / "python3"
        interpreter.touch()

        def resolve(command: str) -> str | None:
            return str(interpreter) if command == "python3" else None

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/opt/lingshu-gate/lingshu-gate"),
            patch("lingshu_gate.diagnostics.shutil.which", side_effect=resolve),
            patch("lingshu_gate.diagnostics._read_version", return_value="Python 3.12.4") as read_version,
        ):
            result = run_diagnostics(
                self._settings("local"),
                self.registry,
                _Runtime(),  # type: ignore[arg-type]
            )

        python_check = next(check for check in result.checks if check.name == "executable.python")
        self.assertEqual(python_check.metadata["resolved"], str(interpreter))
        self.assertNotEqual(python_check.metadata["resolved"], "/opt/lingshu-gate/lingshu-gate")
        read_version.assert_called_once_with(str(interpreter), ["--version"])

    def test_frozen_binary_does_not_fall_back_to_sys_executable(self) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/opt/lingshu-gate/lingshu-gate"),
            patch("lingshu_gate.diagnostics.shutil.which", return_value=None) as which,
        ):
            self.assertIsNone(_find_python_interpreter())

        self.assertEqual(which.call_args_list, [call("python3"), call("python")])

    def test_core_runtime_skips_local_project_toolchain_checks(self) -> None:
        with patch(
            "lingshu_gate.diagnostics.shutil.which",
            side_effect=AssertionError("Core diagnostics must not probe local build tools"),
        ):
            result = run_diagnostics(
                self._settings("core"),
                self.registry,
                _Runtime(),  # type: ignore[arg-type]
            )

        self.assertTrue(result.ok)
        self.assertFalse(any(check.name.startswith("executable.") for check in result.checks))

    def test_missing_local_toolchains_are_capability_warnings(self) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch("lingshu_gate.diagnostics.shutil.which", return_value=None),
        ):
            result = run_diagnostics(
                self._settings("local"),
                self.registry,
                _Runtime(),  # type: ignore[arg-type]
            )

        toolchain_checks = {
            check.name: check
            for check in result.checks
            if check.name in {"executable.python", "executable.node", "executable.npm", "executable.npx"}
        }
        self.assertEqual(len(toolchain_checks), 4)
        self.assertTrue(result.ok)
        self.assertTrue(all(not check.ok for check in toolchain_checks.values()))
        self.assertTrue(all(check.severity == "warning" for check in toolchain_checks.values()))
        self.assertTrue(all(check.metadata["required"] is False for check in toolchain_checks.values()))

    def test_streamable_http_and_tool_summary_match_current_runtime(self) -> None:
        manifest = SimpleNamespace(
            launch=SimpleNamespace(type="external", command=None, package=None),
            transport=SimpleNamespace(type="streamable_http", endpoint="http://127.0.0.1:3100/mcp"),
        )
        result = run_diagnostics(
            self._settings("core"),
            self.registry,
            _Runtime({"example": manifest}),  # type: ignore[arg-type]
        )

        endpoint_check = next(
            check for check in result.checks if check.name == "mcp_server.example.streamable_http_endpoint"
        )
        registered_check = next(check for check in result.checks if check.name == "registered_tools")
        self.assertTrue(endpoint_check.ok)
        self.assertEqual(endpoint_check.severity, "info")
        self.assertIs(endpoint_check.metadata["implemented"], True)
        self.assertEqual(registered_check.metadata, {"total": 1, "mcp": 1})
        self.assertNotIn("builtin_tool_count", result.summary)


if __name__ == "__main__":
    unittest.main()

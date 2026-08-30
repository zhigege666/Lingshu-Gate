"""Startup smoke tests for Lingshu Gate."""

import os
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate import __version__
from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.build_deploy_routes import register_build_deploy_routes
from lingshu_gate.build_preflight import run_build_preflight
from lingshu_gate.config import Settings
from lingshu_gate.models import DiagnosticsCheck, DiagnosticsResponse
from lingshu_gate.project_delivery_mcp import (
    PROJECT_DELIVERY_TOOL_DEFINITIONS,
    ProjectDeliveryMcpService,
    register_project_delivery_tools,
)
from lingshu_gate.system_debug import SystemDebugService
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.tool_classification_mcp import (
    CLASSIFICATION_TOOL_DEFINITIONS,
    ToolClassificationMcpService,
    register_tool_classification_tools,
)


class StartupSmokeTest(unittest.TestCase):
    def test_auth_is_enabled_by_default(self) -> None:
        self.assertTrue(Settings().auth_enabled)
        with patch.dict(os.environ, {"LINGSHU_GATE_AUTH_ENABLED": "false"}):
            self.assertFalse(Settings.from_env().auth_enabled)

    def test_console_entry_disables_cache_and_hashed_assets_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": temp_dir,
                "LINGSHU_GATE_CONFIG_DIR": temp_dir,
                "LINGSHU_GATE_ALLOWED_ROOT": temp_dir,
                "LINGSHU_GATE_AUTH_ENABLED": "false",
            },
        ):
            from lingshu_gate.main import create_app

            with TestClient(create_app()) as client:
                console = client.get("/console")
                console_slash = client.get("/console/")
                script_match = re.search(r'src="([^"]+\.js)"', console.text)

                self.assertEqual(console.status_code, 200)
                self.assertEqual(console_slash.status_code, 200)
                self.assertIn("no-store", console.headers["cache-control"])
                self.assertIn("no-store", console_slash.headers["cache-control"])
                self.assertIsNotNone(script_match)

                asset = client.get(script_match.group(1))  # type: ignore[union-attr]
                self.assertEqual(asset.status_code, 200)
                self.assertIn("immutable", asset.headers["cache-control"])

    def test_startup_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": temp_dir,
                "LINGSHU_GATE_CONFIG_DIR": temp_dir,
                "LINGSHU_GATE_ALLOWED_ROOT": temp_dir,
            },
        ):
            # main 模块在导入时会创建默认应用，测试必须显式隔离数据目录。
            from lingshu_gate.main import create_app

            self.assertTrue(callable(create_app))

        self.assertRegex(__version__, r"^\d+\.\d+\.\d+(?:[-+].+)?$")
        self.assertTrue(callable(BuildDeployStore))
        self.assertTrue(callable(register_build_deploy_routes))
        self.assertTrue(callable(run_build_preflight))
        self.assertEqual(len(PROJECT_DELIVERY_TOOL_DEFINITIONS), 14)
        self.assertTrue(callable(ProjectDeliveryMcpService))
        self.assertTrue(callable(register_project_delivery_tools))
        self.assertEqual(len(CLASSIFICATION_TOOL_DEFINITIONS), 4)
        self.assertTrue(callable(ToolClassificationMcpService))
        self.assertTrue(callable(register_tool_classification_tools))
        self.assertTrue(callable(SystemDebugService))
        self.assertTrue(callable(register_mcp_gateway_route))
        self.assertTrue(DiagnosticsResponse(ok=True, checks=[DiagnosticsCheck(name="startup", ok=True)]).ok)


if __name__ == "__main__":
    unittest.main()

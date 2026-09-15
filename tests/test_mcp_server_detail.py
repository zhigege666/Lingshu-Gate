"""MCP Server 详情诊断提示回归测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.mcp_runtime_routes import register_mcp_runtime_routes
from lingshu_gate.mcp_server_detail import _failure_hints, build_mcp_server_detail


class McpServerDetailSectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(data_dir=Path("unused-detail-test-data"))
        self.runtime = Mock()
        self.store = Mock()
        self.runtime.get_server.return_value.model_dump.return_value = {
            "id": "demo", "status": "running", "tool_count": 3,
        }
        self.manifest = Mock()
        self.manifest.safe_dict.return_value = {"launch": {"type": "external"}}
        self.runtime.iter_manifests.return_value = {"demo": self.manifest}
        self.runtime.list_server_tools.return_value = [{"name": "read_demo"}]
        self.runtime.list_restart_history.return_value = []
        self.store.list_logs.return_value = []
        self.store.list_events.return_value = []

    def test_overview_does_not_load_logs_tools_manifest_or_scan_cache(self) -> None:
        with patch("lingshu_gate.mcp_server_detail.McpRuntimeCacheResolver") as resolver:
            detail = build_mcp_server_detail(self.settings, self.runtime, self.store, "demo", section="overview")
        self.assertEqual(set(detail), {"server"})
        self.runtime.iter_manifests.assert_not_called()
        self.runtime.list_server_tools.assert_not_called()
        self.runtime.list_restart_history.assert_not_called()
        self.store.list_logs.assert_not_called()
        self.store.list_events.assert_not_called()
        resolver.assert_not_called()

    def test_logs_section_has_a_bound_and_does_not_load_other_sections(self) -> None:
        detail = build_mcp_server_detail(self.settings, self.runtime, self.store, "demo", section="logs", limit=25)
        self.store.list_logs.assert_called_once_with(server_id="demo", limit=25)
        self.store.list_events.assert_not_called()
        self.runtime.list_server_tools.assert_not_called()
        self.runtime.iter_manifests.assert_not_called()
        self.assertEqual(set(detail), {"server", "logs", "recent_stdout", "recent_stderr", "timeline"})

    def test_tools_section_reads_only_the_existing_runtime_catalog(self) -> None:
        detail = build_mcp_server_detail(self.settings, self.runtime, self.store, "demo", section="tools")
        self.assertEqual(detail["tools"], [{"name": "read_demo"}])
        self.store.list_logs.assert_not_called()
        self.store.list_events.assert_not_called()
        self.runtime.iter_manifests.assert_not_called()

    def test_default_keeps_the_complete_detail_contract(self) -> None:
        with (
            patch("lingshu_gate.mcp_server_detail.McpRuntimeCacheResolver"),
            patch("lingshu_gate.mcp_server_detail._cache_status", return_value={"size_bytes": 0}) as cache,
        ):
            detail = build_mcp_server_detail(self.settings, self.runtime, self.store, "demo")
        self.assertEqual(set(detail), {
            "server", "manifest", "runtime_cache", "timeline", "recent_stdout", "recent_stderr",
            "logs", "events", "tools", "failure_hints", "restart_history", "recovery_chart", "recovery_summary",
        })
        self.store.list_logs.assert_called_once_with(server_id="demo", limit=80)
        self.store.list_events.assert_called_once_with(subject_id="demo", limit=80)
        cache.assert_called_once()

    def _app(self, allowed: bool = True) -> FastAPI:
        app = FastAPI()

        def require_operator() -> AuthPrincipal:
            if not allowed:
                raise HTTPException(status_code=403, detail="insufficient role")
            return AuthPrincipal(id="test-operator", username="operator", role="operator")

        register_mcp_runtime_routes(
            app, settings=self.settings, mcp_runtime=self.runtime,
            observability_store=self.store, require_operations_manager=require_operator,
        )
        return app

    def test_detail_route_validates_section_and_record_limit(self) -> None:
        with TestClient(self._app()) as client:
            response = client.get("/v1/mcp/servers/demo/detail?section=overview&limit=40")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()), {"server"})
            for query in ("section=unknown", "limit=0", "limit=201"):
                self.assertEqual(client.get("/v1/mcp/servers/demo/detail?" + query).status_code, 422)

    def test_detail_sections_keep_the_operator_permission_gate(self) -> None:
        with TestClient(self._app(allowed=False)) as client:
            response = client.get("/v1/mcp/servers/demo/detail?section=overview")
        self.assertEqual(response.status_code, 403)
        self.runtime.get_server.assert_not_called()


class McpServerDetailFailureHintsTest(unittest.TestCase):
    def test_external_http_server_does_not_require_launch_command(self) -> None:
        hints = _failure_hints(
            {"status": "stopped"},
            {
                "launch": {"type": "external"},
                "transport": {"type": "streamable_http", "endpoint": "http://127.0.0.1:3120/mcp"},
            },
            {},
            [],
            [],
        )

        self.assertNotIn("missing_command", {item["code"] for item in hints})

    def test_managed_process_still_reports_missing_launch_command(self) -> None:
        hints = _failure_hints(
            {"status": "stopped"},
            {
                "launch": {"type": "managed_process"},
                "transport": {"type": "streamable_http", "endpoint": "http://127.0.0.1:3120/mcp"},
            },
            {},
            [],
            [],
        )

        self.assertIn("missing_command", {item["code"] for item in hints})


if __name__ == "__main__":
    unittest.main()

"""MCP Server 详情诊断提示回归测试。"""

from __future__ import annotations

import unittest

from lingshu_gate.mcp_server_detail import _failure_hints


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

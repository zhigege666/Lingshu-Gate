"""仪表盘调用统计的口径与时间窗口。"""

from __future__ import annotations

import tempfile
import unittest
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.database import SQLiteDatabase


class InvocationStatisticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True
        )
        self.database = SQLiteDatabase("", Path(self.temporary_directory.name))
        self.store = AccessControlStore(self.database)
        self.now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_audit(
        self,
        audit_id: str,
        tool_id: str,
        decision: str,
        outcome: str,
        created_at: datetime,
    ) -> None:
        self.database.execute(
            """
            INSERT INTO invocation_audits
                (id, correlation_id, user_id, username, auth_type, server_id,
                 tool_id, tool_access, required_access, granted_access,
                 decision, reason, outcome, payload_json, created_at)
            VALUES (?, ?, 'user', 'viewer', 'session', 'demo',
                    ?, 'read', 'read', 'read', ?, 'test', ?, '{}', ?)
            """,
            (audit_id, audit_id, tool_id, decision, outcome, created_at.isoformat()),
        )

    def test_counts_requests_executions_mcp_and_outcomes_without_truncation(self) -> None:
        start = self.now - timedelta(hours=24)
        self.add_audit("mcp-success", "mcp.demo.search", "allow", "success", start)
        self.add_audit("mcp-error", "mcp.demo.search", "allow", "error", start + timedelta(hours=2))
        self.add_audit("builtin-success", "gate_system_debug", "allow", "success", start + timedelta(hours=4))
        self.add_audit("denied", "mcp.demo.search", "deny", "not_invoked", start + timedelta(hours=6))
        self.add_audit("unbound", "gate_system_debug", "deny", "not_invoked", start + timedelta(hours=8))
        self.add_audit("older", "mcp.demo.search", "allow", "success", start - timedelta(seconds=1))
        self.add_audit("at-end", "mcp.demo.search", "allow", "success", self.now)

        result = self.store.invocation_statistics(now=self.now)

        self.assertEqual(result["totals"], {
            "requests": 5,
            "calls": 3,
            "mcp_calls": 2,
            "success": 2,
            "errors": 1,
            "not_invoked": 2,
        })
        self.assertEqual(len(result["series"]), 12)
        self.assertEqual(sum(item["requests"] for item in result["series"]), 5)
        self.assertEqual(result["series"][0]["requests"], 1)
        self.assertEqual(result["top_tools"][0], {
            "tool_id": "mcp.demo.search",
            "server_id": "demo",
            "calls": 2,
            "errors": 1,
        })
        self.assertEqual(self.store.invocation_statistics(hours=168, now=self.now)["totals"]["requests"], 6)

    def test_empty_window_has_zero_buckets(self) -> None:
        result = self.store.invocation_statistics(now=self.now)
        self.assertEqual(result["totals"]["requests"], 0)
        self.assertEqual(result["top_tools"], [])
        self.assertEqual(len(result["series"]), 12)
        self.assertTrue(all(item["calls"] == 0 for item in result["series"]))

    def test_aggregate_is_not_limited_by_audit_list_page_size(self) -> None:
        created_at = (self.now - timedelta(minutes=5)).isoformat()
        with self.database.session() as connection:
            connection.executemany(
                """
                INSERT INTO invocation_audits
                    (id, correlation_id, user_id, username, auth_type, server_id,
                     tool_id, tool_access, required_access, granted_access,
                     decision, reason, outcome, payload_json, created_at)
                VALUES (?, ?, 'user', 'viewer', 'session', 'demo',
                        'mcp.demo.search', 'read', 'read', 'read',
                        'allow', 'test', 'success', '{}', ?)
                """,
                [(f"audit-{index}", f"audit-{index}", created_at) for index in range(501)],
            )

        result = self.store.invocation_statistics(now=self.now)
        self.assertEqual(result["totals"]["requests"], 501)
        self.assertEqual(result["totals"]["mcp_calls"], 501)

    def test_statistics_route_requires_audit_read(self) -> None:
        root = Path(self.temporary_directory.name)
        with patch.dict(os.environ, {
            "LINGSHU_GATE_DATA_DIR": str(root),
            "LINGSHU_GATE_CONFIG_DIR": str(root / "mcp.d"),
            "LINGSHU_GATE_ALLOWED_ROOT": str(root),
            "LINGSHU_GATE_AUTH_ENABLED": "true",
            "LINGSHU_GATE_ADMIN_USERNAME": "",
            "LINGSHU_GATE_ADMIN_PASSWORD": "",
        }):
            from lingshu_gate.main import create_app

            with TestClient(create_app()) as client:
                auth_store = client.app.state.auth_store
                admin = auth_store.list_users()[0]
                auth_store.change_password(str(admin["id"]), "Admin123!")
                admin_login = client.post("/v1/auth/login", json={"username": "admin", "password": "Admin123!"})
                self.assertEqual(admin_login.status_code, 200)
                response = client.get("/v1/access/invocation-statistics?hours=24")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["totals"]["requests"], 0)
                self.assertEqual(client.get("/v1/access/invocation-statistics?hours=25").status_code, 422)

                auth_store.create_user(username="viewer", password="Viewer123!", role="viewer")
                client.cookies.clear()
                viewer_login = client.post("/v1/auth/login", json={"username": "viewer", "password": "Viewer123!"})
                self.assertEqual(viewer_login.status_code, 200)
                self.assertEqual(client.get("/v1/access/invocation-statistics").status_code, 403)


if __name__ == "__main__":
    unittest.main()

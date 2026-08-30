"""工具读写分类批量确认的事务、状态与权限测试。"""

from __future__ import annotations

import gc
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate.access_control import (
    AccessControlStore,
    ClassificationConfirmationConflictError,
)
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition


def _definition(
    server_id: str,
    tool_id: str,
    *,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = True,
) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id,
        description="用于批量确认测试的工具。",
        source="mcp",
        metadata={
            "server_id": server_id,
            "annotations": {
                "destructiveHint": destructive,
                "idempotentHint": idempotent,
                "openWorldHint": open_world,
            },
        },
    )


class ToolClassificationStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.settings = Settings(
            data_dir=self.root,
            db_url=f"sqlite:///{self.root / 'gate.db'}",
            auth_enabled=True,
        )
        self.database = SQLiteDatabase(self.settings.db_url, self.root)
        self.store = AccessControlStore(self.database)

    def tearDown(self) -> None:
        gc.collect()
        self.temp.cleanup()

    def test_batch_confirm_uses_each_suggestion_and_manual_value_and_skips_safely(self) -> None:
        rule_read = _definition(
            "server-a",
            "mcp.server_a.read",
            idempotent=True,
            open_world=False,
        )
        rule_write = _definition(
            "server-b",
            "mcp.server_b.write",
            destructive=True,
            open_world=True,
        )
        manual = _definition(
            "server-a",
            "mcp.server_a.manual",
            destructive=True,
            idempotent=True,
            open_world=False,
        )
        unknown = _definition("server-a", "mcp.server_a.unknown")
        published = _definition("server-b", "mcp.server_b.published")
        definitions = [rule_read, rule_write, manual, unknown, published]
        self.store.synchronize_tools(definitions)
        self.store.set_classification(
            server_id="server-a",
            tool_id=manual.id,
            access="write",
            destructive=True,
            idempotent=True,
            reviewer_id="previous-reviewer",
            note="保留的逐条人工备注",
        )
        self.store.set_classification(
            server_id="server-b",
            tool_id=published.id,
            access="read",
            destructive=False,
            idempotent=False,
            reviewer_id="previous-reviewer",
        )
        self.store.publish_classifications(
            reviewer_id="previous-reviewer",
            server_id="server-b",
            tool_ids=[published.id],
        )

        before = {
            (item["server_id"], item["tool_id"]): item
            for item in self.store.list_classifications()
            if item["tool_id"] in {definition.id for definition in definitions}
        }
        result = self.store.confirm_classifications(
            reviewer_id="batch-reviewer",
            note="批量确认",
            items=[
                {
                    "server_id": server_id,
                    "tool_id": tool_id,
                    "expected_fingerprint": item["fingerprint"],
                }
                for (server_id, tool_id), item in before.items()
            ],
        )

        self.assertEqual(result["confirmed_count"], 3)
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual(result["total_count"], 5)
        confirmed = {
            (item["server_id"], item["tool_id"]): item
            for item in result["confirmed"]
        }
        self.assertEqual(confirmed[("server-a", rule_read.id)]["effective_access"], "read")
        self.assertEqual(confirmed[("server-b", rule_write.id)]["effective_access"], "write")
        self.assertEqual(confirmed[("server-a", manual.id)]["effective_access"], "write")
        self.assertEqual(
            confirmed[("server-a", manual.id)]["evidence"]["confirmation"]["confirmed_from"],
            "effective",
        )
        self.assertEqual(
            confirmed[("server-a", rule_read.id)]["evidence"]["confirmation"]["confirmed_from"],
            "suggested",
        )
        manual_evidence = confirmed[("server-a", manual.id)]["evidence"]
        self.assertEqual(manual_evidence["manual"]["note"], "保留的逐条人工备注")
        self.assertEqual(manual_evidence["manual"]["reviewer_id"], "previous-reviewer")
        self.assertIn("rule", manual_evidence)
        for key, item in confirmed.items():
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["source"], "manual")
            self.assertEqual(item["reviewed_by"], "batch-reviewer")
            self.assertIsNone(item["reviewed_at"])
            self.assertEqual(item["destructive"], before[key]["destructive"])
            self.assertEqual(item["idempotent"], before[key]["idempotent"])
            self.assertEqual(item["open_world"], before[key]["open_world"])

        skipped = {
            (item["server_id"], item["tool_id"]): item["reason"]
            for item in result["skipped"]
        }
        self.assertEqual(skipped[("server-a", unknown.id)], "unknown")
        self.assertEqual(skipped[("server-b", published.id)], "published")
        after = {
            (item["server_id"], item["tool_id"]): item
            for item in self.store.list_classifications()
        }
        self.assertEqual(after[("server-a", unknown.id)]["effective_access"], "unknown")
        self.assertEqual(after[("server-b", published.id)]["status"], "published")

    def test_fingerprint_conflict_rolls_back_every_confirmation(self) -> None:
        first = _definition("server-a", "mcp.server_a.first")
        second = _definition("server-b", "mcp.server_b.second")
        self.store.synchronize_tools([first, second])
        before = {
            (item["server_id"], item["tool_id"]): item
            for item in self.store.list_classifications()
        }

        with self.assertRaisesRegex(
            ClassificationConfirmationConflictError,
            "fingerprint changed",
        ):
            self.store.confirm_classifications(
                reviewer_id="batch-reviewer",
                items=[
                    {
                        "server_id": "server-a",
                        "tool_id": first.id,
                        "expected_fingerprint": before[("server-a", first.id)]["fingerprint"],
                    },
                    {
                        "server_id": "server-b",
                        "tool_id": second.id,
                        "expected_fingerprint": "outdated-fingerprint",
                    },
                ],
            )

        after = {
            (item["server_id"], item["tool_id"]): item
            for item in self.store.list_classifications()
        }
        for key in (("server-a", first.id), ("server-b", second.id)):
            self.assertEqual(after[key]["effective_access"], "unknown")
            self.assertEqual(after[key]["status"], "pending")
            self.assertEqual(after[key]["source"], "rule")
            self.assertIsNone(after[key]["reviewed_by"])

    def test_pending_batch_confirmation_remains_hidden_until_publish(self) -> None:
        definition = _definition(
            "visibility-server",
            "mcp.visibility_server.search",
            idempotent=True,
            open_world=False,
        )
        self.store.synchronize_tools([definition])
        classification = self.store.list_classifications(server_id="visibility-server")[0]
        result = self.store.confirm_classifications(
            reviewer_id="batch-reviewer",
            items=[
                {
                    "server_id": "visibility-server",
                    "tool_id": definition.id,
                    "expected_fingerprint": classification["fingerprint"],
                }
            ],
        )
        self.assertEqual(result["confirmed"][0]["status"], "pending")

        auth_store = AuthStore(self.settings, self.database)
        viewer = auth_store.create_user(
            username="pending-viewer",
            password="viewer-password",
            role="viewer",
        )
        principal, _, _ = auth_store.login(
            username="pending-viewer",
            password="viewer-password",
        )
        self.store.save_grant(
            subject_type="user",
            subject_id=str(viewer["id"]),
            server_id="visibility-server",
            permission_type_code="read",
            created_by="test-admin",
        )

        self.assertEqual(self.store.visible_tools(principal, [definition]), [])
        self.assertFalse(self.store.evaluate(principal, definition)["allowed"])

        self.store.publish_classifications(
            reviewer_id="batch-reviewer",
            server_id="visibility-server",
            tool_ids=[definition.id],
        )
        self.assertEqual(
            {item.id for item in self.store.visible_tools(principal, [definition])},
            {definition.id},
        )
        self.assertTrue(self.store.evaluate(principal, definition)["allowed"])


class ToolClassificationRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": str(self.data_dir),
                "LINGSHU_GATE_CONFIG_DIR": str(self.data_dir / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": str(self.data_dir),
                "LINGSHU_GATE_AUTH_ENABLED": "true",
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
            },
        )
        self.env.start()

        from lingshu_gate.main import create_app

        self.client_context = TestClient(create_app())
        self.client = self.client_context.__enter__()
        app = self.client.app
        admin = app.state.auth_store.list_users()[0]
        app.state.auth_store.change_password(str(admin["id"]), "Admin123!")
        self.definition = _definition(
            "route-server",
            "mcp.route_server.search",
            idempotent=True,
            open_world=False,
        )
        app.state.registry.register(self.definition, lambda _: {"ok": True})
        self._login("admin", "Admin123!")
        for payload in (
            {
                "username": "classification-operator",
                "display_name": "分类运维用户",
                "password": "Operator123!",
                "roles": ["operator"],
                "status": "active",
                "must_change_password": False,
            },
            {
                "username": "classification-viewer",
                "display_name": "分类只读用户",
                "password": "Viewer123!",
                "roles": ["viewer"],
                "status": "active",
                "must_change_password": False,
            },
        ):
            response = self.client.post("/v1/access/users", json=payload)
            self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.env.stop()
        gc.collect()
        self.temp.cleanup()

    def _login(self, username: str, password: str) -> None:
        self.client.cookies.clear()
        response = self.client.post(
            "/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _classification(self) -> dict[str, object]:
        response = self.client.get(
            "/v1/access/tool-classifications",
            params={"server_id": "route-server"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return next(
            item
            for item in response.json()["classifications"]
            if item["tool_id"] == self.definition.id
        )

    def test_confirm_route_maps_conflict_keeps_pending_and_requires_permission(self) -> None:
        classification = self._classification()
        payload = {
            "items": [
                {
                    "server_id": "route-server",
                    "tool_id": self.definition.id,
                    "expected_fingerprint": "outdated-fingerprint",
                }
            ]
        }
        conflict = self.client.post(
            "/v1/access/tool-classifications/confirm",
            json=payload,
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

        payload["items"][0]["expected_fingerprint"] = classification["fingerprint"]
        confirmed = self.client.post(
            "/v1/access/tool-classifications/confirm",
            json=payload,
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        body = confirmed.json()
        self.assertEqual(body["confirmed_count"], 1)
        self.assertEqual(body["confirmed"][0]["status"], "pending")
        self.assertIsNone(body["confirmed"][0]["reviewed_at"])

        for username, password in (
            ("classification-operator", "Operator123!"),
            ("classification-viewer", "Viewer123!"),
        ):
            with self.subTest(username=username):
                self._login(username, password)
                denied = self.client.post(
                    "/v1/access/tool-classifications/confirm",
                    json=payload,
                )
                self.assertEqual(denied.status_code, 403, denied.text)

    def test_custom_role_with_classification_permission_can_confirm(self) -> None:
        role_response = self.client.post(
            "/v1/access/roles",
            json={
                "code": "classification-reviewer",
                "name": "分类审核员",
                "description": "仅负责确认工具读写分类",
                "permissions": ["console.view", "classifications.manage"],
                "enabled": True,
            },
        )
        self.assertEqual(role_response.status_code, 200, role_response.text)
        user_response = self.client.post(
            "/v1/access/users",
            json={
                "username": "custom-classification-reviewer",
                "display_name": "自定义分类审核员",
                "password": "Reviewer123!",
                "roles": ["classification-reviewer"],
                "status": "active",
                "must_change_password": False,
            },
        )
        self.assertEqual(user_response.status_code, 200, user_response.text)
        classification = self._classification()

        self._login("custom-classification-reviewer", "Reviewer123!")
        response = self.client.post(
            "/v1/access/tool-classifications/confirm",
            json={
                "items": [
                    {
                        "server_id": "route-server",
                        "tool_id": self.definition.id,
                        "expected_fingerprint": classification["fingerprint"],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["confirmed_count"], 1)
        self.assertEqual(body["confirmed"][0]["status"], "pending")
        self.assertEqual(
            body["confirmed"][0]["reviewed_by"],
            user_response.json()["id"],
        )


if __name__ == "__main__":
    unittest.main()

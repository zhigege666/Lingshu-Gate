"""MCP 工具读写分类治理闭环测试。"""

from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolInvocationContext, ToolRegistry
from lingshu_gate.tool_classification_mcp import (
    CLASSIFICATION_TOOL_DEFINITIONS,
    ToolClassificationMcpService,
    register_tool_classification_tools,
)


class ToolClassificationMcpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        settings = Settings(
            data_dir=self.root,
            db_url=f"sqlite:///{self.root / 'gate.db'}",
            auth_enabled=True,
        )
        self.database = SQLiteDatabase(settings.db_url, self.root)
        self.access_store = AccessControlStore(self.database)
        self.registry = ToolRegistry()
        self.service = ToolClassificationMcpService(self.access_store, self.registry)
        register_tool_classification_tools(self.registry, self.service)
        self.definition = ToolDefinition(
            id="mcp.sample-service.search_records",
            name="搜索记录",
            description="查询记录，不修改远端数据。",
            permission="mcp",
            source="mcp",
            input_schema={"type": "object"},
            metadata={
                "server_id": "sample-service",
                "original_tool_name": "search_records",
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": True,
                },
            },
        )
        self.registry.register(self.definition, lambda _: {"ok": True})
        self.context = ToolInvocationContext(
            actor_id="reviewer-1",
            username="reviewer",
            auth_type="session",
            token_id=None,
            correlation_id="classification-test",
            roles=("classification-reviewer",),
            permissions=("classifications.manage",),
            scopes=(),
        )

    def tearDown(self) -> None:
        gc.collect()
        self.temp.cleanup()

    def test_classification_control_tools_are_visible_before_downstream_publish(self) -> None:
        principal = AuthPrincipal(
            id="reviewer-1",
            username="reviewer",
            role="viewer",
            roles=("classification-reviewer",),
            permissions=("classifications.manage",),
        )

        visible = self.access_store.visible_tools(
            principal,
            self.registry.list_definitions(),
        )

        visible_ids = {item.id for item in visible}
        self.assertEqual(
            visible_ids & {item.id for item in CLASSIFICATION_TOOL_DEFINITIONS},
            {item.id for item in CLASSIFICATION_TOOL_DEFINITIONS},
        )
        self.assertNotIn(self.definition.id, visible_ids)
        self.assertTrue(
            self.access_store.evaluate(
                principal,
                CLASSIFICATION_TOOL_DEFINITIONS[0],
            )["allowed"]
        )

    def test_list_review_publish_closes_classification_loop(self) -> None:
        listed = self.registry.invoke(
            "gate_tool_classification_list",
            {"server_id": "sample-service", "status": "needs_review"},
            context=self.context,
        )
        self.assertTrue(listed.ok, listed.error)
        classification = listed.output["classifications"][0]
        self.assertEqual(classification["tool_id"], self.definition.id)
        self.assertEqual(listed.output["counts"]["needs_review"], 1)

        analyzed = self.registry.invoke(
            "gate_tool_classification_analyze",
            {
                "server_id": "sample-service",
                "idempotency_key": "classification-analyze-1",
                "confirmed": True,
            },
            context=self.context,
        )
        self.assertTrue(analyzed.ok, analyzed.error)

        reviewed = self.registry.invoke(
            "gate_tool_classification_review",
            {
                "items": [
                    {
                        "server_id": "sample-service",
                        "tool_id": self.definition.id,
                        "expected_fingerprint": classification["fingerprint"],
                    }
                ],
                "note": "MCP 自动分类审核",
                "idempotency_key": "classification-review-1",
                "confirmed": True,
            },
            context=self.context,
        )
        self.assertTrue(reviewed.ok, reviewed.error)
        self.assertEqual(reviewed.output["confirmed_count"], 1)
        self.assertEqual(reviewed.output["confirmed"][0]["status"], "pending")

        published = self.registry.invoke(
            "gate_tool_classification_publish",
            {
                "server_id": "sample-service",
                "idempotency_key": "classification-publish-1",
                "confirmed": True,
            },
            context=self.context,
        )
        self.assertTrue(published.ok, published.error)
        self.assertEqual(published.output["published_count"], 1)
        self.assertEqual(published.output["needs_review_count"], 0)
        self.assertEqual(published.output["classifications"][0]["status"], "published")

    def test_publish_requires_explicit_scope(self) -> None:
        response = self.registry.invoke(
            "gate_tool_classification_publish",
            {
                "idempotency_key": "classification-publish-2",
                "confirmed": True,
            },
            context=self.context,
        )
        self.assertFalse(response.ok)
        self.assertIn("发布分类必须提供", response.error or "")

    def test_missing_tools_are_hidden_and_cannot_be_reviewed_or_published(self) -> None:
        listed = self.service.list_classifications({"server_id": "sample-service"}, self.context)
        original = listed["classifications"][0]
        self.access_store.set_classification(server_id="sample-service", tool_id=self.definition.id,
            access="read", destructive=False, idempotent=True, reviewer_id=self.context.actor_id, note="Keep this history")
        self.registry.unregister_by_metadata("server_id", "sample-service", source="mcp", retire=False)
        hidden = self.service.list_classifications({"server_id": "sample-service"}, self.context)
        self.assertEqual(hidden["classifications"], [])
        analyzed = self.service.analyze_classifications({"server_id": "sample-service", "confirmed": True,
            "idempotency_key": "missing-analyze-1"}, self.context)
        self.assertEqual(analyzed["classifications"], [])
        review = self.registry.invoke("gate_tool_classification_review", {"confirmed": True,
            "idempotency_key": "missing-review-1", "items": [{"server_id": "sample-service",
            "tool_id": self.definition.id, "expected_fingerprint": original["fingerprint"]}]}, context=self.context)
        self.assertFalse(review.ok)
        explicit = self.registry.invoke("gate_tool_classification_publish", {"confirmed": True,
            "server_id": "sample-service", "tool_ids": [self.definition.id],
            "idempotency_key": "missing-publish-1"}, context=self.context)
        self.assertFalse(explicit.ok)
        scoped = self.service.publish_classifications({"server_id": "sample-service", "confirmed": True,
            "idempotency_key": "missing-server-publish-1"}, self.context)
        self.assertEqual(scoped["classifications"], [])
        self.assertEqual(scoped["published_count"], 0)
        history = self.access_store.list_classifications(server_id="sample-service")[0]
        self.assertEqual(history["status"], "pending")
        self.assertEqual(history["evidence"]["manual"]["note"], "Keep this history")

    def test_missing_classification_permission_is_rejected(self) -> None:
        response = self.registry.invoke(
            "gate_tool_classification_list",
            {},
            context=ToolInvocationContext(
                actor_id="viewer-1",
                username="viewer",
                auth_type="session",
                token_id=None,
                correlation_id="classification-denied",
                roles=("viewer",),
                permissions=("tools.read",),
                scopes=(),
            ),
        )
        self.assertFalse(response.ok)
        self.assertIn("classifications.manage", response.error or "")


if __name__ == "__main__":
    unittest.main()

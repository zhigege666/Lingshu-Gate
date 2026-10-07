"""访问治理、默认管理员与强制改密测试。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from fastapi import HTTPException

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolInvocationContext, ToolRegistry


class DefaultAdminTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_dir.name)
        self.settings = Settings(
            data_dir=self.root,
            db_url=f"sqlite:///{self.root / 'gate.db'}",
            auth_enabled=True,
        )
        self.environment = patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
            },
        )
        self.environment.start()
        self.database = SQLiteDatabase(self.settings.db_url, self.root)
        self.access_store = AccessControlStore(self.database)

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _initial_credentials(store: AuthStore) -> dict[str, str]:
        return json.loads(
            store.initial_admin_credentials_path.read_text(encoding="utf-8")
        )

    def test_first_initialization_creates_forced_change_admin(self) -> None:
        store = AuthStore(self.settings, self.database)

        user = store.list_users()[0]
        credentials = self._initial_credentials(store)
        principal, _, _ = store.login(
            username=credentials["username"],
            password=credentials["password"],
        )

        self.assertEqual(user["username"], "admin")
        self.assertEqual(user["roles"], ["admin"])
        self.assertTrue(user["must_change_password"])
        self.assertTrue(principal.must_change_password)
        self.assertIn("users.manage", principal.permissions)

    def test_password_change_clears_flag_and_revokes_old_session(self) -> None:
        store = AuthStore(self.settings, self.database)
        credentials = self._initial_credentials(store)
        principal, old_session, _ = store.login(
            username=credentials["username"],
            password=credentials["password"],
        )

        store.change_password(principal.id, "new-admin-password")
        changed, _, _ = store.login(username="admin", password="new-admin-password")

        self.assertFalse(changed.must_change_password)
        self.assertIsNone(store._principal_from_session(old_session))
        with self.assertRaisesRegex(HTTPException, "invalid username or password"):
            store.login(
                username=credentials["username"],
                password=credentials["password"],
            )

    def test_existing_user_is_not_overwritten(self) -> None:
        first = AuthStore(self.settings, self.database)
        first.change_password(first.list_users()[0]["id"], "new-admin-password")  # type: ignore[arg-type]

        AuthStore(self.settings, self.database)

        users = first.list_users()
        self.assertEqual(len(users), 1)
        self.assertFalse(users[0]["must_change_password"])

    def test_last_active_admin_cannot_be_disabled(self) -> None:
        store = AuthStore(self.settings, self.database)
        admin = store.list_users()[0]

        with self.assertRaisesRegex(ValueError, "last active admin"):
            store.validate_admin_transition(
                str(admin["id"]),
                status_value="disabled",
                roles=None,
            )

    def test_ac031_ac032_viewer_can_invoke_read_tool_but_not_write_tool(self) -> None:
        auth_store = AuthStore(self.settings, self.database)
        user = auth_store.create_user(
            username="reader",
            password="reader-password",
            role="viewer",
        )
        principal, _, _ = auth_store.login(username="reader", password="reader-password")
        read_tool = ToolDefinition(
            id="mcp.demo.search_records",
            name="Search records",
            description="Search records without modifying them.",
            source="mcp",
            metadata={
                "server_id": "demo",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        )
        write_tool = ToolDefinition(
            id="mcp.demo.update_record",
            name="Update record",
            description="Update an existing record.",
            source="mcp",
            metadata={
                "server_id": "demo",
                "annotations": {"readOnlyHint": False, "destructiveHint": False},
            },
        )
        self.access_store.synchronize_tools([read_tool, write_tool])
        for definition, access in ((read_tool, "read"), (write_tool, "write")):
            self.access_store.set_classification(
                server_id="demo",
                tool_id=definition.id,
                access=access,
                destructive=False,
                idempotent=access == "read",
                reviewer_id="test-admin",
            )
        self.access_store.synchronize_tools([read_tool, write_tool])
        pending = {
            item["tool_id"]: item
            for item in self.access_store.list_classifications(server_id="demo")
        }
        self.assertEqual(pending[read_tool.id]["source"], "manual")
        self.assertEqual(pending[write_tool.id]["source"], "manual")
        self.access_store.publish_classifications(
            reviewer_id="test-admin",
            server_id="demo",
        )
        self.access_store.save_grant(
            subject_type="user",
            subject_id=str(user["id"]),
            server_id="demo",
            permission_type_code="read",
            created_by="test-admin",
        )

        self.assertTrue(self.access_store.evaluate(principal, read_tool)["allowed"])
        self.assertFalse(self.access_store.evaluate(principal, write_tool)["allowed"])
        read_calls: list[dict[str, object]] = []
        write_calls: list[dict[str, object]] = []
        registry = ToolRegistry()
        registry.register(read_tool, lambda arguments: read_calls.append(arguments) or {"count": 1})
        registry.register(write_tool, lambda arguments: write_calls.append(arguments) or {"updated": True})
        visible_tool_ids = {
            item.id
            for item in self.access_store.visible_tools(
                principal,
                [read_tool, write_tool],
            )
        }
        self.assertEqual(visible_tool_ids, {read_tool.id})
        response = self.access_store.invoke_tool(
            registry,
            principal,
            read_tool.id,
            {"query": "docs"},
        )
        self.assertTrue(response.ok)
        self.assertEqual(read_calls, [{"query": "docs"}])
        with self.assertRaises(AccessDeniedError):
            self.access_store.invoke_tool(registry, principal, write_tool.id, {"record_id": "42"})
        denied_audit = self.access_store.list_invocation_audits(
            user_id=str(user["id"]),
            decision="deny",
        )[0]
        self.assertEqual(denied_audit["outcome"], "not_invoked")
        self.assertEqual(write_calls, [])

        self.access_store.save_grant(
            subject_type="user",
            subject_id=str(user["id"]),
            server_id="demo",
            permission_type_code="write",
            created_by="test-admin",
        )
        self.assertFalse(self.access_store.evaluate(principal, write_tool)["allowed"])
        self.assertEqual(
            {
                item.id
                for item in self.access_store.visible_tools(
                    principal,
                    [read_tool, write_tool],
                )
            },
            {read_tool.id},
        )
        with self.assertRaises(AccessDeniedError):
            self.access_store.invoke_tool(
                registry,
                principal,
                write_tool.id,
                {"record_id": "43"},
            )
        self.assertEqual(write_calls, [])
        read_token = auth_store.create_api_token(
            principal=principal,
            name="read-only",
            scopes=["tools.read"],
        )
        token_principal = auth_store._principal_from_api_token(str(read_token["token"]))
        self.assertIsNotNone(token_principal)
        self.assertTrue(self.access_store.evaluate(token_principal, read_tool)["allowed"])  # type: ignore[arg-type]
        self.assertFalse(self.access_store.evaluate(token_principal, write_tool)["allowed"])  # type: ignore[arg-type]

    def test_empty_api_token_scope_is_fail_closed(self) -> None:
        principal = AuthPrincipal(
            id="empty-scope-token",
            username="admin",
            role="admin",
            auth_type="token",
            roles=("admin",),
            permissions=("operations.manage",),
            scopes=(),
        )

        self.assertFalse(
            self.access_store.has_control_permission(
                principal,
                "operations.manage",
            )
        )

    def test_delivery_tool_requires_operations_manage_for_discovery_and_invocation(self) -> None:
        auth_store = AuthStore(self.settings, self.database)
        user = auth_store.create_user(
            username="limited-operator",
            password="limited-password",
            role="viewer",
        )
        user_id = str(user["id"])
        definition = ToolDefinition(
            id="gate_deploy_build",
            name="Deploy build",
            description="Deploy a completed build.",
            permission="write:project_delivery",
            source="builtin",
            metadata={
                "server_id": "gate-delivery",
                "required_control_permission": "operations.manage",
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": True,
                    "openWorldHint": True,
                },
            },
        )
        self.access_store.synchronize_tools([definition])
        self.access_store.set_classification(
            server_id="gate-delivery",
            tool_id=definition.id,
            access="write",
            destructive=True,
            idempotent=True,
            reviewer_id="test-admin",
        )
        self.access_store.publish_classifications(
            reviewer_id="test-admin",
            server_id="gate-delivery",
        )
        self.access_store.save_grant(
            subject_type="user",
            subject_id=user_id,
            server_id="gate-delivery",
            permission_type_code="write",
            created_by="test-admin",
        )
        limited = AuthPrincipal(
            id=user_id,
            username="limited",
            role="custom",
            roles=("custom",),
            permissions=("tools.read", "tools.invoke"),
        )
        registry = ToolRegistry()
        calls: list[dict[str, object]] = []
        registry.register(
            definition,
            lambda arguments: calls.append(arguments) or {"status": "success"},
        )

        denied = self.access_store.evaluate(limited, definition)
        self.assertFalse(denied["allowed"])
        self.assertEqual(denied["reason"], "missing control permission: operations.manage")
        self.assertEqual(self.access_store.visible_tools(limited, [definition]), [])
        with self.assertRaises(AccessDeniedError):
            self.access_store.invoke_tool(registry, limited, definition.id, {"build_id": "demo"})
        self.assertEqual(calls, [])

        allowed = AuthPrincipal(
            id=user_id,
            username="limited",
            role="custom",
            roles=("custom",),
            permissions=("tools.read", "tools.invoke", "operations.manage"),
        )
        self.assertTrue(self.access_store.evaluate(allowed, definition)["allowed"])
        self.assertEqual(
            {item.id for item in self.access_store.visible_tools(allowed, [definition])},
            {definition.id},
        )
        response = self.access_store.invoke_tool(
            registry,
            allowed,
            definition.id,
            {"build_id": "demo"},
        )
        self.assertTrue(response.ok)
        self.assertEqual(calls, [{"build_id": "demo"}])

    def test_delivery_target_access_reuses_server_level_grants(self) -> None:
        auth_store = AuthStore(self.settings, self.database)
        user = auth_store.create_user(
            username="target-operator",
            password="target-password",
            role="viewer",
        )
        user_id = str(user["id"])
        context = ToolInvocationContext(
            actor_id=user_id,
            username="target-operator",
            auth_type="session",
            token_id=None,
            correlation_id="target-access-test",
            roles=("viewer",),
            permissions=("tools.read", "tools.invoke", "operations.manage"),
        )

        self.assertFalse(self.access_store.delivery_target_access(context, "target-a", "read"))
        self.access_store.save_grant(
            subject_type="user",
            subject_id=user_id,
            server_id="target-a",
            permission_type_code="read",
            created_by="test-admin",
        )
        self.assertTrue(self.access_store.delivery_target_access(context, "target-a", "read"))
        self.assertFalse(self.access_store.delivery_target_access(context, "target-a", "write"))

        self.access_store.save_grant(
            subject_type="user",
            subject_id=user_id,
            server_id="target-a",
            permission_type_code="write",
            created_by="test-admin",
        )
        self.assertTrue(self.access_store.delivery_target_access(context, "target-a", "write"))

        missing_control_permission = ToolInvocationContext(
            actor_id=user_id,
            username="target-operator",
            auth_type="session",
            token_id=None,
            correlation_id="target-access-test-denied",
            roles=("viewer",),
            permissions=("tools.read", "tools.invoke"),
        )
        self.assertFalse(
            self.access_store.delivery_target_access(
                missing_control_permission,
                "target-a",
                "read",
            )
        )

    def test_synchronize_tools_is_idempotent_under_concurrent_first_load(self) -> None:
        definition = ToolDefinition(
            id="mcp.demo.concurrent_search",
            name="Concurrent search",
            description="Search records without modifying them.",
            source="mcp",
            metadata={
                "server_id": "demo",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        )
        first_reads = Barrier(2)
        original_load = self.access_store._load_classifications

        def synchronize_first_read(connection, keys):
            rows = original_load(connection, keys)
            first_reads.wait(timeout=2)
            return rows

        with patch.object(self.access_store, "_load_classifications", side_effect=synchronize_first_read):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: self.access_store.synchronize_tools([definition]), range(2)))

        self.assertEqual([len(result) for result in results], [1, 1])
        classifications = self.access_store.list_classifications(server_id="demo")
        self.assertEqual(len(classifications), 1)
        self.assertEqual(classifications[0]["tool_id"], definition.id)

    def _discovery_fixture(self, count: int = 2) -> tuple[AuthPrincipal, list[ToolDefinition], str]:
        user = AuthStore(self.settings, self.database).create_user(
            username="discovery-reader", password="reader-password", role="operator",
        )
        principal = AuthPrincipal(
            id=str(user["id"]), username="discovery-reader", role="operator",
            roles=("operator",), permissions=("tools.read", "tools.invoke"),
        )
        definitions = [
            ToolDefinition(
                id=f"mcp.discovery.read_{index}", name=f"Read {index}", description="Read a test record.", source="mcp",
                metadata={"server_id": "discovery", "annotations": {"readOnlyHint": True}},
            )
            for index in range(count)
        ]
        self.access_store.synchronize_tools(definitions)
        self.database.execute(
            "UPDATE mcp_tool_classifications SET effective_access = 'read', status = 'published' WHERE server_id = ?",
            ("discovery",),
        )
        grant = self.access_store.save_grant(
            subject_type="user", subject_id=principal.id, server_id="discovery",
            permission_type_code="read", created_by="test-admin",
        )
        return principal, definitions, str(grant["id"])

    def test_discovery_access_snapshot_matches_policy_without_mutating_registry(self) -> None:
        principal, definitions, _ = self._discovery_fixture()
        original_metadata = dict(definitions[0].metadata)
        visible = self.access_store.visible_tools(principal, definitions)
        self.assertEqual(visible[0].metadata["gate_access"], {
            "required_access": "read", "classification_status": "published",
        })
        self.assertEqual(definitions[0].metadata, original_metadata)
        self.assertIsNot(visible[0], definitions[0])
        visible[0].metadata["gate_access"]["required_access"] = "write"
        self.assertEqual(
            self.access_store.visible_tools(principal, definitions)[0].metadata["gate_access"]["required_access"],
            "read",
        )
        self.access_store.save_grant(
            subject_type="user", subject_id=principal.id, server_id="discovery",
            permission_type_code="write", created_by="test-admin",
        )
        self.database.execute(
            "UPDATE mcp_tool_classifications SET effective_access = 'write' WHERE tool_id = ?",
            (definitions[0].id,),
        )
        updated = self.access_store.visible_tools(principal, definitions)
        self.assertEqual(updated[0].metadata["gate_access"]["required_access"], "write")
        self.assertTrue(definitions[0].metadata["annotations"]["readOnlyHint"])
        self.assertEqual(self.access_store.evaluate(principal, definitions[0])["required_access"], "write")

    def test_large_published_catalog_uses_bounded_reads_without_classification_writes(self) -> None:
        principal, definitions, _ = self._discovery_fixture(600)
        statements: list[str] = []
        original_connect = self.database.connect

        def traced_connect():
            connection = original_connect()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(self.database, "connect", side_effect=traced_connect) as connect:
            visible = self.access_store.visible_tools(principal, definitions)
        self.assertEqual([item.id for item in visible], [item.id for item in definitions])
        self.assertEqual(connect.call_count, 1)
        self.assertLess(sum(sql.lstrip().upper().startswith("SELECT") for sql in statements), 20)
        self.assertFalse(any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements))

    def test_discovery_observes_revocation_identity_and_changed_tool_on_next_request(self) -> None:
        principal, definitions, grant_id = self._discovery_fixture()
        self.assertEqual(len(self.access_store.visible_tools(principal, definitions)), 2)
        other = AuthPrincipal(
            id="another-user", username="another-user", role="operator",
            permissions=("tools.read", "tools.invoke"),
        )
        self.assertEqual(self.access_store.visible_tools(other, definitions), [])
        self.access_store.delete_grant(grant_id)
        self.assertEqual(self.access_store.visible_tools(principal, definitions), [])
        self.access_store.save_grant(
            subject_type="user", subject_id=principal.id, server_id="discovery",
            permission_type_code="read", created_by="test-admin",
        )
        changed = definitions[0].model_copy(update={"description": "Changed contract"})
        visible = self.access_store.visible_tools(principal, [changed, definitions[1]])
        self.assertEqual([item.id for item in visible], [definitions[1].id])
        self.assertEqual(self.access_store.evaluate(principal, changed)["classification_status"], "stale")

    def test_batched_grants_preserve_user_role_expiry_and_disabled_role_precedence(self) -> None:
        principal, definitions, grant_id = self._discovery_fixture()
        self.access_store.delete_grant(grant_id)
        self.database.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (principal.id, "role-viewer"),
        )

        def grant(subject: str, subject_id: str, level: str, tool_id: str = "", expires_at: str | None = None):
            return self.access_store.save_grant(
                subject_type=subject, subject_id=subject_id, server_id="discovery",
                permission_type_code=level, tool_id=tool_id, expires_at=expires_at,
                created_by="test-admin",
            )

        grant("role", "role-operator", "write")
        grant("role", "role-operator", "none", definitions[0].id)
        grant("role", "role-viewer", "read")
        self.assertEqual(self.access_store.effective_access(principal, "discovery", definitions[0].id), "read")
        self.assertEqual(self.access_store.effective_access(principal, "discovery", definitions[1].id), "write")
        direct = grant("user", principal.id, "none")
        self.assertEqual(self.access_store.visible_tools(principal, definitions), [])
        grant("user", principal.id, "read", definitions[0].id)
        self.assertEqual(
            [item.id for item in self.access_store.visible_tools(principal, definitions)], [definitions[0].id],
        )
        grant("user", principal.id, "read", definitions[0].id, "2000-01-01T00:00:00+00:00")
        self.assertEqual(self.access_store.visible_tools(principal, definitions), [])
        self.access_store.delete_grant(str(direct["id"]))
        self.database.execute("UPDATE roles SET enabled = 0 WHERE id = ?", ("role-viewer",))
        self.assertEqual(
            [item.id for item in self.access_store.visible_tools(principal, definitions)], [definitions[1].id],
        )

    def test_reconcile_server_tools_requires_review_for_changed_retired_and_reappeared_tools(self) -> None:
        original = ToolDefinition(
            id="mcp.demo.read_file",
            server_id="demo",
            name="read_file",
            description="Read one file.",
            input_schema={"type": "object"},
            source="mcp",
            metadata={
                "server_id": "demo",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        )
        self.access_store.synchronize_tools([original])
        self.access_store.set_classification(
            server_id="demo",
            tool_id=original.id,
            access="read",
            destructive=False,
            idempotent=True,
            reviewer_id="test-admin",
        )
        self.access_store.publish_classifications(
            reviewer_id="test-admin",
            server_id="demo",
        )

        unchanged = self.access_store.reconcile_server_tools(
            "demo", [original], "refresh-actor"
        )
        self.assertEqual(unchanged["counts"]["unchanged"], 1)
        self.assertEqual(unchanged["counts"]["needs_review"], 0)

        changed = original.model_copy(update={"description": "Read one file or URL."})
        changed_result = self.access_store.reconcile_server_tools(
            "demo", [changed], "refresh-actor"
        )
        changed_row = self.access_store.list_classifications(server_id="demo")[0]
        self.assertEqual(changed_result["changed_tool_ids"], [original.id])
        self.assertEqual(changed_row["status"], "stale")
        self.assertEqual(changed_row["effective_access"], "unknown")
        self.assertFalse(changed_result["effective_permissions_expanded"])

        retired = self.access_store.reconcile_server_tools("demo", [], "refresh-actor")
        retired_row = self.access_store.list_classifications(server_id="demo")[0]
        self.assertEqual(retired["retired_tool_ids"], [original.id])
        self.assertEqual(retired_row["status"], "stale")
        self.assertEqual(retired_row["effective_access"], "unknown")
        self.assertEqual(retired_row["evidence"]["lifecycle"]["status"], "retired")
        retired_replay = self.access_store.reconcile_server_tools(
            "demo", [], "refresh-actor"
        )
        self.assertEqual(retired_replay["retired_tool_ids"], [])

        reappeared = self.access_store.reconcile_server_tools(
            "demo", [changed], "refresh-actor"
        )
        reappeared_row = self.access_store.list_classifications(server_id="demo")[0]
        self.assertEqual(reappeared["reappeared_tool_ids"], [original.id])
        self.assertEqual(reappeared_row["status"], "stale")
        self.assertEqual(reappeared_row["effective_access"], "unknown")
        self.assertEqual(reappeared_row["evidence"]["lifecycle"]["status"], "active")
        self.assertFalse(reappeared["effective_permissions_expanded"])

    def test_invocation_audit_records_keys_but_not_sensitive_values(self) -> None:
        auth_store = AuthStore(self.settings, self.database)
        user = auth_store.create_user(
            username="audited-reader",
            password="reader-password",
            role="viewer",
        )
        principal, _, _ = auth_store.login(
            username="audited-reader",
            password="reader-password",
        )
        definition = ToolDefinition(
            id="mcp.demo.search_records",
            name="Search records",
            description="Search records without modifying them.",
            source="mcp",
            metadata={
                "server_id": "demo",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        )
        registry = ToolRegistry()
        registry.register(definition, lambda _: {"count": 1})
        self.access_store.synchronize_tools([definition])
        self.access_store.set_classification(
            server_id="demo",
            tool_id=definition.id,
            access="read",
            destructive=False,
            idempotent=True,
            reviewer_id="test-admin",
        )
        self.access_store.publish_classifications(
            reviewer_id="test-admin",
            server_id="demo",
        )
        self.access_store.save_grant(
            subject_type="user",
            subject_id=str(user["id"]),
            server_id="demo",
            permission_type_code="read",
            created_by="test-admin",
        )

        response = self.access_store.invoke_tool(
            registry,
            principal,
            definition.id,
            {"query": "patient", "api_token": "must-not-be-recorded"},
        )
        audit = self.access_store.list_invocation_audits(user_id=str(user["id"]))[0]
        filter_options = self.access_store.list_invocation_audit_filter_options()

        self.assertTrue(response.ok)
        self.assertEqual(audit["decision"], "allow")
        self.assertEqual(audit["outcome"], "success")
        self.assertEqual(audit["payload"]["argument_keys"], ["[REDACTED]", "query"])
        self.assertFalse(audit["payload"]["values_recorded"])
        self.assertNotIn("must-not-be-recorded", str(audit["payload"]))
        self.assertEqual(
            filter_options["users"],
            [{"id": str(user["id"]), "username": "audited-reader"}],
        )
        self.assertEqual(filter_options["servers"], ["demo"])
        self.assertEqual(
            filter_options["tools"],
            [{"server_id": "demo", "tool_id": definition.id}],
        )


if __name__ == "__main__":
    unittest.main()

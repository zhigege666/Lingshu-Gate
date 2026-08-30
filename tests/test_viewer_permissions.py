"""Viewer minimum permissions and API token scope regressions."""

from __future__ import annotations

import gc
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.database import SQLiteDatabase


SENSITIVE_CONTROL_PLANE_PATHS = (
    "/v1/logs",
    "/v1/events",
    "/v1/credentials",
    "/v1/mcp/configs",
    "/v1/mcp/servers",
    "/v1/runtime/environment",
    "/v1/runtime/cache",
    "/v1/diagnostics",
    "/v1/diagnostics/memory",
    "/v1/builds",
    "/v1/deployments",
    "/v1/projects/uploads",
    "/v1/access/invocation-audits",
)


class ViewerControlPlaneRoutesTest(unittest.TestCase):
    """使用真实 FastAPI 路由验证角色与 Token 的负向权限边界。"""

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

        self.app = create_app()
        auth_store = self.app.state.auth_store
        admin = auth_store.list_users()[0]
        auth_store.change_password(str(admin["id"]), "Admin123!")
        auth_store.create_user(
            username="viewer-test",
            password="Viewer123!",
            role="viewer",
        )
        auth_store.create_user(
            username="operator-test",
            password="Operator123!",
            role="operator",
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

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

    def test_ac029_default_viewer_cannot_read_sensitive_control_plane_apis(self) -> None:
        self._login("viewer-test", "Viewer123!")

        for path in SENSITIVE_CONTROL_PLANE_PATHS:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403, response.text)

    def test_viewer_personal_metadata_endpoints_remain_available(self) -> None:
        self._login("viewer-test", "Viewer123!")

        responses = {
            "/v1/auth/me": self.client.get("/v1/auth/me"),
            "/v1/auth/tokens": self.client.get("/v1/auth/tokens"),
            "/v1/auth/downstream-credentials": self.client.get(
                "/v1/auth/downstream-credentials"
            ),
        }

        for path, response in responses.items():
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 200, response.text)

        self.assertEqual(responses["/v1/auth/me"].json()["role"], "viewer")
        self.assertIn("tokens", responses["/v1/auth/tokens"].json())
        self.assertIn(
            "credentials",
            responses["/v1/auth/downstream-credentials"].json(),
        )

    def test_ac030_tools_read_token_cannot_bypass_control_plane_permissions(self) -> None:
        self._login("viewer-test", "Viewer123!")
        created = self.client.post(
            "/v1/auth/tokens",
            json={"name": "viewer-read-only", "scopes": ["tools.read"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        bearer = str(created.json()["token"])
        self.client.cookies.clear()

        for path in SENSITIVE_CONTROL_PLANE_PATHS:
            with self.subTest(path=path):
                response = self.client.get(
                    path,
                    headers={"Authorization": f"Bearer {bearer}"},
                )
                self.assertEqual(response.status_code, 403, response.text)

    def test_admin_token_cannot_mint_a_child_with_broader_scopes(self) -> None:
        self._login("admin", "Admin123!")
        parent = self.client.post(
            "/v1/auth/tokens",
            json={
                "name": "token-manager-only",
                "scopes": ["credentials.manage.self"],
            },
        )
        self.assertEqual(parent.status_code, 200, parent.text)
        bearer = str(parent.json()["token"])
        self.client.cookies.clear()
        headers = {"Authorization": f"Bearer {bearer}"}

        self.assertEqual(
            self.client.get("/v1/auth/tokens", headers=headers).status_code,
            200,
        )
        for scopes in (["operations.manage"], ["tools.read"], ["*"]):
            with self.subTest(scopes=scopes):
                child = self.client.post(
                    "/v1/auth/tokens",
                    headers=headers,
                    json={"name": "broader-child", "scopes": scopes},
                )
                self.assertEqual(child.status_code, 400, child.text)
                self.assertIn("scope exceeds user permissions", child.text)

    def test_active_token_scopes_can_expand_in_place_and_take_effect_immediately(self) -> None:
        self._login("operator-test", "Operator123!")
        created = self.client.post(
            "/v1/auth/tokens",
            json={"name": "operator-token", "scopes": ["tools.read"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        token = created.json()

        updated = self.client.patch(
            f"/v1/auth/tokens/{token['id']}",
            json={"scopes": ["tools.read", "tools.invoke"]},
        )

        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["id"], token["id"])
        self.assertEqual(updated.json()["token_prefix"], token["token_prefix"])
        self.assertEqual(updated.json()["scopes"], ["tools.invoke", "tools.read"])
        self.assertNotIn("token", updated.json())
        principal = self.app.state.auth_store._principal_from_api_token(token["token"])
        self.assertIsNotNone(principal)
        self.assertEqual(set(principal.scopes), {"tools.read", "tools.invoke"})

        reduced = self.client.patch(
            f"/v1/auth/tokens/{token['id']}",
            json={"scopes": ["tools.read"]},
        )
        self.assertEqual(reduced.status_code, 200, reduced.text)
        principal = self.app.state.auth_store._principal_from_api_token(token["token"])
        self.assertIsNotNone(principal)
        self.assertEqual(principal.scopes, ("tools.read",))
        events = self.app.state.observability_store.list_events(
            event_type="gate.auth.token_scopes_updated",
            subject_id=token["id"],
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["payload"]["previous_scopes"], ["tools.invoke", "tools.read"])
        self.assertEqual(events[0]["payload"]["scopes"], ["tools.read"])
        self.assertEqual(events[1]["payload"]["previous_scopes"], ["tools.read"])
        self.assertEqual(events[1]["payload"]["scopes"], ["tools.invoke", "tools.read"])

    def test_token_scope_update_rejects_empty_excess_and_other_user(self) -> None:
        self._login("viewer-test", "Viewer123!")
        created = self.client.post(
            "/v1/auth/tokens",
            json={"name": "viewer-token", "scopes": ["tools.read"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        token_id = created.json()["id"]

        empty = self.client.patch(
            f"/v1/auth/tokens/{token_id}",
            json={"scopes": []},
        )
        excessive = self.client.patch(
            f"/v1/auth/tokens/{token_id}",
            json={"scopes": ["tools.invoke"]},
        )
        self.assertEqual(empty.status_code, 400, empty.text)
        self.assertEqual(excessive.status_code, 400, excessive.text)

        self._login("operator-test", "Operator123!")
        other_user = self.client.patch(
            f"/v1/auth/tokens/{token_id}",
            json={"scopes": ["tools.read"]},
        )
        self.assertEqual(other_user.status_code, 404, other_user.text)

    def test_revoked_and_expired_token_scopes_cannot_be_updated(self) -> None:
        self._login("viewer-test", "Viewer123!")
        created = self.client.post(
            "/v1/auth/tokens",
            json={"name": "revoked-token", "scopes": ["tools.read"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        token_id = created.json()["id"]
        revoked = self.client.delete(f"/v1/auth/tokens/{token_id}")
        self.assertEqual(revoked.status_code, 200, revoked.text)

        updated = self.client.patch(
            f"/v1/auth/tokens/{token_id}",
            json={"scopes": ["tools.read"]},
        )
        self.assertEqual(updated.status_code, 400, updated.text)

        expired = self.client.post(
            "/v1/auth/tokens",
            json={
                "name": "expired-token",
                "scopes": ["tools.read"],
                "expires_at": "2000-01-01T00:00:00+00:00",
            },
        )
        self.assertEqual(expired.status_code, 200, expired.text)
        expired_update = self.client.patch(
            f"/v1/auth/tokens/{expired.json()['id']}",
            json={"scopes": ["tools.read"]},
        )
        self.assertEqual(expired_update.status_code, 400, expired_update.text)

    def test_ac033_operator_and_admin_keep_control_plane_read_access(self) -> None:
        for username, password in (
            ("operator-test", "Operator123!"),
            ("admin", "Admin123!"),
        ):
            self._login(username, password)
            for path in SENSITIVE_CONTROL_PLANE_PATHS:
                with self.subTest(username=username, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200, response.text)


class ViewerSystemRoleMigrationTest(unittest.TestCase):
    """模拟 1.15.0 旧库，确保系统 Viewer 权限清理可重入。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.database = SQLiteDatabase(
            f"sqlite:///{self.root / 'gate.db'}",
            self.root,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _migration_ids(self) -> set[str]:
        return {
            str(row["id"])
            for row in self.database.query_all(
                "SELECT id FROM schema_migrations ORDER BY id"
            )
        }

    def _viewer_has_tools_invoke(self) -> bool:
        row = self.database.query_one(
            """
            SELECT 1
            FROM role_permissions
            JOIN roles ON roles.id = role_permissions.role_id
            JOIN control_permissions
              ON control_permissions.id = role_permissions.permission_id
            WHERE roles.code = 'viewer'
              AND roles.is_system = 1
              AND control_permissions.code = 'tools.invoke'
            """
        )
        return row is not None

    def test_ac034_viewer_baseline_excludes_tool_invocation(self) -> None:
        baseline_migrations = self._migration_ids()
        AccessControlStore(self.database)

        self.assertFalse(self._viewer_has_tools_invoke())
        self.assertEqual(self._migration_ids(), baseline_migrations)


if __name__ == "__main__":
    unittest.main()

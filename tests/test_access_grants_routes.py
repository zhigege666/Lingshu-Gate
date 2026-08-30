"""Access grant route tests for 管理员/运维/只读职责边界与授权链路。"""

from __future__ import annotations

import gc
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient


class AccessGrantsRoutesTest(unittest.TestCase):
    """覆盖 admin/operator 对 /v1/access/grants 的可见性与授权流程。"""

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

        self._login_admin()
        self.operator_user = self._create_user(
            {
                "username": "operator-grant-user",
                "display_name": "运维授权用户",
                "password": "Operator123!",
                "roles": ["operator"],
                "status": "active",
                "must_change_password": False,
            },
        )
        self.viewer_user = self._create_user(
            {
                "username": "viewer-grant-user",
                "display_name": "测试只读用户",
                "password": "Viewer123!",
                "roles": ["viewer"],
                "status": "active",
                "must_change_password": False,
            },
        )
        self.roles = self.client.get("/v1/access/roles").json()["roles"]
        self.users = self.client.get("/v1/access/users").json()["users"]

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.env.stop()
        gc.collect()
        self.temp.cleanup()

    def _login_admin(self) -> None:
        response = self.client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "Admin123!"},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _login(self, username: str, password: str) -> None:
        self.client.cookies.clear()
        response = self.client.post(
            "/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post("/v1/access/users", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    @staticmethod
    def _match_query(grant: dict[str, Any], query: str, users: list[dict[str, Any]], roles: list[dict[str, Any]]) -> bool:
        needle = query.strip().lower()
        subject_label = ""
        if grant["subject_type"] == "user":
            user = next((item for item in users if item["id"] == grant["subject_id"]), None)
            if user is None:
                subject_label = grant["subject_id"]
            elif user["display_name"]:
                subject_label = f"{user['display_name']} (@{user['username']})"
            else:
                subject_label = f"@{user['username']}"
        else:
            role = next((item for item in roles if item["id"] == grant["subject_id"]), None)
            subject_label = grant["subject_id"] if role is None else f"{role['name']} ({role['code']})"

        return (
            needle in subject_label.lower()
            or needle in str(grant["server_id"]).lower()
            or needle in str(grant["tool_id"] or "").lower()
            or needle in str(grant["permission_type_code"]).lower()
        )

    @staticmethod
    def _paginate(items: list[dict[str, Any]], *, page: int, page_size: int) -> list[dict[str, Any]]:
        start = max(page - 1, 0) * page_size
        end = start + page_size
        return items[start:end]

    def test_admin_can_manage_subject_options(self) -> None:
        users_response = self.client.get("/v1/access/users").json()
        roles_response = self.client.get("/v1/access/roles").json()
        subjects_response = self.client.get("/v1/access/subjects").json()

        self.assertIn("users", users_response)
        self.assertIn("roles", roles_response)
        self.assertIn("users", subjects_response)
        self.assertIn("roles", subjects_response)
        self.assertTrue(subjects_response["users"])
        self.assertTrue(subjects_response["roles"])

        subject_user_ids = {item["id"] for item in subjects_response["users"]}
        subject_role_ids = {item["id"] for item in subjects_response["roles"]}
        self.assertEqual(subject_user_ids, {item["id"] for item in users_response["users"]})
        self.assertEqual(subject_role_ids, {item["id"] for item in roles_response["roles"]})

        viewer_user = next(item for item in subjects_response["users"] if item["username"] == "viewer-grant-user")
        self.assertEqual(viewer_user["roles"], ["viewer"])
        operator_role = next(item for item in subjects_response["roles"] if item["code"] == "operator")
        self.assertEqual(operator_role["code"], "operator")

        self.assertGreaterEqual(len(subjects_response["roles"]), 3)

    def test_admin_can_grant_and_filter_by_subject_type(self) -> None:
        operator_role = next(item for item in self.roles if item["code"] == "operator")
        role_save = self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "role",
                "subject_id": operator_role["id"],
                "server_id": "mcp.server-a",
                "tool_id": None,
                "permission_type_code": "read",
                "expires_at": None,
            },
        )
        self.assertEqual(role_save.status_code, 200, role_save.text)
        role_grant = role_save.json()
        self.assertEqual(role_grant["subject_type"], "role")
        self.assertEqual(role_grant["subject_id"], operator_role["id"])
        self.assertEqual(role_grant["server_id"], "mcp.server-a")
        self.assertEqual(role_grant["permission_type_code"], "read")
        self.assertEqual(role_grant["base_level"], "read")

        user_save = self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "user",
                "subject_id": self.viewer_user["id"],
                "server_id": "mcp.server-a",
                "tool_id": None,
                "permission_type_code": "write",
                "expires_at": None,
            },
        )
        self.assertEqual(user_save.status_code, 200, user_save.text)
        user_grant = user_save.json()
        self.assertEqual(user_grant["subject_type"], "user")
        self.assertEqual(user_grant["subject_id"], self.viewer_user["id"])
        self.assertEqual(user_grant["permission_type_code"], "write")
        self.assertEqual(user_grant["base_level"], "write")

        all_grants = self.client.get("/v1/access/grants").json()["grants"]
        self.assertEqual(len(all_grants), 2)

        role_filtered = self.client.get("/v1/access/grants", params={"subject_type": "role"}).json()["grants"]
        self.assertEqual(len(role_filtered), 1)
        self.assertEqual(role_filtered[0]["id"], role_grant["id"])

        user_filtered = self.client.get(
            "/v1/access/grants",
            params={"subject_type": "user", "subject_id": self.viewer_user["id"]},
        ).json()["grants"]
        self.assertEqual(len(user_filtered), 1)
        self.assertEqual(user_filtered[0]["id"], user_grant["id"])

        server_filtered = self.client.get(
            "/v1/access/grants",
            params={"server_id": "mcp.server-a"},
        ).json()["grants"]
        self.assertEqual(
            {item["id"] for item in server_filtered},
            {role_grant["id"], user_grant["id"]},
        )

        query = "viewer"
        search_matches = [
            item
            for item in all_grants
            if self._match_query(item, query, self.users, self.roles)
        ]
        self.assertEqual(len(search_matches), 1)
        self.assertEqual(search_matches[0]["id"], user_grant["id"])

    def test_admin_can_update_existing_grant_and_get_feedback(self) -> None:
        self._login_admin()
        operator_role = next(item for item in self.roles if item["code"] == "operator")
        first = self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "role",
                "subject_id": operator_role["id"],
                "server_id": "mcp.server-b",
                "permission_type_code": "read",
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_grant = first.json()
        self.assertIn("created_by", first_grant)
        self.assertIn("created_at", first_grant)
        self.assertIn("updated_at", first_grant)

        second = self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "role",
                "subject_id": operator_role["id"],
                "server_id": "mcp.server-b",
                "permission_type_code": "write",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_grant = second.json()

        self.assertEqual(second_grant["id"], first_grant["id"])
        self.assertEqual(second_grant["permission_type_code"], "write")
        self.assertIn("updated_at", second_grant)
        self.assertEqual(second_grant["created_at"], first_grant["created_at"])
        self.assertIn("base_level", second_grant)

    def test_admin_grants_list_supports_search_and_pagination_flow(self) -> None:
        operator_role = next(item for item in self.roles if item["code"] == "operator")
        operator_user = self.viewer_user
        self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "role",
                "subject_id": operator_role["id"],
                "server_id": "mcp.server-c",
                "permission_type_code": "read",
            },
        )
        self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "role",
                "subject_id": operator_role["id"],
                "server_id": "mcp.server-d",
                "permission_type_code": "write",
            },
        )
        self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "user",
                "subject_id": operator_user["id"],
                "server_id": "mcp.server-e",
                "permission_type_code": "read",
            },
        )

        all_grants = self.client.get("/v1/access/grants").json()["grants"]
        self.assertGreaterEqual(len(all_grants), 3)

        search_by_user = [
            item
            for item in all_grants
            if self._match_query(item, "viewer-grant-user", self.users, self.roles)
        ]
        self.assertEqual(len(search_by_user), 1)
        self.assertEqual(search_by_user[0]["subject_type"], "user")
        self.assertEqual(search_by_user[0]["subject_id"], operator_user["id"])

        search_by_server = [
            item
            for item in all_grants
            if self._match_query(item, "mcp.server-d", self.users, self.roles)
        ]
        self.assertEqual(len(search_by_server), 1)
        self.assertEqual(search_by_server[0]["server_id"], "mcp.server-d")

        page_size = 2
        page1 = self._paginate(all_grants, page=1, page_size=page_size)
        page2 = self._paginate(all_grants, page=2, page_size=page_size)
        page3 = self._paginate(all_grants, page=3, page_size=page_size)

        self.assertLessEqual(len(page1), page_size)
        self.assertLessEqual(len(page2), page_size)
        self.assertEqual(len(page3), 0)
        self.assertEqual(len(page1) + len(page2), min(page_size * 2, len(all_grants)))
        self.assertTrue(len(page1) >= 1)

    def test_operator_has_no_access_to_grant_management(self) -> None:
        self._login("operator-grant-user", "Operator123!")

        for path in ("/v1/access/grants", "/v1/access/subjects", "/v1/access/roles", "/v1/access/permission-types", "/v1/access/resources"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, response.text)

        denied = self.client.put(
            "/v1/access/grants",
            json={
                "subject_type": "user",
                "subject_id": self.viewer_user["id"],
                "server_id": "mcp.server-a",
                "permission_type_code": "read",
            },
        )
        self.assertEqual(denied.status_code, 403, denied.text)


if __name__ == "__main__":
    unittest.main()

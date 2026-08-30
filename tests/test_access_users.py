"""用户注册与管理员创建账号的访问治理集成测试。"""

from __future__ import annotations

import gc
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class AccessUsersRoutesTest(unittest.TestCase):
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
            },
        )
        self.env.start()
        from lingshu_gate.main import create_app

        self.client_context = TestClient(create_app())
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.env.stop()
        gc.collect()
        self.temp.cleanup()

    def _login_admin(self) -> None:
        credentials = json.loads(
            self.client.app.state.auth_store.initial_admin_credentials_path.read_text(
                encoding="utf-8"
            )
        )
        first_login = self.client.post(
            "/v1/auth/login",
            json={
                "username": credentials["username"],
                "password": credentials["password"],
            },
        )
        self.assertEqual(first_login.status_code, 200)
        self.assertTrue(first_login.json()["user"]["must_change_password"])

        changed = self.client.post(
            "/v1/auth/password",
            json={"password": "Admin123!"},
        )
        self.assertEqual(changed.status_code, 200)

        second_login = self.client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "Admin123!"},
        )
        self.assertEqual(second_login.status_code, 200)

    def test_public_registration_defaults_to_pending_viewer(self) -> None:
        response = self.client.post(
            "/v1/auth/register",
            json={
                "username": "registered-reader",
                "display_name": "注册用户",
                "password": "Reader123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        user = response.json()["user"]
        self.assertEqual(user["status"], "pending")
        self.assertEqual(user["roles"], ["viewer"])

    def test_admin_can_create_active_viewer_with_forced_password_change(self) -> None:
        self._login_admin()

        response = self.client.post(
            "/v1/access/users",
            json={
                "username": "admin-created-reader",
                "display_name": "管理员创建用户",
                "password": "Reader123!",
                "roles": ["viewer"],
                "status": "active",
                "must_change_password": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        user = response.json()
        self.assertEqual(user["status"], "active")
        self.assertEqual(user["roles"], ["viewer"])
        self.assertTrue(user["must_change_password"])

        duplicate = self.client.post(
            "/v1/access/users",
            json={
                "username": "admin-created-reader",
                "password": "Reader123!",
                "roles": ["viewer"],
            },
        )
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__":
    unittest.main()

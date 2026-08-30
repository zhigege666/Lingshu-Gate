"""Secure first-start administrator bootstrap tests."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase


class AuthBootstrapSecurityTest(unittest.TestCase):
    def test_empty_database_uses_local_random_one_time_credentials(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            root = Path(temp_dir)
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)

            with self.assertLogs("lingshu_gate.auth", level="WARNING") as logs:
                store = AuthStore(settings, database)

            path = store.initial_admin_credentials_path
            credentials = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(credentials["username"], "admin")
            self.assertNotEqual(credentials["password"], "admin")
            self.assertGreaterEqual(len(credentials["password"]), 8)
            self.assertNotIn(credentials["password"], "\n".join(logs.output))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            with self.assertRaises(HTTPException):
                store.login(username="admin", password="admin")
            principal, _, _ = store.login(
                username=credentials["username"],
                password=credentials["password"],
            )
            self.assertTrue(principal.must_change_password)

            store.change_password(principal.id, "Replacement123!")
            self.assertFalse(path.exists())
            replacement, _, _ = store.login(
                username="admin",
                password="Replacement123!",
            )
            self.assertFalse(replacement.must_change_password)

    def test_explicit_environment_credentials_do_not_create_local_password_file(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_ADMIN_USERNAME": "owner",
                "LINGSHU_GATE_ADMIN_PASSWORD": "OwnerPassword123!",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            root = Path(temp_dir)
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)
            store = AuthStore(settings, database)

            self.assertFalse(store.initial_admin_credentials_path.exists())
            principal, _, _ = store.login(
                username="owner",
                password="OwnerPassword123!",
            )
            self.assertEqual(principal.username, "owner")
            self.assertTrue(principal.must_change_password)

    def test_password_file_bootstrap_is_forced_change_and_not_in_environment(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            password_file = root / "bootstrap-password"
            password_file.write_text("FileOwnerPassword123!\n", encoding="utf-8")
            password_file.chmod(0o600)
            with patch.dict(
                os.environ,
                {
                    "LINGSHU_GATE_ADMIN_USERNAME": "file-owner",
                    "LINGSHU_GATE_ADMIN_PASSWORD": "",
                    "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": str(password_file),
                },
            ):
                settings = Settings(
                    data_dir=root,
                    db_url=f"sqlite:///{root / 'gate.db'}",
                    auth_enabled=True,
                )
                database = SQLiteDatabase(settings.db_url, root)
                AccessControlStore(database)
                store = AuthStore(settings, database)

            principal, _, _ = store.login(
                username="file-owner",
                password="FileOwnerPassword123!",
            )
            self.assertTrue(principal.must_change_password)
            self.assertFalse(store.initial_admin_credentials_path.exists())

    def test_inline_and_file_bootstrap_passwords_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            password_file = root / "bootstrap-password"
            password_file.write_text("FileOwnerPassword123!\n", encoding="utf-8")
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)

            with patch.dict(
                os.environ,
                {
                    "LINGSHU_GATE_ADMIN_USERNAME": "owner",
                    "LINGSHU_GATE_ADMIN_PASSWORD": "InlineOwnerPassword123!",
                    "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": str(password_file),
                },
            ), self.assertRaisesRegex(ValueError, "mutually exclusive"):
                AuthStore(settings, database)

            self.assertFalse(database.query_one("SELECT id FROM users"))

    def test_invalid_password_file_is_rejected_before_user_creation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            password_file = root / "bootstrap-password"
            password_file.write_text("line-one\nline-two\n", encoding="utf-8")
            password_file.chmod(0o600)
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)

            with patch.dict(
                os.environ,
                {
                    "LINGSHU_GATE_ADMIN_USERNAME": "owner",
                    "LINGSHU_GATE_ADMIN_PASSWORD": "",
                    "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": str(password_file),
                },
            ), self.assertRaisesRegex(ValueError, "exactly one non-empty line"):
                AuthStore(settings, database)

            self.assertFalse(database.query_one("SELECT id FROM users"))

    def test_bootstrap_recovers_from_failure_after_atomic_credentials_publish(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            root = Path(temp_dir)
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)

            with patch.object(AuthStore, "_insert_user", side_effect=RuntimeError("boom")):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    AuthStore(settings, database)

            credentials_path = root / "initial-admin-credentials.json"
            credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
            store = AuthStore(settings, database)
            principal, _, _ = store.login(
                username=credentials["username"],
                password=credentials["password"],
            )
            self.assertTrue(principal.must_change_password)

    def test_concurrent_instances_create_exactly_one_random_admin(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            root = Path(temp_dir)
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)
            barrier = Barrier(4)

            def initialize() -> AuthStore:
                barrier.wait()
                return AuthStore(settings, database)

            with ThreadPoolExecutor(max_workers=4) as executor:
                stores = list(executor.map(lambda _: initialize(), range(4)))

            users = database.query_all("SELECT id, username FROM users")
            assignments = database.query_all("SELECT user_id, role_id FROM user_roles")
            self.assertEqual(len(users), 1)
            self.assertEqual(len(assignments), 1)
            credentials = json.loads(
                stores[0].initial_admin_credentials_path.read_text(encoding="utf-8")
            )
            principal, _, _ = stores[0].login(
                username=credentials["username"],
                password=credentials["password"],
            )
            self.assertTrue(principal.must_change_password)

    def test_create_user_rolls_back_when_role_assignment_fails(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            root = Path(temp_dir)
            settings = Settings(
                data_dir=root,
                db_url=f"sqlite:///{root / 'gate.db'}",
                auth_enabled=True,
            )
            database = SQLiteDatabase(settings.db_url, root)
            AccessControlStore(database)
            store = AuthStore(settings, database)
            database.execute("DELETE FROM roles WHERE code = 'viewer'")

            with self.assertRaisesRegex(RuntimeError, "role is not initialized"):
                store.create_user(
                    username="rolled-back-viewer",
                    password="ViewerPassword123!",
                    role="viewer",
                )

            self.assertFalse(
                database.query_one(
                    "SELECT id FROM users WHERE username = ?",
                    ("rolled-back-viewer",),
                )
            )

    def test_first_login_is_restricted_until_password_change(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": temp_dir,
                "LINGSHU_GATE_CONFIG_DIR": str(Path(temp_dir) / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": temp_dir,
                "LINGSHU_GATE_ADMIN_USERNAME": "",
                "LINGSHU_GATE_ADMIN_PASSWORD": "",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            from lingshu_gate.main import create_app

            app = create_app()
            credentials = json.loads(
                app.state.auth_store.initial_admin_credentials_path.read_text(
                    encoding="utf-8"
                )
            )
            with TestClient(app) as client:
                login = client.post("/v1/auth/login", json=credentials)
                self.assertEqual(login.status_code, 200)
                self.assertTrue(login.json()["user"]["must_change_password"])
                self.assertEqual(client.get("/v1/auth/me").status_code, 200)

                restricted = client.get("/v1/auth/tokens")
                self.assertEqual(restricted.status_code, 403)
                self.assertEqual(restricted.json()["detail"], "password change required")

                changed = client.post(
                    "/v1/auth/password",
                    json={"password": "ReplacementPassword123!"},
                )
                self.assertEqual(changed.status_code, 200)
                self.assertEqual(client.get("/v1/auth/me").status_code, 401)
                relogin = client.post(
                    "/v1/auth/login",
                    json={
                        "username": credentials["username"],
                        "password": "ReplacementPassword123!",
                    },
                )
                self.assertEqual(relogin.status_code, 200)
                self.assertEqual(client.get("/v1/auth/tokens").status_code, 200)

    def test_secure_cookie_flag_is_configurable_for_tls_proxy_deployments(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": temp_dir,
                "LINGSHU_GATE_CONFIG_DIR": str(Path(temp_dir) / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": temp_dir,
                "LINGSHU_GATE_ADMIN_USERNAME": "owner",
                "LINGSHU_GATE_ADMIN_PASSWORD": "OwnerPassword123!",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
                "LINGSHU_GATE_AUTH_COOKIE_SECURE": "true",
            },
        ):
            from lingshu_gate.main import create_app

            app = create_app()
            with TestClient(app, base_url="https://testserver") as client:
                response = client.post(
                    "/v1/auth/login",
                    json={
                        "username": "owner",
                        "password": "OwnerPassword123!",
                    },
                )

            self.assertEqual(response.status_code, 200)
            set_cookie = response.headers["set-cookie"].lower()
            self.assertIn("secure", set_cookie)
            self.assertIn("httponly", set_cookie)
            self.assertIn("samesite=lax", set_cookie)

        with patch.dict(
            os.environ,
            {"LINGSHU_GATE_AUTH_COOKIE_SECURE": "false"},
        ):
            self.assertFalse(Settings.from_env().auth_cookie_secure)


if __name__ == "__main__":
    unittest.main()

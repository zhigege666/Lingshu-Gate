"""MCP 配置 REST 写入顺序与失败补偿测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lingshu_gate.mcp_config_store import McpConfigStore


class McpConfigAtomicityTest(unittest.TestCase):
    @staticmethod
    def _environment(root: Path) -> dict[str, str]:
        return {
            "LINGSHU_GATE_DATA_DIR": str(root / "data"),
            "LINGSHU_GATE_CONFIG_DIR": str(root / "mcp.d"),
            "LINGSHU_GATE_ALLOWED_ROOT": str(root),
            "LINGSHU_GATE_AUTH_ENABLED": "true",
            "LINGSHU_GATE_ADMIN_USERNAME": "atomic-admin",
            "LINGSHU_GATE_ADMIN_PASSWORD": "AtomicAdmin123!",
            "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
        }

    @staticmethod
    def _manifest(server_id: str, endpoint: str, header: str) -> dict[str, object]:
        return {
            "id": server_id,
            "enabled": True,
            "launch": {"type": "external"},
            "transport": {
                "type": "streamable_http",
                "endpoint": endpoint,
                "headers": {"X-Atomic-Secret": header},
            },
            "auto_start": False,
            "user_credentials": [
                {
                    "id": "api_token",
                    "name": "API Token",
                    "injection": {
                        "type": "http_header",
                        "name": "Authorization",
                        "template": "Bearer {value}",
                    },
                }
            ],
        }

    @staticmethod
    def _login(client: TestClient) -> str:
        response = client.post(
            "/v1/auth/login",
            json={"username": "atomic-admin", "password": "AtomicAdmin123!"},
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        user_id = str(response.json()["user"]["id"])
        changed = client.post(
            "/v1/auth/password",
            json={"password": "AtomicAdminChanged123!"},
        )
        if changed.status_code != 200:
            raise AssertionError(changed.text)
        relogin = client.post(
            "/v1/auth/login",
            json={
                "username": "atomic-admin",
                "password": "AtomicAdminChanged123!",
            },
        )
        if relogin.status_code != 200:
            raise AssertionError(relogin.text)
        return user_id

    def _assert_store_failure_preserves_manifest(self, failure_target: str) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            config_dir = Path(temp_dir) / "mcp.d"
            store = McpConfigStore(config_dir)
            store.save_config(
                self._manifest(
                    "atomic-store",
                    "https://old.example.test/mcp",
                    "old-disk-secret",
                ),
                overwrite=False,
            )
            manifest_path = config_dir / "atomic-store.yaml"
            original_bytes = manifest_path.read_bytes()

            with patch(
                f"lingshu_gate.mcp_config_store.{failure_target}",
                side_effect=OSError(f"simulated {failure_target} failure"),
            ):
                with self.assertRaises(OSError):
                    store.save_config(
                        self._manifest(
                            "atomic-store",
                            "https://new.example.test/mcp",
                            "new-disk-secret",
                        ),
                        overwrite=True,
                    )

            self.assertEqual(manifest_path.read_bytes(), original_bytes)
            self.assertEqual(
                store.load_manifest("atomic-store").transport.endpoint,
                "https://old.example.test/mcp",
            )
            self.assertEqual(list(config_dir.glob(".atomic-store.yaml.*.tmp")), [])

    def test_store_fsync_failure_preserves_old_manifest_and_cleans_temp(self) -> None:
        self._assert_store_failure_preserves_manifest("os.fsync")

    def test_store_replace_failure_preserves_old_manifest_and_cleans_temp(self) -> None:
        self._assert_store_failure_preserves_manifest("os.replace")

    def test_create_apply_failure_removes_new_disk_config_and_skips_credentials(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            self._environment(Path(temp_dir)),
        ):
            from lingshu_gate.main import create_app

            app = create_app()
            with TestClient(
                app,
                base_url="https://localhost",
                raise_server_exceptions=False,
            ) as client:
                user_id = self._login(client)
                with patch.object(
                    app.state.mcp_runtime,
                    "apply_manifest",
                    side_effect=RuntimeError("simulated create apply failure"),
                ):
                    response = client.post(
                        "/v1/mcp/configs",
                        json={
                            "manifest": self._manifest(
                                "atomic-create",
                                "https://old.example.test/mcp",
                                "new-disk-secret",
                            ),
                            "apply": True,
                            "start": False,
                            "user_credential_values": {"api_token": "new-user-secret"},
                        },
                    )

                self.assertEqual(response.status_code, 500)
                with self.assertRaises(KeyError):
                    app.state.mcp_config_store.load_manifest("atomic-create")
                self.assertIsNone(
                    app.state.user_credential_store.get_binding(
                        user_id,
                        "atomic-create",
                        "api_token",
                    )
                )

    def test_update_apply_failure_restores_raw_manifest_and_skips_credentials(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            self._environment(Path(temp_dir)),
        ):
            from lingshu_gate.main import create_app

            app = create_app()
            with TestClient(
                app,
                base_url="https://localhost",
                raise_server_exceptions=False,
            ) as client:
                user_id = self._login(client)
                app.state.mcp_config_store.save_config(
                    self._manifest(
                        "atomic-update",
                        "https://old.example.test/mcp",
                        "old-disk-secret",
                    ),
                    overwrite=False,
                )
                with patch.object(
                    app.state.mcp_runtime,
                    "apply_manifest",
                    side_effect=RuntimeError("simulated update apply failure"),
                ):
                    response = client.put(
                        "/v1/mcp/configs/atomic-update",
                        json={
                            "manifest": self._manifest(
                                "atomic-update",
                                "https://new.example.test/mcp",
                                "new-disk-secret",
                            ),
                            "apply": True,
                            "start": False,
                            "user_credential_values": {"api_token": "new-user-secret"},
                        },
                    )

                self.assertEqual(response.status_code, 500)
                restored = app.state.mcp_config_store.load_manifest("atomic-update")
                self.assertEqual(
                    restored.transport.endpoint,
                    "https://old.example.test/mcp",
                )
                self.assertEqual(
                    restored.transport.headers["X-Atomic-Secret"],
                    "old-disk-secret",
                )
                self.assertIsNone(
                    app.state.user_credential_store.get_binding(
                        user_id,
                        "atomic-update",
                        "api_token",
                    )
                )

    def test_delete_runtime_failure_preserves_disk_config_and_credentials(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            self._environment(Path(temp_dir)),
        ):
            from lingshu_gate.main import create_app

            app = create_app()
            with TestClient(
                app,
                base_url="https://localhost",
                raise_server_exceptions=False,
            ) as client:
                user_id = self._login(client)
                manifest_data = self._manifest(
                    "atomic-delete",
                    "https://delete.example.test/mcp",
                    "disk-secret",
                )
                app.state.mcp_config_store.save_config(manifest_data, overwrite=False)
                app.state.mcp_runtime.apply_manifest(
                    app.state.mcp_config_store.load_manifest("atomic-delete"),
                    start=False,
                    source="test_setup",
                )
                app.state.user_credential_store.save_binding(
                    user_id=user_id,
                    server_id="atomic-delete",
                    slot_id="api_token",
                    value="saved-user-secret",
                )

                with patch.object(
                    app.state.mcp_runtime,
                    "remove_manifest",
                    side_effect=RuntimeError("simulated runtime remove failure"),
                ):
                    response = client.delete("/v1/mcp/configs/atomic-delete")

                self.assertEqual(response.status_code, 500)
                self.assertEqual(
                    app.state.mcp_config_store.load_manifest("atomic-delete").id,
                    "atomic-delete",
                )
                self.assertIsNotNone(
                    app.state.user_credential_store.get_binding(
                        user_id,
                        "atomic-delete",
                        "api_token",
                    )
                )

    def test_delete_disk_failure_restores_only_the_target_runtime(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir, patch.dict(
            os.environ,
            self._environment(Path(temp_dir)),
        ):
            from lingshu_gate.main import create_app

            app = create_app()
            with TestClient(
                app,
                base_url="https://localhost",
                raise_server_exceptions=False,
            ) as client:
                self._login(client)
                manifest_data = self._manifest(
                    "atomic-delete-rollback",
                    "https://delete-rollback.example.test/mcp",
                    "disk-secret",
                )
                app.state.mcp_config_store.save_config(manifest_data, overwrite=False)
                app.state.mcp_runtime.apply_manifest(
                    app.state.mcp_config_store.load_manifest("atomic-delete-rollback"),
                    start=False,
                    source="test_setup",
                )

                with patch.object(
                    app.state.mcp_config_store,
                    "delete_config",
                    side_effect=OSError("simulated disk delete failure"),
                ):
                    response = client.delete(
                        "/v1/mcp/configs/atomic-delete-rollback"
                    )

                self.assertEqual(response.status_code, 500)
                self.assertTrue(
                    app.state.mcp_runtime.has_server("atomic-delete-rollback")
                )
                restored = app.state.mcp_runtime.get_server("atomic-delete-rollback")
                self.assertEqual(restored.status, "external")
                self.assertEqual(restored.desired_state, "stopped")
                self.assertEqual(
                    app.state.mcp_config_store.load_manifest(
                        "atomic-delete-rollback"
                    ).id,
                    "atomic-delete-rollback",
                )


if __name__ == "__main__":
    unittest.main()

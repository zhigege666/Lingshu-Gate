"""用户下游 MCP 凭据隔离与 Manifest 约束测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import ValidationError

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.models import McpConfigSaveRequest
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.user_credential_store import UserCredentialBindingError, UserCredentialStore


class _CapturingHttpClient:
    captured_headers: list[dict[str, str]] = []

    def __init__(
        self,
        manifest: McpServerManifest,
        settings: Settings,
        log_sink: Any = None,
        redaction_values: Any = (),
    ) -> None:
        self.manifest = manifest
        self.settings = settings
        self.session_id = None
        self.pid = None

    def start(self) -> None:
        self.captured_headers.append(dict(self.manifest.transport.headers))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "arguments": arguments}

    def stop(self) -> None:
        return None


class UserDownstreamCredentialTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_dir.name)
        self.settings = Settings(
            data_dir=self.root,
            db_url=f"sqlite:///{self.root / 'gate.db'}",
        )
        self.database = SQLiteDatabase(self.settings.db_url, self.root)
        now = "2026-07-28T00:00:00+00:00"
        for user_id, username in (("user-a", "a"), ("user-b", "b")):
            self.database.execute(
                """
                INSERT INTO users
                    (id, username, password_hash, created_at, updated_at,
                     display_name, status, must_change_password)
                VALUES (?, ?, 'hash', ?, ?, '', 'active', 0)
                """,
                (user_id, username, now, now),
            )
        self.store = UserCredentialStore(self.database, self.root)
        self.manifest = McpServerManifest.model_validate(
            {
                "id": "downstream-service",
                "launch": {"type": "external"},
                "transport": {
                    "type": "streamable_http",
                    "endpoint": "https://mcp.example.test/mcp",
                    "headers": {"X-Shared": "discovery"},
                },
                "user_credentials": [
                    {
                        "id": "access_token",
                        "name": "Access token",
                        "required": True,
                        "injection": {
                            "type": "http_header",
                            "name": "Authorization",
                            "template": "Bearer {value}",
                        },
                    }
                ],
            }
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_two_users_resolve_different_values_without_plaintext_metadata(self) -> None:
        self.store.save_binding(
            user_id="user-a",
            server_id="downstream-service",
            slot_id="access_token",
            value="token-a",
        )
        self.store.save_binding(
            user_id="user-b",
            server_id="downstream-service",
            slot_id="access_token",
            value="token-b",
        )

        values_a, missing_a = self.store.resolve_slots(
            user_id="user-a",
            server_id="downstream-service",
            slots=self.manifest.user_credentials,
        )
        values_b, missing_b = self.store.resolve_slots(
            user_id="user-b",
            server_id="downstream-service",
            slots=self.manifest.user_credentials,
        )

        self.assertEqual(values_a, {"access_token": "token-a"})
        self.assertEqual(values_b, {"access_token": "token-b"})
        self.assertEqual(missing_a, [])
        self.assertEqual(missing_b, [])
        self.assertNotIn("token-a", str(self.store.list_bindings("user-a")))
        self.assertNotIn("token-b", str(self.store.list_bindings("user-b")))

    def test_deleting_server_bindings_removes_all_users_without_touching_other_servers(self) -> None:
        for user_id, value in (("user-a", "token-a"), ("user-b", "token-b")):
            self.store.save_binding(
                user_id=user_id,
                server_id="downstream-service",
                slot_id="access_token",
                value=value,
            )
        self.store.save_binding(
            user_id="user-a",
            server_id="other",
            slot_id="api_key",
            value="other-token",
        )

        self.assertEqual(self.store.delete_server_bindings("downstream-service"), 2)
        self.assertEqual(self.store.list_bindings("user-a")[0]["server_id"], "other")
        self.assertEqual(self.store.list_bindings("user-b"), [])

    def test_http_runtime_uses_isolated_manifest_headers_and_delete_invalidates(self) -> None:
        self.store.save_binding(
            user_id="user-a",
            server_id="downstream-service",
            slot_id="access_token",
            value="token-a",
        )
        manager = McpRuntimeManager(
            self.settings,
            ToolRegistry(),
            user_credential_store=self.store,
        )
        manager._servers["downstream-service"] = McpServerRuntime(
            manifest=self.manifest,
            state=McpServerState.RUNNING,
            client=object(),  # type: ignore[arg-type]
        )
        _CapturingHttpClient.captured_headers = []
        with patch(
            "lingshu_gate.mcp_runtime.StreamableHttpMcpClient",
            _CapturingHttpClient,
        ):
            result = manager.invoke_mcp_tool_for_user(
                "downstream-service",
                "search",
                {"query": "docs"},
                user_id="user-a",
            )

        self.assertEqual(result["name"], "search")
        self.assertEqual(
            _CapturingHttpClient.captured_headers,
            [{"X-Shared": "discovery", "Authorization": "Bearer token-a"}],
        )
        self.assertEqual(self.manifest.transport.headers, {"X-Shared": "discovery"})

        self.store.delete_binding(
            user_id="user-a",
            server_id="downstream-service",
            slot_id="access_token",
        )
        with self.assertRaisesRegex(UserCredentialBindingError, "required user credential is missing"):
            manager.invoke_mcp_tool_for_user(
                "downstream-service",
                "search",
                {},
                user_id="user-a",
            )

    def test_stdio_manifest_rejects_user_credentials(self) -> None:
        with self.assertRaisesRegex(ValidationError, "user_credentials currently requires"):
            McpServerManifest.model_validate(
                {
                    "id": "unsafe-stdio",
                    "launch": {"type": "managed_process", "command": "node"},
                    "transport": {"type": "stdio"},
                    "user_credentials": [
                        {
                            "id": "token",
                            "name": "Token",
                            "injection": {
                                "type": "http_header",
                                "name": "Authorization",
                            },
                        }
                    ],
                }
            )

    def test_protected_http_header_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "protected HTTP header"):
            McpServerManifest.model_validate(
                {
                    "id": "unsafe-header",
                    "launch": {"type": "external"},
                    "transport": {
                        "type": "streamable_http",
                        "endpoint": "https://mcp.example.test/mcp",
                    },
                    "user_credentials": [
                        {
                            "id": "session",
                            "name": "Session",
                            "injection": {
                                "type": "http_header",
                                "name": "Mcp-Session-Id",
                            },
                        }
                    ],
                }
            )

    def test_one_time_config_values_are_not_part_of_manifest_or_model_dump(self) -> None:
        request = McpConfigSaveRequest(
            manifest=self.manifest.model_dump(mode="json", exclude={"manifest_path"}),
            user_credential_values={"access_token": "token-a"},
        )

        self.assertNotIn("user_credential_values", request.manifest)
        self.assertNotIn("user_credential_values", request.model_dump(mode="json"))
        self.assertNotIn("token-a", str(request.model_dump(mode="json")))


if __name__ == "__main__":
    unittest.main()

"""受管 Streamable HTTP MCP Manifest 回归测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_managed_http_client import ManagedHttpMcpClient
from lingshu_gate.mcp_manifest import LaunchConfig, McpServerManifest, PackageConfig
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from lingshu_gate.mcp_runtime import (
    McpRuntimeManager,
    McpServerRuntime,
    McpServerState,
)
from lingshu_gate.mcp_runtime_state_store import (
    McpRuntimeIntent,
    McpRuntimeStateStore,
)
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.runtime_environment import derive_launch_capabilities


def _managed_http_manifest(**overrides: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "id": "managed-http-test",
        "launch": {
            "type": "managed_process",
            "command": "example-server",
            "args": ["--foreground"],
        },
        "transport": {
            "type": "streamable_http",
            "endpoint": "http://127.0.0.1:3120/mcp",
        },
        "timeout_seconds": 3,
        "auto_start": True,
        "restart_policy": {
            "enabled": True,
            "health_check": {
                "enabled": True,
                "method": "tools_list",
                "interval_seconds": 30,
                "timeout_seconds": 5,
                "failure_threshold": 2,
            },
        },
    }
    manifest.update(overrides)
    return manifest


class _FakeProcess:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.pid = 4321
        self.returncode: int | None = None
        self.stdout: list[str] = []
        self.stderr: list[str] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.events.append("process-terminate")
        self.returncode = -15

    def kill(self) -> None:
        self.events.append("process-kill")
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _RetryingHttpClient:
    attempts = 0
    events: list[str] = []

    def __init__(
        self,
        manifest: McpServerManifest,
        settings: Settings,
        log_sink: Any = None,
        redaction_values: Any = (),
    ) -> None:
        self.manifest = manifest
        self.settings = settings
        self.initialized = False
        self.session_id = None
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}

    def start(self) -> None:
        type(self).attempts += 1
        if type(self).attempts < 3:
            raise ConnectionError("endpoint is not ready")
        self.initialized = True

    def stop(self) -> None:
        type(self).events.append("http-stop")
        self.initialized = False

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "status", "inputSchema": {"type": "object"}}]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "arguments": arguments}

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return {"method": method}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        return None


class _RuntimeManagedHttpClient:
    created: list["_RuntimeManagedHttpClient"] = []

    def __init__(self, manifest: McpServerManifest, settings: Settings, log_sink: Any = None) -> None:
        self.manifest = manifest
        self.settings = settings
        self.process = None
        self.pid = 9876
        self.started = False
        self.stopped = False
        self.last_stdout: list[str] = []
        self.last_stderr: list[str] = []
        type(self).created.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "status", "inputSchema": {"type": "object"}}]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "arguments": arguments}

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return {"tools": []}


class _ExternalHttpClient:
    created: list["_ExternalHttpClient"] = []

    def __init__(self, manifest: McpServerManifest, settings: Settings, log_sink: Any = None) -> None:
        self.manifest = manifest
        self.settings = settings
        self.process = None
        self.pid = None
        self.started = False
        self.stopped = False
        self.last_stdout: list[str] = []
        self.last_stderr: list[str] = []
        type(self).created.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "external-status", "inputSchema": {"type": "object"}}]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "arguments": arguments}


class ManagedHttpManifestTest(unittest.TestCase):
    def test_manifest_schema_exposes_only_implemented_capabilities(self) -> None:
        self.assertEqual(
            set(LaunchConfig.model_json_schema()["properties"]["type"]["enum"]),
            {"managed_process", "managed_container", "external"},
        )
        self.assertEqual(
            PackageConfig.model_json_schema()["properties"]["manager"]["const"],
            "npm",
        )
        self.assertEqual(
            set(derive_launch_capabilities("unavailable")),
            {"managed_process", "managed_container", "external"},
        )
        core_capabilities = derive_launch_capabilities("native", "core")
        self.assertFalse(core_capabilities["managed_process"]["available"])
        self.assertFalse(core_capabilities["managed_container"]["available"])
        self.assertTrue(core_capabilities["external"]["available"])

    def test_runtime_capability_role_rejects_unknown_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime_role"):
            derive_launch_capabilities("unavailable", "unknown")

    def test_container_preflight_reports_runtime_and_transport_support(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                config_dir=root / "mcp.d",
                data_dir=root / "data",
                allowed_root=root,
                db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
                docker_bin="docker-gate-test",
            )
            manifest = {
                "id": "container-test",
                "launch": {
                    "type": "managed_container",
                    "image": "local/gate-test@sha256:" + "a" * 64,
                },
                "transport": {"type": "stdio"},
                "auto_start": False,
            }
            with patch(
                "lingshu_gate.mcp_manifest_validation.resolve_docker_binary",
                return_value="/usr/bin/docker-gate-test",
            ):
                available = validate_mcp_manifest(
                    settings,
                    McpConfigStore(settings.config_dir),
                    manifest,
                )
            with patch(
                "lingshu_gate.mcp_manifest_validation.resolve_docker_binary",
                side_effect=FileNotFoundError,
            ):
                unavailable = validate_mcp_manifest(
                    settings,
                    McpConfigStore(settings.config_dir),
                    manifest,
                )

        available_checks = {item["name"]: item for item in available["checks"]}
        unavailable_checks = {
            item["name"]: item for item in unavailable["checks"]
        }
        self.assertEqual(available_checks["launch.managed_container"]["severity"], "ok")
        self.assertEqual(available_checks["transport.stdio"]["severity"], "ok")
        self.assertIn(
            "managed_container",
            available_checks["transport.stdio"]["message"],
        )
        self.assertEqual(
            unavailable_checks["launch.managed_container"]["severity"],
            "warning",
        )

    def test_container_preflight_rejects_mount_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            allowed_root = root / "allowed"
            allowed_root.mkdir()
            outside = root / "outside"
            outside.mkdir()
            settings = Settings(
                config_dir=root / "mcp.d",
                data_dir=root / "data",
                allowed_root=allowed_root,
                db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
                docker_bin="docker-gate-test",
            )
            result = validate_mcp_manifest(
                settings,
                McpConfigStore(settings.config_dir),
                {
                    "id": "outside-mount",
                    "launch": {
                        "type": "managed_container",
                        "image": "local/gate-test@sha256:" + "b" * 64,
                        "mounts": [
                            {
                                "source": str(outside),
                                "target": "/workspace",
                                "read_only": True,
                            }
                        ],
                    },
                    "transport": {"type": "stdio"},
                    "auto_start": False,
                },
            )

        checks = {item["name"]: item for item in result["checks"]}
        self.assertFalse(result["can_apply"])
        self.assertEqual(checks["launch.mounts.0.source"]["severity"], "error")
        self.assertIn("outside allowed_root", checks["launch.mounts.0.source"]["message"])

    def test_managed_http_keeps_restart_and_health_policy_enabled(self) -> None:
        manifest = McpServerManifest.model_validate(_managed_http_manifest())

        self.assertEqual(manifest.launch.type, "managed_process")
        self.assertEqual(manifest.transport.type, "streamable_http")
        self.assertTrue(manifest.restart_policy.enabled)
        self.assertTrue(manifest.restart_policy.health_check.enabled)

    def test_preflight_reports_managed_http_and_restart_support(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                config_dir=root / "mcp.d",
                data_dir=root / "data",
                allowed_root=root,
                db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
            )
            result = validate_mcp_manifest(
                settings,
                McpConfigStore(settings.config_dir),
                _managed_http_manifest(),
            )

        checks = {item["name"]: item for item in result["checks"]}
        self.assertTrue(result["ok"], result)
        self.assertEqual(checks["transport.managed_http"]["severity"], "ok")
        self.assertEqual(checks["restart_policy"]["severity"], "ok")


class ManagedHttpClientTest(unittest.TestCase):
    def test_discovery_is_retried_and_stop_closes_client_before_process(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, allowed_root=root)
            manifest = McpServerManifest.model_validate(_managed_http_manifest())
            events: list[str] = []
            fake_process = _FakeProcess(events)
            _RetryingHttpClient.attempts = 0
            _RetryingHttpClient.events = events

            with (
                patch(
                    "lingshu_gate.mcp_managed_http_client.subprocess.Popen",
                    return_value=fake_process,
                ),
                patch(
                    "lingshu_gate.mcp_managed_http_client.StreamableHttpMcpClient",
                    _RetryingHttpClient,
                ),
            ):
                client = ManagedHttpMcpClient(manifest, settings)
                client.start()
                self.assertEqual(_RetryingHttpClient.attempts, 3)
                self.assertEqual(client.pid, 4321)
                self.assertEqual(client.list_tools()[0]["name"], "status")
                client.stop()

        self.assertEqual(events[-2:], ["http-stop", "process-terminate"])

    def test_managed_process_does_not_inherit_control_plane_environment(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, allowed_root=root)
            payload = _managed_http_manifest()
            payload["launch"]["env"] = {"CHILD_SETTING": "explicit"}
            manifest = McpServerManifest.model_validate(payload)
            fake_process = _FakeProcess([])

            with (
                patch.dict(
                    "os.environ",
                    {
                        "PATH": "/usr/bin",
                        "LINGSHU_GATE_BOOTSTRAP_PASSWORD": "must-not-leak",
                    },
                    clear=True,
                ),
                patch(
                    "lingshu_gate.mcp_managed_http_client.subprocess.Popen",
                    return_value=fake_process,
                ) as popen,
            ):
                client = ManagedHttpMcpClient(manifest, settings)
                client._start_process()

            child_env = popen.call_args.kwargs["env"]
            self.assertEqual(child_env["PATH"], "/usr/bin")
            self.assertEqual(child_env["CHILD_SETTING"], "explicit")
            self.assertNotIn("LINGSHU_GATE_BOOTSTRAP_PASSWORD", child_env)

    def test_managed_stream_payloads_are_suppressed_by_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, allowed_root=root)
            manifest = McpServerManifest.model_validate(_managed_http_manifest())
            captured: list[tuple[str, str, str, dict[str, Any]]] = []
            client = ManagedHttpMcpClient(manifest, settings, log_sink=lambda *args: captured.append(args))
            client._redaction_values = ("top-secret",)

            client._read_stream(["token=top-secret\n"], "stderr")

            self.assertEqual(
                client.last_stderr,
                ["[MCP managed HTTP stderr payload suppressed]"],
            )
            self.assertNotIn("top-secret", repr(captured))


class ManagedHttpRuntimeTest(unittest.TestCase):
    def _manager(self, root: Path) -> McpRuntimeManager:
        settings = Settings(
            config_dir=root / "mcp.d",
            data_dir=root / "data",
            allowed_root=root,
            db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
        )
        return McpRuntimeManager(
            settings,
            ToolRegistry(),
            state_store=McpRuntimeStateStore(
                SQLiteDatabase(settings.db_url, settings.data_dir)
            ),
        )

    def test_runtime_selects_managed_http_client_and_preserves_stop_semantics(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            manager = self._manager(root)
            manifest = McpServerManifest.model_validate(_managed_http_manifest())
            manager._servers[manifest.id] = McpServerRuntime(
                manifest=manifest,
                desired_intent=McpRuntimeIntent(
                    manifest.id,
                    "running",
                    "test",
                    None,
                ),
            )
            _RuntimeManagedHttpClient.created = []

            with patch(
                "lingshu_gate.mcp_runtime.ManagedHttpMcpClient",
                _RuntimeManagedHttpClient,
            ):
                started = manager.start_server(manifest.id)
                self.assertEqual(started.status, McpServerState.RUNNING.value)
                self.assertEqual(started.pid, 9876)
                self.assertEqual(started.tool_count, 1)
                stopped = manager.stop_server(manifest.id)

        self.assertEqual(stopped.status, McpServerState.STOPPED.value)
        self.assertTrue(_RuntimeManagedHttpClient.created[0].started)
        self.assertTrue(_RuntimeManagedHttpClient.created[0].stopped)

    def test_external_http_still_only_connects_and_disconnects_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            manifest = McpServerManifest.model_validate(
                {
                    "id": "external-http",
                    "launch": {"type": "external"},
                    "transport": {
                        "type": "streamable_http",
                        "endpoint": "http://127.0.0.1:3999/mcp",
                    },
                    "auto_start": False,
                }
            )
            manager._servers[manifest.id] = McpServerRuntime(
                manifest=manifest,
                state=McpServerState.EXTERNAL,
                desired_intent=McpRuntimeIntent(
                    manifest.id,
                    "running",
                    "test",
                    None,
                ),
            )
            _ExternalHttpClient.created = []

            with patch(
                "lingshu_gate.mcp_runtime.StreamableHttpMcpClient",
                _ExternalHttpClient,
            ):
                started = manager.start_server(manifest.id)
                stopped = manager.stop_server(manifest.id)

        self.assertEqual(started.status, McpServerState.RUNNING.value)
        self.assertIsNone(started.pid)
        self.assertEqual(stopped.status, McpServerState.STOPPED.value)
        self.assertTrue(_ExternalHttpClient.created[0].started)
        self.assertTrue(_ExternalHttpClient.created[0].stopped)

    def test_managed_http_health_failure_reuses_existing_restart_policy(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            manager = self._manager(Path(temp_dir))
            manifest = McpServerManifest.model_validate(_managed_http_manifest())
            manifest.restart_policy.health_check.failure_threshold = 1
            client = _RuntimeManagedHttpClient(manifest, manager.settings)
            runtime = McpServerRuntime(
                manifest=manifest,
                state=McpServerState.RUNNING,
                client=client,
                desired_intent=McpRuntimeIntent(
                    manifest.id,
                    "running",
                    "test",
                    None,
                ),
            )
            manager._servers[manifest.id] = runtime

            with (
                patch.object(manager, "_sleep_or_cancel", return_value=False),
                patch.object(
                    client,
                    "request",
                    side_effect=RuntimeError("health endpoint failed"),
                ),
                patch.object(manager, "_schedule_restart_locked") as schedule,
            ):
                manager._health_loop(manifest.id, runtime, client)

        self.assertEqual(runtime.state, McpServerState.FAILED)
        self.assertIsNone(runtime.client)
        self.assertTrue(client.stopped)
        schedule.assert_called_once_with(
            manifest.id,
            runtime,
            reason="health_check_failed",
            returncode=None,
        )


if __name__ == "__main__":
    unittest.main()

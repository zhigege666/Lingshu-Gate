"""Managed MCP child-process secret isolation regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lingshu_gate.config import Settings
from lingshu_gate.mcp_container import build_docker_command, resolve_docker_binary
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import StdioMcpClient
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.redaction import REDACTED, redact_command, redact_text, redact_value
from lingshu_gate.subprocess_environment import (
    build_docker_subprocess_environment,
    build_subprocess_environment,
)


class McpProcessSecurityTest(unittest.TestCase):
    def test_control_plane_environment_is_not_inherited(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PATH": "/usr/bin",
                "HOME": "/tmp/operator",
                "LINGSHU_GATE_ADMIN_PASSWORD": "control-plane-secret",
                "UNRELATED_SECRET": "also-private",
            },
            clear=True,
        ):
            child_env = build_subprocess_environment({"EXPLICIT_CHILD_VALUE": "allowed"})

        self.assertEqual(child_env["PATH"], "/usr/bin")
        self.assertEqual(child_env["HOME"], "/tmp/operator")
        self.assertEqual(child_env["EXPLICIT_CHILD_VALUE"], "allowed")
        self.assertNotIn("LINGSHU_GATE_ADMIN_PASSWORD", child_env)
        self.assertNotIn("UNRELATED_SECRET", child_env)

    def test_docker_environment_values_never_enter_argv(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            manifest = McpServerManifest.model_validate(
                {
                    "id": "secure-container",
                    "launch": {
                        "type": "managed_container",
                        "image": "example.invalid/mcp@sha256:" + "a" * 64,
                        "environment": {"SERVER_TOKEN": "credential_ref:server-token"},
                    },
                    "transport": {"type": "stdio"},
                }
            )

            command = build_docker_command(
                manifest,
                {"SERVER_TOKEN": "resolved-secret"},
                allowed_root=root,
            )

        self.assertIn("SERVER_TOKEN", command)
        self.assertNotIn("resolved-secret", command)
        self.assertFalse(any(item.startswith("SERVER_TOKEN=") for item in command))

    def test_docker_cli_controls_are_inherited_only_from_the_operator(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PATH": "/usr/bin",
                "DOCKER_HOST": "unix:///trusted/docker.sock",
                "LINGSHU_GATE_ADMIN_PASSWORD": "control-plane-secret",
            },
            clear=True,
        ):
            environment = build_docker_subprocess_environment(
                {"SERVER_TOKEN": "child-secret"}
            )

        self.assertEqual(environment["DOCKER_HOST"], "unix:///trusted/docker.sock")
        self.assertEqual(environment["SERVER_TOKEN"], "child-secret")
        self.assertNotIn("LINGSHU_GATE_ADMIN_PASSWORD", environment)

        for protected_name in (
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONFIG",
            "LINGSHU_GATE_ADMIN_PASSWORD",
            "LD_PRELOAD",
            "PYTHONPATH",
            "HTTPS_PROXY",
            "SSL_CERT_FILE",
        ):
            with self.subTest(protected_name=protected_name), self.assertRaisesRegex(
                ValueError,
                protected_name,
            ):
                build_docker_subprocess_environment({protected_name: "attacker-value"})

    def test_container_manifest_requires_digest_structured_read_only_mounts_and_bounds(self) -> None:
        digest_image = "example.invalid/mcp@sha256:" + "c" * 64
        for image in ("example.invalid/mcp:latest", "example.invalid/mcp@sha256:short"):
            with self.subTest(image=image), self.assertRaisesRegex(ValueError, "sha256"):
                McpServerManifest.model_validate(
                    {
                        "id": "mutable-image",
                        "launch": {"type": "managed_container", "image": image},
                        "transport": {"type": "stdio"},
                    }
                )
        for protected_name in ("DOCKER_HOST", "LINGSHU_GATE_PORT"):
            with self.subTest(protected_name=protected_name), self.assertRaisesRegex(
                ValueError,
                protected_name,
            ):
                McpServerManifest.model_validate(
                    {
                        "id": "protected-environment",
                        "launch": {
                            "type": "managed_container",
                            "image": digest_image,
                            "environment": {protected_name: "attacker-value"},
                        },
                        "transport": {"type": "stdio"},
                    }
                )

        with self.assertRaisesRegex(ValueError, "volumes"):
            McpServerManifest.model_validate(
                {
                    "id": "old-mount-shape",
                    "launch": {
                        "type": "managed_container",
                        "image": digest_image,
                        "volumes": ["/host:/container:ro"],
                    },
                    "transport": {"type": "stdio"},
                }
            )
        with self.assertRaisesRegex(ValueError, "read_only"):
            McpServerManifest.model_validate(
                {
                    "id": "writeable-mount",
                    "launch": {
                        "type": "managed_container",
                        "image": digest_image,
                        "mounts": [
                            {
                                "source": str(Path.cwd()),
                                "target": "/workspace",
                                "read_only": False,
                            }
                        ],
                    },
                    "transport": {"type": "stdio"},
                }
            )
        with self.assertRaisesRegex(ValueError, "target"):
            McpServerManifest.model_validate(
                {
                    "id": "protected-target",
                    "launch": {
                        "type": "managed_container",
                        "image": digest_image,
                        "mounts": [
                            {
                                "source": str(Path.cwd()),
                                "target": "//proc",
                                "read_only": True,
                            }
                        ],
                    },
                    "transport": {"type": "stdio"},
                }
            )
        with self.assertRaisesRegex(ValueError, "less than or equal to 4"):
            McpServerManifest.model_validate(
                {
                    "id": "unbounded-container",
                    "launch": {
                        "type": "managed_container",
                        "image": digest_image,
                        "resources": {"cpus": 8},
                    },
                    "transport": {"type": "stdio"},
                }
            )

    def test_docker_command_enforces_isolation_defaults_and_mount_boundary(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            source = root / "input"
            source.mkdir()
            manifest = McpServerManifest.model_validate(
                {
                    "id": "isolated-container",
                    "launch": {
                        "type": "managed_container",
                        "image": "example.invalid/mcp@sha256:" + "d" * 64,
                        "mounts": [
                            {
                                "source": str(source),
                                "target": "/workspace",
                                "read_only": True,
                            }
                        ],
                    },
                    "transport": {"type": "stdio"},
                }
            )
            command = build_docker_command(manifest, allowed_root=root)

            self.assertIn("lingshu-gate-isolated-container", command)
            for flag, value in (
                ("--network", "none"),
                ("--cap-drop", "ALL"),
                ("--security-opt", "no-new-privileges"),
                ("--memory", "512m"),
                ("--cpus", "1.0"),
                ("--pids-limit", "128"),
            ):
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertIn("--read-only", command)
            self.assertEqual(command.count("--tmpfs"), 2)
            self.assertIn(
                f"type=bind,src={source.resolve()},dst=/workspace,readonly",
                command,
            )
            self.assertNotIn(str(source), repr(manifest.safe_dict()))

            outside = root.parent
            manifest.launch.mounts[0].source = str(outside)
            with self.assertRaisesRegex(ValueError, "outside allowed_root"):
                build_docker_command(manifest, allowed_root=root)

    def test_stdio_container_uses_operator_binary_and_fixed_policy(self) -> None:
        class FakeProcess:
            pid = 4321
            returncode = None
            stdout: list[str] = [""]
            stderr: list[str] = [""]

            @staticmethod
            def poll() -> None:
                return None

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            guard = root / "trusted-docker-guard"
            guard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            guard.chmod(0o755)
            settings = Settings(
                data_dir=root,
                allowed_root=root,
                runtime_role="local",
                docker_bin=str(guard),
            )
            manifest = McpServerManifest.model_validate(
                {
                    "id": "guarded-container",
                    "launch": {
                        "type": "managed_container",
                        "image": "example.invalid/mcp@sha256:" + "b" * 64,
                        "environment": {"SERVER_TOKEN": "child-secret"},
                    },
                    "transport": {"type": "stdio"},
                }
            )
            with (
                patch.dict(
                    "os.environ",
                    {
                        "PATH": "/usr/bin",
                    },
                    clear=True,
                ),
                patch(
                    "lingshu_gate.mcp_stdio_client.subprocess.Popen",
                    return_value=FakeProcess(),
                ) as popen,
                patch.object(StdioMcpClient, "discover", return_value={}),
            ):
                StdioMcpClient(manifest, settings).start()

            command = popen.call_args.args[0]
            environment = popen.call_args.kwargs["env"]
            self.assertEqual(command[0], resolve_docker_binary(str(guard)))
            self.assertEqual(environment["SERVER_TOKEN"], "child-secret")
            self.assertIn("--read-only", command)
            self.assertEqual(command[command.index("--network") + 1], "none")

    def test_common_secret_shapes_are_redacted(self) -> None:
        self.assertEqual(
            redact_command(["server", "--token", "secret-a", "--client-secret=secret-b"]),
            ["server", "--token", REDACTED, f"--client-secret={REDACTED}"],
        )
        self.assertNotIn(
            "secret-a",
            redact_text("Authorization: Bearer secret-a", known_secrets=("secret-a",)),
        )
        for line in (
            "API_TOKEN=top-secret",
            "AUTH_TOKEN: top-secret",
            'client_secret="top secret"',
        ):
            with self.subTest(line=line):
                self.assertNotIn("top-secret", redact_text(line))
                self.assertNotIn("top secret", redact_text(line))
        self.assertEqual(
            redact_value({"refresh_token": "secret-c", "nested": {"password": "secret-d"}}),
            {"refresh_token": REDACTED, "nested": {"password": REDACTED}},
        )

    def test_stdio_stream_diagnostics_suppress_payloads_by_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, allowed_root=root, mcp_log_payloads=False)
            manifest = McpServerManifest.model_validate(
                {
                    "id": "stdio-secret-test",
                    "launch": {"type": "managed_process", "command": "example"},
                    "transport": {"type": "stdio"},
                }
            )
            captured: list[tuple[object, ...]] = []
            client = StdioMcpClient(manifest, settings, log_sink=lambda *args: captured.append(args))
            client._redaction_values = ("top-secret",)

            client.process = type(
                "FakeProcess",
                (),
                {"stderr": ["token=top-secret\n"], "poll": lambda self: None},
            )()
            client._read_stderr()

        self.assertEqual(client.last_stderr, ["[MCP stderr payload suppressed]"])
        self.assertNotIn("top-secret", repr(captured))

    def test_stdio_info_logs_do_not_include_server_or_tool_payloads(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = Settings(data_dir=root, allowed_root=root, mcp_log_payloads=False)
            manifest = McpServerManifest.model_validate(
                {
                    "id": "stdio-log-test",
                    "launch": {"type": "managed_process", "command": "example"},
                    "transport": {"type": "stdio"},
                }
            )
            captured: list[tuple[object, ...]] = []
            client = StdioMcpClient(manifest, settings, log_sink=lambda *args: captured.append(args))
            client.request = Mock(
                return_value={
                    "supportedVersions": [MCP_PROTOCOL_VERSION],
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": "server",
                            "api_token": "server-secret",
                        }
                    },
                    "capabilities": {"tools": {"password": "capability-secret"}},
                }
            )
            with patch("lingshu_gate.mcp_stdio_client.log_event") as log_event_mock:
                client.discover()

            client.request = Mock(
                return_value={
                    "tools": [
                        {
                            "name": "example",
                            "description": "API_TOKEN=tool-secret",
                        }
                    ]
                }
            )
            with patch("lingshu_gate.mcp_stdio_client.log_event") as tools_log_mock:
                client.list_tools()

        combined = repr(log_event_mock.call_args_list) + repr(tools_log_mock.call_args_list)
        combined += repr(captured)
        for secret in ("server-secret", "capability-secret", "tool-secret"):
            self.assertNotIn(secret, combined)


if __name__ == "__main__":
    unittest.main()

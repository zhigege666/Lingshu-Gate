"""Concurrency and snapshot tests for MCP runtime read paths."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerState
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.registry import ToolRegistry


def _lock_owned(lock: threading.RLock) -> bool:
    checker = getattr(lock, "_is_owned", None)
    if not callable(checker):
        raise AssertionError("runtime lock does not expose ownership diagnostics")
    return bool(checker())


class McpRuntimeThreadSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.temp.name)
        settings = Settings(
            config_dir=root / "mcp.d",
            data_dir=root / "data",
            allowed_root=root,
            db_url=f"sqlite:///{root / 'data' / 'gate.db'}",
        )
        database = SQLiteDatabase(settings.db_url, settings.data_dir)
        self.manager = McpRuntimeManager(
            settings,
            ToolRegistry(),
            state_store=McpRuntimeStateStore(database),
        )
        manifest = McpServerManifest.model_validate(
            {
                "id": "thread-safe-demo",
                "enabled": True,
                "launch": {
                    "type": "managed_process",
                    "command": "node",
                    "args": ["server.js"],
                },
                "transport": {"type": "stdio"},
                "auto_start": False,
            }
        )
        intent = self.manager.state_store.set(
            manifest.id,
            "stopped",
            source="test",
        )
        self.runtime = self.manager._new_runtime(manifest, intent)
        self.runtime.tools = [
            {
                "name": "demo",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ]
        with self.manager._manager_lock:
            self.manager._servers[manifest.id] = self.runtime

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_get_server_holds_manager_then_runtime_lock_for_snapshot(self) -> None:
        original = self.runtime.to_response
        entered = threading.Event()
        release = threading.Event()
        writer_acquired = threading.Event()
        responses: list[Any] = []
        errors: list[BaseException] = []

        def blocking_response() -> Any:
            if not _lock_owned(self.manager._manager_lock):
                raise AssertionError("manager lock was not held while reading runtime")
            if not _lock_owned(self.runtime.lock):
                raise AssertionError("runtime lock was not held while building response")
            entered.set()
            if not release.wait(timeout=2):
                raise AssertionError("snapshot test timed out")
            return original()

        def read() -> None:
            try:
                responses.append(self.manager.get_server("thread-safe-demo"))
            except BaseException as exc:  # noqa: BLE001 - propagate thread assertion
                errors.append(exc)

        def write() -> None:
            with self.manager._manager_lock:
                writer_acquired.set()

        self.runtime.to_response = blocking_response  # type: ignore[method-assign]
        reader = threading.Thread(target=read)
        writer = threading.Thread(target=write)
        reader.start()
        self.assertTrue(entered.wait(timeout=2))
        writer.start()
        self.assertFalse(writer_acquired.wait(timeout=0.1))
        release.set()
        reader.join(timeout=2)
        writer.join(timeout=2)

        self.assertFalse(reader.is_alive())
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(responses[0].id, "thread-safe-demo")
        self.assertTrue(writer_acquired.is_set())

    def test_read_collections_are_detached_from_internal_runtime_state(self) -> None:
        tools = self.manager.list_server_tools("thread-safe-demo")
        manifests = self.manager.iter_manifests()

        tools[0]["inputSchema"]["properties"]["query"]["type"] = "integer"
        manifests["thread-safe-demo"].launch.args.append("mutated")

        self.assertEqual(
            self.runtime.tools[0]["inputSchema"]["properties"]["query"]["type"],
            "string",
        )
        self.assertEqual(self.runtime.manifest.launch.args, ["server.js"])

    def test_reconcile_holds_manager_then_runtime_lock(self) -> None:
        self.runtime.desired_intent = self.manager.state_store.set(
            "thread-safe-demo",
            "running",
            source="test",
        )
        lock_states: list[tuple[bool, bool]] = []

        def start(server_id: str, **_: object) -> Any:
            self.assertEqual(server_id, "thread-safe-demo")
            lock_states.append(
                (
                    _lock_owned(self.manager._manager_lock),
                    _lock_owned(self.runtime.lock),
                )
            )
            self.runtime.state = McpServerState.RUNNING
            return self.runtime.to_response()

        with patch.object(self.manager, "start_server", side_effect=start):
            self.manager.reconcile_desired_states()

        self.assertEqual(lock_states, [(True, True)])

    def test_tool_refresh_callback_runs_under_same_lock_order(self) -> None:
        self.runtime.state = McpServerState.RUNNING
        self.runtime.client = SimpleNamespace(
            pid=None,
            list_tools=lambda: [
                {
                    "name": "refreshed",
                    "description": "refreshed tool",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ],
        )  # type: ignore[assignment]
        lock_states: list[tuple[bool, bool]] = []

        def before_replace(_: list[Any]) -> None:
            lock_states.append(
                (
                    _lock_owned(self.manager._manager_lock),
                    _lock_owned(self.runtime.lock),
                )
            )

        result = self.manager.refresh_server_tools(
            "thread-safe-demo",
            before_replace=before_replace,
        )

        self.assertEqual(lock_states, [(True, True)])
        self.assertEqual(result["tool_count"], 1)
        self.assertEqual(self.runtime.tools[0]["name"], "refreshed")


if __name__ == "__main__":
    unittest.main()

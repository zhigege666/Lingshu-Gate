"""Tool change notifications and bounded polling update a complete catalog."""
import io
import json
import threading
from types import SimpleNamespace

import pytest

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerState
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.mcp_stdio_client import StdioMcpClient
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.tool_catalog import ToolCatalog


@pytest.fixture
def runtime(tmp_path):
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d", allowed_root=tmp_path)
    database = SQLiteDatabase("", tmp_path)
    registry, access = ToolRegistry(), AccessControlStore(database)
    manager = McpRuntimeManager(settings, registry, state_store=McpRuntimeStateStore(database))
    access.attach_mcp_runtime(manager)
    manifest = McpServerManifest.model_validate({"id": "sync", "auto_start": False,
        "launch": {"type": "managed_process", "command": "synthetic-peer"}, "transport": {"type": "stdio"}})
    current = manager._new_runtime(manifest, manager.state_store.resolve("sync", auto_start=False))
    manager._servers["sync"] = current
    discovered = threading.Event()

    class Client:
        tools = [{"name": "first", "inputSchema": {"type": "object"}}]
        calls = 0
        on_tools_changed = None

        def list_tools(self):
            self.calls += 1
            discovered.set()
            return list(self.tools)

        def stop(self):
            pass

    client = Client()
    current.client, current.state, current.tools = client, McpServerState.RUNNING, list(client.tools)
    manager._register_mcp_tools(current)
    manager._prepare_tool_sync(current, client)
    yield manager, current, client, discovered, access, settings
    manager.shutdown()
    if current.tool_sync_thread:
        current.tool_sync_thread.join(timeout=1)
        assert not current.tool_sync_thread.is_alive()


@pytest.mark.parametrize("trigger", ["notification", "poll"])
def test_discovery_syncs_new_tool_without_changing_grants_or_faking_review(runtime, monkeypatch, trigger):
    manager, current, client, discovered, access, _ = runtime
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_MIN_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_INTERVAL_SECONDS", 0.02 if trigger == "poll" else 60.0)
    client.tools = [*client.tools, {"name": "read_new", "inputSchema": {"type": "object"},
                                  "annotations": {"readOnlyHint": True}}]
    if trigger == "notification":
        for _ in range(100):
            client.on_tools_changed()
    manager._start_tool_sync("sync", current, client)
    assert discovered.wait(timeout=2)
    # The reader event fires before policy/registry publication. Acquiring the
    # manager lock waits for the complete atomic replacement.
    with manager._manager_lock:
        assert manager.registry.get_definition("mcp.sync.read_new")
        record = next(item for item in access.list_classifications() if item["tool_id"] == "mcp.sync.read_new")
        assert record["required_access"] == "write" and record["policy_source"] == "default_write"
        assert record["reviewed_at"] is None and record["reviewed_by"] is None
        assert record["status"] == "pending"
        assert access.database.query_one("SELECT COUNT(*) FROM mcp_resource_grants")[0] == 0
        if trigger == "notification":
            assert client.calls == 1


def test_invalid_background_discovery_keeps_the_last_complete_catalog(runtime, monkeypatch):
    manager, current, client, discovered, access, _ = runtime
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_MIN_INTERVAL_SECONDS", 0.0)
    client.tools = [{"name": "broken", "inputSchema": "not an object"}]
    client.on_tools_changed()
    manager._start_tool_sync("sync", current, client)
    assert discovered.wait(timeout=2)
    with manager._manager_lock:
        assert [tool.id for tool in manager.registry.list_definitions()] == ["mcp.sync.first"]
        assert current.tools[0]["name"] == "first"
        assert len(access.list_classifications()) == 1


def test_stdio_tools_list_missing_tools_field_is_protocol_error(runtime):
    _, current, _, _, _, settings = runtime
    client = StdioMcpClient(current.manifest, settings)
    client.request = lambda method, params, timeout=None: {}
    from lingshu_gate.mcp_stdio_client import McpProtocolError
    with pytest.raises(McpProtocolError, match="must contain tools"):
        client.list_tools()


def test_http_and_stdio_notifications_only_wake_the_runtime_worker(runtime):
    _, current, _, _, _, settings = runtime
    notification = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    seen = []
    http = StreamableHttpMcpClient(current.manifest, settings)
    http.on_tools_changed = lambda: seen.append("http")
    assert http._match_sse_event([json.dumps(notification)], 1) is None
    response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    assert http._match_sse_event([json.dumps(response)], 1) == response
    stdio = StdioMcpClient(current.manifest, settings)
    stdio.on_tools_changed = lambda: seen.append("stdio")
    process = SimpleNamespace(stdout=io.StringIO(json.dumps(notification) + "\n"), poll=lambda: None)
    stdio._read_stdout(process, stdio._connection_generation)
    assert seen == ["http", "stdio"]


def test_unchanged_poll_keeps_registry_and_policy_revisions_stable(runtime, monkeypatch):
    manager, current, client, discovered, access, _ = runtime
    catalog = ToolCatalog(manager.registry, access)
    catalog.synchronize()
    with access.database.session() as connection:
        before = catalog.revision_marker(connection)
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_MIN_INTERVAL_SECONDS", 0.0)
    client.on_tools_changed()
    manager._start_tool_sync("sync", current, client)
    assert discovered.wait(timeout=2)
    with manager._manager_lock:
        catalog.synchronize()
        with access.database.session() as connection:
            assert catalog.revision_marker(connection) == before

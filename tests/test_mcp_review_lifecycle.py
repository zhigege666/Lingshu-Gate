"""重启、升级和真实移除使用真实 Registry、分类存储与审核快照验证。"""
from copy import deepcopy
from unittest.mock import patch

import pytest

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_authorization_policy import tool_snapshot
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.registry import ToolNotFoundError, ToolRegistry
from lingshu_gate.tool_catalog import ToolCatalog


@pytest.fixture
def lifecycle(tmp_path):
    database = SQLiteDatabase("", tmp_path)
    access, registry = AccessControlStore(database), ToolRegistry()
    catalog = ToolCatalog(registry, access)
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d", allowed_root=tmp_path)
    manager = McpRuntimeManager(settings, registry, state_store=McpRuntimeStateStore(database))
    manifest = McpServerManifest.model_validate({
        "id": "demo", "launch": {"type": "managed_process", "command": "synthetic-peer"},
        "transport": {"type": "stdio"}, "auto_start": False,
    })
    runtime = manager._new_runtime(manifest, manager.state_store.resolve("demo", auto_start=False))
    manager._servers[manifest.id] = runtime
    descriptor = {"name": "existing", "description": "Read a synthetic record",
                  "inputSchema": {"type": "object", "properties": {}},
                  "annotations": {"readOnlyHint": True}}
    runtime.tools = [deepcopy(descriptor)]
    manager._register_mcp_tools(runtime)
    catalog.synchronize()
    access.set_classification(server_id="demo", tool_id="mcp.demo.existing", access="read",
                              destructive=False, idempotent=True, reviewer_id="synthetic-reviewer")
    access.publish_classifications(server_id="demo", reviewer_id="synthetic-reviewer")
    return manager, runtime, catalog, descriptor


def classification(catalog, tool_id="mcp.demo.existing"):
    return dict(catalog.database.query_one(
        "SELECT * FROM mcp_tool_classifications WHERE tool_id=?", (tool_id,)))


@pytest.mark.parametrize("synchronize_during_outage", [False, True])
def test_runtime_restart_preserves_entire_review_and_oauth_snapshot(lifecycle, synchronize_during_outage):
    manager, runtime, catalog, descriptor = lifecycle
    before = classification(catalog)
    snapshot = tool_snapshot(catalog.registry.get_definition("mcp.demo.existing"), before)

    def restore(server_id, **kwargs):
        # 仅替换外部进程启动边界；下架、注册、分类和快照均调用真实实现。
        with pytest.raises(ToolNotFoundError):
            catalog.registry.get_definition("mcp.demo.existing")
        if synchronize_during_outage:
            catalog.synchronize()
            assert classification(catalog) == before
            assert catalog.database.query_one("SELECT COUNT(*) FROM gate_tool_catalog")[0] == 0
        runtime.tools = [deepcopy(descriptor)]
        manager._register_mcp_tools(runtime)
        return manager.get_server(server_id)

    with patch.object(manager, "start_server", side_effect=restore):
        manager.restart_server("demo")
    catalog.synchronize()
    assert classification(catalog) == before
    assert tool_snapshot(catalog.registry.get_definition("mcp.demo.existing"), classification(catalog)) == snapshot


@pytest.mark.parametrize("synchronize_during_outage", [False, True])
def test_upgrade_only_new_tool_needs_review(lifecycle, synchronize_during_outage):
    manager, runtime, catalog, descriptor = lifecycle
    before = classification(catalog)
    manager.stop_server("demo")
    if synchronize_during_outage:
        catalog.synchronize()
    runtime.tools = [deepcopy(descriptor), {**deepcopy(descriptor), "name": "added"}]
    manager._register_mcp_tools(runtime)
    catalog.synchronize()
    assert classification(catalog) == before
    added = classification(catalog, "mcp.demo.added")
    assert added["status"] == "pending" and added["effective_access"] == "unknown"
    assert added["reviewed_at"] is None


@pytest.mark.parametrize("field,value", [
    ("description", "A changed capability"),
    ("inputSchema", {"type": "object", "required": ["new_key"], "properties": {"new_key": {"type": "string"}}}),
    ("outputSchema", {"type": "object"}),
    ("annotations", {"readOnlyHint": False}),
])
def test_changed_definition_still_requires_review(lifecycle, field, value):
    manager, runtime, catalog, descriptor = lifecycle
    before = classification(catalog)
    manager.stop_server("demo")
    catalog.synchronize()
    runtime.tools = [{**deepcopy(descriptor), field: value}]
    manager._register_mcp_tools(runtime)
    catalog.synchronize()
    current = classification(catalog)
    assert current["status"] == "stale" and current["effective_access"] == "unknown"
    assert current["fingerprint"] != before["fingerprint"]


@pytest.mark.parametrize("synchronize_during_outage", [False, True])
def test_tool_removed_from_complete_upgrade_snapshot_stays_retired(lifecycle, synchronize_during_outage):
    manager, runtime, catalog, descriptor = lifecycle
    manager.stop_server("demo")
    if synchronize_during_outage:
        catalog.synchronize()
    runtime.tools = []
    manager._register_mcp_tools(runtime)
    catalog.synchronize()
    assert classification(catalog)["status"] == "stale"
    runtime.tools = [deepcopy(descriptor)]
    manager._register_mcp_tools(runtime)
    catalog.synchronize()
    assert classification(catalog)["status"] == "stale"


def test_explicit_removal_while_unavailable_cannot_restore_review(lifecycle):
    manager, runtime, catalog, descriptor = lifecycle
    manager.stop_server("demo")
    assert catalog.registry.unregister_by_metadata("server_id", "demo", source="mcp") == 1
    runtime.tools = [deepcopy(descriptor)]
    manager._register_mcp_tools(runtime)
    catalog.synchronize()
    assert classification(catalog)["status"] == "stale"


def test_gate_process_recreation_preserves_unchanged_persisted_review(lifecycle):
    manager, runtime, catalog, descriptor = lifecycle
    before = classification(catalog)
    manager.stop_server("demo")
    catalog.synchronize()
    registry = ToolRegistry()
    restored = ToolCatalog(registry, catalog.access)
    manager.registry = registry
    runtime.tools = [deepcopy(descriptor)]
    manager._register_mcp_tools(runtime)
    restored.synchronize()
    assert classification(restored) == before

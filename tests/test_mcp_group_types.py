"""核对显式组用途、旧客户端兼容、数据来源可见性及实例绑定。"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from lingshu_gate.domain.mcp_groups import McpGroupCreate, McpGroupError, McpGroupUpdate
from lingshu_gate.domain.mcp_group_routing import GroupToolCall
from lingshu_gate.persistence.mcp_groups_migration import MCP_GROUPS_MIGRATION_ID, apply_mcp_groups_migration
from lingshu_gate.persistence.mcp_group_routing_migration import MCP_GROUP_ROUTING_MIGRATION_ID, apply_mcp_group_routing_migration
from lingshu_gate.persistence.mcp_group_type_migration import MCP_GROUP_TYPE_MIGRATION_ID, apply_mcp_group_type_migration
from lingshu_gate.persistence.migrations import Migration, MigrationRunner
from lingshu_gate.registry import ToolExecutionError

from test_catalog_group_adapter import integrated as integrated, opened, selected
from test_mcp_group_routing import routing as routing
from test_mcp_group_mcp import invoke as invoke_group_tool, register as register_group_tools
from test_mcp_groups import create, draft, gate as gate, ticket


@pytest.mark.parametrize("group_type", ["execution", "data_source"])
def test_explicit_group_type_is_persisted_listed_and_audited(gate, group_type):
    group = create(gate, group_type=group_type)
    assert group["group_type"] == group_type
    assert gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()["group_type"] == group_type
    assert gate["client"].get("/v1/mcp/groups").json()["groups"][0]["group_type"] == group_type
    instances = gate["client"].get("/v1/mcp/groups/instances", params={"group_id": group["id"]}).json()["instances"]
    assert all(item["groups"][0]["group_type"] == group_type for item in instances)
    event = gate["database"].query_one("SELECT payload_json FROM events WHERE subject_id=?", (group["id"],))
    assert json.loads(event[0])["current"]["group_type"] == group_type
    assert not gate["database"].query_all("SELECT * FROM mcp_resource_grants")


@pytest.mark.parametrize("group_type", ["replica", "federated", "", None, 1])
def test_invalid_group_type_never_creates_a_group_or_receipt(gate, group_type):
    body = draft(group_type=group_type)
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert response.status_code == 422
    assert not gate["database"].query_all("SELECT * FROM mcp_groups")
    assert not gate["database"].query_all("SELECT * FROM mcp_group_requests")


def test_legacy_create_stays_unspecified_and_legacy_update_preserves_an_explicit_type(gate):
    legacy = create(gate)
    assert legacy["group_type"] == "unspecified"
    group = create(gate, group_type="data_source")
    body = draft(expected_revision=group["revision"], name="Renamed by a legacy client")
    response = gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=body,
        headers=ticket(gate, body, "update", group["id"]))
    assert response.status_code == 200
    assert response.json()["group_type"] == "data_source"
    assert response.json()["revision"] == group["revision"] + 1


def test_group_type_is_bound_to_csrf_and_create_idempotency(gate):
    original = draft(group_type="execution")
    changed = {**original, "group_type": "data_source"}
    headers = ticket(gate, original)
    assert gate["client"].post("/v1/mcp/groups", json=changed, headers=headers).status_code == 403
    created = gate["client"].post("/v1/mcp/groups", json=original, headers=ticket(gate, original))
    assert created.status_code == 200
    replay = gate["client"].post("/v1/mcp/groups", json=changed, headers=ticket(gate, changed))
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "group_request_conflict"
    assert gate["database"].query_one("SELECT group_type FROM mcp_groups")[0] == "execution"


def test_legacy_mcp_create_receipt_can_be_replayed_after_upgrade(gate):
    actor = register_group_tools(gate, ["operations.manage", "tools.read", "tools.invoke"])
    body = draft()
    legacy = McpGroupCreate(**body)
    # 升级前实际模型的规范正文包含其旧默认字段，但没有新增 group_type。
    old_digest = hashlib.sha256(json.dumps(legacy.model_dump(exclude={"group_type"}), ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    saved = gate["service"].save(legacy, actor, request_digest=old_digest)
    replay = invoke_group_tool(gate, actor, "gate_mcp_group_save", {"draft": body})
    assert replay.ok and replay.output["id"] == saved["id"] and replay.output["revision"] == 1
    assert replay.output["group_type"] == "unspecified"
    changed = invoke_group_tool(gate, actor, "gate_mcp_group_save", {"draft": {**body, "group_type": "execution"}})
    assert not changed.ok and changed.output["error"]["code"] == "group_request_conflict"
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 1
    assert gate["database"].query_one("SELECT COUNT(*) FROM events WHERE subject_type='mcp_group'")[0] == 1


@pytest.mark.parametrize("group_type", ["execution", "data_source"])
def test_mcp_group_save_accepts_explicit_type_and_omitted_update_preserves_it(gate, group_type):
    actor = register_group_tools(gate, ["operations.manage", "tools.read", "tools.invoke"])
    first = invoke_group_tool(gate, actor, "gate_mcp_group_save", {"draft": draft(group_type=group_type)})
    assert first.ok and first.output["group_type"] == group_type
    updated = invoke_group_tool(gate, actor, "gate_mcp_group_save", {"group_id": first.output["id"],
        "draft": draft(expected_revision=first.output["revision"], name="Legacy MCP update")})
    assert updated.ok and updated.output["group_type"] == group_type and updated.output["revision"] == 2


def test_additive_type_migration_preserves_legacy_identity_members_and_revision(tmp_path):
    path = tmp_path / "legacy-groups.sqlite3"
    migrations = (Migration(MCP_GROUPS_MIGRATION_ID, apply_mcp_groups_migration),
        Migration(MCP_GROUP_ROUTING_MIGRATION_ID, apply_mcp_group_routing_migration))
    def connect():
        return sqlite3.connect(path)
    MigrationRunner(connect, migrations).run()
    with connect() as connection:
        connection.execute("INSERT INTO mcp_groups VALUES(?,?,?,?,?,?,?,?,?)",
            ("a" * 32, "Legacy group", "Unknown business purpose", "active", 7, "legacy", "2026-10-01", "2026-10-01", "instance-a"))
        connection.execute("INSERT INTO mcp_group_members VALUES(?,?,?)", ("a" * 32, "instance-a", "active"))
        previous = connection.execute("SELECT * FROM mcp_groups").fetchone()
    runner = MigrationRunner(connect, (*migrations, Migration(MCP_GROUP_TYPE_MIGRATION_ID, apply_mcp_group_type_migration)))
    assert runner.run() == (MCP_GROUP_TYPE_MIGRATION_ID,)
    assert runner.run() == ()
    with connect() as connection:
        current = connection.execute("SELECT * FROM mcp_groups").fetchone()
        assert current[:-1] == previous and current[-1] == "unspecified"
        assert connection.execute("SELECT * FROM mcp_group_members").fetchone() == ("a" * 32, "instance-a", "active")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE mcp_groups SET group_type='automatic'")


@pytest.mark.parametrize("group_type", ["execution", "data_source"])
def test_public_group_metadata_identifies_visible_sources_and_only_invokes_the_selected_instance(gate, integrated, group_type):
    catalog, group, peers = integrated
    actor = gate["principal"]
    gate["service"].save(McpGroupUpdate(**draft(expected_revision=group["revision"], group_type=group_type,
        members=[member["instance_id"] for member in group["members"]])),
        actor, group_id=group["id"], expected_revision=group["revision"])
    page = catalog.call("gate_catalog_search", {"group_id": group["id"]}, actor).output
    summary = page["tools"][0]
    assert summary["group_type"] == group_type and summary["group_name"] == group["name"]
    sources = catalog.call("gate_instance_list", {"group_id": group["id"], "tool_ref": summary["tool_ref"]}, actor).output["instances"]
    assert {item["instance_name"] for item in sources} == {f"Synthetic instance {index}" for index in range(3)}
    assert all(item["group_type"] == group_type for item in sources)
    described = selected(catalog, group, actor, "instance-2")
    assert described["group_type"] == group_type and described["instance_name"] == "Synthetic instance 2"
    session_result = catalog.call("gate_instance_session_open",
        {key: described[key] for key in ("tool_ref", "instance_id", "schema_revision")}, actor).output
    assert {key: session_result[key] for key in ("group_id", "group_type", "group_name", "instance_name")} == {
        "group_id": group["id"], "group_type": group_type, "group_name": group["name"], "instance_name": "Synthetic instance 2"}
    session = session_result["session_id"]
    arguments = {"target": "Original query argument"}
    response = catalog.call("gate_tool_invoke", {**{key: described[key] for key in ("tool_ref", "instance_id", "schema_revision")},
        "session_id": session, "arguments": arguments}, actor)
    assert response.ok and response.output == {"instance": "instance-2", "arguments": arguments}
    assert not peers["instance-0"].calls and not peers["instance-1"].calls


def test_changing_group_type_invalidates_an_existing_instance_session(gate, integrated):
    catalog, group, peers = integrated
    actor = gate["principal"]
    described = selected(catalog, group, actor)
    session = opened(catalog, described, actor)
    first_page = catalog.call("gate_instance_list", {"group_id": group["id"], "limit": 1}, actor).output
    assert first_page["next_cursor"]
    gate["service"].save(McpGroupUpdate(**draft(expected_revision=group["revision"], group_type="data_source",
        members=[member["instance_id"] for member in group["members"]])),
        actor, group_id=group["id"], expected_revision=group["revision"])
    assert catalog.group_router is not None
    with pytest.raises(McpGroupError) as binding_error:
        with catalog.group_router.dispatch_guard(actor, GroupToolCall(tool_ref=described["tool_ref"],
                instance_id=described["instance_id"], session_id=session, arguments={})):
            pytest.fail("用途变化后，旧会话不能获得派发许可")
    assert binding_error.value.code == "group_session_changed"
    with pytest.raises(ToolExecutionError) as session_error:
        catalog.call("gate_tool_invoke", {**{key: described[key] for key in ("tool_ref", "instance_id", "schema_revision")},
            "session_id": session, "arguments": {}}, actor)
    # 公开目录沿用统一不可用错误；内部绑定原因不对外泄漏。
    assert session_error.value.code == "catalog_tool_unavailable"
    with pytest.raises(ToolExecutionError) as cursor_error:
        catalog.call("gate_instance_list", {"group_id": group["id"], "limit": 1, "cursor": first_page["next_cursor"]}, actor)
    assert cursor_error.value.code == "catalog_cursor_invalid"
    assert all(not peer.calls for peer in peers.values())

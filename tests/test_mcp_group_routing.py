"""Logical contracts and pinned dispatch through the existing audited invoker."""
from __future__ import annotations

import json
from dataclasses import replace
from threading import Event, Thread

import pytest
from pydantic import ValidationError

from lingshu_gate.application.mcp_group_routing import McpGroupRoutingService
from lingshu_gate.domain.mcp_group_routing import GroupToolCall, GroupToolSelection, logical_service_id
from lingshu_gate.domain.mcp_groups import McpGroupError, McpGroupUpdate
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.registry import ToolExecutionError

from test_mcp_groups import PASSWORD, catalog_tool, create, draft
from test_mcp_groups import gate as gate


class SyntheticPeer:
    pid = None

    def __init__(self, instance: str) -> None:
        self.instance = instance
        self.calls: list[tuple[str, dict]] = []
        self.failure: Exception | None = None

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if self.failure:
            raise self.failure
        return {"instance": self.instance, "arguments": dict(arguments)}


@pytest.fixture
def routing(gate):
    group = create(gate, members=[f"instance-{index}" for index in range(3)], default_instance_id="instance-1")
    for index in range(3):
        catalog_tool(gate, f"instance-{index}", name="inspect")
    runtime = McpRuntimeManager(gate["auth"].settings, gate["registry"], state_store=McpRuntimeStateStore(gate["database"]))
    peers = {}
    for index in range(3):
        instance = f"instance-{index}"
        peer = SyntheticPeer(instance)
        peers[instance] = peer
        runtime._servers[instance] = McpServerRuntime(gate["configs"].load_manifest(instance),
            state=McpServerState.RUNNING, client=peer, last_started_at="2026-10-05T00:00:00Z")
    gate["service"].runtime = runtime
    gate["access"].attach_mcp_runtime(runtime)
    service = McpGroupRoutingService(gate["service"], gate["registry"], gate["access"], gate["auth"])
    return service, group, peers


def selection(service, group, actor, instance="instance-0"):
    page = service.search(actor, group_id=group["id"])
    return GroupToolSelection(tool_ref=page["tools"][0]["tool_ref"], instance_id=instance)


def invoke(gate, service, actor, call):
    with service.dispatch_guard(actor, call) as (current, target):
        return gate["access"].invoke_tool(gate["registry"], current, target.tool_id, call.arguments,
            expected_definition_revision=target.definition_fingerprint, allow_read_retry=False)


def test_same_contract_shares_one_ref_and_arguments_are_unchanged(gate, routing):
    service, group, peers = routing
    actor = gate["principal"]
    page = service.search(actor, group_id=group["id"])
    assert page["total"] == 1 and page["tools"][0]["visible_member_count"] == 3
    selected = selection(service, group, actor, "instance-2")
    target = service.resolve(actor, **selected.model_dump())
    assert target.tool_id == "mcp.instance-2.inspect" and target.server_id == target.instance_id == "instance-2"
    assert target.service_id == logical_service_id(group["id"])
    session = service.open_session(actor, selected)
    call = GroupToolCall(**selected.model_dump(), session_id=session["session_id"], arguments={"target": "business-value", "x": 4})
    response = invoke(gate, service, actor, call)
    assert response.ok and response.output["arguments"] == call.arguments
    assert peers["instance-2"].calls == [("inspect", call.arguments)]
    assert peers["instance-0"].calls == peers["instance-1"].calls == []
    assert service.describe(actor, **selected.model_dump())["schema_revision"] == target.schema_revision
    assert gate["database"].query_one("SELECT COUNT(*) FROM invocation_audits WHERE tool_id=?", (target.tool_id,))[0] == 1


def test_incompatible_schema_is_partitioned_and_cannot_resolve_another_instance(gate, routing):
    service, group, _ = routing
    catalog_tool(gate, "instance-2", name="inspect", schema={"type": "object", "properties": {"version2": {"type": "integer"}}})
    page = service.search(gate["principal"], group_id=group["id"])
    assert page["total"] == 2 and all(item["visible_variant_count"] == 2 for item in page["tools"])
    shared = next(item for item in page["tools"] if item["visible_member_count"] == 2)
    with pytest.raises(McpGroupError, match="unavailable"):
        service.resolve(gate["principal"], tool_ref=shared["tool_ref"], instance_id="instance-2")


def user(gate):
    record = gate["auth"].create_user(username="synthetic-route-viewer", password=PASSWORD, role="viewer")
    actor, _, _ = gate["auth"].login(username="synthetic-route-viewer", password=PASSWORD)
    return actor, record


def grant(gate, actor, server, tool=None):
    return gate["access"].save_grant(subject_type="user", subject_id=actor.id, server_id=server,
        tool_id=tool, permission_type_code="read", created_by=gate["principal"].id)


def test_three_instance_acl_intersects_logical_and_physical_grants_and_live_revocation(gate, routing):
    service, group, peers = routing
    actor, _ = user(gate)
    grant(gate, actor, "instance-0")
    assert service.search(actor, group_id=group["id"])["total"] == 0
    logical = grant(gate, actor, logical_service_id(group["id"]))
    page = service.search(actor, group_id=group["id"])
    assert page["tools"][0]["visible_member_count"] == 1
    assert {member["instance_id"] for member in page["tools"][0]["instances"]} == {"instance-0"}
    assert "instance-1" not in json.dumps(page) and "instance-2" not in json.dumps(page)
    selected = selection(service, group, actor)
    session = service.open_session(actor, selected)
    call = GroupToolCall(**selected.model_dump(), session_id=session["session_id"])
    assert invoke(gate, service, actor, call).ok
    gate["database"].execute("DELETE FROM mcp_resource_grants WHERE id=?", (logical["id"],))
    assert service.search(actor, group_id=group["id"])["total"] == 0
    for action in [lambda: service.describe(actor, **selected.model_dump()), lambda: invoke(gate, service, actor, call)]:
        with pytest.raises(McpGroupError):
            action()
    assert len(peers["instance-0"].calls) == 1


@pytest.mark.parametrize("change", ["token_revoked", "token_scopes", "user_disabled", "roles", "session", "delegation"])
def test_authority_is_fresh_for_search_describe_and_dispatch(gate, routing, change):
    service, group, peers = routing
    actor = gate["principal"]
    if change.startswith("token"):
        token = gate["auth"].create_api_token(principal=actor, name="Synthetic routing", scopes=["tools.read", "tools.invoke"])
        actor = gate["auth"]._principal_from_api_token(token["token"])
    selected = selection(service, group, actor)
    session = service.open_session(actor, selected)
    if change == "token_revoked":
        gate["database"].execute("UPDATE api_tokens SET revoked_at='2026-10-05T00:00:00Z' WHERE id=?", (actor.token_id,))
    elif change == "token_scopes":
        gate["database"].execute("UPDATE api_tokens SET scopes_json='[]' WHERE id=?", (actor.token_id,))
    elif change == "user_disabled":
        gate["database"].execute("UPDATE users SET status='disabled' WHERE id=?", (actor.id,))
    elif change == "roles":
        gate["access"].set_user_roles(actor.id, ["viewer"])
    elif change == "session":
        gate["database"].execute("DELETE FROM auth_sessions WHERE id=?", (actor.session_id,))
    else:
        actor = replace(actor, delegated_scopes=())
    try:
        assert service.search(actor, group_id=group["id"])["total"] == 0
    except McpGroupError as exc:
        assert exc.status == 403
    with pytest.raises(McpGroupError):
        service.describe(actor, **selected.model_dump())
    with pytest.raises(McpGroupError):
        invoke(gate, service, actor, GroupToolCall(**selected.model_dump(), session_id=session["session_id"]))
    assert all(not peer.calls for peer in peers.values())


@pytest.mark.parametrize("change", ["other_instance", "other_connection", "closed", "expired", "runtime", "config", "group_revision"])
def test_session_is_bound_to_instance_connection_and_current_generation(gate, routing, change):
    service, group, peers = routing
    actor = gate["principal"]
    selected = selection(service, group, actor)
    session = service.open_session(actor, selected)
    call = GroupToolCall(**selected.model_dump(), session_id=session["session_id"])
    if change == "other_instance":
        call = call.model_copy(update={"instance_id": "instance-1"})
    elif change == "other_connection":
        actor, _, _ = gate["auth"].login(username=actor.username, password=PASSWORD)
    elif change == "closed":
        service.close_session(actor, session["session_id"])
    elif change == "expired":
        gate["database"].execute("UPDATE mcp_group_route_sessions SET expires_at='2000-01-01T00:00:00Z'")
    elif change == "runtime":
        service.groups.runtime._servers["instance-0"].client = SyntheticPeer("replacement")
    elif change == "config":
        config = gate["configs"].load_manifest("instance-0").model_dump(exclude={"manifest_path"})
        gate["configs"].save_config({**config, "name": "Changed"}, overwrite=True)
    else:
        gate["service"].save(McpGroupUpdate(**draft(expected_revision=group["revision"], name="Changed group",
            members=[f"instance-{index}" for index in range(3)])), actor,
            group_id=group["id"], expected_revision=group["revision"])
    with pytest.raises(McpGroupError):
        invoke(gate, service, actor, call)
    assert all(not peer.calls for peer in peers.values())


def test_failure_does_not_replay_write_or_select_another_instance(gate, routing):
    service, group, peers = routing
    for instance in peers:
        gate["access"].set_classification(server_id=instance, tool_id=f"mcp.{instance}.inspect", access="write",
            destructive=True, idempotent=False, reviewer_id=gate["principal"].id)
        gate["access"].publish_classifications(reviewer_id=gate["principal"].id, server_id=instance)
    selected = selection(service, group, gate["principal"])
    session = service.open_session(gate["principal"], selected)
    peers["instance-0"].failure = ToolExecutionError("synthetic_disconnect", "Selected instance disconnected")
    result = invoke(gate, service, gate["principal"], GroupToolCall(**selected.model_dump(), session_id=session["session_id"]))
    assert not result.ok and len(peers["instance-0"].calls) == 1
    assert not peers["instance-1"].calls and not peers["instance-2"].calls


def test_group_deletion_waits_for_pinned_dispatch_then_invalidates_session(gate, routing):
    service, group, _ = routing
    actor = gate["principal"]
    selected = selection(service, group, actor)
    session = service.open_session(actor, selected)
    call = GroupToolCall(**selected.model_dump(), session_id=session["session_id"])
    started, deleted = Event(), Event()
    failures = []

    def delete_group():
        started.set()
        try:
            gate["service"].delete(group["id"], group["revision"], actor)
        except Exception as exc:
            failures.append(exc)
        finally:
            deleted.set()

    with service.dispatch_guard(actor, call):
        worker = Thread(target=delete_group)
        worker.start()
        assert started.wait(1)
        assert not deleted.wait(0.05)
    worker.join(timeout=2)
    assert deleted.is_set() and not failures
    with pytest.raises(McpGroupError):
        invoke(gate, service, actor, call)


def test_schema_change_between_selection_and_dispatch_is_not_reused(gate, routing):
    service, group, peers = routing
    selected = selection(service, group, gate["principal"])
    session = service.open_session(gate["principal"], selected)
    definition = gate["registry"].get_definition("mcp.instance-0.inspect")
    gate["registry"].update_definition(definition.model_copy(update={"input_schema": {"type": "object", "required": ["new"]}}))
    with pytest.raises(McpGroupError):
        invoke(gate, service, gate["principal"], GroupToolCall(**selected.model_dump(), session_id=session["session_id"]))
    assert all(not peer.calls for peer in peers.values())


def test_route_input_rejects_arbitrary_endpoint_secret_and_implicit_default(gate, routing):
    service, group, _ = routing
    selected = selection(service, group, gate["principal"])
    for extra in [{"endpoint": "https://other.example.test"}, {"secret": "synthetic"}]:
        with pytest.raises(ValidationError):
            GroupToolSelection(**selected.model_dump(), **extra)
    with pytest.raises(ValidationError):
        GroupToolSelection(tool_ref=selected.tool_ref)
    with pytest.raises(ValidationError):
        GroupToolSelection(tool_ref=selected.tool_ref, instance_id="https://other.example.test/mcp")


def test_default_is_persisted_but_does_not_select_or_grant(gate, routing):
    _, group, _ = routing
    with gate["database"].session() as connection:
        assert gate["store"].detail(connection, group["id"])["default_instance_id"] == "instance-1"
    with pytest.raises(ValidationError):
        McpGroupUpdate(**draft(expected_revision=1, default_instance_id="not-selected"))
    assert not gate["database"].query_all("SELECT * FROM mcp_resource_grants")


def test_additive_routing_migration_preserves_groups_grants_and_legacy_invocation(gate, routing):
    _, group, peers = routing
    database = gate["database"]
    database.execute("DROP TABLE mcp_group_route_sessions")
    database.execute("ALTER TABLE mcp_groups DROP COLUMN default_instance_id")
    database.execute("DELETE FROM schema_migrations WHERE id='0015_gate_mcp_group_routing'")
    files = {path: path.read_bytes() for path in gate["configs"].config_dir.glob("*")}
    database.initialize()
    database.initialize()
    with database.session() as connection:
        current = gate["store"].detail(connection, group["id"])
    assert current["id"] == group["id"] and current["members"] == group["members"]
    assert current["default_instance_id"] is None
    assert files == {path: path.read_bytes() for path in files}
    response = gate["access"].invoke_tool(gate["registry"], gate["principal"], "mcp.instance-2.inspect", {"legacy": True})
    assert response.ok and peers["instance-2"].calls == [("inspect", {"legacy": True})]


def test_all_safety_annotations_participate_in_contract_partition(gate, routing):
    service, group, _ = routing
    catalog_tool(gate, "instance-2", name="inspect", metadata={"annotations": {"readOnlyHint": True, "vendorSafety": "extra"}})
    assert service.search(gate["principal"], group_id=group["id"])["total"] == 2


def test_advertised_contract_version_partitions_even_when_schema_matches(gate, routing):
    service, group, _ = routing
    catalog_tool(gate, "instance-2", name="inspect", metadata={"contract_version": "2"})
    assert service.search(gate["principal"], group_id=group["id"])["total"] == 2


def test_admin_instance_picker_returns_only_compact_declared_contract_revisions(gate, routing):
    _, _, _ = routing
    gate["service"].registry = gate["registry"]
    page = gate["service"].instances(gate["principal"], q="", group_id=None, ungrouped=False, offset=0, limit=20)
    versions = {item["contract_revision"] for item in page["instances"]}
    assert len(versions) == 1 and len(next(iter(versions))) == 64
    assert "input_schema" not in json.dumps(page) and "endpoint" not in json.dumps(page)
    catalog_tool(gate, "instance-2", name="inspect", metadata={"contract_version": "2"})
    changed = gate["service"].instances(gate["principal"], q="", group_id=None, ungrouped=False, offset=0, limit=20)
    assert len({item["contract_revision"] for item in changed["instances"]}) == 2


class ReusedSessionPeer(StreamableHttpMcpClient):
    def __init__(self, manifest, settings):
        super().__init__(manifest, settings)
        self.session_id = "A"
        self.calls = []
        self.fail_start = False
        self.raw_tools = [{"name": "inspect", "inputSchema": {}, "annotations": {"readOnlyHint": True}}]

    def start(self):
        if self.fail_start:
            raise RuntimeError("Synthetic connect failure")

    def list_tools(self):
        return self.raw_tools

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return {"instance": self.manifest.id, "arguments": arguments}


@pytest.mark.parametrize("change", ["same_sid", "sid_aba", "client_aba", "failed_then_restore"])
def test_reconnect_generations_never_restore_an_old_group_session(gate, routing, change):
    service, group, _ = routing
    manager = service.groups.runtime
    runtime = manager._servers["instance-0"]
    peer = ReusedSessionPeer(runtime.manifest, manager.settings)
    runtime.client = peer
    runtime.tools = peer.list_tools()
    manager._register_mcp_tools(runtime)
    gate["access"].synchronize_tools(gate["registry"].list_definitions())
    gate["access"].set_classification(server_id="instance-0", tool_id="mcp.instance-0.inspect", access="read",
        destructive=False, idempotent=False, reviewer_id=gate["principal"].id)
    gate["access"].publish_classifications(server_id="instance-0", reviewer_id=gate["principal"].id)
    page = service.search(gate["principal"], group_id=group["id"])
    variant = next(item for item in page["tools"] if any(member["instance_id"] == "instance-0" for member in item["instances"]))
    selected = GroupToolSelection(tool_ref=variant["tool_ref"], instance_id="instance-0")
    session = service.open_session(gate["principal"], selected)
    before = runtime.connection_generation
    if change == "client_aba":
        runtime.client = ReusedSessionPeer(runtime.manifest, manager.settings)
        runtime.client = peer
    else:
        if change == "failed_then_restore":
            peer.fail_start = True
            with pytest.raises(ToolExecutionError):
                manager._recover_expired_session_locked("instance-0", runtime, "inspect", {}, retry_read_only=False)
            peer.fail_start = False
        for sid in (["B", "A"] if change == "sid_aba" else ["A"]):
            peer.session_id = sid
            with pytest.raises(ToolExecutionError, match="not automatically replayed"):
                manager._recover_expired_session_locked("instance-0", runtime, "inspect", {}, retry_read_only=False)
    assert runtime.client is peer and peer.session_id == "A"
    assert runtime.connection_generation > before
    assert runtime.last_started_at == "2026-10-05T00:00:00Z"
    with pytest.raises(McpGroupError, match="changed"):
        invoke(gate, service, gate["principal"], GroupToolCall(**selected.model_dump(), session_id=session["session_id"]))
    assert peer.calls == []


def test_a_reconnect_inside_dispatch_invalidates_the_current_group_call(gate, routing):
    service, group, _ = routing
    selected = selection(service, group, gate["principal"])
    session = service.open_session(gate["principal"], selected)
    runtime = service.groups.runtime._servers["instance-0"]
    with pytest.raises(ToolExecutionError, match="bound connection changed"):
        with service.dispatch_guard(gate["principal"], GroupToolCall(**selected.model_dump(), session_id=session["session_id"])):
            runtime.advance_connection_generation()


@pytest.mark.parametrize("instance", ["_legacy", "-prod", ".service", "x" * 180])
def test_legacy_instance_ids_save_search_resolve_and_dispatch_without_renaming(gate, routing, instance):
    service, _, _ = routing
    gate["configs"].save_config({"id": instance, "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}})
    group = create(gate, members=[instance])
    catalog_tool(gate, instance, name="inspect")
    peer = SyntheticPeer(instance)
    service.groups.runtime._servers[instance] = McpServerRuntime(gate["configs"].load_manifest(instance),
        state=McpServerState.RUNNING, client=peer)
    selected = selection(service, group, gate["principal"], instance)
    assert service.resolve(gate["principal"], **selected.model_dump()).server_id == instance
    session = service.open_session(gate["principal"], selected)
    result = invoke(gate, service, gate["principal"], GroupToolCall(**selected.model_dump(), session_id=session["session_id"]))
    assert result.ok and peer.calls == [("inspect", {})]


def test_output_only_contract_change_requires_review_and_is_never_auto_published(gate, routing):
    service, group, _ = routing
    selected = selection(service, group, gate["principal"])
    before = gate["registry"].get_definition("mcp.instance-0.inspect")
    original_review = gate["database"].query_one("SELECT reviewed_at FROM mcp_tool_classifications WHERE tool_id=?", (before.id,))[0]
    changed = before.model_copy(update={"metadata": {**before.metadata, "outputSchema": {"type": "object"}}})
    gate["registry"].update_definition(changed)
    gate["access"].synchronize_tools([changed])
    row = gate["database"].query_one("SELECT status,effective_access,reviewed_at FROM mcp_tool_classifications WHERE tool_id=?", (changed.id,))
    assert row["status"] == "stale" and row["effective_access"] == "unknown"
    assert row["reviewed_at"] == original_review  # Retain history, never current authority.
    gate["access"].publish_classifications(server_id="instance-0", reviewer_id=gate["principal"].id)
    assert gate["database"].query_one("SELECT status FROM mcp_tool_classifications WHERE tool_id=?", (changed.id,))[0] == "stale"
    assert before.input_schema == changed.input_schema
    with pytest.raises(McpGroupError):
        service.resolve(gate["principal"], **selected.model_dump())
    page = service.search(gate["principal"], group_id=group["id"])
    pending = next(item for item in page["tools"] if any(member["instance_id"] == "instance-0" for member in item["instances"]))
    assert pending["compatibility"] == "review_required"

"""One bounded public directory/dispatch path over the existing group port."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lingshu_gate.domain.mcp_group_routing import logical_service_id
from lingshu_gate.interfaces.control_api.catalog_routes import register_catalog_routes
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.tool_catalog import CatalogDescribe, CatalogInvoke, CatalogSearch, ToolCatalog, catalog_tools

from test_mcp_group_routing import gate as gate, routing as routing
from test_mcp_groups import catalog_tool


@pytest.fixture
def integrated(gate, routing):
    router, group, peers = routing
    catalog = ToolCatalog(gate["registry"], gate["access"], group_router=router)
    return catalog, group, peers


def selected(catalog, group, actor, instance="instance-0"):
    summaries = catalog.call("gate_catalog_search", {"group_id": group["id"]}, actor).output["tools"]
    return catalog.call("gate_tool_describe", {"tool_ref": summaries[0]["tool_ref"], "instance_id": instance}, actor).output


def opened(catalog, described, actor):
    return catalog.call("gate_instance_session_open", {key: described[key]
        for key in ("tool_ref", "instance_id", "schema_revision")}, actor).output["session_id"]


def test_public_group_workflow_keeps_real_target_audit_and_original_arguments(gate, integrated):
    catalog, group, peers = integrated
    actor = gate["principal"]
    page = catalog.call("gate_catalog_search", {"group_id": group["id"]}, actor).output
    assert len(page["tools"]) == 1
    assert not {"total", "service_id", "group_revision"} & page.keys()
    assert not {"input_schema", "instances", "visible_member_count"} & page["tools"][0].keys()
    tool_ref = page["tools"][0]["tool_ref"]
    instances = catalog.call("gate_instance_list", {"group_id": group["id"], "tool_ref": tool_ref}, actor).output
    assert {item["instance_id"] for item in instances["instances"]} == set(peers)
    described = selected(catalog, group, actor, "instance-2")
    session_id = opened(catalog, described, actor)
    args = {"target": "Original downstream parameter", "session_id": "Downstream business parameter"}
    response = catalog.call("gate_tool_invoke", {"tool_ref": tool_ref, "instance_id": "instance-2",
        "schema_revision": described["schema_revision"], "session_id": session_id, "arguments": args}, actor,
        refresh_principal=lambda: actor)
    assert response.ok and response.tool_id == "mcp.instance-2.inspect"
    assert peers["instance-2"].calls == [("inspect", args)]
    assert not peers["instance-0"].calls and not peers["instance-1"].calls
    audit = gate["database"].query_one("SELECT tool_id,server_id,outcome FROM invocation_audits ORDER BY rowid DESC LIMIT 1")
    assert tuple(audit) == ("mcp.instance-2.inspect", "instance-2", "success")
    catalog.call("gate_instance_session_close", {"session_id": session_id}, actor)
    with pytest.raises(ToolExecutionError):
        catalog.call("gate_tool_invoke", {"tool_ref": tool_ref, "instance_id": "instance-2",
            "schema_revision": described["schema_revision"], "session_id": session_id, "arguments": {}}, actor)
    assert len(peers["instance-2"].calls) == 1


def test_group_directory_filters_physical_and_logical_grants_before_paging(gate, integrated):
    catalog, group, _ = integrated
    actor_id = gate["auth"].create_user(username="synthetic-group-operator", password="Synthetic-Operator-123!", role="operator")["id"]
    actor, _, _ = gate["auth"].login(username="synthetic-group-operator", password="Synthetic-Operator-123!")
    gate["access"].save_grant(subject_type="user", subject_id=actor_id, server_id="instance-0",
        permission_type_code="read", created_by=gate["principal"].id)
    assert catalog.search(actor, CatalogSearch(group_id=group["id"]))["tools"] == []
    gate["access"].save_grant(subject_type="user", subject_id=actor_id, server_id=logical_service_id(group["id"]),
        permission_type_code="read", created_by=gate["principal"].id)
    page = catalog.search(actor, CatalogSearch(group_id=group["id"]))
    ref = page["tools"][0]["tool_ref"]
    instances = catalog.search(actor, CatalogSearch(group_id=group["id"], tool_ref=ref), instances=True)
    assert instances["instances"] == [{"instance_id": "instance-0", "group_id": group["id"]}]
    assert "instance-1" not in json.dumps(instances) and "instance-2" not in json.dumps(instances)


@pytest.mark.parametrize("change", ["grant", "group", "config", "descriptor"])
def test_group_cursor_invalidates_on_authority_or_structure_change(gate, integrated, change):
    catalog, group, _ = integrated
    actor = gate["principal"]
    request = CatalogSearch(group_id=group["id"], limit=1)
    first = catalog.search(actor, request, instances=True)
    assert first["next_cursor"]
    next_page = catalog.search(actor, request.model_copy(update={"cursor": first["next_cursor"]}), instances=True)
    assert next_page["instances"][0] != first["instances"][0]
    if change == "grant":
        gate["access"].save_grant(subject_type="user", subject_id=actor.id, server_id="instance-0",
            permission_type_code="none", created_by=actor.id)
    elif change == "group":
        gate["database"].execute("UPDATE mcp_groups SET revision=revision+1 WHERE id=?", (group["id"],))
    elif change == "config":
        definition = gate["configs"].load_manifest("instance-0").model_dump(exclude={"manifest_path"})
        gate["configs"].save_config({**definition, "name": "Changed instance name"}, overwrite=True)
    else:
        definition = gate["registry"].get_definition("mcp.instance-0.inspect")
        gate["registry"].update_definition(definition.model_copy(update={"description": "Changed description"}))
    with pytest.raises(ToolExecutionError) as error:
        catalog.search(actor, request.model_copy(update={"cursor": first["next_cursor"]}), instances=True)
    assert error.value.code == "catalog_cursor_invalid"


@pytest.mark.parametrize("invalid", ["instance", "session", "revision", "arguments"])
def test_group_invocation_rejects_incomplete_or_changed_envelope_without_dispatch(gate, integrated, invalid):
    catalog, group, peers = integrated
    actor = gate["principal"]
    for instance in peers:
        catalog_tool(gate, instance, name="inspect", schema={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]})
    described = selected(catalog, group, actor)
    body = {"tool_ref": described["tool_ref"], "instance_id": described["instance_id"],
        "schema_revision": described["schema_revision"], "session_id": opened(catalog, described, actor), "arguments": {"key": "ok"}}
    if invalid in {"instance", "session"}:
        del body[f"{invalid}_id"]
    elif invalid == "revision":
        body["schema_revision"] = "0" * 64
    else:
        body["arguments"] = {"key": 1}
    with pytest.raises(ToolExecutionError):
        catalog.call("gate_tool_invoke", body, actor)
    assert all(not peer.calls for peer in peers.values())


def test_group_invoker_never_enables_read_replay_and_preserves_physical_calls(gate, integrated, monkeypatch):
    catalog, group, peers = integrated
    actor = gate["principal"]
    described = selected(catalog, group, actor)
    session = opened(catalog, described, actor)
    observed = []
    original = gate["access"].invoke_tool

    def checked(*args, **kwargs):
        observed.append(kwargs["allow_read_retry"])
        return original(*args, **kwargs)

    monkeypatch.setattr(gate["access"], "invoke_tool", checked)
    assert catalog.invoke(actor, CatalogInvoke(tool_ref=described["tool_ref"], instance_id=described["instance_id"],
        schema_revision=described["schema_revision"], session_id=session, arguments={})).ok
    assert observed == [False]
    monkeypatch.setattr(gate["access"], "invoke_tool", original)
    physical = catalog.describe(actor, CatalogDescribe(tool_ref="mcp.instance-1.inspect"))
    assert catalog.invoke(actor, CatalogInvoke(tool_ref=physical["tool_ref"], schema_revision=physical["schema_revision"], arguments={})).ok
    assert len(peers["instance-1"].calls) == 1


def test_session_routes_and_fixed_schemas_use_the_same_public_adapter(gate, integrated):
    catalog, group, _ = integrated
    actor = gate["principal"]
    app = FastAPI()
    def authenticated(request: Request):
        return actor
    register_catalog_routes(app, catalog=catalog, require_authenticated=authenticated)
    with TestClient(app) as client:
        described = selected(catalog, group, actor)
        opened_response = client.post("/v1/catalog/sessions/open", json={key: described[key]
            for key in ("tool_ref", "instance_id", "schema_revision")})
        assert opened_response.status_code == 200
        assert client.post("/v1/catalog/sessions/close", json={"session_id": opened_response.json()["session_id"]}).json()["closed"]
    schemas = catalog_tools()
    assert len(schemas) == 6 and sum(schema["name"] == "gate_tool_invoke" for schema in schemas) == 1
    assert schemas[2]["inputSchema"]["additionalProperties"] is False


def test_group_read_token_cannot_use_the_shared_invoker_to_write(gate, integrated):
    catalog, group, peers = integrated
    actor = gate["principal"]
    for instance in peers:
        gate["access"].set_classification(server_id=instance, tool_id=f"mcp.{instance}.inspect", access="write",
            destructive=True, idempotent=False, reviewer_id=actor.id)
        gate["access"].publish_classifications(reviewer_id=actor.id, server_id=instance)
    described = selected(catalog, group, actor)
    session = opened(catalog, described, actor)
    reader = replace(actor, delegated_scopes=("tools.read",))
    with pytest.raises(ToolExecutionError):
        catalog.call("gate_tool_invoke", {"tool_ref": described["tool_ref"], "instance_id": described["instance_id"],
            "schema_revision": described["schema_revision"], "session_id": session, "arguments": {}}, reader)
    assert all(not peer.calls for peer in peers.values())


def test_group_calls_to_two_instances_reach_their_peers_concurrently(gate, integrated, monkeypatch):
    catalog, group, peers = integrated
    actor = gate["principal"]
    requests = []
    for instance in ("instance-0", "instance-1"):
        described = selected(catalog, group, actor, instance)
        requests.append(CatalogInvoke(tool_ref=described["tool_ref"], instance_id=instance,
            schema_revision=described["schema_revision"], session_id=opened(catalog, described, actor), arguments={"target": instance}))
    barrier = Barrier(2)
    for instance in ("instance-0", "instance-1"):
        peer = peers[instance]
        original = peer.call_tool
        def synchronized(name, arguments, original=original):
            barrier.wait(timeout=3)
            return original(name, arguments)
        monkeypatch.setattr(peer, "call_tool", synchronized)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda request: catalog.invoke(actor, request), requests))
    assert all(response.ok for response in results), results
    assert len(peers["instance-0"].calls) == len(peers["instance-1"].calls) == 1


@pytest.mark.parametrize("write", ["config", "group"])
def test_group_dispatch_shared_lease_still_blocks_mutations(gate, integrated, monkeypatch, write):
    catalog, group, peers = integrated
    actor = gate["principal"]
    described = selected(catalog, group, actor)
    request = CatalogInvoke(tool_ref=described["tool_ref"], instance_id="instance-0",
        schema_revision=described["schema_revision"], session_id=opened(catalog, described, actor), arguments={})
    entered, release, started, written = Event(), Event(), Event(), Event()
    original = peers["instance-0"].call_tool
    def blocked(name, arguments):
        entered.set()
        assert release.wait(3)
        return original(name, arguments)
    monkeypatch.setattr(peers["instance-0"], "call_tool", blocked)
    failures, results = [], []
    def mutate():
        started.set()
        try:
            if write == "group":
                gate["service"].delete(group["id"], group["revision"], actor)
            else:
                manifest = gate["configs"].load_manifest("instance-0").model_dump(exclude={"manifest_path"})
                gate["configs"].save_config({**manifest, "name": "After invocation"}, overwrite=True)
        except Exception as error:
            failures.append(error)
        finally:
            written.set()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(catalog.invoke, actor, request)
        assert entered.wait(2)
        thread = Thread(target=mutate)
        thread.start()
        assert started.wait(1) and not written.wait(.05)
        release.set()
        results.append(future.result(timeout=3))
        thread.join(timeout=3)
    assert results[0].ok and written.is_set() and not failures
    with pytest.raises(ToolExecutionError):
        catalog.call("gate_tool_invoke", request.model_dump(), actor)

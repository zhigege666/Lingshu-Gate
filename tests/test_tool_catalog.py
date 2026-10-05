"""Permission, pagination and incremental discovery without full schemas."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.catalog_routes import register_catalog_routes
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.registry import ToolExecutionError, ToolRecord, ToolRegistry
from lingshu_gate.tool_catalog import (
    CATALOG_TOOL_NAMES, CatalogDescribe, CatalogInvoke, CatalogSearch, ToolCatalog, schema_revision, _validate_arguments,
)


@pytest.fixture
def catalog(tmp_path):
    database = SQLiteDatabase("", tmp_path)
    access = AccessControlStore(database)
    registry = ToolRegistry()
    database.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES('alice','alice','unused','now','now')")
    for instance in ("one", "two"):
        for index in range(4):
            registry.register(ToolDefinition(id=f"mcp.{instance}.read_{index}", name=f"Read {index}",
                description="Find records", source="mcp", input_schema={"type": "object", "required": ["key"],
                    "properties": {"key": {"type": "string"}}, "additionalProperties": False},
                metadata={"server_id": instance}), lambda arguments: arguments)
    service = ToolCatalog(registry, access)
    service.synchronize()
    database.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published'")
    access.save_grant(subject_type="user", subject_id="alice", server_id="one", permission_type_code="read", created_by="alice")
    principal = AuthPrincipal(id="alice", username="alice", role="operator", roles=("operator",), permissions=("tools.read", "tools.invoke"))
    return service, principal


def test_search_matches_existing_authorization_and_contains_no_schema(catalog):
    service, principal = catalog
    expected = {d.id for d in service.access.visible_tools(principal, service.registry.list_definitions())}
    output = service.search(principal, CatalogSearch(query="read"))
    assert {t["tool_ref"] for t in output["tools"]} == expected
    assert "two" not in str(output)
    assert "input_schema" not in str(output)
    assert "total" not in output
    assert service.search(principal, CatalogSearch(), instances=True)["instances"] == [{"instance_id": "one", "group_id": None}]


def test_cursor_binding_revocation_and_guessing(catalog):
    service, principal = catalog
    first = service.search(principal, CatalogSearch(limit=1))
    cursor = first["next_cursor"]
    next_page = service.search(principal, CatalogSearch(limit=1, cursor=cursor))
    assert next_page["tools"][0] != first["tools"][0]
    for changed in (replace(principal, id="other"), replace(principal, auth_type="token", scopes=("tools.read",))):
        with pytest.raises(ToolExecutionError, match="cursor"):
            service.search(changed, CatalogSearch(limit=1, cursor=cursor))
    service.database.execute("DELETE FROM mcp_resource_grants")
    with pytest.raises(ToolExecutionError, match="cursor"):
        service.search(principal, CatalogSearch(limit=1, cursor=cursor))
    assert service.search(principal, CatalogSearch())["tools"] == []
    for tool_ref in ("mcp.two.read_0", "missing"):
        with pytest.raises(ToolExecutionError) as error:
            service.describe(principal, CatalogDescribe(tool_ref=tool_ref))
        assert error.value.code == "catalog_tool_unavailable"


def test_incremental_search_never_lists_registry_or_rebuilds_index(catalog, monkeypatch):
    service, principal = catalog
    before = service.database.query_one("SELECT SUM(rowid) FROM gate_tool_catalog")[0]
    monkeypatch.setattr(service.registry, "list_definitions", lambda: pytest.fail("Full catalog scan"))
    monkeypatch.setattr(service.access, "_synchronize_tools", lambda *_: pytest.fail("Per-request classification rebuild"))
    for _ in range(3):
        assert len(service.search(principal, CatalogSearch())["tools"]) == 4
    assert service.database.query_one("SELECT SUM(rowid) FROM gate_tool_catalog")[0] == before


def test_registration_removal_and_reappearance_never_grant_access(catalog):
    service, principal = catalog
    original = service.registry.get_definition("mcp.one.read_0")
    new = original.model_copy(update={"id": "mcp.one.new", "name": "New"})
    service.registry.replace_by_metadata("server_id", "one", [ToolRecord(new, lambda _: {})], source="mcp")
    assert service.search(principal, CatalogSearch())["tools"] == []
    assert service.database.query_one("SELECT status FROM mcp_tool_classifications WHERE tool_id=?", (new.id,))[0] == "pending"
    assert service.database.query_one("SELECT COUNT(*) FROM gate_tool_catalog WHERE instance_id='one'")[0] == 1
    service.registry.unregister_by_metadata("server_id", "one", source="mcp")
    assert service.search(principal, CatalogSearch())["tools"] == []
    service.registry.register(original, lambda _: {})
    assert service.search(principal, CatalogSearch())["tools"] == []
    assert service.database.query_one("SELECT status FROM mcp_tool_classifications WHERE tool_id=?", (original.id,))[0] == "stale"


def test_target_snapshot_replacement_preserves_other_instance_index_and_review(catalog):
    service, principal = catalog
    existing = service.registry.get_definition("mcp.one.read_0")
    unchanged = service.database.query_all("SELECT tool_id,status,effective_access FROM mcp_tool_classifications WHERE server_id='two'")
    service.registry.replace_by_metadata("server_id", "one", [ToolRecord(existing, lambda arguments: arguments)], source="mcp")
    service.search(principal, CatalogSearch())
    assert service.database.query_one("SELECT COUNT(*) FROM gate_tool_catalog WHERE instance_id='two'")[0] == 4
    assert [tuple(row) for row in service.database.query_all(
        "SELECT tool_id,status,effective_access FROM mcp_tool_classifications WHERE server_id='two'")] == [tuple(row) for row in unchanged]


def test_explicit_definition_update_invalidates_directory_and_cursor(catalog):
    service, principal = catalog
    first = service.search(principal, CatalogSearch(limit=1))
    definition = service.registry.get_definition("mcp.one.read_0")
    service.registry.update_definition(definition.model_copy(update={"description": "New visible description"}))
    with pytest.raises(ToolExecutionError) as error:
        service.search(principal, CatalogSearch(limit=1, cursor=first["next_cursor"]))
    assert error.value.code == "catalog_cursor_invalid"
    assert service.database.query_one("SELECT description FROM gate_tool_catalog WHERE tool_ref=?", (definition.id,))[0] == "New visible description"


def test_none_tool_override_and_hidden_ranking(catalog):
    service, principal = catalog
    service.access.save_grant(subject_type="user", subject_id="alice", server_id="one",
        tool_id="mcp.one.read_0", permission_type_code="none", created_by="alice")
    output = service.search(principal, CatalogSearch(query="read"))
    assert len(output["tools"]) == 3
    service.registry.register(ToolDefinition(id="mcp.hidden.exact", name="read", description="read", source="mcp",
        metadata={"server_id": "hidden"}), lambda _: {})
    assert service.search(principal, CatalogSearch(query="read"))["tools"] == output["tools"]


def test_oauth_exact_allowlist_and_publication(catalog):
    service, principal = catalog
    oauth = replace(principal, auth_type="oauth", scopes=("mcp.read",), delegated_scopes=("mcp.read",),
        external_grant_id="synthetic", external_server_ids=("one",), external_tool_ids=("mcp.one.read_1",),
        external_access=("read",), external_expires_at="2999-01-01T00:00:00+00:00")
    assert [item["tool_ref"] for item in service.search(oauth, CatalogSearch())["tools"]] == ["mcp.one.read_1"]
    service.database.execute("UPDATE mcp_tool_classifications SET status='stale' WHERE tool_id='mcp.one.read_1'")
    assert service.search(oauth, CatalogSearch())["tools"] == []
    assert service.search(replace(oauth, oauth_resource="https://gate.example.test/mcp/manage"), CatalogSearch())["tools"] == []


def test_invoke_uses_original_audit_and_validates_arguments_revision_instance(catalog):
    service, principal = catalog
    described = service.describe(principal, CatalogDescribe(tool_ref="mcp.one.read_0"))
    request = CatalogInvoke(tool_ref=described["tool_ref"], schema_revision=described["schema_revision"], arguments={"key": "sample"})
    assert service.invoke(principal, request).output == {"key": "sample"}
    audit = service.database.query_one("SELECT tool_id,server_id,outcome FROM invocation_audits ORDER BY rowid DESC LIMIT 1")
    assert tuple(audit) == ("mcp.one.read_0", "one", "success")
    for changed in (request.model_copy(update={"schema_revision": "0" * 64}),
                    request.model_copy(update={"arguments": {"key": 1}}),
                    request.model_copy(update={"arguments": {"key": "x", "extra": True}}),
                    request.model_copy(update={"instance_id": "two"})):
        with pytest.raises(ToolExecutionError):
            service.invoke(principal, changed)


@pytest.mark.parametrize("metadata", [{}, {"outputSchema": {}}, {"output_schema": {}}])
def test_describe_preserves_empty_schema_and_absent_output_distinction(catalog, metadata):
    service, principal = catalog
    definition = service.registry.get_definition("mcp.one.read_0")
    changed = definition.model_copy(update={"input_schema": {}, "metadata": {**definition.metadata, **metadata}})
    service.registry.update_definition(changed)
    service.synchronize()
    service.database.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published' WHERE tool_id=?", (changed.id,))
    described = service.describe(principal, CatalogDescribe(tool_ref=changed.id))
    assert described["input_schema"] == {}
    assert ("output_schema" in described) == bool(metadata)
    if metadata:
        assert described["output_schema"] == {}


def test_read_token_cannot_invoke_write_and_oauth_cannot_guess_target(catalog):
    service, principal = catalog
    service.database.execute("UPDATE mcp_tool_classifications SET effective_access='write' WHERE tool_id='mcp.one.read_0'")
    service.access.save_grant(subject_type="user", subject_id="alice", server_id="one", permission_type_code="write", created_by="alice")
    definition = service.registry.get_definition("mcp.one.read_0")
    request = CatalogInvoke(tool_ref=definition.id, schema_revision=schema_revision(definition), arguments={"key": "x"})
    reader = replace(principal, auth_type="token", scopes=("tools.read",))
    with pytest.raises(ToolExecutionError) as error:
        service.invoke(reader, request)
    assert error.value.code == "catalog_tool_unavailable"
    assert service.search(reader, CatalogSearch())["tools"]
    assert definition.id not in {t["tool_ref"] for t in service.search(reader, CatalogSearch())["tools"]}


def test_dispatch_reauthenticates_after_queue_admission(catalog, monkeypatch):
    service, principal = catalog
    definition = service.registry.get_definition("mcp.one.read_0")
    calls = []
    service.registry.register(definition, lambda _: calls.append("dispatched") or {}, replace=True)
    reader = replace(principal, auth_type="token", token_id="synthetic", scopes=("tools.read",))
    current = [reader]
    original = service.access.invoke_tool
    def queued(*args, **kwargs):
        current[0] = replace(reader, scopes=())
        return original(*args, **kwargs)
    monkeypatch.setattr(service.access, "invoke_tool", queued)
    result = service.invoke(reader, CatalogInvoke(tool_ref=definition.id, schema_revision=schema_revision(definition),
        arguments={"key": "x"}), refresh_principal=lambda: current[0])
    assert not result.ok
    assert result.output["error"]["code"] == "catalog_identity_changed"
    assert calls == []
    assert service.database.query_one("SELECT outcome FROM invocation_audits ORDER BY rowid DESC LIMIT 1")[0] == "not_invoked"


def test_multiple_instances_dispatch_concurrently(catalog):
    service, principal = catalog
    service.access.save_grant(subject_type="user", subject_id="alice", server_id="two", permission_type_code="read", created_by="alice")
    barrier = Barrier(2)
    for instance in ("one", "two"):
        definition = service.registry.get_definition(f"mcp.{instance}.read_0")
        service.registry.register(definition, lambda _: {"parallel": barrier.wait(timeout=5) >= 0}, replace=True)
    def invoke(instance):
        definition = service.registry.get_definition(f"mcp.{instance}.read_0")
        return service.invoke(principal, CatalogInvoke(tool_ref=definition.id, schema_revision=schema_revision(definition), arguments={"key": "x"}))
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert all(result.ok for result in executor.map(invoke, ("one", "two")))


def test_bounded_outputs_and_query_parameters(catalog):
    service, principal = catalog
    output = service.search(principal, CatalogSearch(max_bytes=2048, limit=1))
    assert len(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()) <= 2048
    assert output["has_more"]
    with pytest.raises(ToolExecutionError):
        service.search(principal, CatalogSearch(query="a b c d e f g h i"))
    definition = service.registry.get_definition("mcp.one.read_0")
    service.registry.register(definition.model_copy(update={"input_schema": {"type": "object", "description": "x" * 3000}}), lambda _: {}, replace=True)
    admin = replace(principal, role="admin", roles=("admin",))
    with pytest.raises(ToolExecutionError) as error:
        service.describe(admin, CatalogDescribe(tool_ref=definition.id, max_bytes=2048))
    assert error.value.code == "catalog_schema_limit"


@pytest.mark.parametrize("schema,arguments", [
    ({"$ref": "https://schema.example.test/tool"}, {}),
    ({"$dynamicRef": "#/x"}, {}),
    ({"$schema": "https://schema.example.test/unknown"}, {}),
    ({"type": "object", "$defs": {"x": {"$ref": "#/$defs/x"}}, "$ref": "#/$defs/x"}, {}),
    ({"type": "object"}, {"x": "x" * 1_048_576}),
])
def test_schema_validation_fails_closed_without_remote_fetch(schema, arguments):
    with pytest.raises(ToolExecutionError):
        _validate_arguments(schema, arguments)


def test_local_reference_full_schema_validation():
    schema = {"type": "object", "$defs": {"key": {"type": "integer", "minimum": 1}},
              "properties": {"key": {"$ref": "#/$defs/key"}}, "required": ["key"]}
    _validate_arguments(schema, {"key": 1})
    with pytest.raises(ToolExecutionError):
        _validate_arguments(schema, {"key": 0})


def test_argument_limit_preserves_existing_512_kib_upload_chunks():
    import base64
    from lingshu_gate.project_delivery_mcp import MAX_CHUNK_BYTES, MAX_BASE64_CHARS

    chunk = base64.b64encode(bytes(MAX_CHUNK_BYTES)).decode()
    _validate_arguments({"type": "object", "properties": {
        "data_base64": {"type": "string", "maxLength": MAX_BASE64_CHARS}}, "required": ["data_base64"]},
        {"data_base64": chunk})


def test_mcp_and_api_adapters_keep_legacy_listing_and_hide_direct_calls(catalog):
    service, principal = catalog
    app = FastAPI()
    def require(request: Request) -> AuthPrincipal:
        return principal
    register_catalog_routes(app, catalog=service, require_authenticated=require)
    register_mcp_gateway_route(app, Settings(), service.registry, service.access, require, catalog=service)
    client = TestClient(app)
    headers = {"accept": "application/json,text/event-stream", "MCP-Protocol-Version": MCP_PROTOCOL_VERSION}
    def rpc(method, params=None, mode="on_demand"):
        current_params, protocol_headers = build_protocol_request(method, params or {},
            client_name="catalog-test", client_version="1.0", protocol_version=MCP_PROTOCOL_VERSION)
        return client.post("/mcp" + (f"?tool_mode={mode}" if mode else ""), headers={**headers, **protocol_headers},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": current_params})
    listed = rpc("tools/list")
    assert listed.status_code == 200
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == list(CATALOG_TOOL_NAMES)
    assert len(rpc("tools/list", mode="").json()["result"]["tools"]) == 4
    assert "error" in rpc("tools/call", {"name": "mcp__one__read_0"}).json()
    searched = rpc("tools/call", {"name": "gate_catalog_search", "arguments": {"query": "read", "limit": 1}})
    assert len(searched.json()["result"]["structuredContent"]["tools"]) == 1
    described = client.post("/v1/catalog/describe", json={"tool_ref": "mcp.one.read_0"}).json()
    invoked = client.post("/v1/catalog/invoke", json={"tool_ref": described["tool_ref"], "schema_revision": described["schema_revision"], "arguments": {"key": "x"}})
    assert invoked.json()["ok"]
    assert client.post("/v1/catalog/search", json={"limit": 1000}).status_code == 400
    assert client.post("/v1/catalog/describe", json={"tool_ref": "mcp.two.read_0"}).status_code == 404
    assert rpc("tools/list", mode="invalid").status_code == 400
    assert rpc("tools/list", mode="direct&tool_mode=on_demand").status_code == 400


def test_reserved_name_collision_fails_closed(catalog):
    service, principal = catalog
    service.registry.register(ToolDefinition(id="gate_catalog_search", name="Collision", description="Hidden"), lambda _: {})
    with pytest.raises(ToolExecutionError) as error:
        service.call("gate_catalog_search", {}, principal)
    assert error.value.code == "catalog_namespace_conflict"
    assert "Hidden" not in error.value.message


def test_discovery_revalidates_principal_before_returning_any_names(catalog):
    service, principal = catalog
    with pytest.raises(ToolExecutionError) as error:
        service.call("gate_catalog_search", {}, principal,
            refresh_principal=lambda: replace(principal, permissions=()))
    assert error.value.code == "catalog_identity_changed"

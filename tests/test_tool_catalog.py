"""Permission, pagination and incremental discovery without full schemas."""
from dataclasses import replace

import pytest

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolExecutionError, ToolRecord, ToolRegistry
from lingshu_gate.tool_catalog import CatalogDescribe, CatalogSearch, ToolCatalog


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


def test_none_tool_override_and_hidden_ranking(catalog):
    service, principal = catalog
    service.access.save_grant(subject_type="user", subject_id="alice", server_id="one",
        tool_id="mcp.one.read_0", permission_type_code="none", created_by="alice")
    output = service.search(principal, CatalogSearch(query="read"))
    assert len(output["tools"]) == 3
    service.registry.register(ToolDefinition(id="mcp.hidden.exact", name="read", description="read", source="mcp",
        metadata={"server_id": "hidden"}), lambda _: {})
    assert service.search(principal, CatalogSearch(query="read"))["tools"] == output["tools"]

from __future__ import annotations

import jsonschema
import pytest
from pydantic import ValidationError

from lingshu_gate.pinned_tools import project_pins
from lingshu_gate.tool_catalog import CatalogSearch, ToolCatalog
from lingshu_gate.domain.mcp_group_routing import logical_service_id
from lingshu_gate.registry import ToolExecutionError
from test_mcp_group_routing import gate as gate, routing as routing, selection, grant, user
from test_mcp_groups import catalog_tool, create


def test_logical_pin_preserves_explicit_instance_session_and_no_replay(gate, routing):
    router, group, peers = routing
    actor = gate["principal"]
    selected = selection(router, group, actor, "instance-2")
    catalog = ToolCatalog(gate["registry"], gate["access"], group_router=router)
    pins = project_pins(catalog, actor, {"tool_discovery_mode": "on_demand",
        "pinned_tools": [{"kind": "group", "tool_ref": selected.tool_ref}]})
    assert len(pins) == 1
    pin = pins[0]
    with pytest.raises(ValidationError):
        pin.invocation({"arguments": {}})
    session = router.open_session(actor, selected)
    request = {"instance_id": "instance-2", "session_id": session["session_id"], "schema_revision": pin.revision,
               "arguments": {"target": "chosen", "x": 4}}
    assert catalog.invoke(actor, pin.invocation(request)).ok
    assert peers["instance-2"].calls == [("inspect", {"target": "chosen", "x": 4})]
    assert peers["instance-0"].calls == peers["instance-1"].calls == []
    with pytest.raises(ValidationError):
        pin.invocation({**request, "tool_ref": "different"})
    router.close_session(actor, session["session_id"])
    with pytest.raises(ToolExecutionError):
        catalog.invoke(actor, pin.invocation(request))
    assert len(peers["instance-2"].calls) == 1


@pytest.mark.parametrize("schema", [
    {"type": "object", "$defs": {"N": {"type": "integer", "minimum": 1}}, "properties": {"n": {"$ref": "#/$defs/N"}}, "required": ["n"]},
    {"type": "object", "properties": {"positive": {"type": "integer", "minimum": 1}, "n": {"$ref": "#/properties/positive"}}, "required": ["n"]},
    {"$id": "urn:synthetic:business", "type": "object", "$defs": {"N": {"type": "integer", "minimum": 1}}, "properties": {"n": {"$ref": "#/$defs/N"}}, "required": ["n"]},
    {"$schema": "http://json-schema.org/draft-04/schema#", "type": "object", "definitions": {"N": {"type": "integer", "minimum": 1}}, "properties": {"n": {"$ref": "#/definitions/N"}}, "required": ["n"]},
])
def test_group_pin_embedding_keeps_local_reference_resource(gate, routing, schema):
    router, group, _ = routing
    for index in range(3):
        catalog_tool(gate, f"instance-{index}", name="inspect", schema=schema)
    actor = gate["principal"]
    selected = selection(router, group, actor)
    catalog = ToolCatalog(gate["registry"], gate["access"], group_router=router)
    pin = project_pins(catalog, actor, {"tool_discovery_mode": "on_demand",
        "pinned_tools": [{"kind": "group", "tool_ref": selected.tool_ref}]})[0]
    envelope = {"instance_id": "instance-0", "session_id": "a" * 32, "schema_revision": pin.revision}
    jsonschema.validate({"n": 1}, schema)
    jsonschema.validate({**envelope, "arguments": {"n": 1}}, pin.payload["inputSchema"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**envelope, "arguments": {"n": 0}}, pin.payload["inputSchema"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**envelope, "arguments": {}}, pin.payload["inputSchema"])


def test_hidden_group_matches_never_create_pages_or_expand_schemas(gate, routing, monkeypatch):
    router, _, _ = routing
    actor, _ = user(gate)
    grant(gate, actor, "instance-0")
    for index in range(3):
        create(gate, name=f"Hidden matching group {index}", members=["instance-0"])
    catalog = ToolCatalog(gate["registry"], gate["access"], group_router=router)
    def no_expansion(*args, **kwargs):
        pytest.fail("A group without any logical grant must not expand tool schemas.")
    monkeypatch.setattr(router, "directory_page", no_expansion)
    for query in ("matching", "absent", ""):
        result = catalog.visible_groups(actor, CatalogSearch(query=query, limit=1))
        assert result == {"groups": [], "next_cursor": None, "has_more": False}


def test_hidden_groups_do_not_displace_visible_pagination(gate, routing):
    router, first, _ = routing
    second = create(gate, name="Other visible group", members=["instance-0"])
    actor, _ = user(gate)
    grant(gate, actor, "instance-0")
    for group in (first, second):
        grant(gate, actor, logical_service_id(group["id"]))
    catalog = ToolCatalog(gate["registry"], gate["access"], group_router=router)
    def pages():
        first_page = catalog.visible_groups(actor, CatalogSearch(limit=1))
        assert len(first_page["groups"]) == 1 and first_page["next_cursor"]
        last_page = catalog.visible_groups(actor, CatalogSearch(limit=1, cursor=first_page["next_cursor"]))
        assert len(last_page["groups"]) == 1 and last_page["next_cursor"] is None
        return first_page["groups"] + last_page["groups"]
    before = pages()
    for index in range(5):
        create(gate, name=f"Hidden group {index}", members=["instance-0"])
    assert pages() == before
    assert {item["id"] for item in before} == {first["id"], second["id"]}


def test_specific_variant_grant_survives_logical_default_none(gate, routing):
    router, group, _ = routing
    tool_ref = selection(router, group, gate["principal"]).tool_ref
    actor, _ = user(gate)
    grant(gate, actor, "instance-0")
    service_id = logical_service_id(group["id"])
    gate["access"].save_grant(subject_type="user", subject_id=actor.id, server_id=service_id,
        permission_type_code="none", created_by=gate["principal"].id)
    grant(gate, actor, service_id, tool_ref)
    catalog = ToolCatalog(gate["registry"], gate["access"], group_router=router)
    result = catalog.visible_groups(actor, CatalogSearch(limit=1))
    assert result["groups"] == [{"id": group["id"], "name": group["name"]}]
    assert result["next_cursor"] is None

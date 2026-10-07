"""Conservative contract partitioning; no routing or downstream execution."""
from __future__ import annotations

import math

import pytest

from lingshu_gate.domain import mcp_group_catalog as catalog
from lingshu_gate.domain.mcp_group_catalog import VisibleCatalogTool, build_catalog, canonical_contract
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.models import ToolDefinition


def visible(index: int, *, name="query", schema=None, metadata=None, review=None):
    instance = f"synthetic-{index}"
    definition = ToolDefinition(id=f"mcp.{instance}.{name}", name=f"Display {index}", description=f"Description {index}",
        source="mcp", input_schema={} if schema is None else schema,
        metadata={"original_tool_name": name, "server_id": instance, **(metadata or {})})
    row = {"status": "published", "reviewed_by": "synthetic-reviewer", "reviewed_at": "2026-10-05T00:00:00Z",
           "effective_access": "write", "destructive": False, "idempotent": False, "open_world": True,
           **(review or {})}
    return VisibleCatalogTool(definition, instance, f"Synthetic {index}", row)


def test_key_order_normalizes_without_changing_types_arrays_or_keywords():
    left = {"type": "object", "properties": {"b": {"type": "string"}, "a": {"type": "boolean"}}}
    right = {"properties": {"a": {"type": "boolean"}, "b": {"type": "string"}}, "type": "object"}
    assert canonical_contract(left) == canonical_contract(right)
    assert canonical_contract({"default": True}) != canonical_contract({"default": 1})
    assert canonical_contract({"required": ["a", "b"]}) != canonical_contract({"required": ["b", "a"]})
    assert canonical_contract({}) != canonical_contract({"description": "Business A"})
    items = [visible(0, schema=left), visible(1, schema=right)]
    before = [item.definition.model_dump() for item in items]
    variants = build_catalog("synthetic-group", items)
    assert len(variants) == 1 and variants[0].summary.compatibility == "reviewed_contract_match"
    assert variants[0].summary.visible_member_count == 2
    assert [item.definition.model_dump() for item in items] == before
    assert [member.tool_id for member in variants[0].members] == [item.definition.id for item in items]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, b"not-json", (1, 2), {1: "non-string key"}])
def test_non_json_contracts_are_rejected(bad):
    with pytest.raises(ValueError):
        canonical_contract({"default": bad})


def test_depth_cycle_size_and_node_limits_are_bounded():
    cycle = {}
    cycle["self"] = cycle
    for value in [cycle, {"description": "x" * (catalog.MAX_SCHEMA_BYTES + 1)}, list(range(catalog.MAX_SCHEMA_NODES + 1))]:
        with pytest.raises(ValueError):
            canonical_contract(value)
    schema = {}
    for _ in range(catalog.MAX_SCHEMA_DEPTH + 1):
        schema = {"properties": schema}
    with pytest.raises(ValueError):
        canonical_contract(schema)


def test_total_contract_bytes_are_checked_before_full_serialization(monkeypatch):
    original = catalog.json.dumps
    def bounded_dump(value, **kwargs):
        assert not isinstance(value, (dict, list)), "Oversize contract must stop before complete serialization"
        return original(value, **kwargs)
    monkeypatch.setattr(catalog.json, "dumps", bounded_dump)
    with pytest.raises(ValueError, match="schema_size_limit"):
        canonical_contract({str(index): "x" * 20_000 for index in range(7)})


def test_byte_budget_counts_json_escapes_and_utf8_exactly(monkeypatch):
    value = {"text": "中文\n\"\\", "list": [True, None, 1.25, -20]}
    expected = catalog.json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    monkeypatch.setattr(catalog, "MAX_SCHEMA_BYTES", len(expected.encode("utf-8")))
    assert canonical_contract(value) == expected
    monkeypatch.setattr(catalog, "MAX_SCHEMA_BYTES", len(expected.encode("utf-8")) - 1)
    with pytest.raises(ValueError, match="schema_size_limit"):
        canonical_contract(value)


def test_missing_output_schema_differs_from_empty_and_nonobject_output():
    variants = build_catalog("group", [visible(0), visible(1, metadata={"outputSchema": {}}),
                                       visible(2, metadata={"outputSchema": None})])
    assert len(variants) == 3
    assert all(item.summary.visible_variant_count == 3 for item in variants)
    assert {item.summary.output_schema_present for item in variants} == {False, True}
    assert next(item for item in variants if item.members[0].instance_id == "synthetic-2").summary.compatibility == "uncomparable"


@pytest.mark.parametrize("review", [{"status": "pending"}, {"status": "stale"}, {"status": "removed"},
                                    {"effective_access": "unknown"}, {"reviewed_by": None}, {"reviewed_at": None}])
def test_unreviewed_contracts_never_aggregate(review):
    variants = build_catalog("group", [visible(0, review=review), visible(1, review=review)])
    assert len(variants) == 2
    assert all(item.summary.compatibility == "review_required" and item.summary.safety is None for item in variants)


@pytest.mark.parametrize("review", [{"effective_access": "read"}, {"destructive": True},
                                    {"idempotent": True}, {"open_world": False}])
def test_each_reviewed_safety_dimension_separates_variants(review):
    variants = build_catalog("group", [visible(0), visible(1, review=review)])
    assert len(variants) == 2 and variants[0].summary.safety_digest != variants[1].summary.safety_digest


@pytest.mark.parametrize("metadata", [{"required_control_permission": "operations.manage"},
                                      {"sensitive_input_fields": ["account"]},
                                      {"sensitive_output_fields": ["account"]},
                                      {"annotations": {"readOnlyHint": True}}])
def test_review_bound_policy_and_sensitive_fields_are_not_dropped(metadata):
    variants = build_catalog("group", [visible(0), visible(1, metadata=metadata)])
    assert len(variants) == 2
    assert all(item.summary.safety.required_access == "write" for item in variants)


def test_original_name_and_input_output_contracts_separate_explicit_variants():
    items = [visible(0), visible(1, name="Query"), visible(2, schema={"type": "object"}),
             visible(3, metadata={"outputSchema": {"type": "object"}})]
    variants = build_catalog("group", items)
    assert len(variants) == 4
    assert all(item.summary.original_tool_name == "query" for item in variants if item.members[0].instance_id != "synthetic-1")
    assert len({item.summary.variant_id for item in variants}) == 4


def test_catalog_capacity_fails_without_partial_results(monkeypatch):
    monkeypatch.setattr(catalog, "MAX_CATALOG_TOOLS", 1)
    with pytest.raises(McpGroupError, match="capacity") as error:
        build_catalog("group", [visible(0), visible(1)])
    assert error.value.status == 503
    monkeypatch.setattr(catalog, "MAX_CATALOG_TOOLS", 10)
    monkeypatch.setattr(catalog, "MAX_CATALOG_CONTRACT_BYTES", 1)
    with pytest.raises(McpGroupError):
        build_catalog("group", [visible(0)])

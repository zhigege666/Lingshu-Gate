"""Immutable publication, bounded ingress and indexed snapshots without live peers."""
from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lingshu_gate.domain import tool_structure
from lingshu_gate.domain.tool_structure import MAX_SCHEMA_BYTES, checked_json_size
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import RegistrySnapshotCapacityError, ToolInvocationContext, ToolRecord, ToolRegistry


def tool(instance="synthetic", name="query"):
    return ToolDefinition(id=f"mcp.{instance}.{name}", name=name, description="Synthetic structure", source="mcp",
        input_schema={"type": "object", "properties": {"items": {"enum": ["first", "second"]}}},
        metadata={"server_id": instance, "original_tool_name": name, "annotations": {"readOnlyHint": True},
                  "outputSchema": {"type": "object"}, "sensitive_input_fields": ["private"]})


class Handler:
    def __init__(self):
        self.calls = []
    def __deepcopy__(self, memo):
        raise AssertionError("Handler must never be deep-copied")
    def __call__(self, arguments, context):
        self.calls.append((arguments, context))
        return {"synthetic": True}


def test_publication_getters_and_nested_schema_metadata_are_isolated_and_handler_is_preserved():
    registry, original, handler = ToolRegistry(), tool(), Handler()
    registry.register(original, handler, contextual=True)
    snapshot = registry.mcp_snapshot(["synthetic"], max_tools=10)
    original.input_schema["properties"]["items"]["enum"].append("external-mutation")
    original.metadata["sensitive_input_fields"].clear()
    original.metadata["annotations"]["readOnlyHint"] = False
    original.description = "external mutation"
    read = registry.get_definition(original.id)
    assert read.input_schema["properties"]["items"]["enum"] == ["first", "second"]
    assert read.metadata["sensitive_input_fields"] == ["private"]
    assert read.metadata["annotations"]["readOnlyHint"] is True
    assert read.description == "Synthetic structure"
    read.input_schema["properties"].clear()
    read.metadata["outputSchema"].clear()
    listed = registry.list_definitions()
    listed[0].metadata["annotations"].clear()
    assert registry.get_definition(original.id).input_schema["properties"]
    assert registry.get_definition(original.id).metadata["outputSchema"] == {"type": "object"}
    assert registry.mcp_snapshot_current(snapshot.revisions)
    frozen = snapshot.tools[0].structure
    with pytest.raises(FrozenInstanceError):
        frozen.description = "forbidden"
    with pytest.raises(TypeError):
        frozen.metadata["annotations"]["readOnlyHint"] = False
    assert frozen.input_schema["properties"]["items"]["enum"] == ("first", "second")
    changed = registry.get_definition(original.id)
    changed.description = "Explicitly published change"
    registry.update_definition(changed)
    assert not registry.mcp_snapshot_current(snapshot.revisions)
    updated = registry.mcp_snapshot(["synthetic"], max_tools=10)
    assert updated.tools[0].revision > snapshot.tools[0].revision
    assert updated.tools[0].structure is not frozen
    context = ToolInvocationContext("synthetic-actor", "synthetic", "session", None, "synthetic-correlation")
    arguments = {"private": "synthetic-value"}
    assert registry.invoke(original.id, arguments, context=context).ok
    assert handler.calls == [(arguments, context)]


@pytest.mark.parametrize("kind", ["cycle", "giant", "nodes", "non_json", "output", "metadata"])
def test_rejected_structure_is_bounded_before_copy_and_preserves_existing_publication(kind):
    registry, original = ToolRegistry(), tool()
    registry.register(original, lambda _: {})
    before = registry.mcp_snapshot(["synthetic"], max_tools=10)
    if kind == "cycle":
        schema = {}
        schema["self"] = schema
    elif kind == "giant":
        schema = {"description": "x" * (MAX_SCHEMA_BYTES + 1)}
    elif kind == "nodes":
        schema = {"enum": list(range(10_001))}
    else:
        schema = {"default": math.nan}
    changed = original.model_copy(update={"input_schema": schema})
    if kind == "output":
        changed = original.model_copy(update={"metadata": {**original.metadata, "outputSchema": []}})
    if kind == "metadata":
        changed = original.model_copy(update={"metadata": {"server_id": "synthetic", "blob": "x" * (512 * 1024)}})
    with patch("lingshu_gate.domain.tool_structure._freeze_json", side_effect=AssertionError("Copy before budget")):
        with pytest.raises(ValueError, match="tool_"):
            registry.register(changed, lambda _: {}, replace=True)
        with pytest.raises(ValueError, match="tool_"):
            registry.update_definition(changed)
        with pytest.raises(ValueError, match="tool_"):
            registry.replace_by_metadata("server_id", "synthetic", [ToolRecord(changed, lambda _: {})], source="mcp")
    assert registry.mcp_snapshot_current(before.revisions)
    assert registry.get_definition(original.id) == original


def test_replace_detaches_external_records_and_unregister_recreate_invalidates_snapshot():
    registry, original = ToolRegistry(), tool()
    registry.replace_by_metadata("server_id", "synthetic", [ToolRecord(original, lambda _: {})], source="mcp")
    original.input_schema.clear()
    before = registry.mcp_snapshot(["synthetic"], max_tools=10)
    assert before.tools[0].structure.input_schema
    registry.register(tool("unrelated"), lambda _: {})
    assert registry.mcp_snapshot_current(before.revisions)
    assert registry.unregister_by_metadata("server_id", "synthetic", source="mcp") == 1
    assert not registry.mcp_snapshot_current(before.revisions)
    missing = registry.mcp_snapshot(["synthetic"], max_tools=10)
    assert not missing.tools
    registry.register(tool(), lambda _: {})
    assert not registry.mcp_snapshot_current(missing.revisions)


def test_copy_stays_bounded_when_external_input_changes_after_preflight():
    registry, original = ToolRegistry(), tool()
    registry.register(original, lambda _: {})
    before = registry.mcp_snapshot(["synthetic"], max_tools=10)
    original_check = tool_structure.check_tool_structure
    def change_after_check(data):
        result = original_check(data)
        original.input_schema["description"] = "x" * (MAX_SCHEMA_BYTES + 1)
        return result
    with patch.object(tool_structure, "check_tool_structure", side_effect=change_after_check):
        with pytest.raises(ValueError, match="size_limit"):
            registry.update_definition(original)
    assert registry.mcp_snapshot_current(before.revisions)
    assert "description" not in registry.get_definition(original.id).input_schema


@pytest.mark.parametrize("field", ["source", "server_id", "original_tool_name"])
def test_structure_update_cannot_retarget_preserved_handler(field):
    registry, original = ToolRegistry(), tool()
    registry.register(original, lambda _: {"original": True})
    before = registry.mcp_snapshot(["synthetic"], max_tools=10)
    changed = original.model_copy(update={"source": "builtin"}) if field == "source" else original.model_copy(
        update={"metadata": {**original.metadata, field: "different"}})
    with pytest.raises(ValueError, match="identity changes"):
        registry.update_definition(changed)
    assert registry.mcp_snapshot_current(before.revisions)
    assert registry.get_definition(original.id) == original
    assert registry.invoke(original.id, {}).output == {"original": True}


def test_json_budget_matches_utf8_and_escaping_without_serializing():
    value = {"text": "中文\n\"\\\u0000", "items": [None, True, False, -25, 1e-7, -0.0]}
    expected = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    with patch("json.dumps", side_effect=AssertionError("Budget must not serialize")):
        assert checked_json_size(value, max_bytes=expected) == expected
        with pytest.raises(ValueError, match="size_limit"):
            checked_json_size(value, max_bytes=expected - 1)


@pytest.mark.parametrize("kind", ["giant", "cycle", "non_json"])
def test_runtime_discovery_rejects_before_model_copy_digest_or_review(kind):
    manifest = McpServerManifest.model_validate({"id": "synthetic", "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}})
    manager = object.__new__(McpRuntimeManager)
    schema = {"description": "x" * (MAX_SCHEMA_BYTES + 1)}
    if kind == "cycle":
        schema = {}
        schema["self"] = schema
    elif kind == "non_json":
        schema = {"default": b"synthetic"}
    with patch("lingshu_gate.mcp_runtime.ToolDefinition") as model:
        with pytest.raises(ValueError, match="tool_structure_"):
            manager._mcp_tool_records(SimpleNamespace(manifest=manifest), [{"name": "query", "inputSchema": schema}], strict=True)
        model.assert_not_called()


def test_5000_instances_50000_tools_snapshot_reads_only_selected_index_buckets():
    registry = ToolRegistry()
    def handler(_):
        return {}
    for index in range(5000):
        for number in range(10):
            registry.register(tool(f"bulk-{index:04d}", f"query-{number:02d}"), handler)
    class NoGlobalScan(dict):
        def __iter__(self):
            raise AssertionError("Global registry iteration")
        def values(self):
            raise AssertionError("Global registry values scan")
        def items(self):
            raise AssertionError("Global registry items scan")
    registry._tools = NoGlobalScan(registry._tools)
    with patch.object(registry, "list_definitions", side_effect=AssertionError("Global registry scan")), \
            patch("json.dumps", side_effect=AssertionError("Indexed read serialized structure")):
        first = registry.mcp_snapshot(["bulk-0999", "bulk-4999"], max_tools=20)
        assert len(first.tools) == 20
        second = registry.mcp_snapshot(["bulk-0999", "bulk-4999"], max_tools=20)
        assert second.revisions == first.revisions
        assert all(left.structure is right.structure for left, right in zip(first.tools, second.tools, strict=True))
        with pytest.raises(RegistrySnapshotCapacityError):
            registry.mcp_snapshot(["bulk-0999", "bulk-4999"], max_tools=19)
    assert {entry.structure.metadata["server_id"] for entry in first.tools} == {"bulk-0999", "bulk-4999"}

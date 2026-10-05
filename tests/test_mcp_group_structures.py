"""Immutable structural cache bounds, identity, and cold-read coordination."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from lingshu_gate.application import mcp_group_structures as structures
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.domain.tool_structure import freeze_tool_definition
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import RegistryToolSnapshot


def entry(index=0, *, revision=1, schema=None):
    definition = ToolDefinition(id=f"mcp.synthetic-{index}.query", name="query", description="Synthetic contract", source="mcp",
        input_schema={} if schema is None else schema,
        metadata={"server_id": f"synthetic-{index}", "original_tool_name": "query"})
    return RegistryToolSnapshot(freeze_tool_definition(definition), revision)


def test_key_requires_both_revision_and_actual_immutable_identity():
    cache = structures.ToolStructureCache()
    first = entry(schema={"type": "object"})
    changed = entry(schema={"type": "string"})
    advanced = RegistryToolSnapshot(first.structure, first.revision + 1)
    with patch.object(structures, "prepare_tool_structure", wraps=structures.prepare_tool_structure) as prepare:
        original = cache.get(first)
        assert cache.get(first) is original
        assert cache.get(changed).fingerprint != original.fingerprint
        assert cache.get(advanced).definition is first.structure
        assert prepare.call_count == 3
    with pytest.raises(TypeError):
        original.definition.input_schema["type"] = "array"
    assert not hasattr(original, "principal") and not hasattr(original, "classification")
    assert not hasattr(original, "grants") and not hasattr(original, "visible")


def test_entry_and_byte_limits_evict_old_structures():
    entries = [entry(index) for index in range(3)]
    cost = structures.prepare_tool_structure(entries[0]).cache_bytes
    for cache in [structures.ToolStructureCache(max_entries=2),
                  structures.ToolStructureCache(max_entries=10, max_bytes=2 * cost)]:
        with patch.object(structures, "prepare_tool_structure", wraps=structures.prepare_tool_structure) as prepare:
            for item in entries:
                cache.get(item)
            count, byte_count = cache.usage()
            assert count == 2 and byte_count <= cache.max_bytes
            cache.get(entries[0])
            assert prepare.call_count == 4
    for cache in [structures.ToolStructureCache(max_entries=0), structures.ToolStructureCache(max_bytes=1)]:
        assert cache.get(entries[0]).definition is entries[0].structure
        assert cache.usage() == (0, 0)


def test_concurrent_cold_read_prepares_once_without_holding_global_cache_lock():
    cache, value = structures.ToolStructureCache(), entry()
    reached, release, started_second = Event(), Event(), Event()
    original = structures.prepare_tool_structure
    def slow_prepare(current):
        reached.set()
        assert release.wait(3)
        return original(current)
    def second_read():
        started_second.set()
        return cache.get(value)
    with patch.object(structures, "prepare_tool_structure", side_effect=slow_prepare) as prepare, \
            ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, value)
        try:
            assert reached.wait(2)
            second = pool.submit(second_read)
            assert started_second.wait(2)
            assert cache.usage() == (0, 0), "Preparation must release the global cache lock"
        finally:
            release.set()
        assert first.result(timeout=3) is second.result(timeout=3)
        assert prepare.call_count == 1


def test_busy_preparation_fails_with_bounded_retryable_error(monkeypatch):
    cache, value = structures.ToolStructureCache(), entry()
    monkeypatch.setattr(structures, "PREPARATION_WAIT_SECONDS", 0.01)
    lock = cache._preparation_locks[hash((value.revision, value.structure)) % len(cache._preparation_locks)]
    with lock:
        with pytest.raises(McpGroupError) as busy:
            cache.get(value)
    assert busy.value.code == "group_catalog_busy" and busy.value.status == 409
    assert cache.usage() == (0, 0)

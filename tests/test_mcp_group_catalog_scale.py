"""Full HTTP directory measurements; synthetic scale is not a latency promise."""
import json
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from lingshu_gate.application import mcp_group_structures as structures
from lingshu_gate.domain import mcp_group_catalog as contracts
from lingshu_gate.models import ToolDefinition

from test_mcp_groups import catalog_path, catalog_token, create
from test_mcp_groups import gate as gate


class NoGlobalScan(dict):
    def __iter__(self):
        raise AssertionError("Directory reads must not iterate the global Registry")

    def values(self):
        raise AssertionError("Directory reads must not iterate the global Registry")

    def items(self):
        raise AssertionError("Directory reads must not iterate the global Registry")


def p95(samples):
    return round(sorted(samples)[math.ceil(len(samples) * 0.95) - 1] * 1000, 3)


@pytest.mark.parametrize("tool_instances,tools_each,over_cache", [(5000, 10, False), (1000, 50, False), (1000, 50, True)],
                         ids=["five_groups", "maximum_single_group", "over_cache_bytes"])
def test_full_directory_5000_instances_50000_tools(gate, monkeypatch, record_property, tool_instances, tools_each, over_cache):
    configs, registry, client = gate["configs"], gate["registry"], gate["client"]
    for index in range(3):
        configs.delete_config(f"instance-{index}")
    for index in range(5000):
        instance = f"scale-{index:04}"
        (configs.config_dir / f"{instance}.json").write_text(json.dumps({
            "id": instance, "name": f"Synthetic instance {index:04}", "launch": {"type": "external"},
            "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}}), encoding="utf-8")
    invoked = []
    def handler(_arguments):
        invoked.append(True)
        return {"synthetic": True}
    definitions = []
    for index in range(tool_instances):
        instance = f"scale-{index:04}"
        for tool_index in range(tools_each):
            name = f"query-{tool_index:02}"
            definition = ToolDefinition(id=f"mcp.{instance}.{name}", name=name, description="Synthetic catalog contract",
                source="mcp", input_schema={"type": "object", "properties": {"id": {"type": "string"}},
                    **({"description": "s" * 190} if over_cache else {})},
                metadata={"server_id": instance, "original_tool_name": name, "annotations": {"readOnlyHint": True}})
            registry.register(definition, handler)
            definitions.append(definition)
    assert len(definitions) == 50_000
    classifications = gate["access"].synchronize_tools(definitions)
    for start in range(0, len(classifications), 500):
        gate["access"].confirm_classifications(reviewer_id=gate["principal"].id, publish=True,
            items=[{"server_id": row["server_id"], "tool_id": row["tool_id"], "expected_fingerprint": row["fingerprint"]}
                   for row in classifications[start:start + 500]])
    del definitions, classifications
    groups = [create(gate, name=f"Synthetic scale group {start // 1000}",
        members=[f"scale-{index:04}" for index in range(start, start + 1000)])
        for start in range(0, tool_instances, 1000)]
    alternating_group = create(gate, name="Synthetic shared scale group",
        members=[f"scale-{index:04}" for index in range(500)]) if over_cache else None
    assert len(configs.instance_metadata()) == 5000
    _, headers = catalog_token(gate, ["operations.manage", "tools.read"])
    for name in ("_tools", "_structures", "_mcp_index"):
        monkeypatch.setattr(registry, name, NoGlobalScan(getattr(registry, name)))
    counts = {"fingerprints": 0, "normalizations": 0, "canonical_serializations": 0}
    originals = {"fingerprints": structures._tool_fingerprint,
                 "normalizations": structures.normalize_tool_contract,
                 "canonical_serializations": contracts.canonical_contract}
    def counted(name):
        def call(*args, **kwargs):
            counts[name] += 1
            return originals[name](*args, **kwargs)
        return call
    monkeypatch.setattr(structures, "_tool_fingerprint", counted("fingerprints"))
    monkeypatch.setattr(structures, "normalize_tool_contract", counted("normalizations"))
    monkeypatch.setattr(contracts, "canonical_contract", counted("canonical_serializations"))
    # Record initial misses independently of preparation. Each HTTP attempt
    # must prepare only these misses, even when insertion evicts held hits.
    batch_misses = []
    original_batch = structures.ToolStructureCache.get_many
    def observed_batch(cache, entries):
        items = tuple(entries)
        with cache._lock:
            missing = sum((item.revision, item.structure) not in cache._entries for item in items)
        before = counts.copy()
        result = original_batch(cache, items)
        assert counts["fingerprints"] - before["fingerprints"] == missing
        assert counts["normalizations"] - before["normalizations"] == missing
        assert counts["canonical_serializations"] - before["canonical_serializations"] == 3 * missing
        batch_misses.append(missing)
        return result
    monkeypatch.setattr(structures.ToolStructureCache, "get_many", observed_batch)
    cold, hot, catalog_pages, member_pages = [], [], [], []
    def query(group, samples, suffix="", **params):
        started = time.perf_counter()
        response = client.get(catalog_path(group, suffix), params=params, headers=headers)
        samples.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        return response.json()
    last_body = None
    for index in range(5):
        if len(groups) == 1:
            # Five independent structural cold reads of the maximal group.
            gate["catalog"].structures = structures.ToolStructureCache()
        group = groups[index % len(groups)]
        last_body = query(group, cold, limit=100)
        assert last_body["visible_tool_count"] == 1000 * tools_each
        assert last_body["visible_member_count"] == 1000 and last_body["total"] == tools_each
        assert all(item["visible_member_count"] == 1000 for item in last_body["variants"])
    expected_preparations = 50_000 if len(groups) == 5 else 250_000
    assert counts == {"fingerprints": expected_preparations, "normalizations": expected_preparations,
                      "canonical_serializations": 3 * expected_preparations}
    cold_counts = counts.copy()
    cached_count, charged_bytes = gate["catalog"].structures.usage()
    if over_cache:
        assert 25_000 < cached_count < 50_000 and charged_bytes <= structures.MAX_STRUCTURE_CACHE_BYTES
        with gate["catalog"].structures._lock:
            sample = next(iter(gate["catalog"].structures._entries.values()))
        assert 50_000 * sample.cache_bytes > structures.MAX_STRUCTURE_CACHE_BYTES
    else:
        assert cached_count == 50_000
    for index in range(10):
        body = query(groups[index % len(groups)], hot, limit=100)
        assert body["visible_tool_count"] == 1000 * tools_each
    for index in range(10):
        group_index = index % len(groups)
        group = groups[group_index]
        last_instance = (group_index + 1) * 1000 - 1
        last_tool = f"mcp.scale-{last_instance:04}.query-{tools_each - 1:02}"
        page = query(group, catalog_pages, q=last_tool, offset=0, limit=1)
        assert page["total"] == 1 and page["variants"][0]["original_tool_name"] == f"query-{tools_each - 1:02}"
        detail = query(group, member_pages, "/" + page["variants"][0]["variant_id"], offset=997, limit=100)
        assert detail["total"] == 1000
        assert [item["tool_id"] for item in detail["members"]] == [
            f"mcp.scale-{number:04}.query-{tools_each - 1:02}" for number in range(last_instance - 2, last_instance + 1)]
    warm_counts = {name: value - cold_counts[name] for name, value in counts.items()}
    if over_cache:
        assert len(batch_misses) == 35
        assert all(0 < missing < 25_000 for missing in batch_misses[5:])
        assert warm_counts["fingerprints"] == warm_counts["normalizations"] == sum(batch_misses[5:])
    else:
        assert counts == cold_counts, "A retained working set must perform zero additional structural preparation"
    alternating_misses = []
    if alternating_group:
        for group in [alternating_group, groups[0], alternating_group, groups[0]]:
            prior = len(batch_misses)
            response = client.get(catalog_path(group), headers=headers)
            assert response.status_code == 200
            assert response.json()["visible_tool_count"] == (25_000 if group is alternating_group else 50_000)
            assert len(batch_misses) == prior + 1
            alternating_misses.append(batch_misses[-1])
            assert batch_misses[-1] < 25_000
    before_writer = counts.copy()
    # A newly published last-member structure forces one cold preparation.
    # Pause it while a real configuration writer acquires the mutation lock.
    last_group, last_instance = groups[-1], tool_instances - 1
    definition = registry.get_definition(f"mcp.scale-{last_instance:04}.query-{tools_each - 1:02}")
    registry.update_definition(definition.model_copy(update={"description": "Synthetic changed publication"}))
    writer_entries = registry.mcp_snapshot(
        [f"scale-{index:04}" for index in range(tool_instances - 1000, tool_instances)], max_tools=50_000).tools
    with gate["catalog"].structures._lock:
        writer_initial_misses = sum((entry.revision, entry.structure) not in gate["catalog"].structures._entries
                                    for entry in writer_entries)
    reached, release = threading.Event(), threading.Event()
    original_prepare = structures.prepare_tool_structure
    def paused(entry):
        reached.set()
        assert release.wait(10)
        return original_prepare(entry)
    def writer():
        started = time.perf_counter()
        with configs.mutation_lock:
            wait = time.perf_counter() - started
            configs.save_config({"id": f"scale-{last_instance:04}", "name": "Edited synthetic scale member",
                "launch": {"type": "external"}, "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}},
                overwrite=True)
        return wait
    with patch.object(structures, "prepare_tool_structure", side_effect=paused), ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(client.get, catalog_path(last_group), headers=headers)
        try:
            assert reached.wait(5)
            lock_wait = pool.submit(writer).result(timeout=5)
        finally:
            release.set()
        after = reader.result(timeout=20)
    assert after.status_code == 200 and after.json()["visible_tool_count"] == 1000 * tools_each - 1
    assert counts["fingerprints"] == before_writer["fingerprints"] + writer_initial_misses
    assert counts["normalizations"] == before_writer["normalizations"] + writer_initial_misses
    assert counts["canonical_serializations"] == before_writer["canonical_serializations"] + 3 * writer_initial_misses
    if not over_cache:
        assert counts["fingerprints"] == before_writer["fingerprints"] + 1
        assert counts["normalizations"] == before_writer["normalizations"] + 1
    assert not invoked
    entries, charged_bytes = gate["catalog"].structures.usage()
    assert entries <= structures.MAX_STRUCTURE_CACHE_ENTRIES and charged_bytes <= structures.MAX_STRUCTURE_CACHE_BYTES
    try:
        import resource
    except ImportError:
        peak_rss_kib = None
    else:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_rss_kib = round(rss / 1024) if sys.platform == "darwin" else rss
    metrics = {"instances": 5000, "registry_tools": 50_000, "groups": len(groups),
        "over_cache_bytes": over_cache, "retained_after_cold": cached_count,
        "estimated_full_working_set_charged_bytes": 50_000 * sample.cache_bytes if over_cache else charged_bytes,
        "members_per_group": 1000, "tools_per_request": 1000 * tools_each,
        "cold_samples": len(cold), "cold_p95_ms": p95(cold), "hot_samples": len(hot), "hot_p95_ms": p95(hot),
        "catalog_page_samples": len(catalog_pages), "catalog_page_p95_ms": p95(catalog_pages),
        "member_page_samples": len(member_pages), "member_page_p95_ms": p95(member_pages),
        "cold_structure_counts": cold_counts, "warm_and_paged_additional_structure_counts": warm_counts,
        "warm_initial_miss_min": min(batch_misses[5:35]), "warm_initial_miss_max": max(batch_misses[5:35]),
        "alternating_group_initial_misses": alternating_misses,
        "writer_initial_misses": writer_initial_misses,
        "writer_additional_preparations": counts["fingerprints"] - before_writer["fingerprints"],
        "config_writer_lock_wait_ms": round(lock_wait * 1000, 3), "cache_entries": entries,
        "cache_charged_bytes": charged_bytes, "process_peak_rss_kib": peak_rss_kib}
    record_property("directory_scale_measurements", json.dumps(metrics))
    print("GROUP_DIRECTORY_MEASUREMENTS " + json.dumps(metrics))

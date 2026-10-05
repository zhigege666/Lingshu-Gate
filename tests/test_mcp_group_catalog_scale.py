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


@pytest.mark.parametrize("tool_instances,tools_each", [(5000, 10), (1000, 50)],
                         ids=["five_groups", "maximum_single_group"])
def test_full_directory_5000_instances_50000_tools(gate, monkeypatch, record_property, tool_instances, tools_each):
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
                source="mcp", input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
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
    assert gate["catalog"].structures.usage()[0] == 50_000
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
    assert counts == cold_counts, "Hot/search/page requests must perform zero structural fingerprinting or canonical serialization"
    # A newly published last-member structure forces one cold preparation.
    # Pause it while a real configuration writer acquires the mutation lock.
    last_group, last_instance = groups[-1], tool_instances - 1
    definition = registry.get_definition(f"mcp.scale-{last_instance:04}.query-{tools_each - 1:02}")
    registry.update_definition(definition.model_copy(update={"description": "Synthetic changed publication"}))
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
    assert counts["fingerprints"] == cold_counts["fingerprints"] + 1
    assert counts["normalizations"] == cold_counts["normalizations"] + 1
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
        "members_per_group": 1000, "tools_per_request": 1000 * tools_each,
        "cold_samples": len(cold), "cold_p95_ms": p95(cold), "hot_samples": len(hot), "hot_p95_ms": p95(hot),
        "catalog_page_samples": len(catalog_pages), "catalog_page_p95_ms": p95(catalog_pages),
        "member_page_samples": len(member_pages), "member_page_p95_ms": p95(member_pages),
        "cold_structure_counts": cold_counts, "warm_and_paged_additional_structure_counts": {
            name: value - cold_counts[name] - (3 if name == "canonical_serializations" else 1) for name, value in counts.items()},
        "config_writer_lock_wait_ms": round(lock_wait * 1000, 3), "cache_entries": entries,
        "cache_charged_bytes": charged_bytes, "process_peak_rss_kib": peak_rss_kib}
    record_property("directory_scale_measurements", json.dumps(metrics))
    print("GROUP_DIRECTORY_MEASUREMENTS " + json.dumps(metrics))

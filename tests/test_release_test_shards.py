"""The release matrix divides work; it must never weaken or skip the suite."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.quality.pytest_shard import CollectionShard, partition

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("count", [1, 2, 4, 9])
def test_partitions_cover_every_node_exactly_once(count):
    ids = [f"tests/test_sample.py::test_case[{i}]" for i in range(197)]
    groups = [partition(ids, index, count) for index in range(count)]
    flattened = [item for selected, _ in groups for item in selected]
    assert set(flattened) == set(ids)
    assert len(flattened) == len(ids)
    assert len({digest for _, digest in groups}) == 1
    assert max(len(selected) for selected, _ in groups) - min(len(selected) for selected, _ in groups) <= 1
    assert [partition(list(reversed(ids)), index, count) for index in range(count)] == groups


@pytest.mark.parametrize("index,count", [(-1, 4), (4, 4), (0, 0), (0, -1), (True, 4), (0, True)])
def test_invalid_partition_fails_closed(index, count):
    with pytest.raises(ValueError):
        partition(["test_example"], index, count)


def test_duplicate_ids_are_rejected_and_digest_binds_full_collection():
    with pytest.raises(ValueError):
        partition(["same", "same"], 0, 1)
    assert partition(["one"], 0, 1)[1] != partition(["one", "two"], 0, 1)[1]


def test_hook_preserves_order_notifies_deselection_and_records_manifest(tmp_path):
    notices = []
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda **kw: notices.extend(kw["items"])),
                             pluginmanager=SimpleNamespace(getplugin=lambda name: None))
    items = [SimpleNamespace(nodeid=name) for name in ["c", "a", "b", "d"]]
    path = tmp_path / "manifest.json"
    CollectionShard(0, 2, path).pytest_collection_modifyitems(config, items)
    assert [item.nodeid for item in items] == ["c", "a"]
    assert [item.nodeid for item in notices] == ["b", "d"]
    assert json.loads(path.read_text())["selected_nodeids"] == ["a", "c"]


def test_real_pytest_propagates_failure_and_empty_partition(tmp_path):
    (tmp_path / "test_probe.py").write_text("def test_a(): assert True\ndef test_b(): assert False\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for index, count, expected in [(0, 2, 0), (1, 2, 1), (3, 4, 5)]:
        run = subprocess.run([sys.executable, "-m", "scripts.quality.pytest_shard", "--index", str(index),
                              "--count", str(count), "--", "-q", "test_probe.py"],
                             cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert run.returncode == expected, run.stdout + run.stderr


def test_formal_quality_matrix_runs_all_four_and_packaging_waits_for_all():
    workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    quality = workflow["jobs"]["quality"]
    assert quality["strategy"]["fail-fast"] == "false"
    assert quality["strategy"]["matrix"]["shard"] == ["0", "1", "2", "3"]
    step = next(step for step in quality["steps"] if step.get("name") == "Verify backend and release engineering")
    assert "scripts.quality.pytest_shard" in step["run"]
    assert '--index "${{ matrix.shard }}" --count 4' in step["run"]
    assert "--ignore" not in step["run"] and " -k " not in step["run"]
    for job in ["native", "docker-compose", "docker-publish"]:
        assert "quality" in workflow["jobs"][job]["needs"]

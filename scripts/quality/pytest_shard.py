"""Run a deterministic, complete partition of collected tests without new dependencies.

Every formal matrix member collects the same suite. Sorted node IDs are assigned
round-robin so parametrized scale cases do not all occupy the same worker. All
matrix members must pass before packaging. Ordinary pytest runs are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


def partition(nodeids: list[str], index: int, count: int) -> tuple[list[str], str]:
    if isinstance(index, bool) or isinstance(count, bool) or count < 1 or not 0 <= index < count:
        raise ValueError("Require 0 <= shard index < shard count and shard count >= 1")
    ordered = sorted(nodeids)
    if len(set(ordered)) != len(ordered):
        raise ValueError("Collected test IDs are not unique")
    digest = hashlib.sha256(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return ordered[index::count], digest


class CollectionShard:
    def __init__(self, index: int, count: int, manifest: Path | None = None) -> None:
        partition([], index, count)
        self.index, self.count, self.manifest = index, count, manifest
        self.summary: dict[str, Any] = {}

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config: Any, items: list[Any]) -> None:
        nodeids = [item.nodeid for item in items]
        try:
            selected, digest = partition(nodeids, self.index, self.count)
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        wanted = set(selected)
        remaining = [item for item in items if item.nodeid in wanted]
        deselected = [item for item in items if item.nodeid not in wanted]
        self.summary = {"shard_index": self.index, "shard_count": self.count,
                        "collected_count": len(nodeids), "collection_sha256": digest,
                        "selected_count": len(remaining), "selected_nodeids": selected}
        if self.manifest:
            self.manifest.parent.mkdir(parents=True, exist_ok=True)
            self.manifest.write_text(json.dumps(self.summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        items[:] = remaining
        if deselected:
            config.hook.pytest_deselected(items=deselected)
        reporter = config.pluginmanager.getplugin("terminalreporter")
        if reporter:
            reporter.write_line(f"release shard {self.index + 1}/{self.count}: "
                                f"{len(remaining)}/{len(nodeids)} tests, collection SHA-256 {digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        plugin = CollectionShard(args.index, args.count, args.manifest)
    except ValueError as exc:
        parser.error(str(exc))
    arguments = args.pytest_args
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    # Exit status 5 (empty partition), collection errors, and test failures remain
    # failures. Never turn a partial or interrupted run into a successful shard.
    return int(pytest.main(arguments, plugins=[plugin]))


if __name__ == "__main__":
    sys.exit(main())

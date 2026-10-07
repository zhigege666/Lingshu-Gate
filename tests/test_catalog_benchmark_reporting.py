"""The synthetic catalog benchmark reports only public outcome statistics."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_tool_catalog.py"
_SPEC = importlib.util.spec_from_file_location("catalog_benchmark", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
benchmark = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(benchmark)


def test_catalog_limit_report_has_only_allowlisted_public_fields(monkeypatch):
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: 12.3456789)
    report = json.loads(json.dumps(benchmark.catalog_limit_statistics(11.0)))

    assert set(report) == {"code", "elapsed_ms"}
    assert report["code"] == "tool_catalog_limit"
    assert isinstance(report["elapsed_ms"], float)
    assert report["elapsed_ms"] == 1345.679

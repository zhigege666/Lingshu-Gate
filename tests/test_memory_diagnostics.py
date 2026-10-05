"""Process diagnostics collect metrics, never credential-bearing host argv."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate import memory_diagnostics
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api.diagnostics_routes import register_diagnostics_routes
from lingshu_gate.logging import JsonFormatter
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.system_debug import SystemDebugService


@pytest.fixture
def synthetic_proc(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "status").write_text("Name:\tsynthetic-gate\nVmRSS:\t1024 kB\nVmSize:\t2048 kB\nThreads:\t2\n")
    (proc / "meminfo").write_text("MemTotal:\t8192 kB\nMemAvailable:\t4096 kB\n")
    sentinels = [f"synthetic-never-emit-process-value-{index}" for index in range(4)]
    argv = [
        ["synthetic-worker", "--unrecognized-option", sentinels[0]],
        ["synthetic-worker", "--auto-discovery", sentinels[1]],
        ["synthetic-worker", f"--unrecognized-option={sentinels[2]}"],
        ["synthetic-worker", f"--auto-discovery={sentinels[3]}"],
    ]
    for index, arguments in enumerate(argv):
        pid = 100 + index
        folder = proc / str(pid)
        folder.mkdir()
        (folder / "status").write_text(f"Name:\tsynthetic-worker\nPid:\t{pid}\nPPid:\t1\nVmRSS:\t{index + 1} kB\nVmSize:\t8 kB\nThreads:\t3\n")
        (folder / "cmdline").write_bytes(b"\x00".join(value.encode() for value in arguments))
        (folder / "environ").write_bytes(b"SYNTHETIC_ENV_VALUE=never-read")
    monkeypatch.setattr(memory_diagnostics, "PROC_ROOT", proc)
    monkeypatch.setattr(memory_diagnostics, "_cgroup_memory", lambda: {"current_bytes": 1024, "limit_bytes": 8192, "peak_bytes": 2048})
    monkeypatch.setattr(memory_diagnostics.platform, "platform", lambda: "synthetic-linux")
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path.name in {"cmdline", "environ"}:
            raise AssertionError("Reading host command lines or environments is forbidden")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    return proc, sentinels


def assert_no_arguments(value, sentinels):
    serialized = json.dumps(value, ensure_ascii=False)
    assert all(sentinel not in serialized for sentinel in sentinels)
    assert "--auto-discovery" not in serialized
    assert "--unrecognized-option" not in serialized
    assert all(item["args"] == "omitted" for item in value["top_processes"])


def test_snapshot_omits_unknown_equal_and_separated_arguments_without_reading(synthetic_proc):
    _, sentinels = synthetic_proc
    snapshot = memory_diagnostics.collect_memory_snapshot()
    assert_no_arguments(snapshot, sentinels)
    assert [item["pid"] for item in snapshot["top_processes"]] == [103, 102, 101, 100]
    assert snapshot["top_processes"][0] == {"pid": 103, "ppid": 1, "rss_bytes": 4096,
        "vsz_bytes": 8192, "threads": 3, "command": "synthetic-worker", "args": "omitted", "source": "procfs"}
    assert snapshot["process"]["rss_bytes"] == 1024 * 1024
    assert snapshot["host"]["total_bytes"] == 8192 * 1024
    assert len(memory_diagnostics.collect_memory_snapshot(top_processes_limit=2)["top_processes"]) == 2
    assert memory_diagnostics.collect_memory_snapshot(top_processes_limit=0)["top_processes"] == []


def test_startup_shutdown_memory_logs_never_contain_host_arguments(synthetic_proc, caplog):
    _, sentinels = synthetic_proc
    logger = logging.getLogger("gate.synthetic.memory")
    events = ["gate.diagnostics.memory_snapshot_startup_before_mcp", "gate.diagnostics.memory_snapshot_startup_complete",
        "gate.diagnostics.memory_snapshot_shutdown_before_mcp_stop", "gate.diagnostics.memory_snapshot_shutdown_complete"]
    with caplog.at_level(logging.INFO, logger=logger.name):
        for event in events:
            memory_diagnostics.log_memory_snapshot(logger, event, "Synthetic memory metrics")
    records = [record for record in caplog.records if record.name == logger.name]
    assert len(records) == len(events)
    for record in records:
        output = json.loads(JsonFormatter().format(record))
        assert_no_arguments(output["memory"], sentinels)


def test_memory_api_persistence_and_debug_log_reader_only_receive_safe_metrics(synthetic_proc, tmp_path, caplog):
    _, sentinels = synthetic_proc
    settings = Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    store = ObservabilityStore(SQLiteDatabase("", settings.data_dir))
    registry = ToolRegistry()
    runtime = Mock(spec=McpRuntimeManager)
    app = FastAPI()
    register_diagnostics_routes(app, settings=settings, registry=registry, mcp_runtime=runtime,
        observability_store=store, require_operations_manager=lambda: None)
    with caplog.at_level(logging.INFO, logger="lingshu_gate.interfaces.control_api.diagnostics_routes"), TestClient(app) as client:
        response = client.get("/v1/diagnostics/memory")
    assert response.status_code == 200
    snapshot = response.json()
    assert_no_arguments(snapshot, sentinels)
    record = next(record for record in caplog.records if getattr(record, "gate_event", "") == "gate.diagnostics.memory_snapshot_requested")
    assert_no_arguments(json.loads(JsonFormatter().format(record))["memory"], sentinels)
    store.add_log("info", "Synthetic memory snapshot", source="diagnostics",
        event_type="gate.diagnostics.memory_snapshot", payload={"memory": snapshot})
    stored = store.list_logs(source="diagnostics")[0]["payload"]["memory"]
    assert_no_arguments(stored, sentinels)
    debug = SystemDebugService(settings, registry, runtime, store).invoke({"action": "logs", "source": "diagnostics"})
    assert_no_arguments(debug["logs"][0]["payload"]["memory"], sentinels)


def test_missing_process_name_never_falls_back_to_command_line(synthetic_proc):
    proc, sentinels = synthetic_proc
    (proc / "103" / "status").write_text("Pid:\t103\nPPid:\t1\nVmRSS:\t10 kB\nVmSize:\t16 kB\nThreads:\t1\n")
    snapshot = memory_diagnostics.collect_memory_snapshot(top_processes_limit=1)
    assert_no_arguments(snapshot, sentinels)
    assert snapshot["top_processes"][0]["command"] == ""

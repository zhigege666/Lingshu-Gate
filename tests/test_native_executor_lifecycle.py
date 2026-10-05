"""Container/cgroup state transitions with durable real journals, fake engine."""
from __future__ import annotations

import json
import os
import stat
from unittest.mock import patch

import pytest

from lingshu_gate.adapters.native_executor.controller import PodmanController, read_regular_result
from lingshu_gate.adapters.native_executor.journal import JobJournal
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.ports.safe_network_executor import ExecutorReadiness, PHASE_CHECKS, ROOTLESS_CHECKS, SafeExecutionCancelled
from lingshu_gate.registry import ToolExecutionError


@pytest.fixture
def engine(tmp_path):
    root = tmp_path / "executor"
    root.mkdir(mode=0o700)
    (root / "workspaces").mkdir(mode=0o700)
    controller = PodmanController(NativeExecutorConfig(enabled=True, root=root, image="registry.example.invalid/executor@sha256:" + "a" * 64))
    controller.journal = JobJournal(root)
    controller.missing = []
    controller.evidence = ExecutorReadiness("linux_rootless_oci", "linux", ROOTLESS_CHECKS | PHASE_CHECKS["git_acquisition"] | PHASE_CHECKS["offline_build"])
    calls = []
    state = {"running": False, "exists": False, "empty": True, "output": True, "exit_code": None}
    def cli(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "create":
            state.update({"exists": True, "name": next(item.split("=", 1)[1] for item in argv if item.startswith("--name="))})
            if state["output"]:
                (controller.workspaces / state["name"] / "output" / "result.json").write_text('{"returncode":0,"node_version":"22.13.0","package_manager_version":"11.6.0"}')
            return ("b" * 64).encode()
        if argv[0] == "start":
            state["running"] = True
            return b""
        if argv[:2] == ["container", "inspect"]:
            if state.get("name") and state["exit_code"] is not None and (controller.workspaces / state["name"] / "control" / "admitted").is_file():
                state["running"] = False
            return json.dumps([{"Id": "b" * 64, "State": {"Running": state["running"], "Pid": 123 if state["running"] else 0, "ExitCode": state["exit_code"]}}]).encode() if state["exists"] else b""
        if argv[0] == "kill":
            state["running"] = False
            return b""
        if argv[0] == "rm":
            state["exists"] = False
            return b""
        if argv[0] == "ps":
            return b"[]"
        return b"{}"
    with patch.object(controller, "_cli", side_effect=cli), patch.object(controller, "_cgroup", return_value="/fixture/sandbox"), patch.object(controller, "_empty", side_effect=lambda path: state["empty"]):
        yield controller, calls, state
    controller.journal.close()


def test_output_is_frozen_only_after_whole_group_stop_and_key_is_not_replayed(engine):
    controller, calls, state = engine
    freeze = controller._freeze
    def stopped(path):
        assert not state["running"] and not state["exists"] and state["empty"]
        freeze(path)
    with patch.object(controller, "_freeze", side_effect=stopped):
        result = controller.run("fixture:prepare", {"kind": "tool_probe", "manager": "npm"}, timeout=10, cancelled=lambda: False)
    assert result["returncode"] == 0
    assert controller.journal.lookup("fixture:prepare")["state"] == "completed"
    assert any(argv[0] == "kill" for argv in calls)
    with pytest.raises(InterruptedError):
        controller.run("fixture:prepare", {"kind": "tool_probe", "manager": "npm"}, timeout=10, cancelled=lambda: False)
    assert sum(argv[0] == "create" for argv in calls) == 1
    controller.release_output(result)


def test_cancellation_is_confirmed_only_after_cgroup_empty(engine):
    controller, calls, state = engine
    with pytest.raises(SafeExecutionCancelled):
        controller.run("fixture:cancel", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: True)
    assert controller.journal.lookup("fixture:cancel")["state"] == "cancelled"
    assert not state["running"]
    assert any(argv[0] == "kill" for argv in calls)


def test_timeout_terminates_sandbox_before_reporting_failure(engine):
    controller, calls, state = engine
    state["output"] = False
    clock = iter(range(100))
    with patch("lingshu_gate.adapters.native_executor.controller.time.monotonic", side_effect=lambda: next(clock)), patch("lingshu_gate.adapters.native_executor.controller.time.sleep"), pytest.raises(TimeoutError):
        controller.run("fixture:timeout", {"kind": "tool_probe"}, timeout=1, cancelled=lambda: False)
    assert controller.journal.lookup("fixture:timeout")["state"] == "failed"
    assert not state["running"]


def test_uncertain_termination_is_unknown_and_blocks_readiness(engine):
    controller, calls, state = engine
    state["empty"] = False
    clock = iter(range(100))
    with patch("lingshu_gate.adapters.native_executor.controller.time.monotonic", side_effect=lambda: next(clock)), patch("lingshu_gate.adapters.native_executor.controller.time.sleep"), pytest.raises(InterruptedError):
        controller.run("fixture:unknown", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: True)
    assert controller.journal.lookup("fixture:unknown")["state"] == "unknown"
    assert not controller.readiness()["available"]
    assert not any(argv[0] == "rm" for argv in calls)


def test_restart_reconciliation_stops_orphan_without_dispatch(engine):
    controller, calls, state = engine
    job = controller.journal.reserve("fixture:orphan", {"source": "a"}, "command")
    controller.journal.update(job["key"], "running", container_id="b" * 64, cgroup="/fixture/sandbox")
    state.update({"running": True, "exists": True})
    controller.reconcile()
    assert controller.journal.lookup(job["key"])["state"] == "interrupted_terminated"
    assert not state["running"]
    assert not any(argv[0] in {"create", "start"} for argv in calls)
    with pytest.raises(InterruptedError):
        controller.journal.reserve(job["key"], {"source": "a"}, "command")


@pytest.mark.parametrize("exit_code,state_name", [(0, "completed"), (23, "failed")])
def test_shared_result_cannot_forge_command_success_before_observed_exit(engine, exit_code, state_name):
    controller, calls, state = engine
    state["exit_code"] = exit_code
    # The fake engine publishes a forged returncode=0 before container start.
    # Admission must still capture the cgroup, then await the engine exit.
    result = controller.run("fixture:command", {"kind": "command", "manager": "npm", "command": ["npm", "run", "build"]}, timeout=10, cancelled=lambda: False)
    assert result["returncode"] == exit_code
    row = controller.journal.lookup("fixture:command")
    assert row["state"] == state_name and row["cgroup"] == "/fixture/sandbox"
    assert not any(argv[0] == "kill" for argv in calls)
    assert not state["running"] and not state["exists"]
    controller.release_output(result)


@pytest.mark.parametrize("kind", ["fifo", "directory", "symlink", "oversized"])
def test_invalid_result_is_terminal_and_releases_admission_for_next_job(engine, kind):
    controller, calls, state = engine
    freeze = controller._freeze
    def malformed(root):
        path = root / "result.json"
        path.unlink()
        if kind == "fifo":
            os.mkfifo(path)
        elif kind == "directory":
            path.mkdir()
        elif kind == "symlink":
            path.symlink_to("/dev/null")
        else:
            path.write_bytes(b" " * 8193)
        freeze(root)
    with patch.object(controller, "_freeze", side_effect=malformed), pytest.raises(ToolExecutionError) as rejected:
        controller.run("fixture:bad-result", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: False)
    assert rejected.value.code == "executor_result_rejected"
    assert controller.journal.lookup("fixture:bad-result")["state"] == "failed"
    assert not list(controller.workspaces.iterdir())
    result = controller.run("fixture:next-result", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: False)
    assert result["returncode"] == 0
    controller.release_output(result)


def test_result_device_type_is_checked_on_open_descriptor(tmp_path):
    result = tmp_path / "result.json"
    result.write_text('{"returncode":0}')
    info = result.stat()
    fields = list(info)
    fields[0] = stat.S_IFCHR | 0o600
    with patch("lingshu_gate.adapters.native_executor.controller.os.fstat", return_value=os.stat_result(fields)), pytest.raises(ToolExecutionError) as rejected:
        read_regular_result(result)
    assert rejected.value.code == "executor_result_rejected"


def test_result_symlink_swap_after_open_is_rejected_without_reading_target(tmp_path):
    result, outside = tmp_path / "result.json", tmp_path / "outside.json"
    result.write_text('{"returncode":0}')
    outside.write_text('{"private":"fixture-secret"}')
    open_file = os.open
    def swapped(path, flags):
        descriptor = open_file(path, flags)
        result.unlink()
        result.symlink_to(outside)
        return descriptor
    with patch("lingshu_gate.adapters.native_executor.controller.os.open", side_effect=swapped), pytest.raises(ToolExecutionError) as rejected:
        read_regular_result(result)
    assert rejected.value.code == "executor_result_rejected"
    assert outside.read_text() == '{"private":"fixture-secret"}'


def test_inventory_regular_file_swapped_for_fifo_before_open_never_blocks(tmp_path):
    result = tmp_path / "file"
    result.write_text("fixture")
    open_file = os.open
    def swapped(path, flags):
        result.unlink()
        os.mkfifo(result)
        assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW
        return open_file(path, flags)
    with patch("lingshu_gate.safe_files.os.open", side_effect=swapped), pytest.raises(ValueError, match="safe_regular_file_rejected"):
        PodmanController._inventory(tmp_path)

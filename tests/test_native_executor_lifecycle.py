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
    state = {"running": False, "exists": False, "empty": True, "output": True, "exit_code": 0}
    def cli(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "create":
            state.update({"exists": True, "name": next(item.split("=", 1)[1] for item in argv if item.startswith("--name="))})
            state["mounts"] = []
            for index, argument in enumerate(argv):
                if argument == "--mount":
                    fields = dict(field.split("=", 1) for field in argv[index + 1].split(","))
                    state["mounts"].append({"Type": fields["type"], "Source": fields["src"], "Destination": fields["dst"], "RW": fields.get("ro") != "true"})
            state["mounts"] += state.get("extra_mounts", [])
            if state.get("payload_bytes"):
                (controller.workspaces / state["name"] / "output" / "work.bin").write_bytes(b"x" * state["payload_bytes"])
            if state["output"]:
                (controller.workspaces / state["name"] / "output" / "result.json").write_text('{"returncode":0,"node_version":"22.13.0","package_manager_version":"11.6.0"}')
            return ("b" * 64).encode()
        if argv[0] == "start":
            state["running"] = True
            return b""
        if argv[:2] == ["container", "inspect"]:
            if state.get("name") and state["output"] and state["exit_code"] is not None and (controller.workspaces / state["name"] / "control" / "admitted").is_file():
                state["running"] = False
            job = controller.journal.lookup_name(argv[2])
            return json.dumps([{"Id": state.get("replacement_id", "b" * 64), "Config": {"Labels": {"io.lingshu-gate.job": state.get("replacement_digest", job["digest"])}}, "Mounts": state.get("mounts", []), "State": {"Running": state["running"], "Pid": 123 if state["running"] else 0, "Status": "running" if state["running"] else "exited" if any(call[0] == "start" for call in calls) else "configured", "ExitCode": state["exit_code"]}}]).encode() if state["exists"] else b""
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
    assert any(argv[0] == "rm" for argv in calls)
    assert not any(argv[0] == "kill" for argv in calls)
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
    assert not list(controller.workspaces.iterdir())
    assert controller.journal.lookup("fixture:cancel")["cleanup_state"] == "cleaned"


def test_timeout_terminates_sandbox_before_reporting_failure(engine):
    controller, calls, state = engine
    state["output"] = False
    clock = iter(range(100))
    with patch("lingshu_gate.adapters.native_executor.controller.time.monotonic", side_effect=lambda: next(clock)), patch("lingshu_gate.adapters.native_executor.controller.time.sleep"), pytest.raises(TimeoutError):
        controller.run("fixture:timeout", {"kind": "tool_probe"}, timeout=1, cancelled=lambda: False)
    assert controller.journal.lookup("fixture:timeout")["state"] == "failed"
    assert not state["running"]
    assert not list(controller.workspaces.iterdir())
    assert controller.journal.lookup("fixture:timeout")["cleanup_state"] == "cleaned"


def test_uncertain_termination_is_unknown_and_blocks_readiness(engine):
    controller, calls, state = engine
    state["empty"] = False
    clock = iter(range(100))
    with patch("lingshu_gate.adapters.native_executor.controller.time.monotonic", side_effect=lambda: next(clock)), patch("lingshu_gate.adapters.native_executor.controller.time.sleep"), pytest.raises(InterruptedError):
        controller.run("fixture:unknown", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: True)
    assert controller.journal.lookup("fixture:unknown")["state"] == "unknown"
    assert not controller.readiness()["available"]
    assert not any(argv[0] == "rm" for argv in calls)
    assert list(controller.workspaces.iterdir())
    assert controller.journal.lookup("fixture:unknown")["cleanup_state"] == "pending"


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
@pytest.mark.parametrize("kind", ["command", "npm_seed", "pnpm_seed", "yarn_seed", "git", "tool_probe"])
def test_shared_result_cannot_forge_phase_success_before_observed_exit(engine, exit_code, state_name, kind):
    controller, calls, state = engine
    state["exit_code"] = exit_code
    # The fake engine publishes a forged returncode=0 before container start.
    # Admission must still capture the cgroup, then await the engine exit.
    result = controller.run("fixture:command", {"kind": kind, "manager": "npm", "command": ["npm", "run", "build"]}, timeout=10, cancelled=lambda: False)
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


@pytest.mark.parametrize("reason", ["cancel", "timeout"])
def test_repeated_terminal_jobs_release_workspace_capacity_and_next_job_runs(engine, reason):
    controller, calls, state = engine
    state["output"] = False
    state["payload_bytes"] = 1024 * 1024
    for index in range(8):
        if reason == "cancel":
            with pytest.raises(SafeExecutionCancelled):
                controller.run(f"fixture:repeat:{index}", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: True)
        else:
            clock = iter(range(100))
            with patch("lingshu_gate.adapters.native_executor.controller.time.monotonic", side_effect=lambda: next(clock)), patch("lingshu_gate.adapters.native_executor.controller.time.sleep"), pytest.raises(TimeoutError):
                controller.run(f"fixture:repeat:{index}", {"kind": "tool_probe"}, timeout=1, cancelled=lambda: False)
        assert not list(controller.workspaces.iterdir())
        assert controller.journal.lookup(f"fixture:repeat:{index}")["cleanup_state"] == "cleaned"
    state["output"] = True
    result = controller.run("fixture:repeat:next", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: False)
    assert result["returncode"] == 0
    controller.release_output(result)


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_restart_reclaims_durable_terminal_workspace_without_dispatch(engine, terminal):
    controller, calls, state = engine
    job = controller.journal.reserve("fixture:leftover", {"phase": "fixture"}, "command")
    controller.journal.update(job["key"], terminal, container_id="b" * 64, cgroup="/fixture/sandbox")
    output = controller.workspaces / job["name"] / "output"
    output.mkdir(parents=True)
    (output / "leftover").write_bytes(b"x" * (1024 * 1024))
    root = controller.root
    controller.journal.close()
    controller.journal = JobJournal(root)
    controller.reconcile()
    assert not list(controller.workspaces.iterdir())
    assert controller.journal.lookup(job["key"])["cleanup_state"] == "cleaned"
    assert not any(argv[0] in {"create", "start"} for argv in calls)


def test_unplanned_engine_mount_is_rejected_and_removed_before_any_start(engine):
    controller, calls, state = engine
    state["extra_mounts"] = [{"Type": "bind", "Source": "/private/fixture", "Destination": "/secret", "RW": False}]
    with pytest.raises(ToolExecutionError) as rejected:
        controller.run("fixture:extra-mount", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: False)
    assert rejected.value.code == "executor_unplanned_mount_rejected"
    assert not any(argv[0] in {"start", "kill"} for argv in calls)
    assert controller.journal.lookup("fixture:extra-mount")["cleanup_state"] == "cleaned"
    assert not list(controller.workspaces.iterdir())


def test_mismatched_container_identity_is_never_killed_or_cleaned(engine):
    controller, calls, state = engine
    state["replacement_id"] = "c" * 64
    with pytest.raises(InterruptedError):
        controller.run("fixture:identity", {"kind": "tool_probe"}, timeout=10, cancelled=lambda: False)
    assert not any(argv[0] in {"start", "kill", "rm"} for argv in calls)
    assert controller.journal.lookup("fixture:identity")["state"] == "unknown"
    assert list(controller.workspaces.iterdir()) and not controller.readiness()["available"]

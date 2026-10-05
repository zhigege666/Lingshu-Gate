"""No real engine, network, credentials or project scripts in these fixtures."""
from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from lingshu_gate.adapters.native_executor.controller import PodmanController
from lingshu_gate.adapters.native_executor.journal import JobJournal
from lingshu_gate.adapters.native_executor.packages import engine_satisfies
from lingshu_gate.adapters.safe_network_factory import create_safe_network_executor, unavailable_readiness
from lingshu_gate.config import Settings
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.registry import ToolExecutionError

IMAGE = "registry.example.invalid/gate-executor@sha256:" + "a" * 64


def config(tmp_path):
    root = tmp_path / "executor"
    root.mkdir(mode=0o700)
    (root / "workspaces").mkdir(mode=0o700)
    return NativeExecutorConfig(enabled=True, root=root, image=IMAGE)


@pytest.mark.parametrize("image", ["node:latest", "node:22", "--privileged", "node@sha256:bad"])
def test_unpinned_administrator_images_are_rejected(tmp_path, image):
    with pytest.raises(ValueError):
        replace(config(tmp_path), image=image)


def test_core_factory_does_not_import_or_probe_engine(tmp_path):
    settings = Settings(runtime_role="core", native_executor=config(tmp_path))
    with patch("lingshu_gate.adapters.native_executor.executor.NativeNetworkExecutor", side_effect=AssertionError("Core must not touch the engine")):
        assert create_safe_network_executor(settings) is None
    assert unavailable_readiness(settings)["missing"] == ["core_gateway_only_native_delivery_disabled"]


def test_disabled_factory_and_other_platform_require_no_engine(tmp_path):
    assert create_safe_network_executor(Settings()) is None
    with patch("lingshu_gate.adapters.safe_network_factory.sys.platform", "darwin"):
        settings = Settings(native_executor=config(tmp_path))
        assert create_safe_network_executor(settings) is None
        assert unavailable_readiness(settings)["missing"] == ["unsupported_platform_linux_required"]


def test_workspace_without_actual_tmpfs_quota_fails_closed(tmp_path):
    controller = PodmanController(config(tmp_path))
    assert not controller._quota()
    with pytest.raises(ToolExecutionError) as blocked:
        controller.require_ready()
    assert "bounded_workspace" in blocked.value.details["missing"]


def test_journal_survives_restart_and_never_replays_a_phase(tmp_path):
    journal = JobJournal(tmp_path)
    first = journal.reserve("build:fixture:install", {"source": "a"}, "install")
    journal.update(first["key"], "running", container_id="b" * 64, cgroup="/fixture")
    journal.close()
    journal = JobJournal(tmp_path)
    assert journal.unfinished()[0]["container_id"] == "b" * 64
    with pytest.raises(InterruptedError):
        journal.reserve(first["key"], {"source": "a"}, "install")
    with pytest.raises(ToolExecutionError) as conflict:
        journal.reserve(first["key"], {"source": "changed"}, "install")
    assert conflict.value.code == "executor_idempotency_conflict"
    journal.close()


def test_journal_enforces_single_owner(tmp_path):
    journal = JobJournal(tmp_path)
    with pytest.raises(ToolExecutionError) as busy:
        JobJournal(tmp_path)
    assert busy.value.code == "executor_owner_busy"
    journal.close()


def test_container_argv_is_fixed_offline_and_only_content_mounted(tmp_path):
    controller = PodmanController(config(tmp_path))
    directory = controller.workspaces / "fixture"
    directory.mkdir()
    (directory / "output").mkdir()
    (directory / "request.json").write_text(json.dumps({"kind": "tool_probe"}))
    observed = []
    def cli(argv, **kwargs):
        observed.extend(argv)
        return ("b" * 64).encode()
    with patch.object(controller, "_cli", side_effect=cli):
        assert controller._create({"name": "gate-job-" + "a" * 32, "digest": "a" * 64}, directory, {}) == "b" * 64
    for required in ["--pull=never", "--network=none", "--cap-drop=ALL", "--read-only", "--http-proxy=false", "--security-opt=no-new-privileges", "--cgroups=enabled", "--pids-limit=128", "--log-driver=none", "--entrypoint=/usr/bin/python3"]:
        assert required in observed
    assert not any("socket" in argument or "--privileged" in argument or "--network=host" in argument for argument in observed)
    assert IMAGE in observed


@pytest.mark.parametrize("node,engines,expected", [("22.13.0", "^20.17.0 || >=22.9.0", True), ("22.8.0", "^20.17.0 || >=22.9.0", False), ("20.17.0", "^20.17.0 || >=22.9.0", True), ("22.13.0", ">=22.13", True), ("22.12.0", ">=22.13", False), ("22.13.0", "unknown", False), ("22.13.0", "*", False)])
def test_exact_official_node_engines_and_unknown_syntax(node, engines, expected):
    assert engine_satisfies(node, engines) is expected


@pytest.mark.parametrize("name,kind", [("../escape", "file"), ("package/link", "link"), ("package/device", "device")])
def test_official_archive_rejects_traversal_links_and_special_types(tmp_path, name, kind):
    import io
    import tarfile
    from lingshu_gate.adapters.native_executor.packages import extract_official
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        entry = tarfile.TarInfo(name)
        entry.type = tarfile.SYMTYPE if kind == "link" else tarfile.CHRTYPE if kind == "device" else tarfile.REGTYPE
        archive.addfile(entry)
    target = tmp_path / "tool"
    target.mkdir()
    with pytest.raises(ToolExecutionError):
        extract_official(stream.getvalue(), target, {"files": 4, "expanded_bytes": 1024})
    assert not (tmp_path / "escape").exists()


def test_official_archive_pax_metadata_cannot_bypass_expanded_budget(tmp_path):
    import io
    import tarfile
    from lingshu_gate.adapters.native_executor.packages import extract_official
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        entry = tarfile.TarInfo("package/file")
        entry.pax_headers = {"comment": "a" * (2 * 1024 * 1024)}
        archive.addfile(entry)
    target = tmp_path / "tool"
    target.mkdir()
    with pytest.raises(ToolExecutionError) as limited:
        extract_official(stream.getvalue(), target, {"files": 4, "expanded_bytes": 1024})
    assert limited.value.code == "package_manager_archive_limit"

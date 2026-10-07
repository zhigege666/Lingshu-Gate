"""Configured installs never run on the host or replace the previous deployment."""

from __future__ import annotations

import json
import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lingshu_gate.build_deploy import BuildDeployStore, LocalExecutionBlocked, _build_subprocess_environment, _init_step_states
from lingshu_gate.build_plan import build_plan
from lingshu_gate.node_toolchain import tool_preparation
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.network_settings import NetworkSelection, NetworkSettingsStore, ProfileWrite
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.ports.safe_network_executor import REQUIRED_CAPABILITIES
from lingshu_gate.project_uploads import ProjectUploadStore
from lingshu_gate.registry import ToolExecutionError


@pytest.fixture
def store(tmp_path):
    database = SQLiteDatabase("", tmp_path)
    audit = ObservabilityStore(database)
    network = NetworkSettingsStore(database, tmp_path, CredentialStore(tmp_path), audit)
    builder = BuildDeployStore(database, tmp_path, ProjectUploadStore(database, tmp_path), None, None, audit, network_settings=network)
    yield builder
    builder.executor.shutdown(wait=False, cancel_futures=True)


def fixture_plan(store):
    proxy = store.network_settings.save_profile(ProfileWrite(name="Example", endpoint="http://proxy.example.invalid:8080"), "admin")
    frozen = store.network_settings.freeze(NetworkSelection(mode="direct"), NetworkSelection(mode="profile", profile_id=proxy["id"], version=1))
    plan = build_plan({"runtime": "node", "metadata": {"node_install_required": True, "package_scripts": [], "node_package_manager": {"name": "npm", "version": "11.6.0", "supported": True, "errors": [], "lockfile": "package-lock.json"}}})
    plan["delivery_network"] = frozen
    source = store.root / "example" / "source"
    source.mkdir(parents=True)
    (source / "index.js").write_text("export {};")
    artifact = source.parent / "artifact"
    artifact.mkdir()
    steps = _init_step_states(plan)
    store._insert_build_record("example", "upload", "node", source, artifact, status="running", plan=plan, steps=steps)
    return plan, source, artifact, steps


def test_network_output_never_enters_persistent_log_or_runtime_environment(store):
    plan, source, artifact, steps = fixture_plan(store)
    observed = []
    def run_command(command, **kwargs):
        observed.append(kwargs)
        return {"returncode": 0, "duration_ms": 1, "started_at": "now", "finished_at": "now", "package_manager_version": "11.6.0", "stdout": "http://proxy.example.invalid:8080 secret-value", "stderr": "secret-value"}
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES, proxy_schemes={"npm": frozenset({"http"})}, run_command=run_command)
    with patch("lingshu_gate.build_deploy._run_command") as host:
        store._run_single_step("example", plan["steps"][0], 0, steps, source, 30, _build_subprocess_environment(source.parent))
    host.assert_not_called()
    logs = json.dumps(store.list_build_logs("example"))
    assert "proxy.example.invalid" not in logs and "secret-value" not in logs
    assert observed[0]["network"]["install"]["version"] == 1
    assert not any("PROXY" in name.upper() for name in observed[0]["environment"])
    assert steps[0]["package_manager"] == {"name": "npm", "version": "11.6.0"}
    assert not list(artifact.iterdir())


def test_actual_build_deletion_releases_its_profile_reference_atomically(store):
    plan, source, artifact, states = fixture_plan(store)
    frozen = plan["delivery_network"]
    profile_id = frozen["install"]["profile_id"]
    store.network_settings.retain(frozen, "build", "example")
    store.database.execute("UPDATE builds SET status='success' WHERE id='example'")
    with pytest.raises(ToolExecutionError):
        store.network_settings.delete_profile(profile_id, 1, "admin")
    with patch.object(store, "_build_reference_server_ids", return_value=[]):
        store.delete_build("example")
    assert store.database.query_one("SELECT 1 FROM builds WHERE id='example'") is None
    assert store.database.query_one("SELECT 1 FROM network_profile_references WHERE resource_type='build' AND resource_id='example'") is None
    assert store.network_settings.delete_profile(profile_id, 1, "admin")["deleted"]


def test_missing_executor_and_network_authorization_block_before_host_execution(store):
    plan, source, artifact, steps = fixture_plan(store)
    upload = {"id": "upload", "root_dir": str(source), "status": "analyzed"}
    preflight = {"status": "ok", "runtime": "node", "project_root_dir": str(source), "checks": []}
    with patch.object(store.uploads, "get_upload", return_value=upload), patch("lingshu_gate.build_deploy._run_command") as host:
        with pytest.raises(ToolExecutionError) as denied:
            store.build_upload("upload", prepared_preflight=preflight, prepared_plan=plan)
        assert denied.value.code == "network_permission_denied"
        with pytest.raises(ToolExecutionError) as missing:
            store.build_upload("upload", prepared_preflight=preflight, prepared_plan=plan, network_authorized=True)
        assert missing.value.code == "safe_executor_unavailable"
    host.assert_not_called()


def test_core_cannot_enable_build_by_injecting_an_executor(store):
    store.runtime_role = "core"
    store.local_execution_enabled = False
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES)
    with pytest.raises(LocalExecutionBlocked):
        store.build_upload("missing-upload", network_authorized=True)


def test_executor_version_drift_does_not_execute_or_publish_artifact(store):
    plan, source, artifact, steps = fixture_plan(store)
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES, proxy_schemes={"npm": frozenset({"http"})}, run_command=lambda *args, **kwargs: {"returncode": 0, "package_manager_version": "12.0.0"})
    with pytest.raises(RuntimeError, match="package_manager_version_changed"), patch("lingshu_gate.build_deploy._run_command") as host:
        store._run_single_step("example", plan["steps"][0], 0, steps, source, 30, _build_subprocess_environment(source.parent))
    host.assert_not_called()
    assert not list(artifact.iterdir())


def test_failed_build_retains_old_deployment_and_artifact(store, tmp_path):
    plan, source, artifact, steps = fixture_plan(store)
    old = tmp_path / "old-artifact"
    old.mkdir()
    (old / "index.js").write_text("old-version")
    store.database.execute("INSERT INTO deployments(id,build_id,server_id,status,manifest_json,created_at,updated_at) VALUES('old','old-build','server','success','{}','now','now')")
    before = dict(store.database.query_one("SELECT * FROM deployments WHERE id='old'"))
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES, proxy_schemes={"npm": frozenset({"http"})}, run_command=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("secret-value")))
    upload_source = tmp_path / "new-upload"
    upload_source.mkdir()
    (upload_source / "index.js").write_text("new-version")
    store._run_build_job("example", {"id": "upload", "filename": "new.zip"}, "node", upload_source, source, artifact, plan, 5)
    assert store.get_build("example")["status"] == "failed"
    assert dict(store.database.query_one("SELECT * FROM deployments WHERE id='old'")) == before
    assert (old / "index.js").read_text() == "old-version"
    assert not list(artifact.iterdir())
    assert "secret-value" not in json.dumps(store.list_build_logs("example"))


def prepared_fixture(store):
    plan, source, artifact, _ = fixture_plan(store)
    manager = {**plan["package_manager"], "requires_prepare": True, "preparation": tool_preparation("npm", "11.6.0")}
    plan = build_plan({"runtime": "node", "metadata": {"node_install_required": True, "node_package_manager": manager}}) | {"delivery_network": plan["delivery_network"]}
    states = _init_step_states(plan)
    store.database.execute("UPDATE builds SET plan_json=?, steps_json=? WHERE id='example'", (json.dumps(plan), json.dumps(states)))
    return plan, source, artifact, states


def test_official_preparation_uses_selected_network_fixed_version_limits_and_records_source(store):
    plan, source, artifact, states = prepared_fixture(store)
    observed = []
    integrity = "sha512-" + base64.b64encode(b"a" * 64).decode()
    def prepare(specification, **kwargs):
        observed.append((specification, kwargs))
        return {"returncode": 0, "duration_ms": 1, "started_at": "now", "finished_at": "now", "package_manager_version": "11.6.0", "source_integrity": integrity, "stdout": "secret-value", "source": "http://proxy.example.invalid:8080"}
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES, proxy_schemes={"npm": frozenset({"http"})}, prepare_package_manager=prepare)
    with patch("lingshu_gate.build_deploy._run_command") as host:
        store._run_single_step("example", plan["steps"][0], 0, states, source, 600, _build_subprocess_environment(source.parent))
    host.assert_not_called()
    spec, arguments = observed[0]
    assert spec["version"] == "11.6.0" and spec["corepack_required"] is False
    assert arguments["timeout_seconds"] == 120
    assert arguments["network"]["install"]["mode"] == "profile"
    assert arguments["cancel_requested"]() is False
    assert states[0]["package_manager"]["source"]["source_integrity"] == integrity
    assert states[0]["package_manager"]["source"]["official_metadata_url"] == "https://registry.npmjs.org/npm/11.6.0"
    assert "secret-value" not in json.dumps(store.list_build_logs("example"))
    assert "proxy.example.invalid" not in json.dumps(states)
    assert not list(artifact.iterdir())


@pytest.mark.parametrize("bad_result", [
    {"returncode": 0, "package_manager_version": "11.6.0", "source_integrity": "unverified"},
    {"returncode": 0, "package_manager_version": "12.0.0"},
])
def test_unverified_bootstrap_never_falls_back_to_host_or_publishes(store, bad_result):
    plan, source, artifact, states = prepared_fixture(store)
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES, proxy_schemes={"npm": frozenset({"http"})}, prepare_package_manager=lambda *args, **kwargs: bad_result)
    with pytest.raises(RuntimeError, match="package_manager_integrity_unverified|package_manager_version_changed"), patch("lingshu_gate.build_deploy._run_command") as host:
        store._run_single_step("example", plan["steps"][0], 0, states, source, 5, {})
    host.assert_not_called()
    assert not list(artifact.iterdir())


@pytest.mark.parametrize("flag", ["cancelled", "timed_out"])
def test_preparation_timeout_cancel_is_terminal_without_install_or_retry(store, flag):
    plan, source, artifact, states = prepared_fixture(store)
    calls = []
    def prepare(*args, **kwargs):
        calls.append(kwargs)
        return {"returncode": -1, "duration_ms": 1, "started_at": "now", "finished_at": "now", flag: True}
    store.safe_network_executor = SimpleNamespace(capabilities=REQUIRED_CAPABILITIES, proxy_schemes={"npm": frozenset({"http"})}, prepare_package_manager=prepare)
    with patch("lingshu_gate.build_deploy._run_command") as host:
        result = store._run_single_step("example", plan["steps"][0], 0, states, source, 5, {})
    assert result[flag] is True and len(calls) == 1
    assert states[1]["status"] == "pending" and not list(artifact.iterdir())
    host.assert_not_called()

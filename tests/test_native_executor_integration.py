"""Synthetic full coordinator + real acquisition/cache/export adapter logic.

The engine and upstream bytes are fixtures; no real network or scripts run.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lingshu_gate.adapters.native_executor.controller import PodmanController
from lingshu_gate.adapters.native_executor.executor import NativeNetworkExecutor
from lingshu_gate.adapters.native_executor.git import packet
from lingshu_gate.adapters.native_executor.journal import JobJournal
from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.git_import_mcp import GitImportService
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.network_settings import NetworkSettingsStore, ProfileWrite, NetworkSelection
from lingshu_gate.node_toolchain import tool_preparation
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.ports.safe_network_executor import ExecutorReadiness, PHASE_CHECKS, ROOTLESS_CHECKS
from lingshu_gate.project_delivery_mcp import ProjectDeliveryMcpService
from lingshu_gate.project_uploads import ProjectUploadStore
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext

URL = "https://github.com/fixture/project"


def sri(data):
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as zipped:
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            zipped.addfile(item, io.BytesIO(content))
    return stream.getvalue()


class Objects:
    def __init__(self, files):
        self.items = {}
        tree = b""
        for name, content in sorted(files.items()):
            oid = self.add("blob", content)
            tree += b"100644 " + name.encode() + b"\0" + bytes.fromhex(oid)
        tree_id = self.add("tree", tree)
        self.commit = self.add("commit", f"tree {tree_id}\nauthor Fixture <fixture@example.invalid> 0 +0000\ncommitter Fixture <fixture@example.invalid> 0 +0000\n\nfixture\n".encode())

    def add(self, kind, content):
        oid = hashlib.sha1(f"{kind} {len(content)}\0".encode() + content).hexdigest()
        self.items[oid] = (kind, content)
        return oid


class Transport:
    def __init__(self, objects, tool, dependency):
        self.objects, self.tool, self.dependency = objects, tool, dependency
        self.calls = []

    def request(self, url, **kwargs):
        self.calls.append((url, {**kwargs, "material": dict(kwargs["material"])}))
        if url.endswith("/info/refs?service=git-upload-pack"):
            return 200, packet(b"# service=git-upload-pack\n") + b"0000" + packet(f"{self.objects.commit} refs/heads/main\0multi_ack_detailed side-band-64k ofs-delta\n".encode()) + b"0000"
        if url.endswith("/git-upload-pack"):
            assert f"want {self.objects.commit} ".encode() in kwargs["body"]
            assert b"main" not in kwargs["body"]
            return 200, packet(b"NAK\n") + packet(b"\x01PACKfixture") + b"0000"
        if url.endswith("/npm/11.6.0"):
            return 200, json.dumps({"name": "npm", "version": "11.6.0", "engines": {"node": "^20.17.0 || >=22.9.0"}, "dist": {"integrity": sri(self.tool), "tarball": "https://registry.npmjs.org/npm/-/npm-11.6.0.tgz"}}).encode()
        if url.endswith("/npm/-/npm-11.6.0.tgz"):
            return 200, self.tool
        if url.endswith("/dep/-/dep-1.0.0.tgz"):
            return 200, self.dependency
        raise AssertionError("Unplanned fetch: " + url)


class FixtureController(PodmanController):
    def __init__(self, config, objects):
        super().__init__(config)
        self.objects = objects
        self.evidence = ExecutorReadiness("linux_rootless_oci", "linux", ROOTLESS_CHECKS | PHASE_CHECKS["git_acquisition"] | PHASE_CHECKS["offline_build"])
        self.missing = []
        self.node_version = "22.13.0"
        self.journal = JobJournal(self.root)
        self.calls = []
        self.mutate = None
        self.interrupt = False

    def run(self, key, request, *, mounts=None, timeout, cancelled, **kwargs):
        mounts = mounts or {}
        job = self.journal.reserve(key, {"request": request, "mounts": {key: self._inventory(value) for key, value in mounts.items()}}, request["kind"])
        self.calls.append((request, mounts))
        if self.interrupt:
            self.journal.update(key, "unknown")
            raise InterruptedError("unknown fixture completion with secret-value")
        directory = self.workspaces / job["name"]
        directory.mkdir()
        output = directory / "output"
        output.mkdir()
        result = {"returncode": 0, "node_version": self.node_version, "package_manager_version": "11.6.0", "duration_ms": 1}
        if request["kind"] == "git":
            (output / "objects").mkdir()
            lines = []
            for oid, (kind, content) in self.objects.items.items():
                (output / "objects" / oid).write_bytes(content)
                lines.append(f"{oid} {kind} {len(content)}")
            (output / "objects.list").write_text("\n".join(lines))
            result.update({"object_format": "sha1", "commit_sha": request["commit_sha"]})
        elif request["kind"] == "npm_seed":
            (output / "cache").mkdir()
            (output / "cache" / "verified-cache").write_text("fixture")
        elif request["kind"] == "command":
            shutil.copytree(mounts["/input"], output / "project", symlinks=True)
            package = output / "project" / "node_modules" / "dep"
            package.mkdir(parents=True, exist_ok=True)
            (package / "index.js").write_text("fixture dependency")
            if request["command"] == ["npm", "run", "build"]:
                (output / "project" / "built.js").write_text("fixture build")
            if self.mutate:
                self.mutate(output / "project")
        (output / "result.json").write_text(json.dumps(result))
        self._freeze(output)
        self.journal.update(key, "completed", result={"returncode": 0})
        return result | {"output": output}


@pytest.fixture
def flow(tmp_path):
    root = tmp_path / "executor"
    root.mkdir(mode=0o700)
    (root / "workspaces").mkdir(mode=0o700)
    dependency = archive({"package/index.js": b"fixture dependency"})
    tool = archive({"package/package.json": json.dumps({"name": "npm", "version": "11.6.0", "engines": {"node": "^20.17.0 || >=22.9.0"}}).encode(), "package/bin/npm-cli.js": b"// reviewed fixture", "package/node_modules/cacache/index.js": b"// reviewed fixture"})
    package = {"name": "fixture", "version": "1.0.0", "packageManager": "npm@11.6.0", "bin": "index.mjs", "dependencies": {"dep": "1.0.0"}, "scripts": {"build": "fixture-build"}}
    lock = {"name": "fixture", "version": "1.0.0", "lockfileVersion": 3, "packages": {"": {"dependencies": {"dep": "1.0.0"}}, "node_modules/dep": {"version": "1.0.0", "resolved": "https://registry.npmjs.org/dep/-/dep-1.0.0.tgz", "integrity": sri(dependency)}}}
    files = {"package.json": json.dumps(package).encode(), "package-lock.json": json.dumps(lock).encode(), "index.mjs": b"export {};"}
    objects = Objects(files)
    config = NativeExecutorConfig(enabled=True, root=root, image="registry.example.invalid/executor@sha256:" + "a" * 64)
    controller = FixtureController(config, objects)
    transport = Transport(objects, tool, dependency)
    data = tmp_path / "gate"
    database = SQLiteDatabase("", data)
    audit = ObservabilityStore(database)
    credentials = CredentialStore(data)
    network = NetworkSettingsStore(database, data, credentials, audit)
    uploads = ProjectUploadStore(database, data)
    executor = NativeNetworkExecutor(config, data / "builds", controller=controller, https=transport)
    network.executor_readiness = executor.readiness
    builds = BuildDeployStore(database, data, uploads, None, None, audit, network_settings=network, safe_network_executor=executor)
    delivery = ProjectDeliveryMcpService(database, data, uploads, builds, None, None, audit)
    imports = GitImportService(delivery, network, executor=executor)
    context = ToolInvocationContext(actor_id="actor-one", username="operator", auth_type="session", token_id=None, correlation_id="fixture", permissions=("operations.manage", "network.use", "tools.invoke"))
    value = SimpleNamespace(root=root, database=database, executor=executor, controller=controller, transport=transport, network=network, imports=imports, uploads=uploads, delivery=delivery, builds=builds, context=context, objects=objects)
    yield value
    builds.executor.shutdown(wait=True)
    controller.journal.close()


def wait_for(function, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = function()
        if value["status"] in expected:
            return value
        time.sleep(0.01)
    raise AssertionError("Fixture coordinator did not become terminal: " + str(value))


def acquire(flow):
    planned = flow.imports.plan({"repository_url": URL}, flow.context)
    arguments = {"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "fixture-import-once", "confirmed": True}
    created = flow.imports.create(arguments, flow.context)
    finished = wait_for(lambda: flow.imports.status({"import_id": created["import_id"]}, flow.context), {"success", "failed", "interrupted"})
    assert finished["status"] == "success", finished
    assert flow.imports.create(arguments, flow.context)["import_id"] == finished["import_id"]
    return finished["upload_id"]


def build(flow, upload_id):
    planned = flow.delivery.build_plan({"upload_id": upload_id, "run_install": True, "run_build": True}, flow.context)
    assert planned["plan"]["buildable"], planned
    assert planned["plan"]["steps"][0]["id"] == "node-toolchain"
    arguments = {"upload_id": upload_id, "run_install": True, "run_build": True, "timeout_seconds": 120, "source_sha256": planned["source_sha256"], "plan_fingerprint": planned["plan_fingerprint"], "idempotency_key": "fixture-build-once", "confirmed": True}
    created = flow.delivery.build_create(arguments, flow.context)
    finished = wait_for(lambda: flow.delivery.build_status({"build_id": created["build_id"]}, flow.context), {"success", "failed", "interrupted"})
    assert flow.delivery.build_create(arguments, flow.context)["build_id"] == finished["build_id"]
    return finished


def test_git_exact_import_tool_prepare_install_build_artifact_and_idempotency(flow):
    with patch("lingshu_gate.build_deploy._run_command", side_effect=AssertionError("Host project execution is prohibited")):
        upload_id = acquire(flow)
        result = build(flow, upload_id)
    assert result["status"] == "success", result
    persisted = flow.builds.get_build(result["build_id"])
    artifact = Path(persisted["artifact_dir"])
    assert (artifact / "node_modules" / "dep" / "index.js").read_text() == "fixture dependency"
    assert (artifact / "built.js").read_text() == "fixture build"
    assert not (artifact / "result.json").exists()
    assert persisted["plan"]["source_provenance"]["git_source"]["commit_sha"] == flow.objects.commit
    assert [call[0]["kind"] for call in flow.controller.calls] == ["git", "tool_probe", "npm_seed", "command", "command"]
    assert flow.network.settings()["executor"]["available"]
    assert len([url for url, _ in flow.transport.calls if url.endswith(".tgz")]) == 2


def test_artifact_secret_and_external_link_rejection_keeps_source_and_old_deployment(flow):
    upload_id = acquire(flow)
    flow.controller.mutate = lambda root: (root / "external").symlink_to("/etc/passwd")
    result = build(flow, upload_id)
    assert result["status"] == "failed"
    artifact = Path(flow.builds.get_build(result["build_id"])["artifact_dir"])
    assert not list(artifact.iterdir())
    assert "external" not in [path.name for path in Path(flow.builds.get_build(result["build_id"])["source_dir"]).iterdir()]


def test_unknown_sandbox_outcome_is_interrupted_and_cannot_cancel_or_delete(flow):
    upload_id = acquire(flow)
    flow.controller.interrupt = True
    result = build(flow, upload_id)
    assert result["status"] == "interrupted", result
    assert result["terminal"] and result["requires_reconciliation"] and not result["execution_terminated"]
    with pytest.raises(ValueError):
        flow.builds.cancel_build(result["build_id"])
    with pytest.raises(Exception, match="reconciliation"):
        flow.builds.delete_build(result["build_id"])
    assert "secret-value" not in json.dumps(flow.builds.list_build_logs(result["build_id"]))


def test_distribution_integrity_failure_never_probes_or_executes_tool(flow):
    network = flow.network.freeze(NetworkSelection(), NetworkSelection())
    network["execution"] = {"build_id": "a" * 32, "actor_id": "actor-one", "plan_fingerprint": "a" * 64, "source_sha256": "b" * 64}
    original = flow.transport.tool
    flow.transport.tool += b"corrupted"
    # Metadata must keep the old pin; otherwise this fixture would represent a
    # different valid official distribution, not a verification failure.
    request = flow.transport.request
    def fetch(url, **kwargs):
        if url.endswith("/npm/11.6.0"):
            flow.transport.tool = original
            result = request(url, **kwargs)
            flow.transport.tool = original + b"corrupted"
            return result
        return request(url, **kwargs)
    flow.transport.request = fetch
    with pytest.raises(ToolExecutionError):
        flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    assert not flow.controller.calls


@pytest.mark.parametrize("first,second", [(None, "sha512"), ("sha512", None), ("sha512", "sha512_upper"), ("sha256", "sha384")])
def test_tool_cache_identity_is_independent_of_each_projects_equivalent_pin(flow, first, second):
    def pin(algorithm):
        if algorithm is None:
            return None
        actual = algorithm.removesuffix("_upper")
        value = hashlib.new(actual, flow.transport.tool).hexdigest()
        return actual + "." + (value.upper() if algorithm.endswith("_upper") else value)
    network = flow.network.freeze(NetworkSelection(), NetworkSelection())
    for index, algorithm in enumerate((first, second)):
        network["execution"] = {"build_id": ("a" if index == 0 else "b") * 32, "actor_id": "actor-one", "plan_fingerprint": "a" * 64, "source_sha256": "b" * 64}
        flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0", pin(algorithm)), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
        prepared = flow.executor.tools.prepared({"name": "npm", "version": "11.6.0", "declared_integrity": pin(algorithm)})
        assert prepared.is_dir()
    assert sum(url.endswith("/npm/-/npm-11.6.0.tgz") for url, _ in flow.transport.calls) == 1
    assert len(list((flow.root / "tools").glob("[a-f0-9]" * 64))) == 1


@pytest.mark.parametrize("algorithm", ["sha256", "sha512"])
def test_wrong_request_pin_cannot_reuse_valid_global_tool_bytes(flow, algorithm):
    network = flow.network.freeze(NetworkSelection(), NetworkSelection())
    network["execution"] = {"build_id": "a" * 32, "actor_id": "actor-one", "plan_fingerprint": "a" * 64, "source_sha256": "b" * 64}
    flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    wrong = algorithm + "." + "0" * (int(algorithm.removeprefix("sha")) // 4)
    network["execution"]["build_id"] = "b" * 32
    with pytest.raises(ToolExecutionError) as rejected:
        flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0", wrong), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    assert rejected.value.code == "package_manager_integrity_unverified"
    with pytest.raises(ToolExecutionError):
        flow.executor.tools.prepared({"name": "npm", "version": "11.6.0", "declared_integrity": wrong})
    assert len(flow.controller.calls) == 1


def test_separate_pinned_git_and_install_proxy_material_never_enters_container(flow):
    git = flow.network.save_profile(ProfileWrite(name="Git proxy", endpoint="http://git-proxy.example.invalid:8080"), "admin")
    install = flow.network.save_profile(ProfileWrite(name="Install proxy", endpoint="socks5://install-proxy.example.invalid:1080"), "admin")
    planned = flow.imports.plan({"repository_url": URL, "git_network": {"mode": "profile", "profile_id": git["id"], "version": 1}, "install_network": {"mode": "profile", "profile_id": install["id"], "version": 1}}, flow.context)
    created = flow.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "fixture-profile-import", "confirmed": True}, flow.context)
    imported = wait_for(lambda: flow.imports.status({"import_id": created["import_id"]}, flow.context), {"success", "failed"})
    assert imported["status"] == "success"
    result = build(flow, imported["upload_id"])
    assert result["status"] == "success", result
    git_calls = [kwargs for url, kwargs in flow.transport.calls if "/fixture/project/" in url]
    installs = [kwargs for url, kwargs in flow.transport.calls if "registry.npmjs.org" in url]
    assert all(kwargs["material"]["proxy"] == "http://git-proxy.example.invalid:8080" for kwargs in git_calls)
    assert all(kwargs["material"]["proxy"] == "socks5://install-proxy.example.invalid:1080" for kwargs in installs)
    serialized = json.dumps([request for request, _ in flow.controller.calls])
    assert "git-proxy.example.invalid" not in serialized and "install-proxy.example.invalid" not in serialized


@pytest.mark.parametrize("command", [["pnpm", "install", "--frozen-lockfile"], ["yarn", "install", "--frozen-lockfile"], ["python", "-m", "pip", "install", "-r", "requirements.txt"]])
def test_unreviewed_cache_workflows_are_rejected_before_dispatch(flow, command):
    with pytest.raises(ToolExecutionError) as rejected:
        flow.executor.validate_plan({"steps": [{"phase": "install", "command": command}]})
    assert rejected.value.code == "dependency_cache_workflow_unsupported"
    assert not flow.controller.calls and not flow.transport.calls


def test_restart_coordinator_marks_orphaned_isolated_build_interrupted_without_dispatch(flow):
    source = flow.builds.root / ("a" * 32) / "source"
    artifact = source.parent / "artifact"
    source.mkdir(parents=True)
    artifact.mkdir()
    flow.builds._insert_build_record("a" * 32, "upload", "node", source, artifact, status="running", plan={"source_provenance": {"commit_sha": "b" * 40}})
    recovered = BuildDeployStore(flow.database, flow.builds.data_dir, flow.uploads, None, None, flow.builds.observability, network_settings=flow.network, safe_network_executor=flow.executor)
    try:
        assert recovered.get_build("a" * 32)["status"] == "interrupted"
        assert not flow.controller.calls
        with pytest.raises(Exception, match="reconciliation"):
            recovered.delete_build("a" * 32)
    finally:
        recovered.executor.shutdown(wait=True)


def test_output_root_symlink_never_exports_host_tree(flow, tmp_path):
    upload_id = acquire(flow)
    outside = tmp_path / "private-host-data"
    outside.mkdir()
    (outside / "private.txt").write_text("fixture host data")
    def replace_root(root):
        shutil.rmtree(root)
        root.symlink_to(outside, target_is_directory=True)
    flow.controller.mutate = replace_root
    result = build(flow, upload_id)
    assert result["status"] == "failed"
    assert result["failure_message"] == "executor_output_root_rejected"
    assert not list(Path(flow.builds.get_build(result["build_id"])["artifact_dir"]).iterdir())
    assert (outside / "private.txt").read_text() == "fixture host data"

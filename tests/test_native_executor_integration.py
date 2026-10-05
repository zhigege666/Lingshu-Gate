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
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from lingshu_gate.adapters.native_executor.controller import PodmanController
from lingshu_gate.adapters.native_executor.executor import NativeNetworkExecutor
from lingshu_gate.adapters.native_executor.git import packet
from lingshu_gate.adapters.native_executor.journal import JobJournal
from lingshu_gate.adapters.native_executor.https import PinnedHTTPS
from lingshu_gate.adapters.native_executor.pending import PendingDNS
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
        self.manager, self.version, self.engines = "npm", "11.6.0", "^20.17.0 || >=22.9.0"

    def request(self, url, **kwargs):
        self.calls.append((url, {**kwargs, "material": dict(kwargs["material"])}))
        if url.endswith("/info/refs?service=git-upload-pack"):
            return 200, packet(b"# service=git-upload-pack\n") + b"0000" + packet(f"{self.objects.commit} refs/heads/main\0multi_ack_detailed side-band-64k ofs-delta\n".encode()) + b"0000"
        if url.endswith("/git-upload-pack"):
            assert f"want {self.objects.commit} ".encode() in kwargs["body"]
            assert b"main" not in kwargs["body"]
            return 200, packet(b"NAK\n") + packet(b"\x01PACKfixture") + b"0000"
        if url.endswith("/" + self.manager + "/" + self.version):
            return 200, json.dumps({"name": self.manager, "version": self.version, "engines": {"node": self.engines}, "dist": {"integrity": sri(self.tool), "tarball": f"https://registry.npmjs.org/{self.manager}/-/{self.manager}-{self.version}.tgz"}}).encode()
        if url.endswith(f"/{self.manager}/-/{self.manager}-{self.version}.tgz"):
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
        if self.interrupt is True or self.interrupt == request["kind"]:
            self.journal.update(key, "unknown")
            self.missing.append("job_termination_unknown")
            raise InterruptedError("unknown fixture completion with secret-value")
        directory = self.workspaces / job["name"]
        directory.mkdir()
        output = directory / "output"
        output.mkdir()
        result = {"returncode": 0, "node_version": self.node_version, "package_manager_version": request.get("version", "11.6.0"), "duration_ms": 1}
        if request["kind"] == "tool_probe":
            result["package_manager_version"] = json.loads((mounts["/tool"] / "package" / "package.json").read_text())["version"]
        if request["kind"] == "git":
            (output / "objects").mkdir()
            lines = []
            for oid, (kind, content) in self.objects.items.items():
                (output / "objects" / oid).write_bytes(content)
                lines.append(f"{oid} {kind} {len(content)}")
            (output / "objects.list").write_text("\n".join(lines))
            result.update({"object_format": "sha1", "commit_sha": request["commit_sha"]})
        elif request["kind"] in {"npm_seed", "pnpm_seed", "yarn_seed"}:
            (output / "cache").mkdir()
            (output / "cache" / "verified-cache").write_text("fixture")
        elif request["kind"] == "command":
            shutil.copytree(mounts["/input"], output / "project", symlinks=True)
            package = output / "project" / "node_modules" / "dep"
            package.mkdir(parents=True, exist_ok=True)
            (package / "index.js").write_text("fixture dependency")
            if request["command"][1:] == ["run", "build"]:
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


def use_manager(flow, name, version):
    engines = ">=16.14" if name == "pnpm" and version.startswith("8.") else ">=18.12" if name == "pnpm" else ">=4.0.0"
    cli = "bin/pnpm.cjs" if name == "pnpm" else "bin/yarn.js"
    flow.transport.manager, flow.transport.version, flow.transport.engines = name, version, engines
    flow.transport.tool = archive({"package/package.json": json.dumps({"name": name, "version": version, "engines": {"node": engines}}).encode(), "package/" + cli: b"// reviewed fixture"})
    package = {"name": "fixture", "version": "1.0.0", "packageManager": name + "@" + version, "bin": "index.mjs", "dependencies": {"dep": "1.0.0"}, "scripts": {"build": "fixture-build", "preinstall": "fixture-untrusted-script"}}
    if name == "yarn":
        lockfile = "yarn.lock"
        content = f'# yarn lockfile v1\n\ndep@1.0.0:\n  version "1.0.0"\n  resolved "https://registry.yarnpkg.com/dep/-/dep-1.0.0.tgz#{hashlib.sha1(flow.transport.dependency).hexdigest()}"\n  integrity {sri(flow.transport.dependency)}\n'.encode()
    else:
        lockfile = "pnpm-lock.yaml"
        major = int(version.split(".")[0])
        pin = {"specifier": "1.0.0", "version": "1.0.0"}
        data = {"lockfileVersion": "6.0" if major == 8 else "9.0", "settings": {"autoInstallPeers": True, "excludeLinksFromLockfile": False}, "packages": {("/" if major == 8 else "") + "dep@1.0.0": {"resolution": {"integrity": sri(flow.transport.dependency)}}}}
        if major == 8:
            data["dependencies"] = {"dep": pin}
        else:
            data["importers"] = {".": {"dependencies": {"dep": pin}}}
            data["snapshots"] = {"dep@1.0.0": {}}
        content = yaml.safe_dump(data).encode()
    objects = Objects({"package.json": json.dumps(package).encode(), lockfile: content, "index.mjs": b"export {};"})
    flow.objects = flow.controller.objects = flow.transport.objects = objects
    return lockfile, content


@pytest.mark.parametrize("name,version", [("yarn", "1.22.22"), ("pnpm", "8.15.9"), ("pnpm", "9.15.4")])
def test_selected_manager_git_prepare_cache_install_build_and_artifact_closed_flow(flow, name, version):
    lockfile, content = use_manager(flow, name, version)
    with patch("lingshu_gate.build_deploy._run_command", side_effect=AssertionError("Host project execution is prohibited")):
        result = build(flow, acquire(flow))
    assert result["status"] == "success", result
    artifact = Path(flow.builds.get_build(result["build_id"])["artifact_dir"])
    assert (artifact / lockfile).read_bytes() == content
    assert (artifact / "built.js").read_text() == "fixture build"
    assert (artifact / "node_modules" / "dep" / "index.js").is_file()
    assert [request["kind"] for request, _ in flow.controller.calls] == ["git", "tool_probe", name + "_seed", "command", "command"]
    seeded = next((request, mounts) for request, mounts in flow.controller.calls if request["kind"] == name + "_seed")
    assert seeded[0]["version"] == version and "lockfile_sha256" in seeded[0]["binding"]
    commands = [request["command"] for request, _ in flow.controller.calls if request["kind"] == "command"]
    assert commands == [[name, "install", "--frozen-lockfile"], [name, "run", "build"]]
    assert "pnpm_8_9_registry_lock_v3_store" in flow.executor.readiness()["support"]["offline_install"]
    assert not list(flow.controller.workspaces.iterdir())


@pytest.mark.parametrize("name,version", [("yarn", "1.22.22"), ("pnpm", "9.15.4")])
def test_frozen_install_lock_mutation_cannot_publish_artifact(flow, name, version):
    lockfile, _ = use_manager(flow, name, version)
    upload = acquire(flow)
    flow.controller.mutate = lambda root: (root / lockfile).write_text("changed by lifecycle")
    result = build(flow, upload)
    assert result["status"] == "failed", result
    artifact = Path(flow.builds.get_build(result["build_id"])["artifact_dir"])
    assert not list(artifact.iterdir())


@pytest.mark.parametrize("version", ["10.18.0", "11.0.0"])
def test_pnpm_unreviewed_cache_format_blocks_plan_before_tool_or_content_acquisition(flow, version):
    with pytest.raises(ToolExecutionError) as rejected:
        flow.executor.validate_plan({"package_manager": {"name": "pnpm", "version": version}, "steps": [{"phase": "install", "command": ["pnpm", "install", "--frozen-lockfile"]}]})
    assert rejected.value.code == "pnpm_cache_format_unsupported"
    assert not flow.controller.calls and not flow.transport.calls


def test_python_legacy_upload_direct_remains_separate_from_git_or_profile_executor(flow):
    direct = {"steps": [{"phase": "install", "command": ["python", "-m", "pip", "install", "-r", "requirements.txt"]}], "delivery_network": {"install": {"mode": "direct"}, "npm_registry": "https://registry.npmjs.org/", "python_index": "https://pypi.org/simple/"}}
    assert not BuildDeployStore._requires_safe_network(direct)
    assert BuildDeployStore._requires_safe_network(direct | {"source_provenance": {"git_source": {"commit_sha": "a" * 40}}})
    assert BuildDeployStore._requires_safe_network(direct | {"delivery_network": direct["delivery_network"] | {"install": {"mode": "profile"}}})
    with pytest.raises(ToolExecutionError):
        flow.executor.validate_plan(direct)
    assert not flow.controller.calls


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


@pytest.mark.parametrize("name,version", [("npm", "11.6.0"), ("yarn", "1.22.22"), ("pnpm", "9.15.4")])
def test_unknown_consumer_retains_acquisition_and_seed_inputs_for_reconciliation(flow, name, version):
    if name != "npm":
        use_manager(flow, name, version)
    upload_id = acquire(flow)
    flow.controller.interrupt = "command"
    result = build(flow, upload_id)
    assert result["status"] == "interrupted", result
    acquisition = flow.controller.journal.lookup("build:" + result["build_id"] + ":install:acquire")
    seeded = flow.controller.journal.lookup("build:" + result["build_id"] + ":install:seed")
    assert acquisition["state"] == seeded["state"] == "completed"
    assert acquisition["cleanup_state"] == seeded["cleanup_state"] == "pending"
    assert (flow.controller.workspaces / acquisition["name"] / "output" / "index.json").is_file()
    assert (flow.controller.workspaces / seeded["name"] / "output" / "cache" / "verified-cache").is_file()
    assert not flow.executor.readiness()["available"]
    assert "secret-value" not in json.dumps(flow.builds.list_build_logs(result["build_id"]))


def native_input(flow):
    identity = uuid4().hex
    source = flow.executor.build_root / identity / "source"
    source.mkdir(parents=True)
    package = {"name": "fixture", "version": "1.0.0", "dependencies": {"dep": "1.0.0"}, "scripts": {"build": "fixture-build"}}
    lock = {"lockfileVersion": 3, "packages": {"": {"dependencies": package["dependencies"]}, "node_modules/dep": {"version": "1.0.0", "resolved": "https://registry.npmjs.org/dep/-/dep-1.0.0.tgz", "integrity": sri(flow.transport.dependency)}}}
    content = json.dumps(lock).encode()
    (source / "package.json").write_text(json.dumps(package))
    (source / "package-lock.json").write_bytes(content)
    return source, {"install": {"mode": "direct"}, "npm_registry": "https://registry.npmjs.org/", "package_manager": {"name": "npm", "version": "11.6.0", "lockfile": "package-lock.json", "lockfile_sha256": hashlib.sha256(content).hexdigest()}, "execution": {"build_id": identity, "actor_id": "fixture-actor", "plan_fingerprint": "a" * 64, "source_sha256": "b" * 64}}


@pytest.mark.parametrize("phase", ["tool_acquisition", "dependency_acquisition", "git_acquisition"])
def test_dns_timeout_blocks_until_reconciled_and_repeated_success_keeps_workspace_empty(flow, phase):
    source, network = native_input(flow)
    if phase != "tool_acquisition":
        flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    release = threading.Event()
    def resolver(host, port, **kwargs):
        release.wait(10)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", port))]
    client = PinnedHTTPS(resolver=resolver)
    trigger = True
    def request(url, **kwargs):
        nonlocal trigger
        if trigger:
            trigger = False
            # Shorten only the test deadline; this is the production unknown
            # branch with the real bounded resolver worker still running.
            client.addresses(kwargs["rule"]["host"], kwargs["rule"]["port"], kwargs["rule"], deadline=time.monotonic() + 0.02)
        return flow.transport.request(url, **kwargs)
    flow.executor.https = flow.executor.tools.https = flow.executor.git.backend.https = client
    key = "build:" + network["execution"]["build_id"] + (":prepare:acquire" if phase == "tool_acquisition" else ":install:acquire")
    try:
        with patch.object(client, "request", side_effect=request), patch.object(flow.controller, "inspect", return_value=None) as inspect:
            with pytest.raises(PendingDNS) as pending:
                if phase == "tool_acquisition":
                    flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                elif phase == "dependency_acquisition":
                    flow.executor.run_command(["npm", "ci"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                else:
                    identity = uuid4().hex
                    key = "git:" + identity + ":acquire"
                    git_request = {"execution": {"import_id": identity}, "source": {"repository_url": URL}, "commit_sha": flow.objects.commit, "host_rule": {"host": "github.com", "port": 443, "private_cidrs": []}, "limits": {"transfer_bytes": 50 * 1024 * 1024}}
                    with flow.executor.git.backend.fetch_exact(git_request, material={"proxy": None}, cancel=threading.Event(), deadline=time.monotonic() + 120):
                        raise AssertionError("Timed-out DNS cannot yield Git content")
            assert flow.controller.journal.lookup(key)["state"] == "unknown"
            assert "job_reconciliation_required" in flow.executor.readiness()["missing"]
            calls = len(flow.controller.calls), len(flow.transport.calls)
            # Clearing a flag is insufficient while the actual worker lives.
            client.dns_busy.clear()
            assert not flow.executor.readiness()["available"]
            with pytest.raises(ToolExecutionError) as blocked:
                flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
            assert blocked.value.code == "safe_executor_unavailable"
            assert calls == (len(flow.controller.calls), len(flow.transport.calls))
            with pytest.raises(InterruptedError, match="active_work_reconciliation_blocked"):
                flow.controller.reconcile()
            inspect.assert_not_called()
            release.set()
            pending.value.worker.join(1)
            assert not pending.value.worker.is_alive()
            # Reader-visible readiness is restored only after real journal /
            # resource reconciliation, before any subsequent command is admitted.
            assert flow.executor.readiness()["available"]
            assert inspect.called
            old = flow.controller.journal.lookup(key)
            assert old["state"] == "interrupted_terminated" and old["cleanup_state"] == "cleaned"
            assert not flow.controller.journal.unfinished()
            assert not list(flow.controller.workspaces.iterdir())
            with pytest.raises(InterruptedError):
                if phase == "tool_acquisition":
                    flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                elif phase == "dependency_acquisition":
                    flow.executor.run_command(["npm", "ci"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                else:
                    with flow.executor.git.backend.fetch_exact(git_request, material={"proxy": None}, cancel=threading.Event(), deadline=time.monotonic() + 120):
                        raise AssertionError("Reconciled Git acquisition must not replay")
            for _ in range(6):
                current, descriptor = native_input(flow)
                flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=descriptor, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                for command in (["npm", "ci"], ["npm", "run", "build"]):
                    result = flow.executor.run_command(command, cwd=current, environment={}, network=descriptor, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                    assert result["returncode"] == 0
                    assert not flow.controller.journal.unfinished()
                    assert not list(flow.controller.workspaces.iterdir())
                assert (current / "built.js").read_text() == "fixture build"
    finally:
        release.set()
        if client._dns_worker:
            client._dns_worker.join(1)


@pytest.mark.parametrize("state", ["unknown", "running", "reserved"])
def test_unproven_unknown_or_stale_journal_state_cannot_admit(flow, state):
    _, network = native_input(flow)
    job = flow.controller.journal.reserve("fixture:stale", {"source": "fixture"}, "dependency_acquisition")
    # A persisted DNS reason is diagnostic, never live-process stop evidence.
    flow.controller.journal.update(job["key"], state, result={"reconciliation_reason": "trusted_dns_termination_unknown"})
    with patch.object(flow.controller, "inspect") as inspect:
        assert not flow.executor.readiness()["available"]
        with pytest.raises(ToolExecutionError) as blocked:
            flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
        assert blocked.value.code == "safe_executor_unavailable"
        inspect.assert_not_called()
    assert flow.controller.journal.lookup(job["key"])["state"] == state
    assert not flow.controller.calls and not flow.transport.calls


def record_stopped_dns(flow):
    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join(1)
    assert not worker.is_alive()
    with pytest.raises(PendingDNS), flow.controller.journal.trusted_phase("fixture:dns", {"source": "fixture"}, "dependency_acquisition"):
        output = flow.controller.acquisition_output("fixture:dns")
        (output / "verified.tgz").write_bytes(b"verified fixture")
        raise PendingDNS(worker)
    return output


def test_stopped_dns_cannot_reap_inputs_of_an_unknown_consumer(flow):
    retained = record_stopped_dns(flow)
    seed = flow.controller.journal.reserve("fixture:seed", {"source": "fixture"}, "npm_seed")
    cache = flow.controller.workspaces / seed["name"] / "output"
    cache.mkdir(parents=True)
    (cache / "verified-cache").write_bytes(b"fixture")
    flow.controller.journal.update(seed["key"], "completed")
    consumer = flow.controller.journal.reserve("fixture:consumer", {"source": "fixture"}, "command")
    flow.controller.journal.update(consumer["key"], "unknown", container_id="b" * 64, cgroup="/fixture/sandbox")
    _, network = native_input(flow)
    with patch.object(flow.controller, "inspect") as inspect:
        assert not flow.executor.readiness()["available"]
        with pytest.raises(ToolExecutionError):
            flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
        inspect.assert_not_called()
    assert retained.is_dir() and (cache / "verified-cache").read_bytes() == b"fixture"
    assert flow.controller.journal.lookup("fixture:dns")["state"] == "unknown"
    assert flow.controller.journal.lookup(seed["key"])["cleanup_state"] == "pending"
    assert not flow.controller.calls and not flow.transport.calls


def test_dns_reconciliation_failure_keeps_readiness_and_admission_blocked(flow):
    retained = record_stopped_dns(flow)
    _, network = native_input(flow)
    with patch.object(flow.controller, "inspect", side_effect=InterruptedError("fixture engine state unknown")) as inspect:
        assert not flow.executor.readiness()["available"]
        with pytest.raises(ToolExecutionError):
            flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
        assert inspect.called
    assert retained.is_dir() and flow.controller.journal.lookup("fixture:dns")["state"] == "unknown"
    assert not flow.controller.calls and not flow.transport.calls


def test_cleanup_failure_after_dns_terminalization_still_blocks_admission(flow):
    retained = record_stopped_dns(flow)
    _, network = native_input(flow)
    with patch.object(flow.controller, "inspect", return_value=None), patch.object(flow.controller, "release_output", side_effect=ToolExecutionError("executor_cleanup_path_rejected", "fixture")):
        state = flow.executor.readiness()
        assert not state["available"] and "job_reconciliation_incomplete" in state["missing"]
        assert flow.controller.journal.lookup("fixture:dns")["state"] == "interrupted_terminated"
        with pytest.raises(ToolExecutionError):
            flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    assert retained.is_dir() and not flow.controller.calls and not flow.transport.calls


@pytest.mark.parametrize("cleanup_method", ["release_output", "release_acquisition"])
def test_command_cleanup_failure_releases_gate_but_keeps_admission_blocked(flow, cleanup_method):
    source, network = native_input(flow)
    flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    with patch.object(flow.controller, cleanup_method, side_effect=OSError("fixture cleanup failed")):
        with pytest.raises(OSError, match="fixture cleanup failed"):
            flow.executor.run_command(["npm", "ci"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    assert not flow.executor._active_call.is_set()
    assert flow.executor._gate.acquire(blocking=False)
    flow.executor._gate.release()
    state = flow.executor.readiness()
    assert not state["available"] and "job_workspace_cleanup_incomplete" in state["missing"]
    assert not flow.controller.journal.unfinished()
    assert flow.controller.journal.cleanup_pending() and list(flow.controller.workspaces.iterdir())
    calls = len(flow.controller.calls), len(flow.transport.calls)
    with pytest.raises(ToolExecutionError) as blocked:
        flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
    assert blocked.value.code == "safe_executor_unavailable"
    assert calls == (len(flow.controller.calls), len(flow.transport.calls))


def test_readiness_and_admission_wait_until_reconciliation_cleanup_finishes(flow):
    retained = record_stopped_dns(flow)
    _, network = native_input(flow)
    entered, release = threading.Event(), threading.Event()
    results = []
    remove = flow.controller.release_output
    def cleanup(result):
        entered.set()
        assert release.wait(5)
        remove(result)
    worker = threading.Thread(target=lambda: results.append(flow.executor.readiness()))
    with patch.object(flow.controller, "inspect", return_value=None), patch.object(flow.controller, "release_output", side_effect=cleanup):
        try:
            worker.start()
            assert entered.wait(1)
            # The DNS row is terminal, but cleanup still owns admission.
            assert flow.controller.journal.lookup("fixture:dns")["state"] == "interrupted_terminated"
            state = flow.executor.readiness()
            assert not state["available"] and "job_reconciliation_in_progress" in state["missing"]
            with pytest.raises(ToolExecutionError) as blocked:
                flow.executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
            assert blocked.value.code == "executor_busy"
            assert retained.is_dir() and not flow.controller.calls and not flow.transport.calls
        finally:
            release.set()
            worker.join(1)
    assert not worker.is_alive() and results[0]["available"]
    assert not retained.parent.exists()


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

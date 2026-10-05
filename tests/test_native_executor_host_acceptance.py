"""Explicit operator-only acceptance; never provisions engines/mounts/images."""
from __future__ import annotations

import json
import os
import hashlib
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from lingshu_gate.adapters.native_executor.executor import NativeNetworkExecutor
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.node_toolchain import tool_preparation
from lingshu_gate.offline_build_contract import parse_strong_sri
from lingshu_gate.registry import ToolExecutionError


@pytest.mark.skipif(not os.environ.get("LINGSHU_GATE_TEST_EXECUTOR_ROOT"), reason="Operator-provisioned rootless Podman/image/tmpfs required; no host fallback")
def test_real_nested_npm_and_existing_only_npx_in_prepared_sandbox(tmp_path):
    configuration = NativeExecutorConfig(enabled=True, root=Path(os.environ["LINGSHU_GATE_TEST_EXECUTOR_ROOT"]), image=os.environ["LINGSHU_GATE_TEST_EXECUTOR_IMAGE"], podman_bin=os.environ.get("LINGSHU_GATE_TEST_PODMAN_BIN", "/usr/bin/podman"))
    executor = NativeNetworkExecutor(configuration, tmp_path / "builds")
    executor.start()
    try:
        assert executor.readiness()["available"], executor.readiness()
        network = {"install": {"mode": "direct"}, "npm_registry": "https://registry.npmjs.org/", "execution": {"build_id": uuid4().hex, "actor_id": "synthetic-host-acceptance", "plan_fingerprint": "a" * 64, "source_sha256": "b" * 64}}
        executor.prepare_package_manager(tool_preparation("npm", "11.6.0"), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
        network["package_manager"] = {"name": "npm", "version": "11.6.0", "declared_integrity": None}
        for expected, script in ((0, "npm run clean && npx --no-install gate-fixture"), (1, "npx gate-absent-fixture-command")):
            network["execution"]["build_id"] = uuid4().hex
            source = tmp_path / "builds" / network["execution"]["build_id"] / "source"
            binary = source / "node_modules" / ".bin" / "gate-fixture"
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/usr/local/bin/node\nrequire("fs").writeFileSync("npx-existing.txt","existing-only");\n')
            binary.chmod(0o755)
            (source / "package.json").write_text(json.dumps({"name": "synthetic-host-acceptance", "version": "1.0.0", "packageManager": "npm@11.6.0", "scripts": {"clean": "npm --version > nested-npm-version.txt", "build": script}}))
            result = executor.run_command(["npm", "run", "build"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=30, cancel_requested=lambda: False)
            assert result["returncode"] == expected, result
            if expected == 0:
                assert (source / "nested-npm-version.txt").read_text().strip() == "11.6.0"
                assert (source / "npx-existing.txt").read_text() == "existing-only"
            else:
                assert not (source / "nested-npm-version.txt").exists()
    finally:
        executor.close()


@pytest.mark.skipif(not os.environ.get("LINGSHU_GATE_TEST_EXECUTOR_ROOT"), reason="Operator-provisioned rootless Podman/image/tmpfs required; no host fallback")
@pytest.mark.parametrize("name,version", [("yarn", "1.22.22"), ("pnpm", "8.15.9"), ("pnpm", "9.15.4")])
def test_real_official_manager_cache_frozen_install_nested_build_and_missing_closure(tmp_path, name, version):
    configuration = NativeExecutorConfig(enabled=True, root=Path(os.environ["LINGSHU_GATE_TEST_EXECUTOR_ROOT"]), image=os.environ["LINGSHU_GATE_TEST_EXECUTOR_IMAGE"], podman_bin=os.environ.get("LINGSHU_GATE_TEST_PODMAN_BIN", "/usr/bin/podman"))
    executor = NativeNetworkExecutor(configuration, tmp_path / "builds")
    executor.start()
    try:
        assert executor.readiness()["available"], executor.readiness()
        network = {"install": {"mode": "direct"}, "npm_registry": "https://registry.npmjs.org/", "execution": {"build_id": uuid4().hex, "actor_id": "synthetic-host-acceptance", "plan_fingerprint": "a" * 64, "source_sha256": "b" * 64}}
        # Fixed public fixture only; no repository, real credential, daemon,
        # provisioning, global install or host project execution is involved.
        metadata = json.loads(executor.tools._fetch("https://registry.npmjs.org/is-number/7.0.0", network=network, material={"proxy": None}, deadline=time.monotonic() + 30, maximum=1024 * 1024, cancelled=lambda: False, official=True))
        assert metadata["name"] == "is-number" and metadata["version"] == "7.0.0"
        integrity = metadata["dist"]["integrity"]
        assert parse_strong_sri(integrity)[0] == "sha512"
        executor.prepare_package_manager(tool_preparation(name, version), network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
        pin = {"specifier": "7.0.0", "version": "7.0.0"}
        if name == "yarn":
            lockfile = "yarn.lock"
            content = f'# yarn lockfile v1\n\nis-number@7.0.0:\n  version "7.0.0"\n  resolved "https://registry.yarnpkg.com/is-number/-/is-number-7.0.0.tgz"\n  integrity {integrity}\n'.encode()
        else:
            lockfile = "pnpm-lock.yaml"
            major = int(version.split(".")[0])
            lock = {"lockfileVersion": "6.0" if major == 8 else "9.0", "settings": {"autoInstallPeers": True, "excludeLinksFromLockfile": False}, "packages": {("/" if major == 8 else "") + "is-number@7.0.0": {"resolution": {"integrity": integrity}}}}
            if major == 8:
                lock["dependencies"] = {"is-number": pin}
            else:
                lock["importers"] = {".": {"dependencies": {"is-number": pin}}}
                lock["snapshots"] = {"is-number@7.0.0": {}}
            content = yaml.safe_dump(lock).encode()
        network["package_manager"] = {"name": name, "version": version, "declared_integrity": None, "lockfile": lockfile, "lockfile_sha256": hashlib.sha256(content).hexdigest()}
        for missing_closure in (False, True):
            network["execution"]["build_id"] = uuid4().hex
            source = tmp_path / "builds" / network["execution"]["build_id"] / "source"
            source.mkdir(parents=True)
            dependencies = {"is-number": "7.0.0"}
            if missing_closure:
                dependencies["gate-deliberately-absent-fixture"] = "1.0.0"
            package = {"name": "synthetic-host-acceptance", "version": "1.0.0", "packageManager": name + "@" + version, "dependencies": dependencies, "scripts": {"preinstall": 'node -e "require(\'fs\').writeFileSync(\'project-install.txt\',\'sandbox-only\')"', "build": name + " --version > nested-manager-version.txt && node fixture.cjs"}}
            (source / "package.json").write_text(json.dumps(package))
            (source / lockfile).write_bytes(content)
            (source / "fixture.cjs").write_text('if(!require("is-number")(42))process.exit(1);require("fs").writeFileSync("artifact.txt","offline-frozen");\n')
            if missing_closure:
                with pytest.raises(ToolExecutionError) as rejected:
                    executor.run_command([name, "install", "--frozen-lockfile"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
                assert rejected.value.code == "dependency_cache_seed_failed"
                assert not (source / "project-install.txt").exists()
                continue
            result = executor.run_command([name, "install", "--frozen-lockfile"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=120, cancel_requested=lambda: False)
            assert result["returncode"] == 0, result
            assert (source / "project-install.txt").read_text() == "sandbox-only"
            assert (source / lockfile).read_bytes() == content
            result = executor.run_command([name, "run", "build"], cwd=source, environment={}, network=network, material={"proxy": None}, timeout_seconds=30, cancel_requested=lambda: False)
            assert result["returncode"] == 0, result
            assert (source / "nested-manager-version.txt").read_text().strip() == version
            assert (source / "artifact.txt").read_text() == "offline-frozen"
    finally:
        executor.close()

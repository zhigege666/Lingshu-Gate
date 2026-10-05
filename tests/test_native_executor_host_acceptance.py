"""Explicit operator-only acceptance; never provisions engines/mounts/images."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from lingshu_gate.adapters.native_executor.executor import NativeNetworkExecutor
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.node_toolchain import tool_preparation


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

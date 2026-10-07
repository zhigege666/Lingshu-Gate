"""Bounded manager cache grammars and fixed offline preparation commands."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

from lingshu_gate.adapters.native_executor import runner
from lingshu_gate.adapters.native_executor.locked_dependencies import pnpm_tarballs, strict_yaml, yarn_tarballs
from lingshu_gate.adapters.native_executor.packages import checked_json, project_policy, seed_manifest
from lingshu_gate.registry import ToolExecutionError


SRI = "sha512-" + base64.b64encode(hashlib.sha512(b"fixture").digest()).decode()
REGISTRY = "https://registry.example.invalid"


def yarn_lock(*, source="https://registry.yarnpkg.com/dep/-/dep-1.0.0.tgz", integrity=SRI):
    return f'# yarn lockfile v1\n\ndep@^1.0.0:\n  version "1.0.0"\n  resolved "{source}"\n  integrity {integrity}\n  dependencies:\n    nested "^2.0.0"\n'.encode()


def pnpm_lock(major, *, resolution=None):
    return yaml.safe_dump({"lockfileVersion": "6.0" if major == 8 else "9.0", "packages": {("/" if major == 8 else "") + "@scope/dep@1.0.0(peer@2.0.0)": {"resolution": resolution or {"integrity": SRI}}}}).encode()


def test_yarn_official_origin_maps_to_selected_mirror_without_changing_lock():
    lock = yarn_lock()
    records = yarn_tarballs(lock, REGISTRY)
    assert records[0].source == REGISTRY + "/dep/-/dep-1.0.0.tgz"
    assert records[0].filename == "dep-1.0.0.tgz" and records[0].integrity == SRI
    assert lock == yarn_lock()


@pytest.mark.parametrize("major", [8, 9])
def test_pnpm_exact_scoped_peer_content_maps_to_selected_registry(major):
    item, = pnpm_tarballs(pnpm_lock(major), REGISTRY, str(major) + ".0.0")
    assert item.source == REGISTRY + "/@scope/dep/-/dep-1.0.0.tgz"
    assert item.filename == "@scope-dep-1.0.0.tgz"


@pytest.mark.parametrize("source", ["https://unreviewed.example.invalid/dep/-/dep-1.0.0.tgz", "file:///dep.tgz", "https://registry.yarnpkg.com/../dep.tgz", "https://registry.yarnpkg.com/dep/-/dep-1.0.0.tgz?token=fixture", "https://user:fixture@registry.yarnpkg.com/dep/-/dep-1.0.0.tgz", "https://registry.yarnpkg.com:444/dep/-/dep-1.0.0.tgz"])
def test_unreviewed_yarn_sources_fail_before_fetch(source):
    with pytest.raises(ToolExecutionError):
        yarn_tarballs(yarn_lock(source=source), REGISTRY)


@pytest.mark.parametrize("integrity", ["sha1-fixture", "", SRI + " " + SRI, "sha512-AAAA"])
def test_weak_missing_multi_or_malformed_lock_hashes_are_refused(integrity):
    with pytest.raises(ToolExecutionError):
        yarn_tarballs(yarn_lock(integrity=integrity), REGISTRY)


@pytest.mark.parametrize("location", ["selector", "dependency"])
def test_yarn_non_registry_edges_fail_before_content_acquisition(location):
    content = yarn_lock()
    content = content.replace(b"dep@^1.0.0:", b'"dep@file:../outside":') if location == "selector" else content.replace(b'nested "^2.0.0"', b'nested "git+https://example.invalid/project"')
    with pytest.raises(ToolExecutionError) as rejected:
        yarn_tarballs(content, REGISTRY)
    assert rejected.value.code == "dependency_cache_workflow_unsupported"


def test_yarn_mixed_quoted_scoped_selectors_are_preserved():
    content = yarn_lock().replace(b"dep@^1.0.0:", b'"@scope/dep@^1.0.0", dep@~1.0.0:')
    assert len(yarn_tarballs(content, REGISTRY)) == 1


@pytest.mark.parametrize("content", [b"a: &a [1]\nb: *a", b"a: !!python/object:fixture {}", b"a: 1\na: 2", b"a: [\n", b"a: " + b"[" * 33 + b"0" + b"]" * 33, b"\xff", b"0: value"])
def test_pnpm_unbounded_or_ambiguous_yaml_is_refused(content):
    with pytest.raises(ToolExecutionError) as rejected:
        strict_yaml(content)
    assert rejected.value.code == "dependency_lock_unsupported"


@pytest.mark.parametrize("major", [10, 11])
def test_pnpm_different_store_formats_are_explicitly_rejected(major):
    with pytest.raises(ToolExecutionError) as rejected:
        pnpm_tarballs(pnpm_lock(9), REGISTRY, str(major) + ".0.0")
    assert rejected.value.code == "pnpm_cache_format_unsupported"


@pytest.mark.parametrize("resolution", [{"type": "git", "integrity": SRI}, {"tarball": "file:fixture", "integrity": SRI}, {"integrity": "sha256-" + base64.b64encode(b"x" * 32).decode()}])
def test_pnpm_non_registry_or_non_sha512_cache_resolutions_fail(resolution):
    with pytest.raises(ToolExecutionError):
        pnpm_tarballs(pnpm_lock(9, resolution=resolution), REGISTRY, "9.15.4")


def test_pnpm_transitive_link_edges_fail_before_acquisition():
    content = yaml.safe_load(pnpm_lock(9))
    content["snapshots"] = {"dep@1.0.0": {"dependencies": {"link": "file:/outside"}}}
    with pytest.raises(ToolExecutionError) as rejected:
        pnpm_tarballs(yaml.safe_dump(content).encode(), REGISTRY, "9.15.4")
    assert rejected.value.code == "dependency_cache_workflow_unsupported"


def test_yaml_and_yarn_large_edge_tables_are_bounded():
    content = yarn_lock() + b"".join(b'    nested "^2.0.0"\n' for _ in range(20000))
    with pytest.raises(ToolExecutionError):
        yarn_tarballs(content, REGISTRY)


@pytest.mark.parametrize("specifier", ["git+https://example.invalid/project", "file:../outside", "npm:alias@1.0.0", "workspace:*", "../outside", "https://example.invalid/pkg.tgz"])
def test_seed_manifest_refuses_non_registry_requests(specifier):
    with pytest.raises(ToolExecutionError):
        seed_manifest({"dependencies": {"dep": specifier}})


def test_seed_manifest_carries_dependencies_without_project_execution_metadata():
    result = seed_manifest({"dependencies": {"dep": "^1.0.0"}, "devDependencies": {"dev": "1.0.0"}, "optionalDependencies": {"opt": "~1.0.0"}, "scripts": {"preinstall": "fixture"}, "bin": "fixture.js", "packageManager": "fixture"})
    assert set(result) == {"name", "version", "private", "dependencies", "devDependencies", "optionalDependencies"}


def test_seed_manifest_preserves_optional_peer_requests():
    result = seed_manifest({"peerDependencies": {"dep": "^1.0.0"}, "peerDependenciesMeta": {"dep": {"optional": True}}})
    assert result["peerDependencies"] == {"dep": "^1.0.0"}
    assert result["peerDependenciesMeta"] == {"dep": {"optional": True}}


def test_project_metadata_fifo_is_rejected_without_blocking(tmp_path):
    os.mkfifo(tmp_path / "package.json")
    with pytest.raises(ToolExecutionError) as rejected:
        checked_json(tmp_path / "package.json")
    assert rejected.value.code == "executor_project_metadata_rejected"


@pytest.mark.parametrize("name,lock", [("yarn", "yarn.lock"), ("pnpm", "pnpm-lock.yaml")])
def test_fixed_manager_seed_uses_official_cli_ignore_scripts_and_cleans_seed(tmp_path, monkeypatch, name, lock):
    work, dependencies = tmp_path / "work", tmp_path / "dependencies"
    work.mkdir()
    dependencies.mkdir()
    (dependencies / "package.json").write_text(json.dumps(seed_manifest({"dependencies": {"dep": "1.0.0"}})))
    (dependencies / lock).write_text("frozen fixture lock")
    (dependencies / "index.json").write_text('[{"file":"mirror/dep-1.0.0.tgz"}]')
    monkeypatch.setattr(runner, "ROOT", work)
    monkeypatch.setattr(runner, "Path", lambda value: dependencies if str(value) == "/dependencies" else dependencies / str(value).removeprefix("/dependencies/") if str(value).startswith("/dependencies/") else tmp_path / "yarnrc" if str(value) == "/tmp/gate-yarnrc" else Path(value))
    monkeypatch.setattr(runner, "tool_probe", lambda request: {"returncode": 0, "package_manager_version": request["version"]})
    calls = []
    def execute(argv, *, cwd, **kwargs):
        calls.append(argv)
        assert cwd == work / "seed"
        assert "scripts" not in json.loads((cwd / "package.json").read_text())
        assert (cwd / lock).read_text() == "frozen fixture lock"
        return 0
    monkeypatch.setattr(runner, "execute", execute)
    result = runner.seed_manager({"kind": name + "_seed", "manager": name, "version": "1.22.22" if name == "yarn" else "9.15.4"})
    assert result["returncode"] == 0
    assert not (work / "seed").exists()
    assert all(call[0] == "/usr/local/bin/node" and call[1] == "/tool/package/" + runner.TOOL_BINS[name] and "--offline" in call for call in calls)
    assert "--frozen-lockfile" in calls[-1] and "--ignore-scripts" in calls[-1]
    if name == "pnpm":
        assert calls[0][2:4] == ["store", "add"]
        assert calls[0][-1] == "/dependencies/mirror/dep-1.0.0.tgz"
    else:
        assert '"/dependencies/mirror"' in (tmp_path / "yarnrc").read_text()


@pytest.mark.parametrize("name,version,lockfile", [("yarn", "1.22.22", "yarn.lock"), ("pnpm", "8.15.9", "pnpm-lock.yaml"), ("pnpm", "9.15.4", "pnpm-lock.yaml")])
def test_selected_lock_is_checked_after_frozen_install(tmp_path, name, version, lockfile):
    (tmp_path / "package.json").write_text('{"name":"fixture"}')
    content = b"frozen"
    (tmp_path / lockfile).write_bytes(content)
    manager = {"name": name, "version": version, "lockfile": lockfile, "lockfile_sha256": hashlib.sha256(content).hexdigest()}
    project_policy(tmp_path, manager, install=True)
    (tmp_path / lockfile).write_bytes(b"changed")
    with pytest.raises(ToolExecutionError) as rejected:
        project_policy(tmp_path, manager, install=True)
    assert rejected.value.code == "dependency_lock_changed"

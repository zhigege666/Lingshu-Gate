"""Offline, bounded artifact export checks; no sandbox or runtime is started."""

from __future__ import annotations

import os

import pytest

from lingshu_gate.git_source import digest_json, verify_git_snapshot
from lingshu_gate.network_artifact import export_network_artifact


def export(source, target, **options):
    target.mkdir(exist_ok=True)
    return export_network_artifact(source, target, ignored={".git"}, forbidden_values=["synthetic-proxy-secret"], cancelled=lambda: False, **options)


def test_regular_files_and_relative_internal_package_links_remain_contained(tmp_path):
    source, target = tmp_path / "source", tmp_path / "artifact"
    (source / "node_modules" / ".pnpm").mkdir(parents=True)
    (source / "node_modules" / ".pnpm" / "package.js").write_text("export {};")
    (source / "node_modules" / "package.js").symlink_to(".pnpm/package.js")
    result = export(source, target)
    assert result["bytes"] == len("export {};")
    assert (target / "node_modules" / "package.js").resolve().is_relative_to(target)


@pytest.mark.parametrize("kind", ["absolute", "outside", "cycle", "ignored"])
def test_artifact_links_cannot_escape_or_copy_host_files(tmp_path, kind):
    source, target = tmp_path / "source", tmp_path / "artifact"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private-host-data")
    (source / ".git").mkdir()
    (source / ".git" / "private").write_text("hidden")
    links = {"absolute": str(outside), "outside": "../outside", "cycle": "link", "ignored": ".git/private"}
    (source / "link").symlink_to(links[kind])
    with pytest.raises(ValueError, match="network_artifact_link_rejected"):
        export(source, target)


def test_artifact_scan_cross_chunk_network_value_is_rejected(tmp_path):
    source, target = tmp_path / "source", tmp_path / "artifact"
    source.mkdir()
    (source / "file").write_bytes(b"x" * (1024 * 1024 - 5) + b"synthetic-proxy-secret")
    with pytest.raises(ValueError, match="network_artifact_secret_rejected"):
        export(source, target)


def test_artifact_size_file_count_cancel_and_timeout_bounds(tmp_path):
    source, target = tmp_path / "source", tmp_path / "artifact"
    source.mkdir()
    (source / "file").write_bytes(b"12345")
    with pytest.raises(ValueError, match="size_limit"):
        export(source, target, limits={"files": 2, "bytes": 4, "seconds": 30})
    os.unlink(target / "file")
    with pytest.raises(ValueError, match="file_limit"):
        export(source, target, limits={"files": 0, "bytes": 10, "seconds": 30})
    with pytest.raises(TimeoutError, match="network_artifact_timeout"):
        export(source, target, limits={"files": 2, "bytes": 10, "seconds": -1})
    with pytest.raises(InterruptedError):
        export_network_artifact(source, target, ignored=set(), forbidden_values=[], cancelled=lambda: True)


@pytest.mark.parametrize("change", ["content", "addition", "removal", "link", "inventory"])
def test_git_snapshot_drift_blocks_fixed_commit_reuse(tmp_path, change):
    import hashlib
    from lingshu_gate.registry import ToolExecutionError
    content = b"original"
    (tmp_path / "index.js").write_bytes(content)
    inventory = [{"path": "index.js", "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}]
    upload = {"root_dir": str(tmp_path), "analysis": {"git_source": {"project_root": "."}, "included_files": inventory, "file_list_sha256": digest_json(inventory)}}
    verify_git_snapshot(upload)
    if change == "content":
        (tmp_path / "index.js").write_bytes(b"modified")
    if change == "addition":
        (tmp_path / "extra.js").write_bytes(b"new")
    if change == "removal":
        (tmp_path / "index.js").unlink()
    if change == "link":
        (tmp_path / "link").symlink_to("index.js")
    if change == "inventory":
        upload["analysis"]["file_list_sha256"] = "0" * 64
    with pytest.raises(ToolExecutionError) as rejected:
        verify_git_snapshot(upload)
    assert rejected.value.code == "git_snapshot_changed"

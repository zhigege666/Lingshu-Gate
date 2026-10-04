"""New writes must not silently disable incompatible process restart flags."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from lingshu_gate.config import Settings
from lingshu_gate.mcp_config_store import McpConfigConflict, McpConfigStore
from lingshu_gate.mcp_manifest import (
    McpServerManifest,
    validate_manifest_for_write,
)
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest


def _external() -> dict[str, Any]:
    return {
        "id": "edit-consistency",
        "enabled": False,
        "launch": {"type": "external"},
        "transport": {
            "type": "streamable_http",
            "endpoint": "https://synthetic.example.test/mcp",
        },
        "auto_start": False,
    }


@pytest.mark.parametrize("flag", [True, "true", 1])
def test_write_and_precheck_reject_the_same_unsupported_restart_flags(
    tmp_path: Path, flag: Any,
) -> None:
    payload = _external()
    payload["restart_policy"] = {
        "enabled": flag,
        "health_check": {"enabled": flag},
    }
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d")
    store = McpConfigStore(settings.config_dir)
    with pytest.raises(ValueError, match="restart_policy.enabled"):
        store.save_config(payload)
    assert not list(settings.config_dir.glob("*.yaml"))

    result = validate_mcp_manifest(settings, store, payload)
    assert result["ok"] is False
    assert result["can_apply"] is False
    errors = {check["name"] for check in result["checks"] if check["severity"] == "error"}
    assert errors == {"restart_policy.enabled", "restart_policy.health_check.enabled"}
    assert not any(check["name"].startswith("restart_policy") and check["severity"] == "ok" for check in result["checks"])
    assert payload["restart_policy"]["enabled"] == flag


def test_failed_edit_preserves_saved_bytes_and_enabled_value(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path)
    original = _external()
    store.save_config(original)
    path = tmp_path / "edit-consistency.yaml"
    before = path.read_bytes()
    edited = {**original, "enabled": True, "restart_policy": {"enabled": True}}
    with pytest.raises(ValueError, match="Unsupported runtime settings"):
        store.save_config(edited, overwrite=True)
    assert path.read_bytes() == before
    assert store.load_manifest(original["id"]).enabled is False


@pytest.mark.parametrize("enabled", [False, True])
def test_enabled_round_trips_without_enabling_or_starting_other_settings(
    tmp_path: Path, enabled: bool,
) -> None:
    store = McpConfigStore(tmp_path)
    payload = {**_external(), "enabled": enabled, "restart_policy": {"enabled": False, "health_check": {"enabled": False}}}
    store.save_config(payload)
    saved = store.load_manifest(payload["id"])
    assert saved.enabled is enabled
    assert saved.auto_start is False
    assert saved.restart_policy.enabled is False
    assert saved.restart_policy.health_check.enabled is False


def test_legacy_read_normalization_remains_readable_without_rewriting_history(tmp_path: Path) -> None:
    payload = {**_external(), "restart_policy": {"enabled": True, "health_check": {"enabled": True}}}
    path = tmp_path / "edit-consistency.json"
    text = json.dumps(payload)
    path.write_text(text)
    loaded = McpConfigStore(tmp_path).load_manifest(payload["id"])
    assert loaded.restart_policy.enabled is False
    assert loaded.restart_policy.health_check.enabled is False
    assert path.read_text() == text
    assert McpServerManifest.model_validate(payload).restart_policy.enabled is False


def test_managed_http_restart_policy_is_supported_without_altering_the_draft() -> None:
    payload = {**_external(), "launch": {"type": "managed_process", "command": "synthetic-server"}, "restart_policy": {"enabled": True, "health_check": {"enabled": True}}}
    validated = validate_manifest_for_write(payload)
    assert validated.restart_policy.enabled is True
    assert validated.restart_policy.health_check.enabled is True


def test_unknown_draft_fields_still_fail_the_persistence_schema() -> None:
    with pytest.raises(ValueError):
        validate_manifest_for_write({**_external(), "synthetic_unknown": {"flag": False}})


def test_stale_config_digest_cannot_replace_an_explicit_startup_policy(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path)
    original = store.save_config(_external())
    assert original.digest
    current = store.save_config({**_external(), "auto_start": True, "startup_policy": "gate_start_v1"}, overwrite=True, expected_digest=original.digest)
    with pytest.raises(McpConfigConflict):
        store.save_config({**_external(), "name": "Stale edit"}, overwrite=True, expected_digest=original.digest)
    assert store.get_config(original.id).digest == current.digest
    assert store.load_manifest(original.id).startup_policy == "gate_start_v1"


def test_edit_snapshot_digest_matches_the_manifest_during_atomic_replacement(tmp_path: Path) -> None:
    store = McpConfigStore(tmp_path)
    store.save_config({**_external(), "name": "Before"})
    path = tmp_path / "edit-consistency.yaml"
    original = path.read_bytes()
    read_bytes = Path.read_bytes

    def replace_after_open(opened: Path) -> bytes:
        content = read_bytes(opened)
        if opened == path:
            path.write_bytes(original.replace(b"name: Before", b"name: After"))
        return content

    # Replace during the snapshot read, after the independent ID lookup.
    with patch.object(store, "_find_path", return_value=path), patch.object(Path, "read_bytes", replace_after_open):
        snapshot = store.get_config("edit-consistency")
    assert snapshot.manifest["name"] == "Before"
    assert snapshot.digest == hashlib.sha256(original).hexdigest()
    with pytest.raises(McpConfigConflict):
        store.save_config({**_external(), "name": "Stale edit"}, overwrite=True, expected_digest=snapshot.digest)


@pytest.mark.parametrize("operation", ["get", "load", "save", "delete"])
def test_symlinked_configuration_cannot_read_or_replace_a_sibling_directory(
    tmp_path: Path, operation: str,
) -> None:
    config_dir = tmp_path / "mcp.d"
    config_dir.mkdir()
    # The sibling deliberately shares the root's lexical prefix.
    outside_dir = tmp_path / "mcp.d-outside"
    outside_dir.mkdir()
    outside = outside_dir / "edit-consistency.yaml"
    outside.write_text(json.dumps({**_external(), "name": "Outside configuration"}))
    original = outside.read_bytes()
    linked = config_dir / outside.name
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this test host")
    store = McpConfigStore(config_dir)
    read_bytes = Path.read_bytes

    def reject_external_read(path: Path) -> bytes:
        assert path.resolve().parent == config_dir, "outside configuration content was read"
        return read_bytes(path)

    with patch.object(Path, "read_bytes", reject_external_read), pytest.raises(ValueError, match="direct file in config_dir"):
        if operation == "get":
            store.get_config("edit-consistency")
        elif operation == "load":
            store.load_manifest("edit-consistency")
        elif operation == "save":
            store.save_config({**_external(), "name": "Replacement"}, overwrite=True,
                              expected_digest=hashlib.sha256(original).hexdigest())
        else:
            store.delete_config("edit-consistency")
    assert outside.read_bytes() == original
    assert linked.is_symlink()
    listing = store.list_configs()
    assert listing.configs == []
    assert len(listing.errors) == 1
    assert "Outside configuration" not in listing.errors[0]


@pytest.mark.parametrize("server_id", ["../outside", "nested/server", "nested\\server", "/outside", "invalid\n"])
def test_server_id_validation_rejects_path_characters_before_lookup(tmp_path: Path, server_id: str) -> None:
    store = McpConfigStore(tmp_path)
    with patch.object(store, "_find_path", side_effect=AssertionError("invalid ID reached lookup")):
        for operation in (store.get_config, store.load_manifest, store.delete_config):
            with pytest.raises(ValueError, match="server_id must match"):
                operation(server_id)
        with pytest.raises(ValueError, match="server_id must match"):
            store.save_config({**_external(), "id": server_id})


def test_config_directory_symlink_and_legacy_filename_remain_supported(tmp_path: Path) -> None:
    actual = tmp_path / "actual-configs"
    actual.mkdir()
    config_dir = tmp_path / "mcp.d"
    try:
        config_dir.symlink_to(actual, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this test host")
    path = actual / "legacy saved config.json"
    path.write_text(json.dumps(_external()))
    store = McpConfigStore(config_dir)
    current = store.get_config("edit-consistency")
    updated = store.save_config({**_external(), "name": "Saved"}, overwrite=True, expected_digest=current.digest)
    assert updated.format == "json"
    assert json.loads(path.read_text())["name"] == "Saved"
    store.delete_config("edit-consistency")
    assert not path.exists()

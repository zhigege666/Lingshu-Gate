"""Versioned Gate startup policy and legacy runtime intent compatibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.registry import ToolRegistry


def _setup(tmp_path: Path) -> tuple[Settings, McpConfigStore, McpRuntimeStateStore]:
    settings = Settings(config_dir=tmp_path / "mcp.d", data_dir=tmp_path / "data", allowed_root=tmp_path, db_url=f"sqlite:///{tmp_path / 'data' / 'gate.db'}")
    return settings, McpConfigStore(settings.config_dir), McpRuntimeStateStore(SQLiteDatabase(settings.db_url, settings.data_dir))


def _manifest(*, external: bool, auto_start: bool, enabled: bool = True, policy: str = "gate_start_v1") -> dict[str, Any]:
    return {
        "id": "synthetic-startup",
        "enabled": enabled,
        "launch": {"type": "external"} if external else {"type": "managed_process", "command": "synthetic-server"},
        "transport": {"type": "streamable_http", "endpoint": "https://synthetic.example.test/mcp"} if external else {"type": "stdio"},
        "auto_start": auto_start,
        "startup_policy": policy,
    }


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("auto_start", [False, True])
def test_new_policy_uses_the_switch_at_next_boot_despite_opposite_saved_intent(
    tmp_path: Path, external: bool, auto_start: bool,
) -> None:
    settings, store, states = _setup(tmp_path)
    store.save_config(_manifest(external=external, auto_start=auto_start))
    states.set("synthetic-startup", "stopped" if auto_start else "running", source="user")
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    status = manager.get_server("synthetic-startup")
    assert status.desired_state == ("running" if auto_start else "stopped")
    assert status.desired_state_source == "gate_start_policy"
    with patch.object(manager, "start_server") as start:
        manager.reconcile_desired_states()
    if auto_start:
        start.assert_called_once_with("synthetic-startup")
    else:
        start.assert_not_called()


@pytest.mark.parametrize("external", [False, True])
def test_manual_stop_controls_current_runtime_but_not_next_boot(tmp_path: Path, external: bool) -> None:
    settings, store, states = _setup(tmp_path)
    store.save_config(_manifest(external=external, auto_start=True))
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    with patch.object(manager, "stop_server", side_effect=lambda server_id: manager.get_server(server_id)):
        manager.request_stop("synthetic-startup")
    with patch.object(manager, "start_server") as start:
        manager.reconcile_desired_states()
    start.assert_not_called()
    assert manager.get_server("synthetic-startup").desired_state == "stopped"
    assert store.load_manifest("synthetic-startup").auto_start is True
    restarted = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    restarted.load_manifests()
    assert restarted.get_server("synthetic-startup").desired_state == "running"


def test_saving_startup_policy_alone_leaves_current_runtime_and_intent_unchanged(tmp_path: Path) -> None:
    settings, store, states = _setup(tmp_path)
    payload = _manifest(external=True, auto_start=False, policy="legacy_restore")
    store.save_config(payload)
    states.set("synthetic-startup", "stopped", source="user")
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    before = states.get("synthetic-startup")
    store.save_config({**payload, "auto_start": True, "startup_policy": "gate_start_v1"}, overwrite=True)
    assert states.get("synthetic-startup") == before
    assert manager.get_server("synthetic-startup").desired_state == "stopped"
    with patch.object(manager, "start_server") as start:
        manager.reconcile_desired_states()
    start.assert_not_called()
    restarted = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    restarted.load_manifests()
    assert restarted.get_server("synthetic-startup").desired_state == "running"


@pytest.mark.parametrize("external", [False, True])
def test_disabled_has_precedence_over_enabled_startup_policy(tmp_path: Path, external: bool) -> None:
    settings, store, states = _setup(tmp_path)
    store.save_config(_manifest(external=external, auto_start=True, enabled=False))
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    with patch.object(manager, "start_server") as start:
        manager.reconcile_desired_states()
    start.assert_not_called()
    assert manager.get_server("synthetic-startup").effective_should_run is False
    assert manager.get_server("synthetic-startup").desired_state == "stopped"


def test_external_startup_only_connects_and_never_constructs_a_managed_process(tmp_path: Path) -> None:
    settings, store, states = _setup(tmp_path)
    store.save_config(_manifest(external=True, auto_start=True))
    client = Mock()
    client.list_tools.return_value = []
    client.pid = None
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    with patch("lingshu_gate.mcp_runtime.StreamableHttpMcpClient", return_value=client) as http, patch("lingshu_gate.mcp_runtime.StdioMcpClient") as stdio, patch("lingshu_gate.mcp_runtime.ManagedHttpMcpClient") as managed:
        manager.reconcile_desired_states()
    http.assert_called_once()
    client.start.assert_called_once()
    stdio.assert_not_called()
    managed.assert_not_called()


def test_name_or_endpoint_edits_do_not_migrate_legacy_policy(tmp_path: Path) -> None:
    settings, store, states = _setup(tmp_path)
    payload = _manifest(external=True, auto_start=False, policy="legacy_restore")
    payload.pop("startup_policy")
    store.save_config(payload)
    states.set("synthetic-startup", "running", source="user")
    updated = store.load_manifest("synthetic-startup").model_dump(mode="json", exclude={"manifest_path"})
    updated["name"] = "Renamed synthetic service"
    updated["transport"]["endpoint"] = "https://other.example.test/mcp"
    store.save_config(updated, overwrite=True)
    assert store.load_manifest("synthetic-startup").startup_policy == "legacy_restore"
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    assert manager.get_server("synthetic-startup").desired_state == "running"
    assert manager.get_server("synthetic-startup").desired_state_source == "user"


def test_explicit_in_process_reload_keeps_the_current_manual_stop(tmp_path: Path) -> None:
    settings, store, states = _setup(tmp_path)
    store.save_config(_manifest(external=True, auto_start=True))
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    with patch.object(manager, "stop_server", side_effect=lambda server_id: manager.get_server(server_id)):
        manager.request_stop("synthetic-startup")
    with patch.object(manager, "start_server") as start:
        manager.reload_manifests()
    start.assert_not_called()
    assert manager.get_server("synthetic-startup").desired_state == "stopped"


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("stored_intent", [None, "running"])
def test_new_service_saved_after_boot_waits_for_explicit_start_or_next_boot(
    tmp_path: Path, external: bool, stored_intent: str | None,
) -> None:
    settings, store, states = _setup(tmp_path)
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    store.save_config(_manifest(external=external, auto_start=True))
    if stored_intent:
        states.set("synthetic-startup", "running", source="user")
    before = states.get("synthetic-startup")

    with patch.object(manager, "start_server", side_effect=lambda server_id: manager.get_server(server_id)) as start:
        manager.reload_manifests()
        start.assert_not_called()
        assert manager.get_server("synthetic-startup").desired_state == "stopped"
        assert states.get("synthetic-startup") == before
        manager.request_start("synthetic-startup")
        start.assert_called_once_with("synthetic-startup")
    assert manager.get_server("synthetic-startup").desired_state == "running"

    restarted = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    restarted.load_manifests()
    with patch.object(restarted, "start_server") as start_at_boot:
        restarted.reconcile_desired_states()
    start_at_boot.assert_called_once_with("synthetic-startup")
    assert restarted.get_server("synthetic-startup").desired_state_source == "gate_start_policy"


@pytest.mark.parametrize("auto_start", [False, True])
def test_legacy_new_service_reload_retains_manifest_default(tmp_path: Path, auto_start: bool) -> None:
    settings, store, states = _setup(tmp_path)
    manager = McpRuntimeManager(settings, ToolRegistry(), state_store=states)
    manager.load_manifests()
    store.save_config(_manifest(external=False, auto_start=auto_start, policy="legacy_restore"))
    with patch.object(manager, "start_server") as start:
        manager.reload_manifests()
    if auto_start:
        start.assert_called_once_with("synthetic-startup")
    else:
        start.assert_not_called()
    assert manager.get_server("synthetic-startup").desired_state_source == "manifest_default"

"""新建自启默认值与已有配置、显式关闭的兼容边界。"""
from __future__ import annotations

import json
import sys
from unittest.mock import Mock

import pytest

from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import McpConfigSaveRequest
from lingshu_gate.user_credential_store import UserCredentialStore


def _manifest(launch_type: str = "external") -> dict:
    if launch_type == "external":
        return {"id": "autostart-default", "launch": {"type": "external"},
                "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}}
    return {"id": "autostart-default", "launch": {"type": "managed_process", "command": sys.executable},
            "transport": {"type": "stdio"}}


@pytest.mark.parametrize("launch_type", ["external", "managed_process"])
def test_new_config_defaults_to_gate_start_without_mutating_request(tmp_path, launch_type):
    store = McpConfigStore(tmp_path)
    supplied = _manifest(launch_type)
    saved = store.save_config(supplied)
    assert saved.manifest["auto_start"] is True
    assert saved.manifest["startup_policy"] == "gate_start_v1"
    assert "auto_start" not in supplied and "startup_policy" not in supplied


@pytest.mark.parametrize("flags", [
    {"auto_start": False},
    {"auto_start": False, "startup_policy": "gate_start_v1"},
    {"startup_policy": "legacy_restore"},
])
def test_new_config_preserves_explicit_off_or_legacy_policy(tmp_path, flags):
    saved = McpConfigStore(tmp_path).save_config({**_manifest(), **flags})
    assert saved.manifest["auto_start"] is False
    if "startup_policy" in flags:
        assert saved.manifest["startup_policy"] == flags["startup_policy"]


def test_disabled_new_config_remains_disabled(tmp_path):
    saved = McpConfigStore(tmp_path).save_config({**_manifest(), "enabled": False})
    assert saved.manifest["enabled"] is False
    assert saved.manifest["auto_start"] is True


def test_old_file_read_and_ordinary_edit_keep_legacy_startup(tmp_path):
    raw = _manifest()
    path = tmp_path / "autostart-default.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    store = McpConfigStore(tmp_path)
    before = store.get_config(raw["id"])
    assert before.manifest["auto_start"] is False
    assert before.manifest["startup_policy"] == "legacy_restore"
    assert json.loads(path.read_text(encoding="utf-8")) == raw
    saved = store.save_config({**raw, "name": "普通名称编辑"}, overwrite=True, expected_digest=before.digest)
    assert saved.manifest["auto_start"] is False
    assert saved.manifest["startup_policy"] == "legacy_restore"


def test_create_preparation_and_save_agree_without_applying_runtime(tmp_path):
    store = McpConfigStore(tmp_path)
    runtime = Mock(spec=McpRuntimeManager)
    credentials = Mock(spec=UserCredentialStore)
    service = McpConfigurationService(store, runtime, credentials)
    request = McpConfigSaveRequest(manifest=_manifest(), apply=False, start=False)
    prepared = service.prepare_user_credentials(request)
    assert prepared.manifest.auto_start is True
    assert prepared.manifest.startup_policy == "gate_start_v1"
    result = service.create(request, user_id="synthetic-user", prepared=prepared)
    assert result.config.manifest["auto_start"] is True
    assert result.server is None
    runtime.apply_manifest.assert_not_called()


def test_existing_preparation_does_not_take_creation_defaults(tmp_path):
    raw = _manifest()
    (tmp_path / "autostart-default.json").write_text(json.dumps(raw), encoding="utf-8")
    service = McpConfigurationService(
        McpConfigStore(tmp_path), Mock(spec=McpRuntimeManager), Mock(spec=UserCredentialStore),
    )
    prepared = service.prepare_user_credentials(
        McpConfigSaveRequest(manifest=raw), existing_server_id=raw["id"],
    )
    assert prepared.manifest.auto_start is False
    assert prepared.manifest.startup_policy == "legacy_restore"

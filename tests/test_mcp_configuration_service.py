"""Compensation failure tests for MCP configuration application workflows."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import (
    McpConfigResponse,
    McpConfigSaveRequest,
    McpServerStatusResponse,
)
from lingshu_gate.user_credential_store import UserCredentialStore


def _request(server_id: str = "compensation-test") -> McpConfigSaveRequest:
    return McpConfigSaveRequest(
        manifest={
            "id": server_id,
            "enabled": True,
            "launch": {"type": "external"},
            "transport": {
                "type": "streamable_http",
                "endpoint": "https://service.example.test/mcp",
            },
            "auto_start": False,
        },
        apply=True,
        start=False,
    )


def _service() -> tuple[
    McpConfigurationService,
    Mock,
    Mock,
    Mock,
]:
    config_store = Mock(spec=McpConfigStore)
    runtime = Mock(spec=McpRuntimeManager)
    user_credential_store = Mock(spec=UserCredentialStore)
    service = McpConfigurationService(
        config_store,
        runtime,
        user_credential_store,
    )
    return service, config_store, runtime, user_credential_store


def _config(server_id: str = "compensation-test") -> McpConfigResponse:
    return McpConfigResponse(
        id=server_id,
        path=f"/config/{server_id}.yaml",
        manifest={"id": server_id},
    )


def test_create_reports_disk_compensation_failure() -> None:
    service, config_store, runtime, user_credential_store = _service()
    request = _request()
    prepared = service.prepare_user_credentials(request)
    config_store.save_config.return_value = _config()
    config_store.load_manifest.return_value = prepared.manifest
    runtime.apply_manifest.side_effect = RuntimeError("apply failed")
    config_store.delete_config.side_effect = OSError("disk rollback failed")

    with pytest.raises(RuntimeError, match="disk rollback failed") as raised:
        service.create(request, user_id="user-1", prepared=prepared)

    assert str(raised.value.__cause__) == "apply failed"
    user_credential_store.save_binding.assert_not_called()


def test_update_reports_manifest_compensation_failure() -> None:
    service, config_store, runtime, user_credential_store = _service()
    request = _request()
    prepared = service.prepare_user_credentials(request)
    config_store.load_manifest.side_effect = [prepared.manifest, prepared.manifest]
    config_store.save_config.side_effect = [
        _config(),
        OSError("manifest restore failed"),
    ]
    runtime.apply_manifest.side_effect = RuntimeError("apply failed")

    with pytest.raises(RuntimeError, match="manifest restore failed") as raised:
        service.update(
            prepared.manifest.id,
            request,
            user_id="user-1",
            prepared=prepared,
        )

    assert str(raised.value.__cause__) == "apply failed"
    user_credential_store.save_binding.assert_not_called()


def test_delete_reports_runtime_compensation_failure() -> None:
    service, config_store, runtime, _ = _service()
    request = _request()
    prepared = service.prepare_user_credentials(request)
    server_id = prepared.manifest.id
    config_store.load_manifest.return_value = prepared.manifest
    config_store.delete_config.side_effect = OSError("disk delete failed")
    runtime.has_server.return_value = True
    runtime.get_server.return_value = McpServerStatusResponse(
        id=server_id,
        enabled=True,
        launch_type="external",
        transport_type="streamable_http",
        status="external",
        desired_state="stopped",
    )
    runtime.apply_manifest.side_effect = RuntimeError("runtime restore failed")

    with pytest.raises(RuntimeError, match="runtime restore failed") as raised:
        service.delete(server_id)

    assert str(raised.value.__cause__) == "disk delete failed"


def test_apply_registers_manifest_without_starting_it() -> None:
    service, config_store, runtime, _ = _service()
    request = _request()
    prepared = service.prepare_user_credentials(request)
    config_store.get_config.return_value = _config()
    config_store.load_manifest.return_value = prepared.manifest
    runtime.apply_manifest.return_value = McpServerStatusResponse(
        id=prepared.manifest.id,
        enabled=True,
        launch_type="external",
        transport_type="streamable_http",
        status="external",
    )

    service.apply(prepared.manifest.id)

    runtime.apply_manifest.assert_called_once_with(
        prepared.manifest,
        start=False,
        source="config_apply",
    )

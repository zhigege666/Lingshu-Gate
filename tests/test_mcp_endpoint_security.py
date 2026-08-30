"""Outbound MCP endpoint validation and disclosure-boundary tests."""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.endpoint_security import REDACTED_ENDPOINT
from lingshu_gate.logging import JsonFormatter
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_http_client import McpHttpAuthenticationError
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from lingshu_gate.mcp_runtime import McpServerRuntime
from lingshu_gate.models import McpConfigSaveRequest
from lingshu_gate.observability_store import ObservabilityStore


def _manifest(endpoint: str, *, server_id: str = "endpoint-security") -> dict[str, object]:
    return {
        "id": server_id,
        "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": endpoint},
        "auto_start": False,
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://service.example.test/mcp",
        "http://localhost:3100/mcp",
        "http://127.0.0.1:3100/mcp",
        "http://127.255.255.254/mcp",
        "http://[::1]:3100/mcp",
    ],
)
def test_streamable_http_accepts_https_and_loopback_http(endpoint: str) -> None:
    manifest = McpServerManifest.model_validate(_manifest(endpoint))

    assert manifest.transport.endpoint == endpoint


@pytest.mark.parametrize(
    ("endpoint", "expected_message"),
    [
        ("ftp://service.example.test/mcp", "scheme must be http or https"),
        ("http://service.example.test/mcp", "must use HTTPS"),
        ("http://localhost.example.test/mcp", "must use HTTPS"),
        ("http://127.1/mcp", "must use HTTPS"),
        ("https://user:private-password@service.example.test/mcp", "must not include user information"),
        ("https://service.example.test/mcp?token=private-token", "must not include a query"),
        ("https://service.example.test/mcp#private-fragment", "must not include a fragment"),
        ("https://service.example.test:0/mcp", "port must be between"),
        ("https://service.example.test/%0aheader", "path contains an unsupported character"),
        ("https://service.example.test/bad\\path", "contains an unsupported character"),
    ],
)
def test_streamable_http_rejects_unsafe_endpoint_without_echoing_input(
    endpoint: str,
    expected_message: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        McpServerManifest.model_validate(_manifest(endpoint))

    error_text = str(raised.value)
    assert expected_message in error_text
    assert endpoint not in error_text
    assert "private-password" not in error_text
    assert "private-token" not in error_text
    assert "private-fragment" not in error_text


def test_endpoint_assignment_error_hides_rejected_value() -> None:
    manifest = McpServerManifest.model_validate(
        _manifest("https://service.example.test/mcp")
    )
    endpoint = "https://user:private-password@service.example.test/mcp"

    with pytest.raises(ValidationError) as raised:
        manifest.transport.endpoint = endpoint

    assert endpoint not in str(raised.value)
    assert "private-password" not in str(raised.value)


def test_validation_response_drops_rejected_url_and_pydantic_input(tmp_path) -> None:
    endpoint = "https://user:private-password@service.example.test/mcp?token=private-token"
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d")
    result = validate_mcp_manifest(
        settings,
        McpConfigStore(settings.config_dir),
        _manifest(endpoint),
    )
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["ok"] is False
    assert endpoint not in serialized
    assert "private-password" not in serialized
    assert "private-token" not in serialized
    schema_check = next(check for check in result["checks"] if check["name"] == "manifest.schema")
    assert set(schema_check["metadata"]["errors"][0]) == {"type", "loc", "msg"}


def test_config_api_shape_masks_endpoint_and_masked_edit_preserves_disk_value(tmp_path) -> None:
    endpoint = "https://service.example.test/private-path-token"
    store = McpConfigStore(tmp_path / "mcp.d")

    created = store.save_config(_manifest(endpoint), overwrite=False)
    assert created.manifest["transport"]["endpoint"] == REDACTED_ENDPOINT
    assert endpoint not in repr(created.manifest)
    assert store.load_manifest(created.id).transport.endpoint == endpoint

    edited = _manifest(REDACTED_ENDPOINT)
    edited["name"] = "Edited safely"
    updated = store.save_config(edited, expected_id=created.id, overwrite=True)

    assert updated.manifest["transport"]["endpoint"] == REDACTED_ENDPOINT
    assert store.load_manifest(created.id).transport.endpoint == endpoint


def test_configuration_service_restores_mask_before_validating_an_edit(tmp_path) -> None:
    endpoint = "https://service.example.test/private-path-token"
    store = McpConfigStore(tmp_path / "mcp.d")
    created = store.save_config(_manifest(endpoint), overwrite=False)
    service = McpConfigurationService(store, Mock(), Mock())
    request = McpConfigSaveRequest(manifest=_manifest(REDACTED_ENDPOINT))

    prepared = service.prepare_user_credentials(
        request,
        existing_server_id=created.id,
    )

    assert prepared.manifest.transport.endpoint == endpoint


def test_config_store_validation_error_never_returns_rejected_url(tmp_path) -> None:
    endpoint = "https://user:private-password@service.example.test/mcp"
    store = McpConfigStore(tmp_path / "mcp.d")

    with pytest.raises(ValueError) as raised:
        store.save_config(_manifest(endpoint), overwrite=False)

    assert endpoint not in str(raised.value)
    assert "private-password" not in str(raised.value)


def test_runtime_status_and_manifest_safe_dict_mask_endpoint() -> None:
    endpoint = "https://service.example.test/private-path-token"
    manifest = McpServerManifest.model_validate(_manifest(endpoint))
    runtime = McpServerRuntime(
        manifest=manifest,
        last_error=f"Failed to reach {endpoint}",
    )

    status = runtime.to_response()
    assert status.endpoint == REDACTED_ENDPOINT
    assert endpoint not in str(status.last_error)
    assert manifest.safe_dict()["transport"]["endpoint"] == REDACTED_ENDPOINT


def test_observability_and_json_log_boundaries_redact_urls(tmp_path) -> None:
    endpoint = "https://service.example.test/private-path-token"
    store = ObservabilityStore(SQLiteDatabase("", tmp_path))

    log = store.add_log(
        "error",
        f"Failed to reach {endpoint}",
        event_type="gate.mcp.server_start_failed",
        payload={"endpoint": endpoint, "detail": f"retry {endpoint}"},
    )
    event = store.emit_event(
        "gate.mcp.server_start_failed",
        payload={"endpoint": endpoint},
    )
    record = logging.LogRecord(
        "gate.test",
        logging.ERROR,
        __file__,
        1,
        f"Failed to reach {endpoint}",
        (),
        None,
    )
    record.gate_endpoint = endpoint
    formatted = JsonFormatter().format(record)

    assert endpoint not in repr(log)
    assert endpoint not in repr(event)
    assert endpoint not in formatted
    assert log["payload"]["endpoint"] == REDACTED_ENDPOINT
    assert event["payload"]["endpoint"] == REDACTED_ENDPOINT


def test_http_authentication_error_does_not_expose_endpoint() -> None:
    endpoint = "https://service.example.test/private-path-token"
    error = McpHttpAuthenticationError(
        401,
        endpoint,
        f"upstream rejected {endpoint}",
    )

    assert error.endpoint == REDACTED_ENDPOINT
    assert endpoint not in str(error)
    assert "private-path-token" not in str(error)

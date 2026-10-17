"""Blank optional stdio endpoints must not inherit HTTP URL requirements."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from lingshu_gate.config import Settings
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_manifest import McpServerManifest, TransportConfig, validate_manifest_for_write
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from test_external_mcp_configuration import gate as gate


def _stdio(transport: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "synthetic-stdio",
        "name": "Synthetic MCP Server",
        "enabled": True,
        "launch": {"type": "managed_process", "command": "npx", "args": ["-y", "@example/mcp-server"]},
        "transport": {"type": "stdio", **transport},
        "timeout_seconds": 120,
        "permissions": {"default": "read"},
        "startup_policy": "gate_start_v1",
        "auto_start": False,
    }


@pytest.mark.parametrize("transport", [{}, {"endpoint": None}, {"endpoint": ""}, {"endpoint": " \t\r\n"}])
def test_stdio_blank_endpoint_validates_saves_and_reloads_without_mutating_draft(
    tmp_path: Path, transport: dict[str, Any],
) -> None:
    draft = _stdio(transport)
    original = copy.deepcopy(draft)
    (tmp_path / "runtime-cache").mkdir()
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d")
    store = McpConfigStore(settings.config_dir)

    manifest = validate_manifest_for_write(draft)
    assert manifest.transport.endpoint is None
    result = validate_mcp_manifest(settings, store, draft)
    assert result["ok"] is True, result
    assert result["can_apply"] is True, result
    assert not any(check["severity"] == "error" for check in result["checks"])

    saved = store.save_config(draft)
    loaded = store.load_manifest(saved.id)
    assert loaded.transport.type == "stdio"
    assert loaded.transport.endpoint is None
    assert loaded.launch.command == "npx"
    assert loaded.launch.args == original["launch"]["args"]
    assert loaded.auto_start is False
    assert loaded.startup_policy == "gate_start_v1"
    assert draft == original

    edited = {**draft, "name": "Edited synthetic server"}
    assert validate_mcp_manifest(settings, store, edited, expected_id=saved.id)["ok"] is True
    store.save_config(edited, expected_id=saved.id, overwrite=True, expected_digest=saved.digest)
    assert store.load_manifest(saved.id).transport.endpoint is None


@pytest.mark.parametrize("transport", [{}, {"endpoint": None}, {"endpoint": ""}, {"endpoint": " \t\r\n"}])
@pytest.mark.parametrize("launch", [{"type": "external"}, {"type": "managed_process", "command": "synthetic-server"}])
def test_http_still_rejects_blank_endpoint_at_precheck_and_save(
    tmp_path: Path, transport: dict[str, Any], launch: dict[str, Any],
) -> None:
    draft = {**_stdio({}), "launch": launch, "transport": {"type": "streamable_http", **transport}}
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d")
    store = McpConfigStore(settings.config_dir)
    assert validate_mcp_manifest(settings, store, draft)["ok"] is False
    with pytest.raises(ValueError):
        store.save_config(draft)
    assert not list(settings.config_dir.glob("*.yaml"))


@pytest.mark.parametrize("endpoint", ["", " \t\r\n"])
def test_managed_container_stdio_accepts_blank_endpoint(endpoint: str) -> None:
    draft = _stdio({"endpoint": endpoint})
    draft["launch"] = {"type": "managed_container", "image": "example/server@sha256:" + "a" * 64}
    assert McpServerManifest.model_validate(draft).transport.endpoint is None


@pytest.mark.parametrize("endpoint", [False, 0, [], {}])
def test_stdio_does_not_coerce_malformed_endpoint_types(endpoint: Any) -> None:
    with pytest.raises(ValidationError):
        McpServerManifest.model_validate(_stdio({"endpoint": endpoint}))


def test_stdio_endpoint_assignment_normalizes_blank_without_weakening_http_assignment() -> None:
    transport = TransportConfig(type="stdio")
    transport.endpoint = ""
    assert transport.endpoint is None
    transport.endpoint = " \t"
    assert transport.endpoint is None
    transport.endpoint = "https://service.example.test/mcp"
    transport.type = "streamable_http"
    with pytest.raises(ValidationError):
        transport.endpoint = ""
    assert transport.endpoint == "https://service.example.test/mcp"


def test_changing_blank_stdio_transport_to_http_requires_an_endpoint() -> None:
    transport = TransportConfig(type="stdio", endpoint="")
    with pytest.raises(ValidationError, match="transport.endpoint is required"):
        transport.type = "streamable_http"


def test_stdio_http_round_trip_preserves_explicit_http_fields() -> None:
    endpoint = "https://service.example.test/mcp"
    transport = {"endpoint": endpoint, "headers": {"X-Trace": "synthetic"}}
    draft = _stdio(transport)
    assert validate_manifest_for_write(draft).transport.endpoint == endpoint
    http = {**draft, "transport": {**draft["transport"], "type": "streamable_http"}}
    assert validate_manifest_for_write(http).transport.endpoint == endpoint
    assert draft["transport"] == {"type": "stdio", **transport}


def test_authenticated_config_routes_accept_stdio_blank_without_starting(gate, tmp_path: Path) -> None:
    client = gate["client"]
    runtime = gate["app"].state.mcp_runtime
    (tmp_path / "runtime-cache").mkdir(exist_ok=True)
    draft = _stdio({"endpoint": ""})
    request = {"manifest": draft, "apply": False, "start": False}
    path = "/v1/mcp/configs/" + draft["id"]
    with patch.object(runtime, "start_server", side_effect=AssertionError("save must not execute")) as start:
        checked = client.post("/v1/mcp/configs/validate", json=request)
        assert checked.status_code == 200 and checked.json()["ok"], checked.text
        created = client.post("/v1/mcp/configs", json=request)
        assert created.status_code == 200, created.text
        saved = client.get(path).json()
        assert saved["manifest"]["transport"]["type"] == "stdio"
        assert saved["manifest"]["transport"]["endpoint"] is None
        edited = {**request, "manifest": {**draft, "name": "Edited through the API"},
                  "expected_config_digest": saved["digest"]}
        assert client.post(path + "/validate", json=edited).json()["ok"] is True
        assert client.put(path, json=edited).status_code == 200
        current = client.get(path).json()
        invalid = {**edited, "manifest": {**draft, "transport": {"type": "streamable_http", "endpoint": ""}},
                   "expected_config_digest": current["digest"]}
        assert client.post(path + "/validate", json=invalid).json()["ok"] is False
        assert client.put(path, json=invalid).status_code == 400
        assert client.get(path).json()["digest"] == current["digest"]
        start.assert_not_called()
        assert gate["calls"] == []
    client.cookies.clear()
    assert client.post("/v1/mcp/configs", json=request).status_code == 401

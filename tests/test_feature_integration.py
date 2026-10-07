"""Combined application composition; synthetic Native boundary, no host engine."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def main_module(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    for name, directory in (("DATA_DIR", "data"), ("CONFIG_DIR", "config"), ("ALLOWED_ROOT", "projects")):
        monkeypatch.setenv("LINGSHU_GATE_" + name, str(tmp_path / directory))
    monkeypatch.setenv("LINGSHU_GATE_AUTH_ENABLED", "false")
    monkeypatch.setenv("LINGSHU_GATE_LOG_LEVEL", "WARNING")
    from lingshu_gate import main
    return main


@pytest.mark.parametrize("close_unknown", [False, True])
def test_combined_factory_keeps_catalog_groups_oauth_and_delivery_with_native_lifecycle(main_module, close_unknown):
    executor = SimpleNamespace(start=Mock(), close=Mock(side_effect=InterruptedError("fixture DNS outcome unknown") if close_unknown else None), readiness=lambda: {"available": True, "code": "safe_executor_ready", "missing": []})
    with patch.object(main_module, "create_safe_network_executor", return_value=executor):
        app = main_module.create_app()
    state = app.state
    assert state.git_import_service.executor is executor
    assert state.build_deploy_store.safe_network_executor is executor
    assert state.network_settings_store.settings()["executor"]["available"]
    assert state.tool_catalog.group_router is state.mcp_group_router
    assert state.oauth_server.candidate_catalog.index is state.tool_catalog
    migrations = state.database.query_all("SELECT id FROM schema_migrations")
    ids = [str(row["id"]) for row in migrations]
    assert len(ids) == len(set(ids))
    assert {"0012_gate_tool_catalog", "0013_gate_mcp_groups", "0014_gate_mcp_group_requests", "0015_gate_mcp_group_routing", "0016_gate_catalog_group_epoch"} <= set(ids)
    error = pytest.raises(InterruptedError, match="fixture DNS outcome unknown") if close_unknown else None
    with patch.object(state.mcp_runtime, "shutdown", wraps=state.mcp_runtime.shutdown) as runtime_shutdown, patch.object(state.external_mcp_configuration_service, "shutdown", wraps=state.external_mcp_configuration_service.shutdown) as config_shutdown, patch.object(main_module, "log_event", wraps=main_module.log_event) as events:
        try:
            if error is not None:
                with error, TestClient(app) as client:
                    assert client.get("/healthz").status_code == 200
            else:
                with TestClient(app) as client:
                    assert client.get("/healthz").status_code == 200
        finally:
            state.build_deploy_store.executor.shutdown(wait=True)
        executor.start.assert_called_once()
        executor.close.assert_called_once()
        config_shutdown.assert_called_once()
        runtime_shutdown.assert_called_once()
        assert ("gate.shutdown_complete" in {call.args[2] for call in events.call_args_list}) == (not close_unknown)


def test_combined_core_factory_keeps_catalog_and_oauth_without_constructing_native(main_module, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGSHU_GATE_RUNTIME_ROLE", "core")
    monkeypatch.setenv("LINGSHU_GATE_NATIVE_EXECUTOR", json.dumps({"enabled": True, "root": str(tmp_path / "executor"), "image": "registry.example.invalid/executor@sha256:" + "a" * 64}))
    with patch("lingshu_gate.adapters.native_executor.executor.NativeNetworkExecutor", side_effect=AssertionError("Core cannot construct the engine boundary")):
        app = main_module.create_app()
        try:
            with TestClient(app) as client:
                assert client.get("/healthz").status_code == 200
                assert app.state.tool_catalog.group_router is app.state.mcp_group_router
                assert app.state.oauth_server.candidate_catalog.index is app.state.tool_catalog
                assert app.state.git_import_service.executor is None
                assert app.state.build_deploy_store.safe_network_executor is None
                assert app.state.network_settings_store.settings()["executor"]["missing"] == ["core_gateway_only_native_delivery_disabled"]
        finally:
            app.state.build_deploy_store.executor.shutdown(wait=True)

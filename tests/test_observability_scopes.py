"""Real API contracts for permission-scoped operational log/event selectors."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def observability_api(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(key)
    for key, value in {
        "DATA_DIR": str(tmp_path), "CONFIG_DIR": str(tmp_path / "mcp.d"),
        "DB_URL": f"sqlite:///{tmp_path / 'isolated.db'}", "ALLOWED_ROOT": str(tmp_path),
        "AUTH_ENABLED": "true",
    }.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{key}", value)
    from lingshu_gate.main import create_app
    from lingshu_gate.mcp_manifest import McpServerManifest

    with TestClient(create_app()) as client:
        state = client.app.state
        auth, access, records = state.auth_store, state.access_store, state.observability_store
        admin = auth.list_users()[0]
        auth.change_password(admin["id"], "Synthetic-admin-123!")
        operator = auth.create_user(username="scoped-operator", password="Synthetic-pass-123!", role="operator")
        auth.create_user(username="ordinary-reader", password="Synthetic-pass-123!", role="viewer")
        for server_id, name in (("allowed-a", "Allowed Alpha"), ("hidden-b", "Hidden Beta")):
            state.mcp_runtime.apply_manifest(McpServerManifest.model_validate({
                "id": server_id, "name": name,
                "launch": {"type": "managed_process", "command": "synthetic-never-started"},
                "transport": {"type": "stdio"},
            }), start=False)
        for server_id in ("allowed-a", "deleted-allowed"):
            access.save_grant(subject_type="user", subject_id=operator["id"], server_id=server_id,
                permission_type_code="read", created_by=admin["id"])
        access.save_grant(subject_type="user", subject_id=operator["id"], server_id="tool-only",
            tool_id="mcp.tool-only.read", permission_type_code="read", created_by=admin["id"])
        for server_id in ("allowed-a", "deleted-allowed", "hidden-b", "tool-only", "deleted-hidden"):
            records.add_log("info", f"synthetic log {server_id}", server_id=server_id)
            records.emit_event("gate.synthetic.event", subject_type="server", subject_id=server_id,
                               payload={"marker": server_id})
        # A deployment subject is not a service identity. Its explicit server_id is.
        records.emit_event("gate.synthetic.event", subject_type="deployment", subject_id="deployment-not-a-server",
                           payload={"server_id": "allowed-a"})
        records.emit_event("gate.synthetic.event", subject_type="user", subject_id="allowed-a",
                           payload={"marker": "global-private-marker"})
        records.add_log("info", "global-private-marker")
        for index in range(120):
            records.add_log("info", f"hidden-synthetic-{index}", server_id=f"hidden-{index}")
        def login(name):
            client.cookies.clear()
            client.headers.pop("Authorization", None)
            response = client.post("/v1/auth/login", json={"username": name,
                "password": "Synthetic-admin-123!" if name == "admin" else "Synthetic-pass-123!"})
            assert response.status_code == 200, response.text
        yield client, state, operator, login


def test_log_scope_search_count_pagination_and_history_are_authorized_first(observability_api):
    client, state, operator, login = observability_api
    login("scoped-operator")
    response = client.get("/v1/observability/mcp-scopes", params={"limit": 1})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert payload["capabilities"] == {"can_read_all": False, "all_scope": "authorized_services"}
    assert payload["scopes"] == [{"id": "allowed-a", "name": "Allowed Alpha", "availability": "current"}]
    assert client.get("/v1/observability/mcp-scopes", params={"q": "Beta"}).json()["total"] == 0
    assert client.get("/v1/observability/mcp-scopes", params={"q": "Alpha"}).json()["total"] == 1
    assert client.get("/v1/observability/mcp-scopes", params={"offset": 1}).json()["scopes"] == [
        {"id": "deleted-allowed", "name": "deleted-allowed", "availability": "historical"}]
    assert client.get("/v1/observability/mcp-scopes", params={"server_id": "deleted-allowed"}).status_code == 200
    for guessed in ("hidden-b", "deleted-hidden", "tool-only", "does-not-exist", "deployment-not-a-server"):
        response = client.get("/v1/observability/mcp-scopes", params={"server_id": guessed})
        assert response.status_code == 404
        assert response.json() == {"detail": "MCP log scope not found"}


def test_logs_events_and_streams_share_scoped_all_and_exact_contract(observability_api):
    client, state, operator, login = observability_api
    login("scoped-operator")
    for path in ("/v1/logs", "/v1/events", "/v1/logs/stream", "/v1/events/stream"):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert "allowed-a" in response.text and "deleted-allowed" in response.text
        for hidden in ("hidden-b", "deleted-hidden", "global-private-marker", "tool-only", "hidden-synthetic"):
            assert hidden not in response.text
        allowed = client.get(path, params={"server_id": "deleted-allowed"})
        assert allowed.status_code == 200 and "deleted-allowed" in allowed.text
        assert "allowed-a" not in allowed.text
        for server_id in ("hidden-b", "does-not-exist"):
            assert client.get(path, params={"server_id": server_id}).status_code == 404
    event_ids = {item["subject_id"] for item in client.get("/v1/events", params={"server_id": "allowed-a"}).json()["events"]}
    assert "deployment-not-a-server" in event_ids
    assert client.get("/v1/events", params={"subject_id": "hidden-b"}).json()["events"] == []
    assert client.get("/v1/logs", params={"keyword": "hidden-synthetic"}).json()["logs"] == []


def test_regular_user_cannot_observe_management_logs_or_options(observability_api):
    client, state, operator, login = observability_api
    login("ordinary-reader")
    for path in ("/v1/observability/mcp-scopes", "/v1/logs", "/v1/events", "/v1/logs/stream", "/v1/events/stream"):
        assert client.get(path).status_code == 403


def test_admin_global_capability_and_token_scope_ceiling(observability_api):
    client, state, operator, login = observability_api
    login("admin")
    options = client.get("/v1/observability/mcp-scopes").json()
    assert options["capabilities"] == {"can_read_all": True, "all_scope": "global"}
    assert options["total"] == 125
    assert "global-private-marker" in client.get("/v1/logs", params={"limit": 500}).text
    assert "global-private-marker" in client.get("/v1/events").text
    token = client.post("/v1/auth/tokens", json={"name": "scoped-operations", "scopes": ["operations.manage"]}).json()
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token['token']}"
    assert client.get("/v1/observability/mcp-scopes").json()["capabilities"]["can_read_all"] is False
    assert "global-private-marker" not in client.get("/v1/logs", params={"limit": 500}).text
    assert "global-private-marker" not in client.get("/v1/events").text


def test_scope_revocation_applies_to_next_request_and_global_capability_is_explicit(observability_api):
    client, state, operator, login = observability_api
    login("scoped-operator")
    for grant in state.access_store.list_grants(subject_type="user", subject_id=operator["id"]):
        state.access_store.delete_grant(grant["id"])
    assert client.get("/v1/observability/mcp-scopes").json()["total"] == 0
    assert client.get("/v1/logs").json()["logs"] == []
    assert client.get("/v1/events").json()["events"] == []
    assert client.get("/v1/logs", params={"server_id": "allowed-a"}).status_code == 404
    state.access_store.save_role(code="log-reviewer", name="Log reviewer", description="Synthetic",
        permissions=["operations.manage", "observability.read.all", "console.view"])
    state.access_store.set_user_roles(operator["id"], ["log-reviewer"])
    assert client.get("/v1/observability/mcp-scopes").json()["capabilities"]["can_read_all"] is True
    assert "global-private-marker" in client.get("/v1/events").text


def test_auth_disabled_local_console_retains_global_observability(observability_api):
    client, state, operator, login = observability_api
    state.auth_store.enabled = False
    client.cookies.clear()
    options = client.get("/v1/observability/mcp-scopes")
    assert options.status_code == 200
    assert options.json()["capabilities"]["can_read_all"] is True
    assert "global-private-marker" in client.get("/v1/events").text


def test_detail_log_sections_and_full_response_cannot_bypass_scope(observability_api):
    client, state, operator, login = observability_api
    login("scoped-operator")
    for server_id in ("hidden-b", "unknown-id"):
        for query in ({}, {"section": "logs"}, {"section": "events"}, {"section": "recovery"}):
            result = client.get(f"/v1/mcp/servers/{server_id}/detail", params=query)
            assert result.status_code == 404, result.text
            assert result.json() == {"detail": "MCP log scope not found"}
    assert client.get("/v1/mcp/servers/hidden-b/detail", params={"section": "overview"}).status_code == 200
    logs = client.get("/v1/mcp/servers/allowed-a/detail", params={"section": "logs"})
    assert logs.status_code == 200 and "synthetic log allowed-a" in logs.text
    events = client.get("/v1/mcp/servers/allowed-a/detail", params={"section": "events"})
    assert events.status_code == 200 and "deployment-not-a-server" in events.text
    assert "global-private-marker" not in events.text
    complete = client.get("/v1/mcp/servers/allowed-a/detail")
    assert complete.status_code == 200, complete.text
    assert "global-private-marker" not in complete.text
    login("admin")
    assert client.get("/v1/mcp/servers/hidden-b/detail", params={"section": "logs"}).status_code == 200


def test_debug_tool_does_not_bypass_global_capability_or_service_scope(observability_api):
    client, state, operator, login = observability_api
    state.observability_store.add_log("error", "global-private-error-marker")
    login("admin")
    token = client.post("/v1/auth/tokens", json={"name": "debug-operations",
        "scopes": ["tools.invoke", "operations.manage"]}).json()
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token['token']}"
    for action in ("events", "logs", "overview"):
        result = client.post("/v1/tools/gate_system_debug/invoke", json={"arguments": {"action": action}})
        assert result.status_code == 200, result.text
        assert result.json()["ok"] is True, result.text
        assert "global-private-marker" not in result.text
        assert "global-private-error-marker" not in result.text
        protocol = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "gate_system_debug", "arguments": {"action": action}}})
        assert protocol.status_code == 200
        assert "global-private-marker" not in protocol.text
        assert "global-private-error-marker" not in protocol.text
    login("admin")
    token = client.post("/v1/auth/tokens", json={"name": "debug-no-operations", "scopes": ["tools.invoke"]}).json()
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token['token']}"
    denied = client.post("/v1/tools/gate_system_debug/invoke", json={"arguments": {"action": "events"}})
    assert denied.status_code == 200 and denied.json()["ok"] is False
    overview = client.post("/v1/tools/gate_system_debug/invoke", json={"arguments": {"action": "overview"}})
    assert overview.json()["ok"] is True
    assert overview.json()["output"]["recent_error_logs_access"] == "denied"
    assert "global-private-error-marker" not in overview.text
    definition = state.registry.get_definition("gate_system_debug")
    state.access_store.synchronize_tools([definition])
    state.access_store.set_classification(server_id="builtin", tool_id=definition.id,
        access="read", destructive=False, idempotent=True, reviewer_id="synthetic")
    state.access_store.publish_classifications(server_id="builtin", reviewer_id="synthetic")
    state.access_store.save_grant(subject_type="user", subject_id=operator["id"], server_id="builtin",
        tool_id=definition.id, permission_type_code="read", created_by="synthetic")
    login("scoped-operator")
    for action in ("server_detail", "logs", "events"):
        denied = client.post("/v1/tools/gate_system_debug/invoke",
            json={"arguments": {"action": action, "server_id": "hidden-b"}})
        assert denied.status_code == 200 and denied.json()["ok"] is False, denied.text
        assert "MCP log scope not found" in denied.text


def test_tool_options_authorize_service_before_catalog_history_search_and_count(observability_api, monkeypatch):
    client, state, operator, login = observability_api
    from lingshu_gate.models import ToolDefinition
    state.registry.register(ToolDefinition(
        id="mcp.allowed-a.read", name="Read records", description="Synthetic",
        source="mcp", metadata={"server_id": "allowed-a"}, input_schema={},
    ), handler=lambda _: {})
    records = state.observability_store
    records.add_log("info", "synthetic", server_id="allowed-a", tool_id="mcp.allowed-a.read")
    records.add_log("info", "synthetic", server_id="deleted-allowed", tool_id="mcp.deleted-allowed.old")
    records.add_log("info", "synthetic", server_id="hidden-b", tool_id="secret-tool-marker")
    login("scoped-operator")
    path = "/v1/observability/tool-scopes"
    response = client.get(path, params={"server_id": "allowed-a", "q": "Read records"})
    assert response.status_code == 200, response.text
    assert response.json()["scopes"] == [{"id": "mcp.allowed-a.read", "name": "Read records", "availability": "current"}]
    assert response.json()["total"] == 1  # Catalog/history deduplicate.
    assert client.get(path, params={"server_id": "allowed-a", "q": "secret"}).json()["total"] == 0
    history = client.get(path, params={"server_id": "deleted-allowed"}).json()
    assert history["scopes"] == [{"id": "mcp.deleted-allowed.old", "name": "mcp.deleted-allowed.old", "availability": "historical"}]
    # Unauthorized guesses must fail before reading any tool names or history.
    with monkeypatch.context() as patch:
        def forbidden_lookup(*args, **kwargs):
            raise AssertionError("Tool lookup happened before service authorization")
        patch.setattr(state.registry, "list_definitions", forbidden_lookup)
        patch.setattr(records, "historical_tool_ids", forbidden_lookup)
        for guessed in ("hidden-b", "missing", "tool-only"):
            response = client.get(path, params={"server_id": guessed, "q": "secret"})
            assert response.status_code == 404
            assert response.json() == {"detail": "MCP log scope not found"}
    assert client.get(path, params={"server_id": "allowed-a", "tool_id": "secret-tool-marker"}).json()["scopes"] == []
    assert client.get(path).status_code == 422
    login("ordinary-reader")
    assert client.get(path, params={"server_id": "allowed-a"}).status_code == 403


def test_tool_options_empty_catalog_paging_and_revocation(observability_api):
    client, state, operator, login = observability_api
    login("scoped-operator")
    path = "/v1/observability/tool-scopes"
    assert client.get(path, params={"server_id": "allowed-a"}).json()["total"] == 0
    for index in range(55):
        state.observability_store.add_log("info", "synthetic", server_id="allowed-a", tool_id=f"tool-{index:03}")
    page = client.get(path, params={"server_id": "allowed-a", "offset": 40, "limit": 40}).json()
    assert page["total"] == 55 and len(page["scopes"]) == 15
    assert page["scopes"][0]["id"] == "tool-040"
    for grant in state.access_store.list_grants(subject_type="user", subject_id=operator["id"]):
        state.access_store.delete_grant(grant["id"])
    assert client.get(path, params={"server_id": "allowed-a"}).status_code == 404


def test_global_unfiltered_reads_skip_historical_directory_but_scoped_reads_do_not(observability_api, monkeypatch):
    client, state, operator, login = observability_api
    original = state.observability_store.historical_server_ids
    calls = []

    def counted():
        calls.append(True)
        return original()

    monkeypatch.setattr(state.observability_store, 'historical_server_ids', counted)
    state.observability_store.add_log('info', 'global-latest-probe')
    state.observability_store.emit_event('gate.synthetic.event', payload={'marker': 'global-latest-probe'})
    login('admin')
    for path in ('/v1/logs', '/v1/events', '/v1/logs/stream', '/v1/events/stream'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'global-latest-probe' in response.text
    assert calls == []
    assert client.get('/v1/logs?server_id=unknown-id').status_code == 404
    assert calls  # Named resources still receive existence/scope validation.
    calls.clear()
    login('scoped-operator')
    response = client.get('/v1/logs')
    assert response.status_code == 200
    assert 'global-private-marker' not in response.text
    assert calls  # The optimization never skips ordinary service grants.

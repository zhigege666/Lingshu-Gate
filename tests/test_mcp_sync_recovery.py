"""Complete discovery, safe recovery and the operator synchronization boundary."""

import threading
import time
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.credential_store import CredentialUsageDenied
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api.mcp_runtime_routes import register_mcp_runtime_routes
from lingshu_gate.mcp_http_client import McpHttpAuthenticationError, StreamableHttpMcpClient
from lingshu_gate.mcp_runtime import McpServerState
from test_mcp_session_recovery import connected_runtime


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    assert predicate()


def start_worker(manager, current, client, monkeypatch):
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_RETRY_BASE_SECONDS", 0.02)
    manager._prepare_tool_sync(current, client)
    manager._start_tool_sync(current.manifest.id, current, client)


def stop_worker(manager, current):
    manager.shutdown()
    if current.tool_sync_thread is not None:
        current.tool_sync_thread.join(timeout=2)
        assert not current.tool_sync_thread.is_alive()


def test_manual_discovery_recovers_expired_session_without_business_replay(tmp_path):
    with connected_runtime(tmp_path) as (manager, current, client, state):
        result = manager.synchronize_server_tools(current.manifest.id)
        assert result.tool_sync.state == "ready"
        assert result.tool_sync.last_success_at is not None
        assert result.tool_sync.last_error is None
        assert current.state == McpServerState.RUNNING
        assert len(state["sessions"]) == 2 and state["writes"] == 0
        assert client.session_id not in state["expired_sessions"]


def test_reconnect_synchronizes_access_policy_before_exposing_changed_tools(tmp_path):
    with connected_runtime(tmp_path) as (manager, current, client, state):
        store = AccessControlStore(SQLiteDatabase(manager.settings.db_url, tmp_path))
        store.attach_mcp_runtime(manager)
        store.synchronize_tools(manager.registry.list_definitions())
        changed = [{"name": "added_write", "inputSchema": {"type": "object"}}]
        with patch.object(client, "list_tools", return_value=changed):
            manager._reconnect_external_tools_locked(current.manifest.id, current)
        record = next(item for item in store.list_classifications() if item["tool_id"].endswith(".added_write"))
        assert record["required_access"] == "write" and record["policy_source"] == "default_write"
        assert record["reviewed_at"] is None
        assert manager.registry.get_definition("mcp.legacy-http.added_write")
        assert state["writes"] == 0


def test_discovery_failure_after_new_handshake_closes_the_failed_session(tmp_path):
    with connected_runtime(tmp_path) as (manager, current, client, state):
        before = list(current.tools)
        with patch.object(client, "list_tools", side_effect=RuntimeError("invalid discovery")):
            with pytest.raises(RuntimeError, match="invalid discovery"):
                manager._reconnect_external_tools_locked(current.manifest.id, current)
        assert len(state["sessions"]) == 2
        deleted_sessions = {next(value for key, value in headers.items() if key.lower() == "mcp-session-id")
                            for message, headers in state["messages"] if message["method"] == "DELETE"}
        assert "test-session-2" in deleted_sessions
        assert client.session_id is None and not client.initialized
        assert current.client is client and current.state == McpServerState.FAILED
        assert current.tools == before and current.tool_sync.state == "retrying"
        assert state["writes"] == 0


def test_invalid_discovery_retains_complete_snapshot_and_reports_recovery(tmp_path):
    with connected_runtime(tmp_path) as (manager, current, client, _state):
        before = list(current.tools)
        with patch.object(client, "list_tools", return_value=[{"name": "ok", "inputSchema": {}}, {"name": "bad", "inputSchema": "secret-token"}]):
            result = manager.synchronize_server_tools(current.manifest.id)
        assert result.tool_sync.state == "retrying"
        assert result.tool_sync.last_success_at is None
        assert result.tool_sync.next_sync_at is not None
        assert "secret-token" not in result.model_dump_json()
        assert current.tools == before
        assert [tool.id for tool in manager.registry.list_definitions()] == ["mcp.legacy-http.echo"]
        recovered = manager.synchronize_server_tools(current.manifest.id)
        assert recovered.tool_sync.state == "ready"
        assert recovered.tool_sync.error_code is None


@pytest.mark.parametrize("error", [McpHttpAuthenticationError(401, "http://peer.invalid/mcp"), McpHttpAuthenticationError(403, "http://peer.invalid/mcp"), CredentialUsageDenied("secret-token")])
def test_authorization_failures_pause_background_attempts_until_operator_sync(tmp_path, monkeypatch, error):
    with connected_runtime(tmp_path) as (manager, current, client, _state):
        try:
            with patch.object(client, "list_tools", side_effect=error) as discover:
                start_worker(manager, current, client, monkeypatch)
                wait_for(lambda: current.tool_sync.state == "auth_required")
                first_calls = discover.call_count
                for _ in range(20):
                    client.on_tools_changed()
                threading.Event().wait(0.08)
                assert discover.call_count == first_calls == 1
                assert current.tool_sync.next_sync_at is None
                assert "secret-token" not in current.to_response().model_dump_json()
            result = manager.synchronize_server_tools(current.manifest.id)
            assert result.tool_sync.state == "ready"
        finally:
            stop_worker(manager, current)


def test_polling_recovers_expiry_and_transient_discovery_failure(tmp_path, monkeypatch):
    with connected_runtime(tmp_path) as (manager, current, client, state):
        original = client.list_tools
        calls = 0

        def discover():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("peer-secret")
            return original()

        try:
            with patch.object(client, "list_tools", side_effect=discover):
                start_worker(manager, current, client, monkeypatch)
                wait_for(lambda: current.tool_sync.state == "ready")
                assert len(state["sessions"]) == 2
                assert state["writes"] == 0
                assert calls >= 3
                assert current.tool_sync_failures == 0
        finally:
            stop_worker(manager, current)


def test_notification_burst_cannot_bypass_retry_backoff(tmp_path, monkeypatch):
    with connected_runtime(tmp_path) as (manager, current, client, _state):
        try:
            with patch.object(client, "list_tools", side_effect=ConnectionError("offline")) as discover:
                start_worker(manager, current, client, monkeypatch)
                monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_RETRY_BASE_SECONDS", 100.0)
                wait_for(lambda: current.tool_sync.state == "retrying")
                for _ in range(100):
                    client.on_tools_changed()
                threading.Event().wait(0.08)
                assert discover.call_count == 1
        finally:
            stop_worker(manager, current)


def test_operator_refresh_does_not_reapply_stale_listener_auth_error(tmp_path, monkeypatch):
    with connected_runtime(tmp_path) as (manager, current, client, _state):
        error = McpHttpAuthenticationError(401, "http://peer.invalid/mcp")
        manager._prepare_tool_sync(current, client)
        current.tool_sync_errors.put(error)
        current.tool_sync.state = "auth_required"
        manager.synchronize_server_tools(current.manifest.id)
        assert current.tool_sync.state == "ready" and current.tool_sync_errors.empty()
        completed = threading.Event()
        complete = manager._complete_tool_sync

        def complete_and_signal(runtime, previous, discovered):
            complete(runtime, previous, discovered)
            completed.set()

        try:
            # Observe an actual background completion instead of sampling between
            # short polling cycles. The explicit wakeup drives this discovery.
            monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_INTERVAL_SECONDS", 60.0)
            monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_MIN_INTERVAL_SECONDS", 0.0)
            current.tool_sync.next_sync_at = None
            with patch.object(manager, "_complete_tool_sync", side_effect=complete_and_signal) as completion, \
                    patch.object(manager, "_fail_tool_sync", wraps=manager._fail_tool_sync) as failure:
                manager._start_tool_sync(current.manifest.id, current, client)
                current.tool_sync_wakeup.set()
                assert completed.wait(timeout=2), "Background tool synchronization did not complete"
                with current.lock:
                    assert completion.call_count == 1
                    assert current.tool_sync.state == "ready"
                    assert current.tool_sync.last_error is None and current.tool_sync.error_code is None
                    assert current.tool_sync_errors.empty()
                    failure.assert_not_called()
        finally:
            stop_worker(manager, current)


def test_stopping_during_backoff_prevents_reconnection(tmp_path, monkeypatch):
    with connected_runtime(tmp_path) as (manager, current, client, state):
        try:
            with patch.object(client, "list_tools", side_effect=RuntimeError("offline")) as discover:
                start_worker(manager, current, client, monkeypatch)
                wait_for(lambda: current.tool_sync.state == "retrying")
                manager.request_stop(current.manifest.id)
                calls = discover.call_count
                threading.Event().wait(0.08)
                assert discover.call_count == calls
                assert current.tool_sync.state == "disabled"
                assert current.tool_sync.next_sync_at is None
                assert len(state["sessions"]) == 1
        finally:
            stop_worker(manager, current)


def test_failed_initial_connection_recovers_when_desired_state_is_running(tmp_path, monkeypatch):
    with connected_runtime(tmp_path) as (manager, current, _client, state):
        monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_MIN_INTERVAL_SECONDS", 0.0)
        monkeypatch.setattr("lingshu_gate.mcp_runtime.TOOL_SYNC_RETRY_BASE_SECONDS", 0.02)
        original = StreamableHttpMcpClient.start
        starts = 0

        def reconnect(client):
            nonlocal starts
            starts += 1
            if starts == 1:
                raise ConnectionError("offline")
            return original(client)

        try:
            with patch.object(StreamableHttpMcpClient, "start", new=reconnect):
                result = manager.request_restart(current.manifest.id)
                assert result.status == "failed" and result.tool_sync.state == "retrying"
                wait_for(lambda: current.state == McpServerState.RUNNING)
                assert starts == 2
                assert current.tool_sync.state == "ready"
                assert manager.registry.get_definition("mcp.legacy-http.echo")
                assert state["writes"] == 0
        finally:
            stop_worker(manager, current)


def test_unchanged_discovery_preserves_changed_timestamp_and_reports_deltas(tmp_path):
    with connected_runtime(tmp_path) as (manager, current, client, _state):
        manager.synchronize_server_tools(current.manifest.id)
        previous_changed = current.tool_sync.last_changed_at
        manager.synchronize_server_tools(current.manifest.id)
        assert current.tool_sync.last_changed_at == previous_changed
        changed = [{"name": "new", "inputSchema": {"type": "object"}}]
        with patch.object(client, "list_tools", return_value=changed):
            manager.synchronize_server_tools(current.manifest.id)
        assert (current.tool_sync.added, current.tool_sync.updated, current.tool_sync.removed) == (1, 0, 1)
        assert current.tool_sync.last_changed_at != previous_changed


@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("auth_type", ["session", "token"])
def test_operator_sync_route_requires_management_permission_and_performs_discovery(tmp_path, allowed, auth_type):
    with connected_runtime(tmp_path) as (manager, current, _client, state):
        app = FastAPI()

        def operator():
            if not allowed:
                raise HTTPException(403, "insufficient permission")
            return AuthPrincipal(id="operator", username="operator", role="operator", auth_type=auth_type)

        observability = Mock()
        register_mcp_runtime_routes(app, settings=manager.settings, mcp_runtime=manager,
                                    observability_store=observability, access_store=Mock(), require_operations_manager=operator)
        with TestClient(app, headers={"Origin": "http://testserver"} if auth_type == "session" else {}) as web:
            if allowed and auth_type == "session":
                assert web.post(f"/v1/mcp/servers/{current.manifest.id}/tools/refresh", headers={"Origin": "http://untrusted.invalid"}).status_code == 403
                assert len(state["sessions"]) == 1
            result = web.post(f"/v1/mcp/servers/{current.manifest.id}/tools/refresh")
            assert result.status_code == (200 if allowed else 403)
            if allowed:
                assert result.json()["tool_sync"]["state"] == "ready"
                assert len(state["sessions"]) == 2
                observability.emit_event.assert_called_once()
                assert observability.emit_event.call_args.kwargs["payload"]["actor_id"] == "operator"
                manager.request_stop(current.manifest.id)
                assert web.post(f"/v1/mcp/servers/{current.manifest.id}/tools/refresh").status_code == 409
                assert web.post("/v1/mcp/servers/missing/tools/refresh").status_code == 404
            else:
                assert len(state["sessions"]) == 1
                observability.emit_event.assert_not_called()
        assert state["writes"] == 0

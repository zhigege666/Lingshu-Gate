"""通过真实本地 HTTP 对端验证会话恢复、调用重放及分类边界。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_http_client import McpSessionExpiredError, StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import UserCredentialSlot
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.registry import ToolExecutionError, ToolRegistry
from test_mcp_downstream_legacy import http_client, legacy_http_peer


@contextmanager
def connected_runtime(tmp_path):
    with legacy_http_peer() as (endpoint, state):
        client = http_client(tmp_path, endpoint, "2025-03-26", {"Authorization": "Bearer test-only-secret"})
        client.start()
        manager = McpRuntimeManager(client.settings, ToolRegistry())
        runtime = McpServerRuntime(
            manifest=client.manifest, state=McpServerState.RUNNING,
            client=client, tools=client.list_tools(),
        )
        manager._servers[client.manifest.id] = runtime
        manager._register_mcp_tools(runtime)
        state["expired_sessions"].add(client.session_id)
        try:
            yield manager, runtime, client, state
        finally:
            client.stop()


def test_read_reconnects_once_and_uses_new_session(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, client, state):
        result = manager.invoke_mcp_tool(runtime.manifest.id, "echo", {}, retry_read_only=True)
        assert result["isError"] is False
        assert len(state["sessions"]) == 2
        assert state["writes"] == 2
        assert client.session_id not in state["expired_sessions"]
        assert runtime.state == McpServerState.RUNNING
        assert runtime.health_status == "healthy" and runtime.last_error is None
        initializes = [headers for message, headers in state["messages"] if message["method"] == "initialize"]
        assert all(not any(key.lower() == "mcp-session-id" for key in headers) for headers in initializes)


def test_unclassified_or_write_call_reconnects_without_replay(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, _client, state):
        with pytest.raises(ToolExecutionError) as caught:
            manager.invoke_mcp_tool(runtime.manifest.id, "echo", {})
        assert caught.value.code == "mcp_session_reconnected_not_replayed"
        assert not caught.value.retryable
        assert state["writes"] == 1 and len(state["sessions"]) == 2
        assert runtime.state == McpServerState.RUNNING
        manager.invoke_mcp_tool(runtime.manifest.id, "echo", {})
        assert state["writes"] == 2


def test_concurrent_reads_share_single_reconnection(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, _client, state):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: manager.invoke_mcp_tool(
                runtime.manifest.id, "echo", {}, retry_read_only=True,
            ), range(6)))
        assert all(not result["isError"] for result in results)
        assert len(state["sessions"]) == 2
        assert state["writes"] == 7


def test_failed_reconnect_is_visible_and_does_not_loop(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, client, state):
        with patch.object(client, "start", side_effect=RuntimeError("test-only-secret")) as start:
            with pytest.raises(ToolExecutionError) as caught:
                manager.invoke_mcp_tool(runtime.manifest.id, "echo", {}, retry_read_only=True)
        assert start.call_count == 1 and state["writes"] == 1
        assert caught.value.code == "mcp_session_reconnect_failed"
        assert "test-only-secret" not in str(caught.value)
        assert "test-only-secret" not in runtime.last_error
        assert runtime.state == McpServerState.FAILED and runtime.health_status == "unhealthy"
        with pytest.raises(RuntimeError, match="not running"):
            manager.invoke_mcp_tool(runtime.manifest.id, "echo", {}, retry_read_only=True)


def test_new_session_expiring_during_retry_stops_recovery(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, client, state):
        original_call = client.call_tool
        calls = 0

        def expire_again(name, arguments):
            nonlocal calls
            calls += 1
            if calls == 2:
                state["expired_sessions"].add(client.session_id)
            return original_call(name, arguments)

        with patch.object(client, "call_tool", side_effect=expire_again):
            with pytest.raises(ToolExecutionError) as caught:
                manager.invoke_mcp_tool(runtime.manifest.id, "echo", {}, retry_read_only=True)
        assert caught.value.code == "mcp_session_reconnect_failed"
        assert len(state["sessions"]) == 2 and state["writes"] == 2
        assert runtime.state == McpServerState.FAILED


def test_changed_tool_definition_is_not_replayed(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, client, state):
        changed = [{"name": "echo", "inputSchema": {"type": "object"}, "description": "changed"}]
        with patch.object(client, "list_tools", return_value=changed):
            with pytest.raises(ToolExecutionError) as caught:
                manager.invoke_mcp_tool(runtime.manifest.id, "echo", {}, retry_read_only=True)
        assert caught.value.code == "mcp_tool_changed_after_reconnect"
        assert state["writes"] == 1
        assert manager.registry.get_definition("mcp.legacy-http.echo").description == "changed"


def test_stopped_runtime_is_not_reconnected(tmp_path):
    with connected_runtime(tmp_path) as (manager, runtime, _client, state):
        manager.stop_server(runtime.manifest.id)
        with pytest.raises(RuntimeError, match="not running"):
            manager.invoke_mcp_tool(runtime.manifest.id, "echo", {}, retry_read_only=True)
        assert len(state["sessions"]) == 1 and state["writes"] == 0


@pytest.mark.parametrize("published,access,expected", [(True, "read", True), (True, "write", False), (False, "read", False)])
def test_replay_permission_comes_from_published_classification(tmp_path, published, access, expected):
    with connected_runtime(tmp_path) as (manager, runtime, _client, state):
        store = AccessControlStore(SQLiteDatabase(manager.settings.db_url, tmp_path))
        store.attach_mcp_runtime(manager)
        tool_id = "mcp.legacy-http.echo"
        store.synchronize_tools([manager.registry.get_definition(tool_id)])
        store.set_classification(server_id=runtime.manifest.id, tool_id=tool_id, access=access,
                                 destructive=False, idempotent=False, reviewer_id="test-admin")
        if published:
            store.publish_classifications(reviewer_id="test-admin", server_id=runtime.manifest.id)
        principal = AuthPrincipal(id="test-admin", username="admin", role="admin", auth_type="session")
        response = store.invoke_tool(manager.registry, principal, tool_id, {})
        assert response.ok is expected
        assert state["writes"] == (2 if expected else 1)
        if not expected:
            assert response.output["error"]["code"] == "mcp_session_reconnected_not_replayed"


def test_transport_expiry_remains_a_typed_non_replaying_error(tmp_path):
    with connected_runtime(tmp_path) as (_manager, _runtime, client, state):
        with pytest.raises(McpSessionExpiredError):
            client.call_tool("echo", {})
        assert len(state["sessions"]) == 1 and state["writes"] == 1


@pytest.mark.parametrize("retry_read_only", [True, False])
def test_user_session_recovery_preserves_identity_and_shared_state(tmp_path, retry_read_only):
    with connected_runtime(tmp_path) as (manager, runtime, shared_client, state):
        runtime.manifest.user_credentials = [UserCredentialSlot.model_validate({
            "id": "token", "name": "Token", "required": True,
            "injection": {"name": "Authorization", "template": "Bearer {value}"},
        })]
        manager.user_credential_store = Mock()
        manager.user_credential_store.resolve_slots.side_effect = [({"token": "user-a"}, []), ({"token": "user-b"}, [])]
        shared_session = shared_client.session_id

        def create_user_client(*args, **kwargs):
            client = StreamableHttpMcpClient(*args, **kwargs)
            original_call = client.call_tool
            first = True

            def expire_first(name, arguments):
                nonlocal first
                if first:
                    state["expired_sessions"].add(client.session_id)
                    first = False
                return original_call(name, arguments)

            client.call_tool = expire_first
            return client

        with patch("lingshu_gate.mcp_runtime.StreamableHttpMcpClient", side_effect=create_user_client):
            for user_id in ("user-a", "user-b"):
                if retry_read_only:
                    result = manager.invoke_mcp_tool_for_user(runtime.manifest.id, "echo", {}, user_id=user_id, retry_read_only=True)
                    assert not result["isError"]
                else:
                    with pytest.raises(ToolExecutionError) as caught:
                        manager.invoke_mcp_tool_for_user(runtime.manifest.id, "echo", {}, user_id=user_id)
                    assert caught.value.code == "mcp_session_reconnected_not_replayed"
        assert list(state["sessions"].values()) == ["Bearer test-only-secret", "Bearer user-a", "Bearer user-a", "Bearer user-b", "Bearer user-b"]
        assert state["writes"] == (4 if retry_read_only else 2)
        assert runtime.client is shared_client and shared_client.session_id == shared_session
        assert runtime.state == McpServerState.RUNNING and runtime.health_status == "unknown"
        assert manager.user_credential_store.mark_used.call_count == 2

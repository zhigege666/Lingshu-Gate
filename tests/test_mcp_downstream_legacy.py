"""用真实 HTTP/stdio 对端验证旧版下游生命周期与故障边界。"""

from __future__ import annotations

import json
import io
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from lingshu_gate.config import Settings
from lingshu_gate.mcp_http_client import McpHttpAuthenticationError, StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import McpProtocolError, StdioMcpClient
from lingshu_gate.protocol.version import LEGACY_PROTOCOL_VERSIONS, MCP_PROTOCOL_VERSION, STDIO_LEGACY_PROTOCOL_VERSIONS


@contextmanager
def legacy_http_peer(*, session=True, sse=False, negotiated=None, auth_status=None,
                     discovery_error=(-32601, "Method not found"), modern=False):
    state = {"messages": [], "sessions": {}, "expired": False, "writes": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, body=None, *, session_id=None):
            payload = json.dumps(body).encode() if body is not None else b""
            if sse and body is not None:
                payload = b"event: message\ndata: " + payload + b"\n\n"
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
            if session_id is not None:
                self.send_header("Mcp-Session-Id", session_id)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):  # noqa: N802
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["messages"].append((message, dict(self.headers)))
            if auth_status:
                self.respond(auth_status)
                return
            method = message["method"]
            if method == "server/discover":
                payload = {"jsonrpc": "2.0", "id": message["id"]}
                if modern:
                    payload["result"] = {"supportedVersions": [MCP_PROTOCOL_VERSION], "capabilities": {"tools": {}}}
                else:
                    payload["error"] = {"code": discovery_error[0], "message": discovery_error[1]}
                self.respond(200, payload)
                return
            owner = self.headers.get("Authorization")
            if method == "initialize":
                session_id = f"test-session-{len(state['sessions']) + 1}" if session else None
                if session_id:
                    state["sessions"][session_id] = owner
                self.respond(200, {"jsonrpc": "2.0", "id": message["id"], "result": {
                    "protocolVersion": negotiated or message["params"]["protocolVersion"],
                    "serverInfo": {"name": "legacy-peer", "version": "1"},
                    "capabilities": {"tools": {}},
                }}, session_id=session_id)
                return
            if session and (
                self.headers.get("Mcp-Session-Id") not in state["sessions"]
                or state["sessions"][self.headers["Mcp-Session-Id"]] != owner
            ):
                self.respond(403)
                return
            if method == "notifications/initialized":
                self.respond(202)
                return
            if method == "tools/call":
                state["writes"] += 1
            if state["expired"]:
                self.respond(404)
                return
            if method == "tools/list":
                result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
            else:
                result = {"content": [{"type": "text", "text": "ok"}], "isError": False}
            self.respond(200, {"jsonrpc": "2.0", "id": message["id"], "result": result})

        def do_DELETE(self):  # noqa: N802
            state["messages"].append(({"method": "DELETE"}, dict(self.headers)))
            self.respond(405)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def http_client(directory, endpoint, version, headers=None):
    manifest = McpServerManifest.model_validate({
        "id": "legacy-http", "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": endpoint,
                      "protocol_version": version, "headers": headers or {}},
        "timeout_seconds": 3,
    })
    return StreamableHttpMcpClient(manifest, Settings(data_dir=directory))


@pytest.mark.parametrize("version", LEGACY_PROTOCOL_VERSIONS)
@pytest.mark.parametrize("session,sse", [(True, False), (True, True), (False, False)])
def test_http_legacy_lifecycle(tmp_path, version, session, sse):
    with legacy_http_peer(session=session, sse=sse) as (endpoint, state):
        client = http_client(tmp_path, endpoint, version)
        try:
            client.start()
            client.start()
            assert client.initialized
            assert bool(client.session_id) == session
            assert client.server_info["name"] == "legacy-peer"
            assert client.list_tools()[0]["name"] == "echo"
            assert not client.call_tool("echo", {})["isError"]
        finally:
            client.stop()
        messages = state["messages"]
        assert [m["method"] for m, _ in messages] == [
            "initialize", "notifications/initialized", "tools/list", "tools/call",
        ] + (["DELETE"] if session else [])
        initial_headers = {k.lower(): v for k, v in messages[0][1].items()}
        assert "mcp-protocol-version" not in initial_headers
        assert "mcp-session-id" not in initial_headers
        for message, headers in messages:
            assert "_meta" not in message.get("params", {})
            normalized = {k.lower(): v for k, v in headers.items()}
            assert "mcp-method" not in normalized
            if message["method"] != "initialize":
                assert normalized["mcp-protocol-version"] == version
                assert ("mcp-session-id" in normalized) == session
        assert client.session_id is None
        assert not client.initialized


def test_http_uses_negotiated_version_and_separates_user_sessions(tmp_path):
    with legacy_http_peer(negotiated="2025-03-26") as (endpoint, state):
        first = http_client(tmp_path, endpoint, "2025-11-25", {"Authorization": "Bearer alice"})
        second = http_client(tmp_path, endpoint, "2025-11-25", {"Authorization": "Bearer bob"})
        try:
            first.start()
            second.start()
            assert first.session_id != second.session_id
            assert first.protocol_version == second.protocol_version == "2025-03-26"
            first.call_tool("echo", {})
            second.call_tool("echo", {})
            for message, headers in state["messages"]:
                if message["method"] != "initialize":
                    normalized = {k.lower(): v for k, v in headers.items()}
                    assert normalized["mcp-protocol-version"] == "2025-03-26"
                    assert state["sessions"][normalized["mcp-session-id"]] == normalized["authorization"]
        finally:
            first.stop()
            second.stop()


def test_expired_session_never_replays_business_request(tmp_path):
    with legacy_http_peer() as (endpoint, state):
        client = http_client(tmp_path, endpoint, "2025-06-18")
        try:
            client.start()
            state["expired"] = True
            with pytest.raises(McpProtocolError, match="session expired"):
                client.call_tool("write", {})
            assert state["writes"] == 1
            assert not client.initialized and client.session_id is None
            with pytest.raises(McpProtocolError, match="reconnect"):
                client.call_tool("write", {})
            assert state["writes"] == 1
            state["expired"] = False
            client.start()
            assert client.initialized
            assert client.list_tools()
            assert state["writes"] == 1
        finally:
            client.stop()


@pytest.mark.parametrize("status", [401, 403, 500])
def test_legacy_http_errors_do_not_probe_other_versions(tmp_path, status):
    with legacy_http_peer(auth_status=status) as (endpoint, state):
        client = http_client(tmp_path, endpoint, "2025-06-18")
        expected = McpHttpAuthenticationError if status in {401, 403} else McpProtocolError
        with pytest.raises(expected):
            client.start()
        assert len(state["messages"]) == 1
        assert not client.initialized


@pytest.mark.parametrize("version", ["2000-01-01", MCP_PROTOCOL_VERSION, "secret-invalid-version"])
def test_http_rejects_unsupported_negotiation_and_cleans_session(tmp_path, version):
    with legacy_http_peer(negotiated=version) as (endpoint, state):
        client = http_client(tmp_path, endpoint, "2025-06-18")
        with pytest.raises(McpProtocolError) as caught:
            client.start()
        assert version not in str(caught.value)
        assert [m["method"] for m, _ in state["messages"]] == ["initialize", "DELETE"]
        assert not client.initialized and client.session_id is None


STDIO_PEER = '''import json, sys
initialized = 0
for line in sys.stdin:
    message = json.loads(line)
    method = message['method']
    if method == 'server/discover':
        print(json.dumps({'jsonrpc': '2.0', 'id': message['id'],
                          'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
        continue
    assert '_meta' not in message.get('params', {})
    if method == 'initialize':
        assert initialized == 0
        result = {'protocolVersion': sys.argv[1], 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'strict-stdio', 'version': '1'}}
    elif method == 'notifications/initialized':
        initialized += 1
        continue
    elif method == 'tools/list':
        assert initialized == 1
        result = {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
    elif method == 'tools/call':
        assert initialized == 1
        result = {'content': [{'type': 'text', 'text': 'ok'}], 'isError': False}
    else:
        raise AssertionError(method)
    print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)
'''


def stdio_client(directory: Path, version, negotiated):
    peer = directory / "peer.py"
    peer.write_text(STDIO_PEER, encoding="utf-8")
    manifest = McpServerManifest.model_validate({
        "id": "legacy-stdio",
        "launch": {"type": "managed_process", "command": sys.executable, "args": [str(peer), negotiated]},
        "transport": {"type": "stdio", "protocol_version": version},
        "timeout_seconds": 3,
    })
    return StdioMcpClient(manifest, Settings(data_dir=directory / "data", allowed_root=directory))


@pytest.mark.parametrize("version", [*STDIO_LEGACY_PROTOCOL_VERSIONS, None, "auto"])
@pytest.mark.parametrize("negotiated", STDIO_LEGACY_PROTOCOL_VERSIONS)
def test_stdio_initializes_once_and_can_restart(tmp_path, version, negotiated):
    client = stdio_client(tmp_path, version, negotiated)
    try:
        for _ in range(2):
            client.start()
            client.start()
            assert client.initialized
            assert client.protocol_version == negotiated
            assert client.list_tools()[0]["name"] == "echo"
            assert not client.call_tool("echo", {})["isError"]
            client.stop()
    finally:
        client.stop()


def test_stdio_failed_negotiation_stops_child(tmp_path):
    client = stdio_client(tmp_path, "2025-06-18", "unsupported-secret-version")
    with pytest.raises(McpProtocolError, match="unsupported") as caught:
        client.start()
    assert "unsupported-secret-version" not in str(caught.value)
    assert client.process is None and not client.initialized


def test_2024_stdio_does_not_enable_unsupported_http_transport(tmp_path):
    with pytest.raises(ValueError, match="unsupported MCP protocol version"):
        http_client(tmp_path, "https://mcp.example.test/mcp", "2024-11-05")
    with legacy_http_peer(negotiated="2024-11-05") as (endpoint, state):
        client = http_client(tmp_path, endpoint, None)
        with pytest.raises(McpProtocolError, match="unsupported initialize protocol version"):
            client.start()
        assert not client.initialized and client.session_id is None
        assert [m["method"] for m, _ in state["messages"]] == ["server/discover", "initialize", "DELETE"]


@pytest.mark.parametrize("session_id", ["", "bad session", "bad\nsecret", "会话"])
def test_invalid_http_session_header_fails_without_echo(tmp_path, session_id):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", "2025-11-25")
    response = io.BytesIO(b"{}")
    response.headers = {"Mcp-Session-Id": session_id}
    response.status = 200
    with patch.object(client._opener, "open", return_value=response) as opened:
        with pytest.raises(McpProtocolError, match="invalid session identifier"):
            client.start()
    assert opened.call_count == 1
    assert not client.initialized and client.session_id is None


@pytest.mark.parametrize("result", [
    {}, {"protocolVersion": "2025-11-25", "capabilities": [], "serverInfo": "secret-value"},
])
def test_malformed_initialize_result_is_sanitized(tmp_path, result):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", "2025-11-25")
    response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode())
    response.headers = {"Content-Type": "application/json"}
    response.status = 200
    with patch.object(client._opener, "open", return_value=response) as opened:
        with pytest.raises(McpProtocolError, match="Invalid MCP initialize result") as caught:
            client.start()
    assert "secret-value" not in str(caught.value)
    assert opened.call_count == 1
    assert not client.initialized


@pytest.mark.parametrize("version", [None, "auto"])
@pytest.mark.parametrize("error", [(-32601, "Method not found"), (-32602, "Invalid request parameters"),
                                  (-32022, "Unsupported protocol version"), (-32000, "Unknown method: server/discover")])
def test_auto_http_negotiates_without_changing_manifest(tmp_path, version, error):
    with legacy_http_peer(discovery_error=error) as (endpoint, state):
        client = http_client(tmp_path, endpoint, version)
        try:
            client.start()
            assert client.protocol_version == "2025-11-25"
            assert client.manifest.transport.protocol_version == version
            assert client.list_tools()
            assert [message["method"] for message, _ in state["messages"]] == [
                "server/discover", "initialize", "notifications/initialized", "tools/list",
            ]
        finally:
            client.stop()


def test_auto_prefers_current_when_peer_supports_it(tmp_path):
    with legacy_http_peer(modern=True, session=False) as (endpoint, state):
        client = http_client(tmp_path, endpoint, None)
        try:
            client.start()
            assert client.protocol_version == MCP_PROTOCOL_VERSION
            assert client.list_tools()
            assert [message["method"] for message, _ in state["messages"]] == ["server/discover", "tools/list"]
        finally:
            client.stop()


@pytest.mark.parametrize("code,message", [(401, "unauthorized"), (403, "forbidden"),
                                         (-32000, "authentication failed"), (-32603, "internal error")])
def test_auto_does_not_fallback_on_non_protocol_errors(tmp_path, code, message):
    with legacy_http_peer(discovery_error=(code, message)) as (endpoint, state):
        client = http_client(tmp_path, endpoint, None)
        with pytest.raises(McpProtocolError):
            client.start()
        assert len(state["messages"]) == 1


@pytest.mark.parametrize("status", [401, 403, 500])
def test_auto_http_status_errors_do_not_fallback(tmp_path, status):
    with legacy_http_peer(auth_status=status) as (endpoint, state):
        client = http_client(tmp_path, endpoint, None)
        with pytest.raises(McpProtocolError):
            client.start()
        assert len(state["messages"]) == 1


def test_auto_timeout_and_business_errors_never_negotiate_or_replay(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch.object(client._opener, "open", side_effect=TimeoutError) as opened:
        with pytest.raises(McpProtocolError, match="deadline"):
            client.start()
    assert opened.call_count == 1
    response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": 2,
                                    "error": {"code": -32601, "message": "Method not found"}}).encode())
    response.headers = {"Content-Type": "application/json"}
    response.status = 200
    with patch.object(client._opener, "open", return_value=response) as opened:
        with pytest.raises(McpProtocolError):
            client.call_tool("write", {})
    assert opened.call_count == 1

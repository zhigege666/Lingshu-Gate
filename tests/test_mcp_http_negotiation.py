"""Bounded automatic discovery fallback, using real HTTP and strict wire errors."""

from __future__ import annotations

import io
import json
import ssl
import urllib.error
from unittest.mock import patch

import pytest

from lingshu_gate.mcp_runtime import McpServerRuntime, McpServerState
from lingshu_gate.mcp_stdio_client import McpProtocolError
from lingshu_gate.protocol.version import LEGACY_PROTOCOL_VERSIONS, MCP_PROTOCOL_VERSION
from test_mcp_downstream_legacy import http_client, legacy_http_peer


INITIALIZATION_ERROR = {
    "jsonrpc": "2.0", "id": None,
    "error": {"code": -32000, "message": "Bad Request: Server not initialized"},
}


def http_error(body=INITIALIZATION_ERROR, *, status=400, content_type="application/json", declared_length=None):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"Content-Type": content_type, "Content-Length": str(len(raw) if declared_length is None else declared_length)}
    return urllib.error.HTTPError("https://mcp.example.test/mcp", status, "synthetic", headers, io.BytesIO(raw))


def response(payload=None, *, status=200, session=None):
    result = io.BytesIO(json.dumps(payload).encode() if payload is not None else b"")
    result.headers = {"Content-Type": "application/json"}
    if session:
        result.headers["Mcp-Session-Id"] = session
    result.status = status
    return result


@pytest.mark.parametrize("version", [None, "auto"])
@pytest.mark.parametrize("negotiated", LEGACY_PROTOCOL_VERSIONS)
def test_real_http_400_null_id_falls_back_once_and_reports_actual_version(tmp_path, version, negotiated):
    with legacy_http_peer(discovery_error=(-32000, "Bad Request: Server not initialized"),
                          discovery_status=400, discovery_id=None, negotiated=negotiated) as (endpoint, state):
        client = http_client(tmp_path, endpoint, version)
        runtime = McpServerRuntime(manifest=client.manifest, state=McpServerState.EXTERNAL, client=client)
        assert runtime.to_response().negotiated_protocol_version is None
        try:
            client.start()
            client.start()
            assert client.protocol_version == negotiated
            assert runtime.to_response().negotiated_protocol_version == negotiated
            assert client.manifest.transport.protocol_version == version
            assert client.list_tools()[0]["name"] == "echo"
            methods = [message["method"] for message, _ in state["messages"]]
            assert methods == ["server/discover", "initialize", "notifications/initialized", "tools/list"]
            initialize = state["messages"][1][0]
            assert initialize["params"]["protocolVersion"] == "2025-11-25"
            for _, headers in state["messages"][2:]:
                assert {k.lower(): v for k, v in headers.items()}["mcp-protocol-version"] == negotiated
        finally:
            client.stop()
        assert state["messages"][-1][0]["method"] == "DELETE"
        assert not client.initialized and client.session_id is None
        assert runtime.to_response().negotiated_protocol_version is None


@pytest.mark.parametrize("version", [None, "auto", MCP_PROTOCOL_VERSION])
def test_modern_unsupported_version_is_not_a_legacy_signal(tmp_path, version):
    with legacy_http_peer(discovery_error=(-32022, "Unsupported protocol version")) as (endpoint, state):
        client = http_client(tmp_path, endpoint, version)
        with pytest.raises(McpProtocolError) as caught:
            client.start()
        assert caught.value.code == -32022
        assert [message["method"] for message, _ in state["messages"]] == ["server/discover"]
        assert client.protocol_version == MCP_PROTOCOL_VERSION
        assert not client.initialized and client.session_id is None


def test_matching_id_json_error_allows_normalization_without_logging_error_data(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", "auto")
    captured = []
    client.log_sink = lambda *args: captured.append(args)
    wire_error = {"jsonrpc": "2.0", "id": 1, "error": {
        "code": -32000, "message": "  BAD REQUEST: Server not initialized \n",
        "data": {"synthetic_sensitive_value": "must-not-be-logged"},
    }}
    initialized = {"jsonrpc": "2.0", "id": 2, "result": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "peer", "version": "test"},
    }}
    with patch.object(client._opener, "open", side_effect=[http_error(wire_error, content_type="Application/JSON; charset=utf-8"),
                                                         response(initialized), response(status=202)]) as opened:
        client.start()
    assert opened.call_count == 3
    assert client.protocol_version == "2025-03-26" and client.initialized
    assert "must-not-be-logged" not in repr(captured)
    assert any(entry[2] == "gate.mcp.http_protocol_fallback" for entry in captured)


INVALID_BODIES = [
    b"not json", b"<html>Bad Request: Server not initialized</html>", b"[]", b"null",
    b'{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"Bad Request: Server not initialized"},"id":1}',
    b'{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"Bad Request: Server not initialized","data":NaN}}',
    {**INITIALIZATION_ERROR, "jsonrpc": "1.0"},
    {"id": None, "error": INITIALIZATION_ERROR["error"]},
    {"jsonrpc": "2.0", "error": INITIALIZATION_ERROR["error"]},
    {**INITIALIZATION_ERROR, "result": {}},
    *[{**INITIALIZATION_ERROR, "id": value} for value in [2, "1", True, 1.0]],
    *[{**INITIALIZATION_ERROR, "error": {"code": value, "message": "Bad Request: Server not initialized"}}
      for value in [-32022, -32601, "-32000", -32000.0, False]],
    *[{**INITIALIZATION_ERROR, "error": {"code": -32000, "message": value}}
      for value in [None, "Server not initialized", "Bad Request: Server not initialized: retry", "Bad Request: permission denied"]],
    {**INITIALIZATION_ERROR, "error": []},
    {**INITIALIZATION_ERROR, "error": {**INITIALIZATION_ERROR["error"], "unsupported": "extra"}},
    b'{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"Bad Request: Server not initialized"},"bad_utf8":"\xff"}',
]


@pytest.mark.parametrize("body", INVALID_BODIES)
def test_malformed_or_other_http_400_errors_do_not_negotiate(tmp_path, body):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch.object(client._opener, "open", side_effect=http_error(body)) as opened:
        with pytest.raises(McpProtocolError, match="HTTP 400"):
            client.start()
    assert opened.call_count == 1
    assert client.protocol_version == MCP_PROTOCOL_VERSION
    assert not client.initialized and client.session_id is None


@pytest.mark.parametrize("status", [401, 403, 404, 405, 429, 500, 503])
def test_other_http_status_with_identical_body_does_not_negotiate(tmp_path, status):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch.object(client._opener, "open", side_effect=http_error(status=status)) as opened:
        with pytest.raises(McpProtocolError):
            client.start()
    assert opened.call_count == 1 and client.protocol_version == MCP_PROTOCOL_VERSION


@pytest.mark.parametrize("content_type", ["text/html", "text/plain", "text/event-stream", "application/problem+json", ""])
def test_wrong_content_type_never_enables_legacy_probe(tmp_path, content_type):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch.object(client._opener, "open", side_effect=http_error(content_type=content_type)) as opened:
        with pytest.raises(McpProtocolError):
            client.start()
    assert opened.call_count == 1


@pytest.mark.parametrize("stage", ["explicit-modern", "existing-session", "ordinary-discover", "tool-call"])
def test_special_null_id_is_limited_to_fresh_automatic_discovery(tmp_path, stage):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", MCP_PROTOCOL_VERSION if stage == "explicit-modern" else None)
    if stage == "existing-session":
        client.session_id = "existing-synthetic-session"
    with patch.object(client._opener, "open", side_effect=http_error()) as opened:
        with pytest.raises(McpProtocolError):
            if stage in {"explicit-modern", "existing-session"}:
                client.start()
            elif stage == "ordinary-discover":
                client.request("server/discover", {})
            else:
                client.initialized = True
                client.call_tool("synthetic_write", {})
    methods = [call.args[0].get_method() for call in opened.call_args_list]
    assert methods == (["POST", "DELETE"] if stage == "existing-session" else ["POST"])
    assert client.protocol_version == MCP_PROTOCOL_VERSION


@pytest.mark.parametrize("failure", [urllib.error.URLError(ssl.SSLError("synthetic TLS failure")),
                                     urllib.error.URLError("synthetic network failure"), TimeoutError("synthetic timeout")])
def test_transport_failures_do_not_negotiate(tmp_path, failure):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch.object(client._opener, "open", side_effect=failure) as opened:
        with pytest.raises(McpProtocolError):
            client.start()
    assert opened.call_count == 1 and not client.initialized


def test_oversized_http_error_is_closed_without_initializing(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    error = http_error(declared_length=1024)
    with patch("lingshu_gate.mcp_http_client.MAX_HTTP_RESPONSE_BYTES", 128), \
         patch.object(client._opener, "open", side_effect=error) as opened:
        with pytest.raises(McpProtocolError, match="HTTP 400"):
            client.start()
    assert error.fp.closed and opened.call_count == 1


@pytest.mark.parametrize("method", ["tools/list", "tools/call"])
@pytest.mark.parametrize("response_id", [None, "1", True, 1.0, 9])
def test_ordinary_rpc_requires_exact_id_and_is_never_replayed(tmp_path, method, response_id):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    wire_response = {"jsonrpc": "2.0", "id": response_id, "result": {}}
    with patch.object(client._opener, "open", return_value=response(wire_response)) as opened:
        with pytest.raises(McpProtocolError, match="Invalid JSON-RPC"):
            client.request(method, {})
    assert opened.call_count == 1


@pytest.mark.parametrize("exhaust_budget", [False, True])
def test_handshake_uses_one_deadline_and_cleanup_retains_original_error(tmp_path, exhaust_budget):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    clock = [100.0]
    attempts = []

    def open_response(request, *, timeout):
        method = request.get_method()
        message = json.loads(request.data) if request.data else {}
        attempts.append((message.get("method", method), timeout))
        if method == "DELETE":
            assert timeout <= 5
            raise RuntimeError("cleanup-must-not-replace-handshake-error")
        if message["method"] == "server/discover":
            clock[0] += 0.7
            raise http_error()
        if message["method"] == "initialize":
            clock[0] += 2.4 if exhaust_budget else 1.7
            return response({"jsonrpc": "2.0", "id": message["id"], "result": {
                "protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "peer", "version": "test"},
            }}, session="synthetic-session")
        return response(status=202)

    with patch("lingshu_gate.mcp_http_client.time.monotonic", side_effect=lambda: clock[0]), \
         patch.object(client._opener, "open", side_effect=open_response):
        if exhaust_budget:
            with pytest.raises(McpProtocolError, match="absolute deadline") as caught:
                client.start()
            assert "cleanup" not in str(caught.value)
            assert not client.initialized and client.session_id is None
            assert [method for method, _ in attempts] == ["server/discover", "initialize", "DELETE"]
        else:
            client.start()
            assert [method for method, _ in attempts] == ["server/discover", "initialize", "notifications/initialized"]
            assert [timeout for _, timeout in attempts] == pytest.approx([3.0, 2.3, 0.6])
            assert client.initialized

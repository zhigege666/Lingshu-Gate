"""Exercise independent tool notification streams against a real HTTP peer."""

from __future__ import annotations

import json
import queue
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lingshu_gate.config import Settings
from lingshu_gate.mcp_http_client import (
    McpHttpAuthenticationError,
    McpSessionExpiredError,
    StreamableHttpMcpClient,
)
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import McpProtocolError
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION


SUBSCRIPTION_META = "io.modelcontextprotocol/subscriptionId"


@contextmanager
def notification_peer(*, negotiated="2025-06-18", stream_status=200, advertised=True):
    """A separately framed peer: tests explicitly decide when it acknowledges."""
    state = {"requests": [], "streams": queue.Queue(), "stop": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def respond(self, status, body=None, *, session=None):
            payload = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if session:
                self.send_header("Mcp-Session-Id", session)
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        def open_stream(self, request_id):
            if stream_status != 200:
                self.respond(stream_status, {"detail": "credential-private-peer-body"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "close")
            self.end_headers()
            stream = {"id": request_id, "send": queue.Queue(), "closed": threading.Event()}
            state["streams"].put(stream)
            try:
                while not state["stop"].is_set():
                    try:
                        message = stream["send"].get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if message is None:
                        return
                    payload = message if isinstance(message, bytes) else (
                        b"data: " + json.dumps(message).encode() + b"\n\n"
                    )
                    self.wfile.write(payload)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self.close_connection = True
                stream["closed"].set()

        def do_POST(self):  # noqa: N802
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((message, {key.lower(): value for key, value in self.headers.items()}))
            method = message["method"]
            capabilities = {"tools": {"listChanged": advertised}}
            if method == "server/discover":
                result = {"supportedVersions": [MCP_PROTOCOL_VERSION], "capabilities": capabilities}
            elif method == "initialize":
                self.respond(200, {"jsonrpc": "2.0", "id": message["id"], "result": {
                    "protocolVersion": negotiated, "capabilities": capabilities,
                    "serverInfo": {"name": "notification-peer", "version": "1"},
                }}, session="notification-test-session")
                return
            elif method == "notifications/initialized":
                self.respond(202)
                return
            elif method == "subscriptions/listen":
                self.open_stream(message["id"])
                return
            elif method == "tools/list":
                result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
            else:
                self.respond(500)
                return
            self.respond(200, {"jsonrpc": "2.0", "id": message["id"], "result": result})

        def do_GET(self):  # noqa: N802
            state["requests"].append(({"method": "GET"}, {key.lower(): value for key, value in self.headers.items()}))
            self.open_stream(None)

        def do_DELETE(self):  # noqa: N802
            state["requests"].append(({"method": "DELETE"}, dict(self.headers)))
            self.respond(204)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp", state
    finally:
        state["stop"].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def new_client(tmp_path, endpoint, version):
    manifest = McpServerManifest.model_validate({
        "id": "notification-peer", "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": endpoint, "protocol_version": version},
        "timeout_seconds": 3,
    })
    return StreamableHttpMcpClient(manifest, Settings(data_dir=tmp_path))


def acknowledged(stream, *, accepted=True, subscription_id=None):
    return {"jsonrpc": "2.0", "method": "notifications/subscriptions/acknowledged", "params": {
        "notifications": {"toolsListChanged": accepted},
        "_meta": {SUBSCRIPTION_META: stream["id"] if subscription_id is None else subscription_id},
    }}


def tools_changed(stream):
    result = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
    if stream["id"] is not None:
        result["params"] = {"_meta": {SUBSCRIPTION_META: stream["id"]}}
    return result


@pytest.mark.parametrize("version", ["2025-11-25", MCP_PROTOCOL_VERSION])
def test_notifications_use_negotiated_transport_without_blocking_business_requests(tmp_path, version):
    with notification_peer() as (endpoint, peer):
        client = new_client(tmp_path, endpoint, version)
        changes, errors = queue.Queue(), queue.Queue()
        try:
            client.start()
            client.on_tools_changed = lambda: changes.put("changed")
            assert client.start_tool_notifications(on_error=errors.put)
            listener = client._notifications
            stream = peer["streams"].get(timeout=2)
            if version == MCP_PROTOCOL_VERSION:
                assert changes.empty(), "a subscription is not established until acknowledged"
                stream["send"].put(acknowledged(stream))
            assert changes.get(timeout=2) == "changed"  # refresh after establishing the stream

            # Requests on a notification stream are never executed or interpreted
            # as permission. Only a notification with no id wakes synchronization.
            if version != MCP_PROTOCOL_VERSION:
                stream["send"].put({"jsonrpc": "2.0", "id": 999, "method": "tools/call",
                                    "params": {"name": "delete_all", "arguments": {}}})
            stream["send"].put(tools_changed(stream))
            assert changes.get(timeout=2) == "changed"
            assert client.list_tools()[0]["name"] == "echo"
            assert errors.empty()
            assert changes.empty()
            methods = [message["method"] for message, _ in peer["requests"]]
            assert "tools/call" not in methods
            message, headers = next((m, h) for m, h in peer["requests"]
                                    if m["method"] in {"GET", "subscriptions/listen"})
            assert headers["mcp-protocol-version"] == client.protocol_version
            if version == MCP_PROTOCOL_VERSION:
                assert message["params"]["notifications"] == {"toolsListChanged": True}
                assert message["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == MCP_PROTOCOL_VERSION
                assert headers["mcp-method"] == "subscriptions/listen"
            else:
                assert client.protocol_version == "2025-06-18"
                assert headers["mcp-session-id"] == "notification-test-session"
                assert "mcp-method" not in headers
            started = time.monotonic()
            client.stop_tool_notifications()
            assert time.monotonic() - started < 1.5
            assert listener is not None and not listener.thread.is_alive()
        finally:
            client.stop()


@pytest.mark.parametrize("version", ["2025-11-25", MCP_PROTOCOL_VERSION])
def test_optional_405_keeps_normal_client_usable(tmp_path, version):
    with notification_peer(stream_status=405) as (endpoint, peer):
        client = new_client(tmp_path, endpoint, version)
        changes, errors = queue.Queue(), queue.Queue()
        try:
            client.start()
            assert client.start_tool_notifications(lambda: changes.put(True), errors.put)
            listener = client._notifications
            listener.thread.join(timeout=2)
            assert not listener.thread.is_alive()
            assert errors.empty() and changes.empty()
            assert client.initialized and client.list_tools()[0]["name"] == "echo"
            assert len([m for m, _ in peer["requests"] if m["method"] in {"GET", "subscriptions/listen"}]) == 1
        finally:
            client.stop()


@pytest.mark.parametrize("status", [401, 403, 404])
def test_session_and_authentication_failures_are_classifiable_and_secret_safe(tmp_path, status):
    with notification_peer(stream_status=status) as (endpoint, _peer):
        client = new_client(tmp_path, endpoint, "2025-11-25")
        errors = queue.Queue()
        try:
            client.start()
            original_session = client.session_id
            assert client.start_tool_notifications(on_error=errors.put)
            error = errors.get(timeout=2)
            if status == 404:
                assert isinstance(error, McpSessionExpiredError)
            else:
                assert isinstance(error, McpHttpAuthenticationError)
                assert error.status_code == status
            assert "credential-private-peer-body" not in str(error)
            assert endpoint not in str(error)
            assert client.initialized and client.session_id == original_session  # runtime owns recovery
            client._notifications.thread.join(timeout=2)
            assert not client._notifications.thread.is_alive()
            assert errors.empty()
        finally:
            client.stop()


@pytest.mark.parametrize("invalid", ["before_ack", "wrong_subscription", "declined"])
def test_modern_subscription_requires_correlated_acceptance(tmp_path, invalid):
    with notification_peer() as (endpoint, peer):
        client = new_client(tmp_path, endpoint, MCP_PROTOCOL_VERSION)
        changes, errors = queue.Queue(), queue.Queue()
        try:
            client.start()
            client.start_tool_notifications(lambda: changes.put(True), errors.put)
            stream = peer["streams"].get(timeout=2)
            if invalid == "before_ack":
                stream["send"].put(tools_changed(stream))
            elif invalid == "wrong_subscription":
                stream["send"].put(acknowledged(stream, subscription_id=stream["id"] + 1))
            else:
                stream["send"].put(acknowledged(stream, accepted=False))
            if invalid == "declined":
                client._notifications.thread.join(timeout=2)
                assert not client._notifications.thread.is_alive()
                assert errors.empty()
            else:
                assert isinstance(errors.get(timeout=2), McpProtocolError)
            assert changes.empty()
            assert client.list_tools()[0]["name"] == "echo"
        finally:
            client.stop()


def test_reconnect_wakes_a_refresh_even_when_no_change_notification_was_replayed(tmp_path, monkeypatch):
    monkeypatch.setattr("lingshu_gate.mcp_http_client.NOTIFICATION_RETRY_MAX_SECONDS", 0.01)
    with notification_peer() as (endpoint, peer):
        client = new_client(tmp_path, endpoint, "2025-11-25")
        changes, errors = queue.Queue(), queue.Queue()
        try:
            client.start()
            client.start_tool_notifications(lambda: changes.put(True), errors.put)
            first = peer["streams"].get(timeout=2)
            assert changes.get(timeout=2)
            first["send"].put(None)
            second = peer["streams"].get(timeout=2)
            assert second is not first and changes.get(timeout=2)
            assert errors.empty()
        finally:
            client.stop()


def test_notification_stream_has_a_byte_budget_and_preserves_business_state(tmp_path):
    with notification_peer() as (endpoint, peer):
        client = new_client(tmp_path, endpoint, "2025-11-25")
        errors = queue.Queue()
        try:
            client.start()
            client.settings = replace(client.settings, mcp_max_message_bytes=512)
            client.start_tool_notifications(on_error=errors.put)
            stream = peer["streams"].get(timeout=2)
            stream["send"].put(b"data: " + b"x" * 1024 + b"\n\n")
            assert isinstance(errors.get(timeout=2), McpProtocolError)
            assert client.initialized and client.list_tools()[0]["name"] == "echo"
        finally:
            client.stop()


def test_listener_can_stop_from_its_callback_without_joining_itself(tmp_path):
    with notification_peer() as (endpoint, _peer):
        client = new_client(tmp_path, endpoint, "2025-11-25")
        stopped = queue.Queue()

        def stop_in_callback():
            client.stop_tool_notifications()
            stopped.put(threading.current_thread())

        try:
            client.start()
            assert client.start_tool_notifications(stop_in_callback)
            thread = stopped.get(timeout=2)
            thread.join(timeout=2)
            assert not thread.is_alive()
            assert client._notifications is None
        finally:
            client.stop()


def test_absent_capability_uses_existing_requests_without_opening_a_stream(tmp_path):
    with notification_peer(advertised=False) as (endpoint, peer):
        client = new_client(tmp_path, endpoint, "2025-11-25")
        try:
            client.start()
            assert not client.start_tool_notifications()
            assert client.list_tools()[0]["name"] == "echo"
            assert peer["streams"].empty()
            assert client._notifications is None
        finally:
            client.stop()


def test_callback_errors_do_not_fail_an_existing_post_response_or_leak_secrets(tmp_path):
    client = new_client(tmp_path, "http://127.0.0.1:1/mcp", "2025-11-25")
    logs = []
    client.log_sink = lambda *args: logs.append(args)

    def broken_callback():
        raise ValueError("private-callback-credential")

    client.on_tools_changed = broken_callback
    assert client._match_sse_event([json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})], 1) is None
    result = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    assert client._match_sse_event([json.dumps(result)], 1) == result
    assert logs and "private-callback-credential" not in repr(logs)

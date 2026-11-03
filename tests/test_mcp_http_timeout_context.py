"""HTTP timeout facts stay structured without promising remote termination."""

from __future__ import annotations

import io
import json
import traceback
import urllib.error
from unittest.mock import patch

import pytest

from lingshu_gate.domain.mcp_request_outcome import McpRequestTimeout
from lingshu_gate.mcp_stdio_client import McpProtocolError
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from test_mcp_downstream_legacy import http_client


SECRET = "http-timeout-private-value"


def timeout_context(error: McpProtocolError) -> dict:
    assert isinstance(error.__cause__, McpRequestTimeout)
    details = error.__cause__.details
    assert details["transport"] == "streamable_http"
    assert details["recovery_supported"] is False
    assert details["recovery_scope"] == "none"
    assert details["execution_terminated"] is False
    assert len(details["request_handle"]) == 32
    assert len(details["connection_generation"]) == 32
    assert SECRET not in "".join(traceback.format_exception(error))
    assert SECRET not in repr(details)
    return details


@pytest.mark.parametrize("wrapped", [False, True])
def test_open_timeout_is_unknown_dispatch_without_replay_or_sensitive_reason(tmp_path, wrapped):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", MCP_PROTOCOL_VERSION)
    client.manifest.transport.headers = {"Authorization": f"Bearer {SECRET}"}
    logs = []
    client.log_sink = lambda *args: logs.append(args)
    failure = TimeoutError(f"private endpoint or header: {SECRET}")
    if wrapped:
        failure = urllib.error.URLError(failure)
    with patch.object(client._opener, "open", side_effect=failure) as opened:
        with pytest.raises(McpProtocolError, match="absolute deadline") as caught:
            client.call_tool("synthetic_write", {"value": SECRET})
    details = timeout_context(caught.value)
    assert details["method"] == "tools/call"
    assert details["business_request"] is True
    assert details["phase"] == "connect_or_send"
    assert details["dispatch_state"] == "unknown"
    assert details["execution_state"] == "unknown"
    assert opened.call_count == 1
    assert SECRET not in repr(logs)


class _ReadTimeout(io.BytesIO):
    def __init__(self, content_type: str) -> None:
        super().__init__()
        self.headers = {"Content-Type": content_type}
        self.status = 200

    def read1(self, size: int = -1) -> bytes:
        raise TimeoutError(f"private peer output: {SECRET}")


@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream"])
def test_read_timeout_reports_sent_request_and_closes_response(tmp_path, content_type):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", MCP_PROTOCOL_VERSION)
    response = _ReadTimeout(content_type)
    with patch.object(client._opener, "open", return_value=response) as opened:
        with pytest.raises(McpProtocolError, match="response exceeded its absolute deadline") as caught:
            client.call_tool("synthetic_write", {})
    details = timeout_context(caught.value)
    assert details["phase"] == "downstream_response"
    assert details["dispatch_state"] == "sent"
    assert details["execution_state"] == "unknown"
    assert response.closed
    assert opened.call_count == 1


def test_expired_operation_before_dispatch_cannot_claim_remote_work_started(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", MCP_PROTOCOL_VERSION)
    client._operation_deadline = 0.0
    with patch.object(client._opener, "open") as opened:
        with pytest.raises(McpProtocolError, match="absolute deadline") as caught:
            client.call_tool("synthetic_write", {})
    details = timeout_context(caught.value)
    assert details["phase"] == "prepare"
    assert details["dispatch_state"] == "not_dispatched"
    assert details["execution_state"] == "not_started"
    opened.assert_not_called()


def test_handshake_timeout_does_not_imply_business_dispatch(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch.object(client._opener, "open", side_effect=TimeoutError(SECRET)) as opened:
        with pytest.raises(McpProtocolError, match="absolute deadline") as caught:
            client.start()
    details = timeout_context(caught.value)
    assert details["method"] == "server/discover"
    assert details["business_request"] is False
    assert details["execution_state"] == "not_started"
    assert opened.call_count == 1
    assert not client.initialized


def test_handshake_budget_expired_before_send_retains_safe_context(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", None)
    with patch("lingshu_gate.mcp_http_client.time.monotonic", side_effect=[100.0, 104.0]), \
         patch.object(client._opener, "open") as opened:
        with pytest.raises(McpProtocolError, match="handshake exceeded its absolute deadline") as caught:
            client.start()
    details = timeout_context(caught.value)
    assert details["method"] == "server/discover"
    assert details["phase"] == "handshake"
    assert details["dispatch_state"] == "not_dispatched"
    assert details["business_request"] is False
    assert details["execution_state"] == "not_started"
    opened.assert_not_called()


def test_request_handles_are_unique_and_new_connection_has_new_generation(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", MCP_PROTOCOL_VERSION)

    def reply(request, *, timeout):
        message = json.loads(request.data)
        if message["method"] == "tools/call":
            raise TimeoutError(SECRET)
        body = {"jsonrpc": "2.0", "id": message["id"], "result": {
            "supportedVersions": [MCP_PROTOCOL_VERSION], "capabilities": {},
        }}
        result = io.BytesIO(json.dumps(body).encode())
        result.headers = {"Content-Type": "application/json"}
        result.status = 200
        return result

    outcomes = []
    with patch.object(client._opener, "open", side_effect=reply):
        client.start()
        for _ in range(2):
            with pytest.raises(McpProtocolError) as caught:
                client.call_tool("synthetic_write", {})
            outcomes.append(timeout_context(caught.value))
        client.stop()
        client.start()
        with pytest.raises(McpProtocolError) as caught:
            client.call_tool("synthetic_write", {})
        outcomes.append(timeout_context(caught.value))
        client.stop()
    assert len({item["request_handle"] for item in outcomes}) == 3
    assert outcomes[0]["connection_generation"] == outcomes[1]["connection_generation"]
    assert outcomes[1]["connection_generation"] != outcomes[2]["connection_generation"]


def test_network_error_text_is_not_misclassified_as_timeout(tmp_path):
    client = http_client(tmp_path, "https://mcp.example.test/mcp", MCP_PROTOCOL_VERSION)
    with patch.object(client._opener, "open", side_effect=urllib.error.URLError("peer says timed out")):
        with pytest.raises(McpProtocolError) as caught:
            client.call_tool("synthetic_write", {})
    assert not isinstance(caught.value.__cause__, McpRequestTimeout)

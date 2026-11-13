"""Wire-level gateway subscriptions with real authentication and access policy."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest
import uvicorn
from mcp.types import SubscriptionsAcknowledgedNotification, SubscriptionsListenResult

from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.tool_catalog import CATALOG_TOOL_NAMES, ToolCatalog
from lingshu_gate.transports.http import build_protocol_request
from test_builtin_oauth import gate as gate


@pytest.fixture
def streaming_gateway(gate, monkeypatch):
    monkeypatch.setattr("lingshu_gate.mcp_notifications.NOTIFICATION_CHECK_SECONDS", 0.02)
    monkeypatch.setattr("lingshu_gate.mcp_notifications.NOTIFICATION_HEARTBEAT_SECONDS", 0.06)
    monkeypatch.setattr("lingshu_gate.mcp_notifications.NOTIFICATION_LIFETIME_SECONDS", 10.0)
    catalog = ToolCatalog(gate["registry"], gate["access"])
    catalog.synchronize()
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
                               gate["auth"].authenticate_mcp_request, catalog=catalog)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(gate["app"], host="127.0.0.1", port=port, lifespan="off",
                                           log_level="critical", timeout_graceful_shutdown=1))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 3
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield gate, f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=3)
        listener.close()
        assert not thread.is_alive()


def credential(gate, *, mode="direct"):
    token = gate["auth"].create_api_token(principal=gate["principals"]["alice"], name="Synthetic notification client",
                                          scopes=["tools.read", "tools.invoke"])
    gate["db"].execute("INSERT INTO authorization_discovery(kind,authorization_id,mode,revision) VALUES('api',?,?,1)",
                       (token["id"], mode))
    return token


def rpc(endpoint, token, method, params=None, *, version=MCP_PROTOCOL_VERSION):
    prepared, headers = build_protocol_request(method, params or {}, client_name="independent-test", client_version="1",
                                                protocol_version=version)
    headers.update({"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    data = json.dumps({"jsonrpc": "2.0", "id": 17, "method": method, "params": prepared}).encode()
    return urllib.request.Request(endpoint, data=data, headers=headers, method="POST")


@contextmanager
def stream(endpoint, token, version=MCP_PROTOCOL_VERSION, *, notifications=None):
    if version == MCP_PROTOCOL_VERSION:
        request = rpc(endpoint, token, "subscriptions/listen", {"notifications":
                      {"toolsListChanged": True} if notifications is None else notifications})
        request.add_header("Accept", "application/json, text/event-stream")
    else:
        request = urllib.request.Request(endpoint, headers={"Authorization": "Bearer " + token,
            "MCP-Protocol-Version": version, "Accept": "text/event-stream"}, method="GET")
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 200 and response.headers.get_content_type() == "text/event-stream"
        yield response


def frame(response):
    lines = []
    while True:
        line = response.readline()
        if not line:
            return None
        if line in {b"\n", b"\r\n"}:
            return lines
        lines.append(line.rstrip(b"\r\n"))


def message(response):
    while (lines := frame(response)) is not None:
        data = [line[5:].lstrip() for line in lines if line.startswith(b"data:")]
        if data:
            return json.loads(b"\n".join(data))
    return None


def accepted(response, version):
    if version == MCP_PROTOCOL_VERSION:
        first = message(response)
        SubscriptionsAcknowledgedNotification.model_validate(first, by_name=False)
        assert first["method"] == "notifications/subscriptions/acknowledged"
        assert first["params"]["notifications"] == {"toolsListChanged": True}
        assert first["params"]["_meta"]["io.modelcontextprotocol/subscriptionId"] == 17
    else:
        assert frame(response) == [b": connected"]


def only_heartbeats(response, count=2):
    for _ in range(count):
        assert frame(response) == [b": keepalive"]


def listed(endpoint, token):
    with urllib.request.urlopen(rpc(endpoint, token, "tools/list"), timeout=2) as response:
        return json.load(response)["result"]["tools"]


@pytest.mark.parametrize("version", ["2025-06-18", MCP_PROTOCOL_VERSION])
def test_only_currently_visible_catalog_changes_notify_without_running_tools(streaming_gateway, version):
    gate, endpoint = streaming_gateway
    token = credential(gate)
    with stream(endpoint, token["token"], version) as response:
        accepted(response, version)
        before = listed(endpoint, token["token"])
        hidden = gate["registry"].get_definition("mcp.B.read")
        gate["registry"].update_definition(hidden.model_copy(update={"description": "hidden-private-schema-change"}))
        only_heartbeats(response)
        assert listed(endpoint, token["token"]) == before

        visible = gate["registry"].get_definition("mcp.A.read")
        gate["registry"].update_definition(visible.model_copy(update={"description": "Visible description changed"}))
        notification = message(response)
        assert notification["method"] == "notifications/tools/list_changed"
        assert set(notification) == ({"jsonrpc", "method", "params"} if version == MCP_PROTOCOL_VERSION else {"jsonrpc", "method"})
        assert "hidden-private" not in json.dumps(notification) and "mcp." not in json.dumps(notification)
        if version == MCP_PROTOCOL_VERSION:
            assert notification["params"] == {"_meta": {"io.modelcontextprotocol/subscriptionId": 17}}
        assert any(item["description"] == "Visible description changed" for item in listed(endpoint, token["token"]))
        only_heartbeats(response)
        assert gate["db"].query_one("SELECT COUNT(*) FROM invocation_audits")[0] == 0


@pytest.mark.parametrize("revocation", ["token", "expiry", "user"])
def test_stream_reauthenticates_and_closes_after_revocation_or_expiry(streaming_gateway, revocation):
    gate, endpoint = streaming_gateway
    token = credential(gate)
    with stream(endpoint, token["token"]) as response:
        accepted(response, MCP_PROTOCOL_VERSION)
        started = time.monotonic()
        if revocation == "token":
            gate["auth"].revoke_api_token(token["id"], user_id=gate["principals"]["alice"].id)
        elif revocation == "expiry":
            gate["db"].execute("UPDATE api_tokens SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (token["id"],))
        else:
            gate["db"].execute("UPDATE users SET status='disabled' WHERE id=?", (gate["principals"]["alice"].id,))
        assert message(response) is None  # no result or private error after authorization fails
        assert time.monotonic() - started < 1.5
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(rpc(endpoint, token["token"], "tools/list"), timeout=2)
    assert error.value.code == 401
    error.value.close()


def test_on_demand_ignores_hidden_catalog_churn_but_notifies_saved_view_changes(streaming_gateway):
    gate, endpoint = streaming_gateway
    token = credential(gate, mode="on_demand")
    grants = [tuple(row) for row in gate["db"].query_all("SELECT * FROM mcp_resource_grants ORDER BY id")]
    # Token-owned settings take precedence on subscriptions exactly as on tools/list.
    endpoint += "?tool_mode=direct"
    with stream(endpoint, token["token"]) as response:
        accepted(response, MCP_PROTOCOL_VERSION)
        assert [item["name"] for item in listed(endpoint, token["token"])] == list(CATALOG_TOOL_NAMES)
        gate["registry"].register(ToolDefinition(id="mcp.A.new", name="New", source="mcp", permission="write",
            description="New business tool", metadata={"server_id": "A", "original_tool_name": "new"}), lambda _: {})
        only_heartbeats(response)
        gate["db"].execute("INSERT INTO authorization_tool_preferences VALUES('api',?,?,?)", (token["id"],
            json.dumps([{"kind": "tool", "tool_ref": "mcp.A.read"}]), json.dumps({"enabled": False})))
        assert message(response)["method"] == "notifications/tools/list_changed"
        assert any(item["name"].startswith("gate_pinned_") for item in listed(endpoint, token["token"]))
        gate["db"].execute("UPDATE authorization_discovery SET mode='direct', revision=revision+1 WHERE authorization_id=?",
                           (token["id"],))
        assert message(response)["method"] == "notifications/tools/list_changed"
        assert "mcp__A__new" in {item["name"] for item in listed(endpoint, token["token"])}
    assert [tuple(row) for row in gate["db"].query_all("SELECT * FROM mcp_resource_grants ORDER BY id")] == grants


def test_subscription_acknowledges_only_supported_requested_notifications(streaming_gateway):
    gate, endpoint = streaming_gateway
    token = credential(gate)
    with stream(endpoint, token["token"], notifications={"promptsListChanged": True}) as response:
        first = message(response)
        SubscriptionsAcknowledgedNotification.model_validate(first, by_name=False)
        assert first["params"]["notifications"] == {}
        final = message(response)
        assert final["id"] == 17 and final["result"]["resultType"] == "complete"
        SubscriptionsListenResult.model_validate(final["result"], by_name=False)
        assert message(response) is None


@pytest.mark.parametrize("params", [{}, {"notifications": True}, {"notifications": {"toolsListChanged": "true"}},
                                    {"notifications": {"resourcesListChanged": 1}}])
def test_subscription_filter_is_validated_without_coercion(streaming_gateway, params):
    gate, endpoint = streaming_gateway
    token = credential(gate)
    request = rpc(endpoint, token["token"], "subscriptions/listen", params)
    request.add_header("Accept", "text/event-stream")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=2)
    assert error.value.code == 400
    assert json.load(error.value)["error"]["code"] == -32602
    error.value.close()


def test_subscription_validation_errors_do_not_expose_exception_details(streaming_gateway, monkeypatch):
    gate, endpoint = streaming_gateway
    token = credential(gate)

    def reject(_params):
        raise ValueError("private-parser-canary /private/config Traceback: internal validation")

    monkeypatch.setattr("lingshu_gate.mcp_gateway.subscription_tools_requested", reject)
    request = rpc(endpoint, token["token"], "subscriptions/listen", {"notifications": {"toolsListChanged": True}})
    request.add_header("Accept", "text/event-stream")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=2)
    try:
        assert error.value.code == 400
        payload = json.load(error.value)
        assert payload["error"] == {"code": -32602, "message": "Invalid notification subscription parameters"}
        assert "private-parser-canary" not in json.dumps(payload)
    finally:
        error.value.close()


def test_get_preserves_authentication_origin_version_and_accept_boundaries(streaming_gateway):
    gate, endpoint = streaming_gateway
    token = credential(gate)
    common = {"Authorization": "Bearer " + token["token"], "Accept": "text/event-stream",
              "MCP-Protocol-Version": "2025-11-25"}
    cases = [({"Authorization": "Bearer invalid"}, 401), ({"Origin": "https://untrusted.invalid"}, 403),
             ({"MCP-Protocol-Version": "2099-01-01"}, 400), ({"MCP-Protocol-Version": MCP_PROTOCOL_VERSION}, 405),
             ({"Accept": "application/json"}, 406)]
    for override, status in cases:
        request = urllib.request.Request(endpoint, headers={**common, **override}, method="GET")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        assert error.value.code == status
        error.value.close()
    request = rpc(endpoint, token["token"], "subscriptions/listen", {"notifications": {"toolsListChanged": True}},
                  version="2025-11-25")
    request.add_header("Accept", "text/event-stream")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=2)
    assert error.value.code == 404 and json.load(error.value)["error"]["code"] == -32601
    error.value.close()


def test_notification_admission_is_bounded_and_released_on_disconnect(streaming_gateway, monkeypatch):
    gate, endpoint = streaming_gateway
    token = credential(gate)
    monkeypatch.setattr("lingshu_gate.mcp_notifications.MAX_NOTIFICATION_STREAMS_PER_IDENTITY", 1)
    with stream(endpoint, token["token"]) as response:
        accepted(response, MCP_PROTOCOL_VERSION)
        with pytest.raises(urllib.error.HTTPError) as error:
            with stream(endpoint, token["token"]):
                pytest.fail("second stream must not be admitted")
        assert error.value.code == 429
        error.value.close()
    deadline = time.monotonic() + 1.5
    while True:
        try:
            with stream(endpoint, token["token"]) as response:
                accepted(response, MCP_PROTOCOL_VERSION)
            break
        except urllib.error.HTTPError as error:
            error.close()
            if error.code != 429 or time.monotonic() >= deadline:
                raise
            time.sleep(0.02)

"""旧版 Streamable HTTP 握手与逐请求安全边界回归。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.protocol.request import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_META_KEY
from lingshu_gate.registry import ToolRegistry

VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")


class AccessStore:
    allowed = True
    invocations = 0

    def visible_tools(self, principal, definitions):
        return definitions if self.allowed else []

    def invoke_tool(self, registry, principal, tool_id, arguments):
        if not self.allowed:
            raise AccessDeniedError("revoked", required_access="read", granted_access="none")
        self.invocations += 1
        return registry.invoke(tool_id, arguments)


@pytest.fixture
def gateway():
    app = FastAPI()
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            id="test.echo", name="Echo", description="Echo", permission="read",
            input_schema={"type": "object", "properties": {}}, source="test",
        ),
        lambda arguments: {"echo": arguments},
    )
    store = AccessStore()

    def authenticate(request: Request) -> AuthPrincipal:
        if request.headers.get("authorization") != "Bearer test-token":
            raise HTTPException(status_code=401, detail="authentication required")
        return AuthPrincipal(id="legacy-test", username="legacy-test", role="viewer")

    register_mcp_gateway_route(app, Settings(), registry, store, authenticate)
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        yield client, store


def initialize(version="2025-11-25"):
    return {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": version, "capabilities": {},
            "clientInfo": {"name": "legacy-test", "version": "1.0"},
        },
    }


@pytest.mark.parametrize("version", VERSIONS)
def test_legacy_initialize_notify_list_call_and_ping(gateway, version):
    client, store = gateway
    response = client.post("/mcp", json=initialize(version))
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["protocolVersion"] == version
    assert result["serverInfo"]["name"] == "lingshu_gate"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert "mcp-session-id" not in response.headers
    headers = {"MCP-Protocol-Version": version}
    notification = client.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notification.status_code == 202
    assert not notification.content
    listing = client.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert listing.headers["MCP-Protocol-Version"] == version
    assert [tool["name"] for tool in listing.json()["result"]["tools"]] == ["test__echo"]
    assert "resultType" not in listing.json()["result"]
    assert "cacheScope" not in listing.json()["result"]
    invocation = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "test__echo", "arguments": {"value": "hello"}},
    })
    output = invocation.json()["result"]
    assert output["isError"] is False
    assert "hello" in output["content"][0]["text"]
    assert "resultType" not in output
    assert output["structuredContent"] == {"echo": {"value": "hello"}}
    assert store.invocations == 1
    ping = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 4, "method": "ping"})
    assert ping.json()["result"] == {}


def test_initialize_negotiates_unknown_proposal(gateway):
    client, _ = gateway
    response = client.post("/mcp", json=initialize("2099-01-01"))
    assert response.json()["result"]["protocolVersion"] == VERSIONS[-1]


def test_missing_header_uses_streamable_http_compatibility_default(gateway):
    client, _ = gateway
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 200
    assert response.headers["MCP-Protocol-Version"] == "2025-03-26"


@pytest.mark.parametrize("params", [None, {}, [], {"protocolVersion": "2025-11-25"}])
def test_malformed_initialize_is_rejected(gateway, params):
    client, store = gateway
    message = initialize()
    message["params"] = params
    response = client.post("/mcp", json=message)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32602
    assert store.invocations == 0


def test_initialize_cannot_be_notification(gateway):
    client, _ = gateway
    message = initialize()
    del message["id"]
    response = client.post("/mcp", json=message)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


def test_unknown_header_and_modern_metadata_cannot_downgrade(gateway):
    client, store = gateway
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    response = client.post("/mcp", headers={"MCP-Protocol-Version": "2099-01-01"}, json=request)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32022
    for meta in ({PROTOCOL_META_KEY: "2026-07-28"}, {CLIENT_CAPABILITIES_META_KEY: {}}):
        request["params"] = {"_meta": meta}
        for headers in ({}, {"MCP-Protocol-Version": "2025-11-25"}):
            response = client.post("/mcp", headers=headers, json=request)
            assert response.status_code == 400
    assert store.invocations == 0


def test_legacy_requests_keep_auth_origin_and_revocation_checks(gateway):
    client, store = gateway
    assert client.post("/mcp", json=initialize()).status_code == 200
    headers = {"MCP-Protocol-Version": "2025-11-25"}
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "test__echo"}}
    for message in (initialize(), request, {"jsonrpc": "2.0", "method": "notifications/initialized"}):
        denied = client.post("/mcp", headers={**headers, "Authorization": "Bearer invalid"}, json=message)
        assert denied.status_code == 401
        origin = client.post("/mcp", headers={**headers, "Origin": "https://untrusted.invalid"}, json=message)
        assert origin.status_code == 403
    store.allowed = False
    listing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert listing.json()["result"]["tools"] == []
    denied = client.post("/mcp", headers=headers, json=request)
    assert denied.json()["result"]["isError"] is True
    assert store.invocations == 0

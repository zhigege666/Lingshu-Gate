"""Owner-visible OAuth exclusions and newly discovered MCPs, without external credentials."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_server import OAuthError
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, PASSWORD, RESOURCE, enable, exchange, issue_code, refresh
from test_builtin_oauth import gate as gate


def admin_grant(gate):
    username = gate["admin"]["username"]
    principal, session, _ = gate["auth"].login(username=username, password=PASSWORD)
    _, consent_session, _ = gate["auth"].login(username=username, password=PASSWORD, purpose="oauth_consent")
    gate["principals"]["admin"], gate["sessions"]["admin"] = principal, session
    gate["users"]["admin"], gate["oauth_sessions"]["admin"] = gate["admin"], consent_session
    client, secret = enable(gate)
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client, user="admin", tools=["mcp.A.read", "mcp.A.write"]))
    grant = gate["server"].store.grants(principal.id)[0]
    return principal, session, client, secret, grant, tokens


def discover(gate, server_id="synthetic-plane"):
    for name in ("list", "project"):
        gate["registry"].register(ToolDefinition(id=f"mcp.{server_id}.{name}", name=name, source="mcp",
            description="Synthetic mixed-operation tool", permission="read", metadata={
                "server_id": server_id, "server_name": "Synthetic Plane", "original_tool_name": name,
                "annotations": {"readOnlyHint": True}}), lambda arguments: None)
    gate["access"].synchronize_tools(gate["registry"].list_definitions())


def publish(gate, server_id="synthetic-plane"):
    for name, access in (("list", "read"), ("project", "write")):
        gate["access"].set_classification(server_id=server_id, tool_id=f"mcp.{server_id}.{name}", access=access,
            destructive=False, idempotent=False, reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id=server_id, reviewer_id=gate["admin"]["id"])


def test_admin_api_token_calls_unpublished_new_mcp_while_oauth_explains_publication_gate(gate):
    principal, session, _, _, grant, tokens = admin_grant(gate)
    discover(gate)
    calls = []

    class SyntheticRuntime:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, **kwargs):
            calls.append((server_id, tool_name, user_id))
            return {"content": [{"type": "text", "text": "Synthetic successful invocation"}]}

    gate["access"].attach_mcp_runtime(SyntheticRuntime())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"], gate["auth"].authenticate_mcp_request,
        McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    api = gate["auth"].create_api_token(principal=principal, name="Synthetic admin API", scopes=["tools.read", "tools.invoke"])
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        params, headers = build_protocol_request("tools/call", {"name": "mcp__synthetic-plane__project", "arguments": {}},
            client_name="Synthetic", client_version="1", protocol_version="2026-07-28")
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
        called = browser.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer " + str(api["token"])})
        assert called.status_code == 200 and not called.json()["result"].get("isError", False)
        assert calls == [("synthetic-plane", "project", principal.id)]
        denied = browser.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer " + tokens["access_token"]})
        assert denied.json()["result"]["isError"] and len(calls) == 1
        browser.cookies.set(gate["auth"].cookie_name, session)
        response = browser.get(f"/v1/auth/oauth/grants/{grant['id']}/scope-options")
        assert response.headers["cache-control"] == "no-store"
        offered = response.json()
    assert all(tool["server_id"] != "synthetic-plane" for tool in offered["tools"])
    assert offered["unavailable_servers"] == [{"server_id": "synthetic-plane", "server_name": "Synthetic Plane",
        "reasons": [{"code": "classification_not_published", "count": 2}]}]
    assert offered["can_review_classifications"] is True
    with pytest.raises(OAuthError, match="tool_scope_changed"):
        gate["server"].preview_scope(principal, grant["id"], session, offered["csrf"], grant["revision"],
            ["mcp.A.read", "mcp.synthetic-plane.project"], grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])


def test_fresh_options_include_published_new_service_and_cannot_expand_old_read_only_family(gate):
    principal, session, client, secret, grant, tokens = admin_grant(gate)
    read_only = refresh(gate["server"], client, secret, tokens["refresh_token"], scope="tools.read")
    discover(gate)
    before = gate["server"].scope_options(principal, grant["id"], session)
    publish(gate)
    offered = gate["server"].scope_options(principal, grant["id"], session)
    new = [tool for tool in offered["tools"] if tool["server_id"] == "synthetic-plane"]
    assert {tool["id"]: tool["access"] for tool in new} == {"mcp.synthetic-plane.list": "read", "mcp.synthetic-plane.project": "write"}
    assert offered["unavailable_servers"] == []
    assert offered["family_scope_limits"] == [{"scopes": ["tools.read"], "count": 1}]
    ids = list(grant["tools"]) + [tool["id"] for tool in new]
    with pytest.raises(OAuthError, match="tool_scope_changed"):
        gate["server"].preview_scope(principal, grant["id"], session, before["csrf"], grant["revision"], ids,
            grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])
    prepared = gate["server"].preview_scope(principal, grant["id"], session, offered["csrf"], grant["revision"], ids,
        grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])
    gate["server"].update_scope(principal, grant["id"], session, prepared["confirmation"], grant["revision"], ids,
        grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])
    assert set(gate["server"].verify(read_only["access_token"]).external_tool_ids) == {"mcp.A.read", "mcp.synthetic-plane.list"}
    with pytest.raises(OAuthError, match="invalid_scope"):
        refresh(gate["server"], client, secret, read_only["refresh_token"], scope="tools.read tools.invoke")


def test_diagnostics_distinguish_grant_and_client_ceilings_without_listing_invisible_services(gate):
    client, _ = enable(gate)
    issue_code(gate, client)
    grant = gate["server"].store.grants(gate["users"]["alice"]["id"])[0]
    discover(gate, "synthetic-private-service")
    offered = gate["server"].scope_options(gate["principals"]["alice"], grant["id"], gate["sessions"]["alice"])
    assert offered["unavailable_servers"] == [{"server_id": "A", "server_name": "Synthetic service A",
        "reasons": [{"code": "grant_scope_ceiling", "count": 1}]}]
    assert "synthetic-private-service" not in json.dumps(offered) and '"server_id": "B"' not in json.dumps(offered)
    assert offered["can_review_classifications"] is False
    mixed_code = issue_code(gate, client, tools=["mcp.A.read", "mcp.A.write"])
    assert mixed_code
    mixed = next(item for item in gate["server"].store.grants(gate["users"]["alice"]["id"]) if item["id"] != grant["id"])
    gate["server"].update_client(client["id"], client["revision"], name=client["name"], redirects=client["redirect_uris"], scopes=["tools.read"], enabled=True)
    current = gate["server"].scope_options(gate["principals"]["alice"], mixed["id"], gate["sessions"]["alice"])
    assert current["effective_scopes"] == ["tools.read"]
    assert current["unavailable_servers"] == [{"server_id": "A", "server_name": "Synthetic service A",
        "reasons": [{"code": "client_scope_ceiling", "count": 1}]}]

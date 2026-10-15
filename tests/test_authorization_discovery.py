"""真实授权存储及 ASGI 验证发现方式、会话和原子保存边界。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.authorization_discovery import discovery_setting, register_authorization_discovery_routes
from lingshu_gate.external_connection_store import ExternalConnectionStore
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.tool_catalog import CATALOG_TOOL_NAMES, ToolCatalog
from lingshu_gate.transports.http import build_protocol_request
from test_builtin_oauth import ISSUER, gate as gate
from test_oauth_live_scope import initial
from test_token_authorizations import save, tokens as tokens


@pytest.fixture
def browser(gate):
    register_authorization_discovery_routes(gate["app"], gate["auth"], gate["access"], ObservabilityStore(gate["db"]))
    with TestClient(gate["app"], base_url=ISSUER) as client:
        client.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        yield client


def setting_path(kind, authorization_id):
    return f"/v1/auth/authorizations/{kind}/{authorization_id}/discovery"


def preview(client, kind, authorization_id, mode):
    path = setting_path(kind, authorization_id)
    offered = client.get(path)
    assert offered.status_code == 200, offered.text
    state = offered.json()
    body = {"tool_discovery_mode": mode, "expected_revision": state["discovery_revision"], "csrf": state["csrf"]}
    response = client.post(path + "-preview", json=body, headers={"Origin": ISSUER})
    assert response.status_code == 200, response.text
    return {**body, "csrf": response.json()["csrf"]}


def set_mode(client, kind, authorization_id, mode):
    body = preview(client, kind, authorization_id, mode)
    response = client.post(setting_path(kind, authorization_id), json=body, headers={"Origin": ISSUER})
    assert response.status_code == 200, response.text
    return response.json()


def legacy(gate, name="Synthetic legacy"):
    return gate["auth"].create_api_token(principal=gate["principals"]["alice"], name=name, scopes=["tools.read"])


def rpc(client, token, method="tools/list", params=None, suffix="", mode_headers=()):
    prepared, headers = build_protocol_request(method, params, client_name="Synthetic", client_version="1")
    return client.post("/mcp" + suffix, headers=[*headers.items(), ("Authorization", "Bearer " + token), *mode_headers],
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared})


def test_new_and_legacy_tokens_default_on_demand_and_are_independent(browser, tokens, gate):
    old, new = legacy(gate), save(tokens, gate, tool_ids=["mcp.A.read"])
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request, catalog=ToolCatalog(gate["registry"], gate["access"]))
    for token in (old, new):
        assert [item["name"] for item in rpc(browser, token["token"]).json()["result"]["tools"]] == list(CATALOG_TOOL_NAMES)
        assert [item["name"] for item in rpc(browser, token["token"], suffix="?tool_mode=direct").json()["result"]["tools"]] == list(CATALOG_TOOL_NAMES)
    set_mode(browser, "api", old["id"], "direct")
    assert {item["name"] for item in rpc(browser, old["token"]).json()["result"]["tools"]} == {"mcp__A__read"}
    assert len(rpc(browser, new["token"]).json()["result"]["tools"]) == 6
    assert {item["name"] for item in rpc(browser, old["token"], suffix="?tool_mode=on_demand").json()["result"]["tools"]} == {"mcp__A__read"}
    set_mode(browser, "api", old["id"], "on_demand")
    assert len(rpc(browser, old["token"]).json()["result"]["tools"]) == 6
    assert all(item["tool_discovery_mode"] == "on_demand" for item in gate["auth"].list_api_tokens())


@pytest.mark.parametrize("mode", ["on_demand", "direct"])
def test_legacy_query_and_headers_are_ignored_for_business_authorizations(browser, gate, mode):
    token = legacy(gate)
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request, catalog=ToolCatalog(gate["registry"], gate["access"]))
    set_mode(browser, "api", token["id"], mode)
    expected = set(CATALOG_TOOL_NAMES) if mode == "on_demand" else {"mcp__A__read"}
    cases = [
        ("?tool_mode=direct", ()),
        ("?tool_mode=on_demand", ()),
        ("?tool_mode=unknown", ()),
        ("?tool_mode=direct&tool_mode=on_demand", ()),
        ("?tool_mode=direct", (("X-Gate-Tool-Mode", "on_demand"),)),
        ("", (("X-Gate-Tool-Mode", "unknown"),)),
        ("", (("X-Gate-Tool-Mode", "direct"), ("X-Gate-Tool-Mode", "on_demand"))),
    ]
    for suffix, headers in cases:
        response = rpc(browser, token["token"], suffix=suffix, mode_headers=headers)
        assert response.status_code == 200, response.text
        assert {item["name"] for item in response.json()["result"]["tools"]} == expected


def test_modes_do_not_reapprove_scope_or_reset_token_policy(browser, tokens, gate):
    token = save(tokens, gate, tool_ids=["mcp.A.read"])
    before = dict(gate["db"].query_one("SELECT * FROM api_token_authorizations WHERE token_id=?", (token["id"],)))
    gate["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE tool_id='mcp.A.read'")
    set_mode(browser, "api", token["id"], "direct")
    assert dict(gate["db"].query_one("SELECT * FROM api_token_authorizations WHERE token_id=?", (token["id"],))) == before


def test_origin_session_owner_and_strict_modes_are_required(browser, gate):
    token = legacy(gate)
    path = setting_path("api", token["id"])
    offered = browser.get(path).json()
    body = {"tool_discovery_mode": "direct", "expected_revision": 0, "csrf": offered["csrf"]}
    assert browser.post(path + "-preview", json=body).status_code == 403
    for mode in ["invalid", None, 1, True]:
        assert browser.post(path + "-preview", json={**body, "tool_discovery_mode": mode}, headers={"Origin": ISSUER}).status_code == 422
    assert browser.get(path, headers={"Authorization": "Bearer " + token["token"]}).status_code == 403
    browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["bob"])
    assert browser.get(path).status_code == 404


def test_confirmations_bind_mode_revision_record_and_are_single_use(browser, gate):
    token = legacy(gate)
    path = setting_path("api", token["id"])
    body = preview(browser, "api", token["id"], "direct")
    assert browser.post(path, json={**body, "tool_discovery_mode": "on_demand"}, headers={"Origin": ISSUER}).status_code == 409
    assert browser.post(path, json=body, headers={"Origin": ISSUER}).status_code == 200
    assert browser.post(path, json=body, headers={"Origin": ISSUER}).status_code == 409
    body = preview(browser, "api", token["id"], "on_demand")
    gate["auth"].revoke_api_token(token["id"], user_id=gate["principals"]["alice"].id)
    assert browser.post(path, json=body, headers={"Origin": ISSUER}).status_code == 409


def test_audit_failure_rolls_back_setting_and_confirmation(browser, gate):
    token = legacy(gate)
    path = setting_path("api", token["id"])
    body = preview(browser, "api", token["id"], "direct")
    gate["db"].execute("CREATE TRIGGER reject_discovery_audit BEFORE INSERT ON events WHEN NEW.type='gate.auth.discovery_updated' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
    with pytest.raises(Exception, match="synthetic audit failure"):
        browser.post(path, json=body, headers={"Origin": ISSUER})
    with gate["db"].session() as connection:
        assert discovery_setting(connection, "api", token["id"])["tool_discovery_mode"] == "on_demand"
    gate["db"].execute("DROP TRIGGER reject_discovery_audit")
    assert browser.post(path, json=body, headers={"Origin": ISSUER}).status_code == 200


def test_oauth_and_external_grants_have_separate_modes(browser, gate):
    _, _, grant, token = initial(gate)
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request, catalog=ToolCatalog(gate["registry"], gate["access"]))
    assert len(rpc(browser, token["access_token"]).json()["result"]["tools"]) == 6
    assert len(rpc(browser, token["access_token"], suffix="?tool_mode=direct", mode_headers=(("X-Gate-Tool-Mode", "unknown"),)).json()["result"]["tools"]) == 6
    external = ExternalConnectionStore(gate["db"])
    payload = {"client_id": "synthetic-external", "enabled": True, "server_allowlist": ["A"], "tool_allowlist": ["mcp.A.read"],
        "access": ["read"], "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "rate_per_minute": 6000, "concurrency": 100}
    external_grant = external.create_grant(gate["principals"]["alice"].id, payload)
    set_mode(browser, "builtin", grant["id"], "direct")
    assert {item["name"] for item in rpc(browser, token["access_token"]).json()["result"]["tools"]} == {"mcp__A__read"}
    assert browser.get(setting_path("external", external_grant["id"])).json()["tool_discovery_mode"] == "on_demand"
    set_mode(browser, "external", external_grant["id"], "direct")
    assert external.list_grants(gate["principals"]["alice"].id)[0]["tool_discovery_mode"] == "direct"
    assert gate["server"].verify(token["access_token"]).external_tool_ids == ("mcp.A.read",)
    assert gate["server"].store.grants(grant["user_id"])[0]["tool_discovery_mode"] == "direct"
    # 管理资源不能借业务发现设置切换入口。
    gate["db"].execute("UPDATE gate_oauth_grants SET resource=? WHERE id=?", (ISSUER + "/mcp/manage", grant["id"]))
    assert browser.get(setting_path("builtin", grant["id"])).status_code == 409
    assert json.loads(gate["db"].query_one("SELECT payload_json FROM user_external_grant_drafts WHERE id=?", (external_grant["id"],))[0]) == payload


def test_on_demand_dispatch_rechecks_mode_after_waiting(browser, gate):
    token = legacy(gate)
    calls = []

    class SyntheticPeer:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, dispatch_guard=None, **kwargs):
            # 模拟排队期间另一请求保存发现设置，不伪造生产权限类型。
            gate["db"].execute("INSERT INTO authorization_discovery VALUES('api',?,'direct',1)", (token["id"],))
            if dispatch_guard:
                dispatch_guard()
            calls.append(tool_name)
            return {"content": []}

    gate["access"].attach_mcp_runtime(SyntheticPeer())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request, catalog=ToolCatalog(gate["registry"], gate["access"]))
    described = rpc(browser, token["token"], "tools/call", {"name": "gate_tool_describe", "arguments": {"tool_ref": "mcp.A.read"}}).json()["result"]["structuredContent"]
    rejected = rpc(browser, token["token"], "tools/call", {"name": "gate_tool_invoke", "arguments": {
        "tool_ref": "mcp.A.read", "schema_revision": described["schema_revision"], "arguments": {}}})
    assert rejected.json()["result"]["isError"] and calls == []

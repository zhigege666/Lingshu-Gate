"""Separate management audience, exercised with synthetic ASGI/SQLite fixtures."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.auth import hash_secret
from lingshu_gate.domain.oauth_management import MANAGEMENT_METADATA_PATH, MANAGEMENT_TOOL_IDS
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_server import OAuthError
from lingshu_gate.oauth_store import OAuthStore
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, PASSWORD, REDIRECT, RESOURCE, VERIFIER, enable, exchange, issue_code, mcp_request, parameters
from test_builtin_oauth import gate as gate

MANAGEMENT_RESOURCE = ISSUER + "/mcp/manage"


def setup_management(gate, *, resources=None):
    business, business_secret = enable(gate)
    for tool_id in sorted(MANAGEMENT_TOOL_IDS):
        gate["registry"].register(ToolDefinition(id=tool_id, name=tool_id, source="builtin", description="Synthetic management",
            permission="read" if tool_id in {"gate_mcp_config_plan", "gate_mcp_config_status"} else "write",
            metadata={"server_id": "gate_mcp_configuration"}), lambda arguments: {"synthetic": True})
    server = gate["server"]
    server.save_management_config(True, 0)
    created = server.create_client("Synthetic management client", [REDIRECT],
        ["operations.manage", "tools.invoke", "tools.read"] if resources == ["business", "management"] else ["operations.manage", "tools.invoke"],
        resources=resources or ["management"])
    principal, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD, purpose="oauth_consent")
    gate["management_principal"], gate["management_session"] = principal, session
    return created["client"], created["client_secret"], business, business_secret


def management_code(gate, client, *, scopes="operations.manage tools.invoke", tools=None, targets=None):
    server, browser = gate["server"], "synthetic-management-browser"
    ticket = server.start_authorization(parameters(client, resource=MANAGEMENT_RESOURCE, scope=scopes), browser)
    context = server.consent_context(ticket, browser, gate["management_session"])
    redirect = server.consent(ticket, browser, context["csrf"], gate["management_principal"],
        tools or sorted(MANAGEMENT_TOOL_IDS), 7, 30, 1, management_targets=targets or {"synthetic-external": ["create", "update"]})
    return parse_qs(urlsplit(redirect).query)["code"][0]


def management_tokens(gate, client, secret, **kwargs):
    return exchange(gate["server"], client, secret, management_code(gate, client, **kwargs), resource=MANAGEMENT_RESOURCE)


def register_gateways(gate):
    def business_boundary():
        return McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,)))

    def management_boundary():
        if not gate["server"].store.management_config()["active"]:
            return None
        return McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(MANAGEMENT_RESOURCE, (ISSUER,),
            ("operations.manage", "tools.invoke")), metadata_path=MANAGEMENT_METADATA_PATH)

    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
                              gate["auth"].authenticate_mcp_request, business_boundary)
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request, management_boundary, path="/mcp/manage", metadata_path=MANAGEMENT_METADATA_PATH)


def test_default_off_does_not_generate_credentials_or_upgrade_existing_clients(gate):
    server = gate["server"]
    assert server.store.management_config() == {"enabled": False, "active": False, "revision": 0, "resource": ""}
    client, _ = enable(gate)
    assert client["resources"] == ["business"]
    keys = [tuple(row) for row in gate["db"].query_all("SELECT * FROM gate_oauth_keys")]
    OAuthStore(gate["db"])
    assert server.store.clients()[0]["resources"] == ["business"]
    assert [tuple(row) for row in gate["db"].query_all("SELECT * FROM gate_oauth_keys")] == keys
    register_gateways(gate)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        assert browser.get(MANAGEMENT_METADATA_PATH).status_code == 404
        assert browser.post("/mcp/manage", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 404
        assert browser.get("/.well-known/oauth-protected-resource/mcp").json()["scopes_supported"] == ["tools.read", "tools.invoke"]
        assert browser.get("/.well-known/oauth-authorization-server").json()["scopes_supported"] == ["tools.invoke", "tools.read"]


def test_management_challenge_is_explicit_and_does_not_offer_anonymous_tools(gate):
    setup_management(gate)
    register_gateways(gate)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        metadata = browser.get(MANAGEMENT_METADATA_PATH).json()
        assert metadata["resource"] == MANAGEMENT_RESOURCE
        assert metadata["authorization_servers"] == [ISSUER]
        assert metadata["scopes_supported"] == ["operations.manage", "tools.invoke"]
        for method in ("initialize", "tools/list", "tools/call"):
            response = browser.post("/mcp/manage", json={"jsonrpc": "2.0", "id": 1, "method": method})
            assert response.status_code == 401 and "tools" not in response.json()
            assert 'scope="operations.manage tools.invoke"' in response.headers["www-authenticate"]
            assert MANAGEMENT_METADATA_PATH in response.headers["www-authenticate"]
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        assert browser.post("/mcp/manage", json={}).status_code == 401


def test_full_management_browser_login_consent_and_exchange(gate):
    client, secret, _, _ = setup_management(gate)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        authorization = browser.get("/oauth/authorize", params=parameters(client, resource=MANAGEMENT_RESOURCE,
            scope="operations.manage tools.invoke", ui_locales="zh-CN"), follow_redirects=False)
        assert authorization.status_code == 303
        ticket = parse_qs(urlsplit(authorization.headers["location"]).fragment)["request"][0]
        context = browser.get("/oauth/context", params={"request_id": ticket}).json()
        logged = browser.post("/oauth/login", json={"request_id": ticket, "csrf": context["csrf"],
            "username": "synthetic-admin", "password": PASSWORD}, headers={"Origin": ISSUER})
        assert logged.status_code == 200
        context = logged.json()
        assert context["resource_kind"] == "management" and {item["id"] for item in context["tools"]} == MANAGEMENT_TOOL_IDS
        decision = browser.post("/oauth/decision", json={"request_id": ticket, "csrf": context["csrf"],
            "tool_ids": sorted(MANAGEMENT_TOOL_IDS), "management_targets": {"synthetic-external": ["create"]}}, headers={"Origin": ISSUER})
        assert decision.status_code == 200
        code = parse_qs(urlsplit(decision.json()["redirect"]).query)["code"][0]
        issued = browser.post("/oauth/token", data={"grant_type": "authorization_code", "resource": MANAGEMENT_RESOURCE,
            "redirect_uri": REDIRECT, "code_verifier": VERIFIER, "code": code, "client_id": client["id"], "client_secret": secret})
        assert issued.status_code == 200 and issued.json()["scope"] == "operations.manage tools.invoke"
        principal = gate["auth"].authenticate_mcp_request(mcp_request(issued.json()["access_token"], "/mcp/manage"))
        assert principal.oauth_builtin and principal.oauth_resource == MANAGEMENT_RESOURCE
        assert set(principal.external_tool_ids) == MANAGEMENT_TOOL_IDS and principal.oauth_target_revision == 1
        grant = gate["server"].store.grants(principal.id)[0]
        assert grant["management_targets"] == {"synthetic-external": ["create"]}
        assert principal.oauth_family_id and principal.oauth_client_id == client["id"]


@pytest.mark.parametrize("direction", ["business_to_management", "management_to_business"])
def test_code_jwt_and_refresh_cannot_cross_audiences_even_with_same_client(gate, direction):
    client, secret, _, _ = setup_management(gate, resources=["business", "management"])
    server = gate["server"]
    management = direction == "management_to_business"
    source, target = (MANAGEMENT_RESOURCE, RESOURCE) if management else (RESOURCE, MANAGEMENT_RESOURCE)
    code = management_code(gate, client) if management else issue_code(gate, client)
    with pytest.raises(OAuthError):
        exchange(server, client, secret, code, resource=target)
    tokens = exchange(server, client, secret, code, resource=source)
    with pytest.raises(HTTPException) as denied:
        gate["auth"].authenticate_mcp_request(mcp_request(tokens["access_token"], urlsplit(target).path))
    assert denied.value.status_code == 401
    with pytest.raises(OAuthError):
        server.token({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "resource": target}, client["id"], secret)
    assert server.token({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "resource": source}, client["id"], secret)["resource"] == source


@pytest.mark.parametrize("scope,resource", [("operations.manage", RESOURCE), ("tools.read", MANAGEMENT_RESOURCE), ("tools.invoke", MANAGEMENT_RESOURCE)])
def test_resource_scope_policy_has_no_implicit_operations_upgrade(gate, scope, resource):
    client, _, _, _ = setup_management(gate, resources=["business", "management"])
    with pytest.raises(OAuthError) as error:
        gate["server"].start_authorization(parameters(client, scope=scope, resource=resource), "synthetic-scope-browser")
    assert error.value.code == "invalid_scope"


def test_management_requires_admin_and_exact_targets_and_tool_snapshot(gate):
    client, _, _, _ = setup_management(gate)
    server = gate["server"]
    browser = "synthetic-negative-browser"
    ticket = server.start_authorization(parameters(client, scope="operations.manage tools.invoke", resource=MANAGEMENT_RESOURCE), browser)
    with pytest.raises(OAuthError, match="management_admin_required"):
        server.consent_context(ticket, browser, gate["oauth_sessions"]["alice"])
    context = server.consent_context(ticket, browser, gate["management_session"])
    for targets in ({}, {"*": ["create"]}, {"synthetic": ["delete"]}, {"synthetic": ["create", "create"]}):
        with pytest.raises(OAuthError, match="invalid_management_targets"):
            server.consent(ticket, browser, context["csrf"], gate["management_principal"], sorted(MANAGEMENT_TOOL_IDS), 7, 30, 1,
                           management_targets=targets)
    gate["registry"].get_definition("gate_mcp_config_plan").description = "Changed synthetic schema envelope"
    with pytest.raises(OAuthError, match="tool_scope_changed"):
        server.consent(ticket, browser, context["csrf"], gate["management_principal"], sorted(MANAGEMENT_TOOL_IDS), 7, 30, 1,
                       management_targets={"synthetic": ["create"]})


def test_management_disable_revokes_only_management_and_access_revocation_is_supported(gate):
    client, secret, business, business_secret = setup_management(gate)
    server = gate["server"]
    ordinary = exchange(server, business, business_secret, issue_code(gate, business))
    managed = management_tokens(gate, client, secret)
    server.revoke_token(managed["access_token"], client["id"], secret)
    with pytest.raises(OAuthError):
        server.verify(managed["access_token"], expected_resource=MANAGEMENT_RESOURCE)
    assert server.verify(ordinary["access_token"]).oauth_resource == RESOURCE
    managed = management_tokens(gate, client, secret)
    server.save_management_config(False, 1)
    with pytest.raises(HTTPException) as error:
        gate["auth"].authenticate_mcp_request(mcp_request(managed["access_token"], "/mcp/manage"))
    assert error.value.status_code == 404
    assert server.verify(ordinary["access_token"]).external_tool_ids == ("mcp.A.read",)


def test_management_never_falls_back_to_external_or_api_verifier(gate, monkeypatch):
    client, secret, _, _ = setup_management(gate)
    token = management_tokens(gate, client, secret)["access_token"]
    called = []

    class OtherVerifier:
        def verify(self, token):
            called.append(token)
            raise AssertionError("Management route invoked external verifier")

    gate["auth"].external_verifier = OtherVerifier()
    assert gate["auth"].authenticate_mcp_request(mcp_request(token, "/mcp/manage")).oauth_resource == MANAGEMENT_RESOURCE
    for invalid in ("lgt_synthetic_token", "synthetic.invalid.jwt", token[:-3] + "bad"):
        with pytest.raises(HTTPException):
            gate["auth"].authenticate_mcp_request(mcp_request(invalid, "/mcp/manage"))
    assert not called


def test_management_enable_is_console_session_origin_csrf_and_cas_bound(gate):
    enable(gate)
    _, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        browser.cookies.set(gate["auth"].cookie_name, session)
        body = {"enabled": True, "expected_revision": 0}
        digest = hash_secret(json.dumps(body, sort_keys=True, separators=(",", ":")))
        path = "/v1/auth/oauth/management/config"
        assert browser.post(path, json=body, headers={"Origin": ISSUER}).status_code == 403
        assert browser.post("/v1/auth/oauth/management/csrf", params={"action": "config", "request_digest": digest}).status_code == 403
        issued = browser.post("/v1/auth/oauth/management/csrf", params={"action": "config", "request_digest": digest}, headers={"Origin": ISSUER})
        assert issued.status_code == 200
        headers = {"Origin": ISSUER, "X-CSRF-Token": issued.json()["csrf"]}
        assert browser.post(path, json={**body, "expected_revision": 1}, headers=headers).status_code == 403
        assert browser.post(path, json=body, headers={**headers, "Origin": "https://other.example.test"}).status_code == 403
        saved = browser.post(path, json=body, headers=headers)
        assert saved.status_code == 200 and saved.json()["active"] and saved.json()["revision"] == 1
        assert browser.post(path, json=body, headers=headers).status_code == 403
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        assert browser.get(path).status_code == 403
        assert gate["server"].store.management_config()["active"]

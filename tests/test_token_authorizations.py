"""以真实认证、资源规则和 SQLite 事务核对个人令牌授权。"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.models import ToolDefinition
from lingshu_gate.token_authorizations import TokenAuthorizationStore, register_token_authorization_routes
from test_builtin_oauth import ISSUER, PASSWORD, gate as gate, mcp_request


@pytest.fixture
def tokens(gate):
    store = TokenAuthorizationStore(gate["auth"], gate["access"], gate["registry"], ObservabilityStore(gate["db"]))
    register_token_authorization_routes(gate["app"], store, gate["auth"].authenticate_request)
    return store


def draft(offered, **overrides):
    return {"expected_revision": offered["revision"], "catalog_revision": offered["catalog_revision"],
            "mode": offered["mode"], "scopes": offered["scopes"], "tool_ids": offered["tool_ids"],
            "server_policies": offered["server_policies"], "rate_per_minute": offered["rate_per_minute"] or 6000,
            "concurrency": offered["concurrency"] or 100, **overrides}


def save(tokens, gate, target="new", **overrides):
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    offered = tokens.options(owner, session, target)
    body = draft(offered, **overrides)
    preview = tokens.change(owner, session, target, {**body, "csrf": offered["csrf"]}, save=False)
    return tokens.change(owner, session, target, {**body, "confirmation": preview["confirmation"]}, save=True)


def test_create_scope_and_secret_are_atomic_and_only_returned_once(tokens, gate):
    created = save(tokens, gate, name="Synthetic token", server_policies=[{"server_id": "A", "mode": "continuous", "access": "read"}])
    assert created["rate_per_minute"] == 6000 and created["concurrency"] == 100
    assert created["authorization_mode"] == "independent" and created["authorization_revision"] == 1
    assert created["server_policies"][0]["server_binding"]
    principal = gate["auth"].authenticate_request(mcp_request(created["token"]))
    assert principal.api_token_authorization_mode == "independent"
    assert principal.api_token_rate_per_minute == 6000
    assert principal.api_token_server_policies[0][::2] == ("A", "read")
    listed = gate["auth"].list_api_tokens(user_id=principal.id)
    assert listed[0]["server_policies"] == created["server_policies"] and "token" not in listed[0]
    audit = gate["db"].query_one("SELECT payload_json FROM events WHERE type='gate.auth.token_authorization_created'")
    assert created["token"] not in audit[0]


def test_legacy_token_keeps_account_scope_and_unset_quota_until_explicit_update(tokens, gate):
    old = gate["auth"].create_api_token(principal=gate["principals"]["alice"], name="Legacy", scopes=["tools.read"])
    offered = tokens.options(gate["principals"]["alice"], gate["sessions"]["alice"], old["id"])
    assert offered["mode"] == "account" and offered["revision"] == 0 and offered["rate_per_minute"] is None
    principal = gate["auth"].authenticate_request(mcp_request(old["token"]))
    assert principal.api_token_rate_per_minute == 0 and principal.api_token_authorization_mode == "account"
    changed = save(tokens, gate, old["id"], rate_per_minute=300, concurrency=1)
    assert changed["authorization_mode"] == "account" and changed["rate_per_minute"] == 300
    raised = save(tokens, gate, old["id"])
    assert raised["rate_per_minute"] == 300  # 编辑始终回填实际值。
    raised = save(tokens, gate, old["id"], rate_per_minute=6000, concurrency=100)
    assert raised["rate_per_minute"] == 6000 and raised["scopes"] == ["tools.read"]


def test_empty_independent_scope_is_not_account_mode_and_modes_are_mutually_exclusive(tokens, gate):
    created = save(tokens, gate)
    principal = gate["auth"].authenticate_request(mcp_request(created["token"]))
    assert principal.api_token_authorization_mode == "independent" and principal.api_token_tool_snapshots == ()
    with pytest.raises(ValueError, match="server_scope_modes_conflict"):
        save(tokens, gate, tool_ids=["mcp.A.read"], server_policies=[{"server_id": "A", "mode": "continuous", "access": "read"}])
    with pytest.raises(ValueError, match="account_mode_cannot_be_restored"):
        save(tokens, gate, created["id"], mode="account")


def test_confirmation_replay_and_concurrent_scope_change_are_rejected(tokens, gate):
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    offered = tokens.options(owner, session, "new")
    body = draft(offered, tool_ids=["mcp.A.read"])
    preview = tokens.change(owner, session, "new", {**body, "csrf": offered["csrf"]}, save=False)
    request = {**body, "confirmation": preview["confirmation"]}
    created = tokens.change(owner, session, "new", request, save=True)
    with pytest.raises(HTTPException):
        tokens.change(owner, session, "new", request, save=True)
    assert len(gate["auth"].list_api_tokens(user_id=owner.id)) == 1
    offered = tokens.options(owner, session, created["id"])
    body = draft(offered)
    preview = tokens.change(owner, session, created["id"], {**body, "csrf": offered["csrf"]}, save=False)
    gate["auth"].update_api_token_scopes(created["id"], principal=owner, scopes=["tools.read", "tools.invoke"])
    with pytest.raises(HTTPException, match="authorization_catalog_changed"):
        tokens.change(owner, session, created["id"], {**body, "confirmation": preview["confirmation"]}, save=True)


def test_audit_failure_rolls_back_secret_and_policy_and_confirmation(tokens, gate):
    gate["db"].execute("CREATE TRIGGER reject_token_audit BEFORE INSERT ON events WHEN NEW.type='gate.auth.token_authorization_created' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
    with pytest.raises(Exception, match="synthetic audit failure"):
        save(tokens, gate, tool_ids=["mcp.A.read"])
    assert gate["db"].query_all("SELECT * FROM api_tokens") == []
    assert gate["db"].query_all("SELECT * FROM api_token_authorizations") == []
    assert gate["db"].query_one("SELECT COUNT(*) FROM api_token_authorization_tickets WHERE purpose='confirmation'")[0] == 1


def test_http_requires_origin_console_owner_and_strict_quota(tokens, gate):
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        offered = browser.get("/v1/auth/tokens/authorization-options").json()
        assert {tool["id"] for tool in offered["tools"]} == {"mcp.A.read", "mcp.A.write"}
        body = {**draft(offered), "csrf": offered["csrf"]}
        assert browser.post("/v1/auth/tokens/authorization-preview", json=body).status_code == 403
        for invalid in [0, -1, 10001, 1.5, True, "6000"]:
            assert browser.post("/v1/auth/tokens/authorization-preview", json={**body, "rate_per_minute": invalid}, headers={"Origin": ISSUER}).status_code == 422
        assert browser.post("/v1/auth/tokens/authorization-preview", json={**body, "unexpected": True}, headers={"Origin": ISSUER}).status_code == 422
        response = browser.post("/v1/auth/tokens/authorization-preview", json=body, headers={"Origin": ISSUER})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        saved = browser.post("/v1/auth/tokens/authorization", json={**draft(offered), "confirmation": response.json()["confirmation"]}, headers={"Origin": ISSUER})
        assert saved.status_code == 200
        token = saved.json()
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["bob"])
        assert browser.get(f"/v1/auth/tokens/{token['id']}/authorization-options").status_code == 404
        assert browser.get("/v1/auth/tokens/authorization-options", headers={"Authorization": "Bearer " + token["token"]}).status_code == 403


def test_quota_only_does_not_reapprove_changed_tool_snapshot(tokens, gate):
    created = save(tokens, gate, tool_ids=["mcp.A.read"])
    before = gate["db"].query_one("SELECT tools_json FROM api_token_authorizations WHERE token_id=?", (created["id"],))[0]
    gate["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE tool_id='mcp.A.read'")
    changed = save(tokens, gate, created["id"], concurrency=1)
    assert changed["concurrency"] == 1
    after = gate["db"].query_one("SELECT tools_json FROM api_token_authorizations WHERE token_id=?", (created["id"],))[0]
    assert json.loads(before) == json.loads(after)


def test_preview_can_be_cancelled_and_latest_confirmation_replaces_previous(tokens, gate):
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    offered = tokens.options(owner, session, "new")
    body = draft(offered)
    first = tokens.change(owner, session, "new", {**body, "csrf": offered["csrf"]}, save=False)
    second = tokens.change(owner, session, "new", {**body, "csrf": offered["csrf"]}, save=False)
    with pytest.raises(HTTPException, match="authorization_confirmation_changed"):
        tokens.change(owner, session, "new", {**body, "confirmation": first["confirmation"]}, save=True)
    assert tokens.change(owner, session, "new", {**body, "confirmation": second["confirmation"]}, save=True)["id"]


def test_quota_only_preserves_invalidated_service_identity_even_if_client_omits_binding(tokens, gate):
    created = save(tokens, gate, server_policies=[{"server_id": "A", "mode": "continuous", "access": "read"}])
    old = created["server_policies"]
    gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-new-incarnation' WHERE server_id='A'")
    changed = save(tokens, gate, created["id"], concurrency=1,
        server_policies=[{"server_id": "A", "mode": "continuous", "access": "read"}])
    assert changed["server_policies"] == old
    assert changed["server_policies"][0]["server_binding"] != "synthetic-new-incarnation"


def test_large_unrelated_owner_catalog_does_not_block_small_token_quota_edit(tokens, gate):
    owner, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)

    def edit(target="new", **overrides):
        offered = tokens.options(owner, session, target)
        body = draft(offered, **overrides)
        preview = tokens.change(owner, session, target, {**body, "csrf": offered["csrf"]}, save=False)
        saved = tokens.change(owner, session, target, {**body, "confirmation": preview["confirmation"]}, save=True)
        return saved, offered

    created, _ = edit(tool_ids=["mcp.A.read"])
    for index in range(101):
        gate["registry"].register(ToolDefinition(id=f"mcp.extra{index}.read", name=f"extra{index}.read", source="mcp",
            description="Synthetic extra service", metadata={"server_id": f"extra{index}"}), lambda arguments: None)
    changed, options = edit(created["id"], concurrency=1)
    assert options["catalog_complete"] is False and options["scope_editable"] is False
    assert changed["tool_ids"] == ["mcp.A.read"] and changed["concurrency"] == 1
    assert gate["auth"].authenticate_request(mcp_request(created["token"])).api_token_concurrency == 1
    with pytest.raises(HTTPException, match="authorization_catalog_limit"):
        tokens.options(owner, session, "new")


def test_selected_tools_bind_service_identity_even_if_descriptor_is_identical(tokens, gate):
    created = save(tokens, gate, tool_ids=["mcp.A.read"])
    principal = gate["auth"].authenticate_request(mcp_request(created["token"]))
    binding = gate["db"].query_one("SELECT binding FROM gate_mcp_authorization_identities WHERE server_id='A'")[0]
    assert principal.api_token_tool_bindings == (("mcp.A.read", binding),)
    definitions = gate["registry"].get_definitions(["mcp.A.read"])
    assert [tool.id for tool in gate["access"].visible_tools(principal, definitions)] == ["mcp.A.read"]
    gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-replaced-service' WHERE server_id='A'")
    principal = gate["auth"].authenticate_request(mcp_request(created["token"]))
    assert gate["access"].visible_tools(principal, definitions) == []

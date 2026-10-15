"""持续 MCP 范围按真实分类、当前账号和 OAuth scope 交集生效。"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.interfaces.control_api.oauth_routes import ConsentRequest
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_candidate_catalog import OAuthCandidateCatalog
from lingshu_gate.oauth_server import OAuthError
from lingshu_gate.tool_catalog import ToolCatalog
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, RESOURCE, enable, exchange, parameters, refresh
from test_builtin_oauth import gate as gate
from test_oauth_live_scope import initial, options


def save_policy(gate, grant, *, access="write", rate=6000, concurrency=100):
    server = gate["server"]
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    policies = [{"server_id": "A", "mode": "continuous", "access": access}]
    offered = options(gate, grant)
    prepared = server.preview_scope(owner, grant["id"], session, offered["csrf"], grant["revision"], [],
        grant["expires_at"], rate, concurrency, server_policies=policies)
    saved = server.update_scope(owner, grant["id"], session, prepared["confirmation"], grant["revision"], [],
        grant["expires_at"], rate, concurrency, server_policies=policies)
    return saved, prepared


def discover(gate, name="later", access="read"):
    tool = ToolDefinition(id=f"mcp.A.{name}", name=name, source="mcp", description="Synthetic tool",
        permission=access, metadata={"server_id": "A", "server_name": "Synthetic A", "original_tool_name": name})
    gate["registry"].register(tool, lambda arguments: None)
    gate["access"].synchronize_tools(gate["registry"].list_definitions())
    return tool.id


def publish(gate, tool_id, access="read"):
    gate["access"].set_classification(server_id="A", tool_id=tool_id, access=access,
        destructive=False, idempotent=access == "read", reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id="A", reviewer_id=gate["admin"]["id"])


def test_same_bearer_gains_future_published_tools_and_readback_keeps_policy_separate(gate):
    client, secret, grant, tokens = initial(gate, both=True)
    saved, prepared = save_policy(gate, grant)
    assert saved["tools"] == {} and saved["server_policies"][0]["server_binding"]
    assert prepared["previous_server_policies"] == []
    assert set(gate["server"].verify(tokens["access_token"]).external_tool_ids) == {"mcp.A.read", "mcp.A.write"}
    later = discover(gate)
    assert later not in gate["server"].verify(tokens["access_token"]).external_tool_ids
    publish(gate, later)
    assert later in gate["server"].verify(tokens["access_token"]).external_tool_ids
    assert later in gate["server"].verify(refresh(gate["server"], client, secret, tokens["refresh_token"])["access_token"]).external_tool_ids
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        result = browser.get("/v1/auth/oauth/grants").json()["grants"][0]
    assert result["effective_tool_count"] == 3 and len(result["server_policies"]) == 1


def test_same_http_bearer_lists_and_calls_later_published_tool_without_new_consent(gate):
    _, _, grant, tokens = initial(gate, both=True)
    gate["db"].execute("INSERT INTO authorization_discovery VALUES('builtin',?,'direct',1)", (grant["id"],))
    save_policy(gate, grant)
    calls = []

    class SyntheticDownstream:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, **kwargs):
            calls.append((server_id, tool_name, user_id))
            return {"content": [{"type": "text", "text": "Synthetic continuous success"}]}

    gate["access"].attach_mcp_runtime(SyntheticDownstream())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request,
        McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    later = discover(gate)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        def request(method, arguments=None):
            params, headers = build_protocol_request(method, arguments, client_name="Synthetic", client_version="1")
            result = browser.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                headers={**headers, "Authorization": "Bearer " + tokens["access_token"]})
            assert result.status_code == 200, result.text
            return result.json()["result"]

        assert "mcp__A__later" not in {item["name"] for item in request("tools/list")["tools"]}
        publish(gate, later)
        assert "mcp__A__later" in {item["name"] for item in request("tools/list")["tools"]}
        result = request("tools/call", {"name": "mcp__A__later", "arguments": {}})
    assert not result.get("isError", False)
    assert calls == [("A", "later", grant["user_id"])]


def test_read_policy_and_narrowed_family_never_gain_future_write_tools(gate):
    client, secret, grant, tokens = initial(gate, both=True)
    read_tokens = refresh(gate["server"], client, secret, tokens["refresh_token"], scope="tools.read")
    saved, _ = save_policy(gate, grant)
    later = discover(gate, "later_write", "write")
    publish(gate, later, "write")
    assert later not in gate["server"].verify(read_tokens["access_token"]).external_tool_ids
    save_policy(gate, saved, access="read")
    principal = gate["server"].verify(tokens["access_token"])
    assert principal.external_tool_ids == ("mcp.A.read",)


def test_continuous_policy_rechecks_account_permissions_and_service_lifecycle(gate):
    _, _, grant, tokens = initial(gate, both=True)
    save_policy(gate, grant)
    gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-new-lifecycle' WHERE server_id='A'")
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == ()


def test_new_selected_snapshot_is_bound_to_service_identity_but_legacy_snapshot_is_compatible(gate):
    _, _, grant, tokens = initial(gate, both=True)
    assert all(item["server_binding"] for item in grant["tools"].values())
    gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-selected-replaced' WHERE server_id='A'")
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == ()
    legacy_tools = {key: {field: value for field, value in item.items() if field != "server_binding"}
                    for key, item in grant["tools"].items()}
    gate["db"].execute("UPDATE gate_oauth_grants SET tools_json=? WHERE id=?", (json.dumps(legacy_tools), grant["id"]))
    assert set(gate["server"].verify(tokens["access_token"]).external_tool_ids) == {"mcp.A.read", "mcp.A.write"}


def test_selected_scope_confirmation_does_not_rebind_service_replaced_after_preview(gate):
    _, _, grant, _ = initial(gate, both=True)
    offered = options(gate, grant)
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    prepared = gate["server"].preview_scope(owner, grant["id"], session, offered["csrf"], grant["revision"], ["mcp.A.read"],
        grant["expires_at"], 30, 1)
    gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-selected-replaced' WHERE server_id='A'")
    with pytest.raises(OAuthError, match="scope_confirmation_changed"):
        gate["server"].update_scope(owner, grant["id"], session, prepared["confirmation"], grant["revision"], ["mcp.A.read"],
            grant["expires_at"], 30, 1)


def test_continuous_policy_still_honors_explicit_tool_denial(gate):
    _, _, grant, tokens = initial(gate, both=True)
    save_policy(gate, grant)
    gate["access"].save_grant(subject_type="user", subject_id=grant["user_id"], server_id="A", tool_id="mcp.A.write",
        permission_type_code="none", created_by=gate["admin"]["id"])
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == ("mcp.A.read",)


def test_saved_zero_tool_policy_remains_visible_and_quota_edit_does_not_remove_it(gate):
    _, _, grant, tokens = initial(gate, both=True)
    saved, _ = save_policy(gate, grant)
    gate["registry"].unregister_by_metadata("server_id", "A", source="mcp")
    gate["access"].synchronize_tools(gate["registry"].list_definitions())
    offered = options(gate, saved)
    group = next(item for item in offered["servers"] if item["server_id"] == "A")
    assert group["tool_count"] == 0 and group["server_binding"] == saved["server_policies"][0]["server_binding"]
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    prepared = gate["server"].preview_scope(owner, saved["id"], session, offered["csrf"], saved["revision"], [],
        saved["expires_at"], 100, 2)
    updated = gate["server"].update_scope(owner, saved["id"], session, prepared["confirmation"], saved["revision"], [],
        saved["expires_at"], 100, 2)
    assert updated["server_policies"] == saved["server_policies"]
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == ()


@pytest.mark.parametrize("kind", ["selected_stale", "binding_replaced"])
def test_quota_only_preserves_invalid_saved_authority_without_reapproving_it(gate, kind):
    _, _, grant, tokens = initial(gate, both=True)
    if kind == "binding_replaced":
        grant, _ = save_policy(gate, grant)
        gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-replaced' WHERE server_id='A'")
    else:
        gate["db"].execute("UPDATE mcp_tool_classifications SET status='stale',effective_access='unknown' WHERE tool_id='mcp.A.read'")
    before = gate["server"].verify(tokens["access_token"]).external_tool_ids
    offered = options(gate, grant)
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    policies = [{key: value for key, value in item.items() if key != "server_binding"} for item in grant["server_policies"]]
    prepared = gate["server"].preview_scope(owner, grant["id"], session, offered["csrf"], grant["revision"], list(grant["tools"]),
        grant["expires_at"], 100, 2, server_policies=policies)
    updated = gate["server"].update_scope(owner, grant["id"], session, prepared["confirmation"], grant["revision"], list(grant["tools"]),
        grant["expires_at"], 100, 2, server_policies=policies)
    assert updated["tools"] == grant["tools"] and updated["server_policies"] == grant["server_policies"]
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == before
    assert updated["rate_per_minute"] == 100 and updated["concurrency"] == 2


@pytest.mark.parametrize("explicit_binding", [False, True])
def test_other_mcp_scope_edit_preserves_stale_binding_until_explicit_current_binding_confirmation(gate, explicit_binding):
    _, _, grant, tokens = initial(gate, both=True)
    grant, _ = save_policy(gate, grant)
    old_binding = grant["server_policies"][0]["server_binding"]
    gate["db"].execute("UPDATE gate_mcp_authorization_identities SET binding='synthetic-replaced' WHERE server_id='A'")
    gate["access"].save_grant(subject_type="user", subject_id=grant["user_id"], server_id="B",
        permission_type_code="read", created_by=gate["admin"]["id"])
    owner, session = gate["principals"]["alice"], gate["sessions"]["alice"]
    policies = [{"server_id": "A", "mode": "continuous", "access": "write"}]
    if explicit_binding:
        policies[0]["server_binding"] = old_binding
    offered = options(gate, grant)
    prepared = gate["server"].preview_scope(owner, grant["id"], session, offered["csrf"], grant["revision"], ["mcp.B.read"],
        grant["expires_at"], 6000, 100, server_policies=policies)
    updated = gate["server"].update_scope(owner, grant["id"], session, prepared["confirmation"], grant["revision"], ["mcp.B.read"],
        grant["expires_at"], 6000, 100, server_policies=policies)
    assert updated["server_policies"][0]["server_binding"] == old_binding
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == ("mcp.B.read",)
    policies[0]["server_binding"] = "synthetic-replaced"
    offered = options(gate, updated)
    prepared = gate["server"].preview_scope(owner, updated["id"], session, offered["csrf"], updated["revision"], ["mcp.B.read"],
        updated["expires_at"], 6000, 100, server_policies=policies)
    rebound = gate["server"].update_scope(owner, updated["id"], session, prepared["confirmation"], updated["revision"], ["mcp.B.read"],
        updated["expires_at"], 6000, 100, server_policies=policies)
    assert rebound["server_policies"][0]["server_binding"] == "synthetic-replaced"
    assert set(gate["server"].verify(tokens["access_token"]).external_tool_ids) == {"mcp.A.read", "mcp.A.write", "mcp.B.read"}


@pytest.mark.parametrize("paged", [False, True])
def test_unsubscribed_large_owner_catalog_does_not_block_small_continuous_grant(gate, monkeypatch, paged):
    _, _, grant, tokens = initial(gate, both=True)
    save_policy(gate, grant)
    gate["access"].save_grant(subject_type="user", subject_id=grant["user_id"], server_id="B",
        permission_type_code="read", created_by=gate["admin"]["id"])
    definitions = [ToolDefinition(id=f"mcp.B.extra-{index}", name=f"Synthetic extra {index}", source="mcp",
        description="Synthetic catalog", permission="read", metadata={"server_id": "B", "original_tool_name": f"extra_{index}"})
        for index in range(5000)]
    for tool in definitions:
        gate["registry"].register(tool, lambda arguments: None)
    with gate["db"].session() as connection:
        gate["access"]._synchronize_tools(connection, definitions)
        connection.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published',"
            "source='manual',reviewed_by=?,reviewed_at='2026-10-05T00:00:00+00:00' WHERE server_id='B'",
            (gate["admin"]["id"],))
    if paged:
        gate["server"].candidate_catalog = OAuthCandidateCatalog(ToolCatalog(gate["registry"], gate["access"]), gate["access"])
    monkeypatch.setattr(gate["registry"], "list_definitions", lambda: pytest.fail("Unsubscribed full registry traversal"))
    principal = gate["server"].verify(tokens["access_token"])
    assert set(principal.external_tool_ids) == {"mcp.A.read", "mcp.A.write"}


def test_continuous_scope_rejects_missing_oauth_capability_and_conflicting_selected_mode(gate):
    _, _, grant, _ = initial(gate)
    with pytest.raises(OAuthError, match="grant_scope_insufficient"):
        save_policy(gate, grant, access="write")
    offered = options(gate, grant)
    with pytest.raises(OAuthError, match="server_policy_conflict"):
        gate["server"].preview_scope(gate["principals"]["alice"], grant["id"], gate["sessions"]["alice"],
            offered["csrf"], grant["revision"], ["mcp.A.read"], grant["expires_at"], 6000, 100,
            server_policies=[{"server_id": "A", "mode": "continuous", "access": "read"}])


def test_initial_consent_accepts_continuous_policy_and_business_quota_defaults(gate):
    client, secret = enable(gate)
    server, browser = gate["server"], "synthetic-continuous-browser-" + "b" * 32
    interaction = server.start_authorization(parameters(client), browser)
    context = server.consent_context(interaction, browser, gate["oauth_sessions"]["alice"])
    body = ConsentRequest.model_validate({"request_id": interaction, "csrf": context["csrf"],
        "server_policies": [{"server_id": "A", "mode": "continuous", "access": "write"}]})
    redirect = server.consent(interaction, browser, body.csrf, gate["principals"]["alice"], [], 7,
        body.rate_per_minute, body.concurrency, server_policies=[item.model_dump(exclude_none=True) for item in body.server_policies])
    tokens = exchange(server, client, secret, parse_qs(urlsplit(redirect).query)["code"][0])
    principal = server.verify(tokens["access_token"])
    assert principal.external_rate_per_minute == 6000 and principal.external_concurrency == 100
    assert set(principal.external_tool_ids) == {"mcp.A.read", "mcp.A.write"}
    assert context["server_bindings"]["A"] and context["default_rate_per_minute"] == 6000

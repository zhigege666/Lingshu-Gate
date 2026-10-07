"""Real HTTP OAuth candidates share the index and never use a paged allowlist."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_candidate_catalog import OAuthCandidateCatalog
from lingshu_gate.tool_catalog import ToolCatalog
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, PASSWORD, RESOURCE, enable, exchange, issue_code, refresh
from test_builtin_oauth import gate as gate
from test_oauth_catalog_scaling import _install, _scaled_catalog
from test_oauth_scope_catalog import admin_grant, discover, publish


@pytest.fixture
def paged(gate):
    client, secret = enable(gate)
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client, tools=["mcp.A.read", "mcp.A.write"]))
    grant = gate["server"].store.grants(gate["users"]["alice"]["id"])[0]
    # A real confirmed tool reduction retains the original scope ceiling. Do
    # not manufacture a broader ceiling to make write candidates appear.
    server, owner, session = gate["server"], gate["principals"]["alice"], gate["sessions"]["alice"]
    options = server.scope_options(owner, grant["id"], session)
    narrowed = server.preview_scope(owner, grant["id"], session, options["csrf"], grant["revision"],
        ["mcp.A.read"], grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])
    grant = server.update_scope(owner, grant["id"], session, narrowed["confirmation"], grant["revision"],
        narrowed["tool_ids"], grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])
    index = ToolCatalog(gate["registry"], gate["access"])
    gate["server"].candidate_catalog = OAuthCandidateCatalog(index, gate["access"])
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        yield {**gate, "browser": browser, "path": f"/v1/auth/oauth/grants/{grant['id']}",
               "grant": grant, "client": client, "secret": secret, "tokens": tokens, "index": index}


def catalog(paged, **params):
    response = paged["browser"].get(paged["path"] + "/scope-catalog", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["complete"] is False and "tools" not in result
    return result


def select(paged, offered, ids=None, **changes):
    body = {"csrf": offered["csrf"], "catalog_revision": offered["catalog_revision"],
        "expected_revision": paged["grant"]["revision"], "tool_ids": ["mcp.A.read"] if ids is None else ids,
        "mode": "ids", **changes}
    return paged["browser"].post(paged["path"] + "/scope-selection", json=body, headers={"Origin": ISSUER})


def target(paged, offered, ids):
    grant = paged["grant"]
    return {"expected_revision": grant["revision"], "catalog_revision": offered["catalog_revision"],
        "tool_ids": ids, "expires_at": grant["expires_at"], "rate_per_minute": grant["rate_per_minute"],
        "concurrency": grant["concurrency"]}


def prepared(paged, offered, ids):
    response = paged["browser"].post(paged["path"] + "/scope-preview",
        json={**target(paged, offered, ids), "csrf": offered["csrf"]}, headers={"Origin": ISSUER})
    assert response.status_code == 200, response.text
    return response.json()


def test_real_5000_service_50000_tool_pages_search_selection_and_atomic_limits(paged, monkeypatch):
    definitions = _scaled_catalog(paged)
    _install(paged, definitions)
    paged["index"].synchronize()
    monkeypatch.setattr(paged["registry"], "list_definitions", lambda: pytest.fail("Full registry projection"))
    monkeypatch.setattr(paged["access"], "list_classifications", lambda: pytest.fail("Full classification projection"))
    grants = paged["browser"].get("/v1/auth/oauth/grants")
    assert grants.status_code == 200 and grants.json()["grants"][0]["scope_catalog_mode"] == "paged"
    offered = catalog(paged, limit=100, view="groups")
    assert offered["catalog_counts"] == {"tools": 50000, "read": 27000, "write": 23000, "mcps": 5000}
    assert offered["selection_limits"] == {"tools": 5000, "mcps": 100}
    servers = [item["server_id"] for item in offered["items"]]
    cursor = offered["next_cursor"]
    # Every actual MCP group page; no 10,000-offset ceiling or hidden truncation.
    while cursor:
        next_page = catalog(paged, limit=100, view="groups", cursor=cursor,
                            catalog_revision=offered["catalog_revision"])
        servers.extend(item["server_id"] for item in next_page["items"])
        assert next_page["catalog_revision"] == offered["catalog_revision"]
        cursor = next_page["next_cursor"]
    assert len(servers) == len(set(servers)) == 5000
    last = catalog(paged, server_id="synthetic-4999", limit=2)
    assert last["matching_counts"]["tools"] == 9
    found = catalog(paged, query="synthetic 8", server_id="synthetic-4999")
    assert [item["id"] for item in found["items"]] == ["mcp.synthetic-4999.tool-8"]
    selection = select(paged, last, mode="groups", server_ids=["synthetic-4999"]).json()
    assert len(selection["tool_ids"]) == 10 and selection["unavailable_ids"] == []
    assert selection["selected_counts"]["mcps"] == 2 and selection["difference_summary"]["added"] == 10
    assert "input_schema" not in json.dumps(selection) and "description" not in json.dumps(selection)
    prior = dict(paged["db"].query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (paged["grant"]["id"],)))
    for mode in ("all", "read"):
        rejected = select(paged, last, ids=selection["tool_ids"], mode=mode)
        assert rejected.status_code == 409 and rejected.json()["error"] == "scope_selection_tool_limit"
    assert dict(paged["db"].query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (paged["grant"]["id"],))) == prior
    # Search found a small subset far outside the saved grant and first page.
    preview = prepared(paged, last, selection["tool_ids"])
    saved = paged["browser"].post(paged["path"] + "/scope", json={**target(paged, last, selection["tool_ids"]),
        "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER})
    assert saved.status_code == 200, saved.text
    assert set(paged["server"].verify(paged["tokens"]["access_token"]).external_tool_ids) == set(selection["tool_ids"])
    paged["db"].execute("DELETE FROM mcp_resource_grants WHERE server_id='synthetic-4999'")
    assert paged["server"].refresh_verified_principal(paged["server"].verify(paged["tokens"]["access_token"])).external_tool_ids == ("mcp.A.read",)


def test_5000_selected_ids_have_bounded_metadata_and_read_choice_is_whole_catalog(paged):
    definitions = _scaled_catalog(paged)
    _install(paged, definitions[:5000])
    offered = catalog(paged, query="read", limit=1)
    assert len(offered["items"]) == 1
    selected = select(paged, offered, mode="all", max_bytes=8192).json()
    assert len(selected["tool_ids"]) == 5000
    assert len(selected["tools"]) <= 50
    assert len(json.dumps({"tools": selected["tools"], "group_selected_counts": selected["group_selected_counts"]}, ensure_ascii=False).encode()) <= 8192
    read = select(paged, offered, mode="read").json()
    assert len(read["tool_ids"]) == 2500 and read["selected_counts"]["write"] == 0
    assert read["selected_counts"]["mcps"] == 100
    assert paged["server"].store.grants(paged["users"]["alice"]["id"])[0]["tools"] == paged["grant"]["tools"]


def test_candidate_ceiling_is_independent_of_saved_subset_and_narrow_family(paged):
    paged["access"].save_grant(subject_type="user", subject_id=paged["users"]["alice"]["id"], server_id="B",
        permission_type_code="write", created_by=paged["admin"]["id"])
    narrowed = refresh(paged["server"], paged["client"], paged["secret"], paged["tokens"]["refresh_token"], scope="tools.read")
    offered = catalog(paged, server_id="B", access="write")
    assert [tool["id"] for tool in offered["items"]] == ["mcp.B.write"]
    assert offered["family_scope_limits"] == [{"scopes": ["tools.read"], "count": 1}]
    before = [tuple(row) for row in paged["db"].query_all("SELECT * FROM gate_oauth_families")]
    ids = ["mcp.A.read", "mcp.B.write"]
    preview = prepared(paged, offered, ids)
    assert preview["difference_summary"] == {"added": 1, "removed": 0, "added_write": 1, "removed_write": 0, "write": 1}
    response = paged["browser"].post(paged["path"] + "/scope", json={**target(paged, offered, ids),
        "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER})
    assert response.status_code == 200
    assert [tuple(row) for row in paged["db"].query_all("SELECT * FROM gate_oauth_families")] == before
    principal = paged["server"].verify(narrowed["access_token"])
    assert principal.external_tool_ids == ("mcp.A.read",)
    assert not paged["access"].evaluate(principal, paged["registry"].get_definition("mcp.B.write"))["allowed"]


def test_whole_catalog_and_explicit_ids_keep_the_100_mcp_selection_limit(paged):
    definitions = []
    for index in range(100):
        server_id = f"synthetic-mcp-limit-{index:03}"
        definitions.append(ToolDefinition(id=f"mcp.{server_id}.read", name="Synthetic read tool",
            source="mcp", description="Synthetic selection-limit fixture", permission="read",
            metadata={"server_id": server_id, "original_tool_name": "read"}))
        paged["access"].save_grant(subject_type="user", subject_id=paged["users"]["alice"]["id"],
            server_id=server_id, permission_type_code="read", created_by=paged["admin"]["id"])
    _install(paged, definitions)
    offered = catalog(paged)
    assert offered["catalog_counts"]["mcps"] == 101
    ids = ["mcp.A.read", *[tool.id for tool in definitions]]
    for mode in ("all", "read", "ids"):
        response = select(paged, offered, ids=ids, mode=mode)
        assert response.status_code == 409 and response.json()["error"] == "server_scope_limit"
    assert paged["server"].store.grants(paged["users"]["alice"]["id"])[0]["tools"] == paged["grant"]["tools"]


@pytest.mark.parametrize("change", ["classification", "registry", "owner_permission", "client_scope", "client_revision", "grant_revision", "resource_revision", "grant_expiry"])
def test_revision_conflicts_reject_cursor_selection_preview_and_save_without_mutation(paged, change):
    offered = catalog(paged, limit=1)
    preview = prepared(paged, offered, ["mcp.A.read", "mcp.A.write"])
    if change == "classification":
        paged["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE tool_id='mcp.A.write'")
    elif change == "registry":
        paged["registry"].unregister_by_metadata("original_tool_name", "write", source="mcp")
    elif change == "owner_permission":
        paged["db"].execute("DELETE FROM mcp_resource_grants WHERE subject_id=?", (paged["users"]["alice"]["id"],))
    elif change == "client_scope":
        paged["db"].execute("UPDATE gate_oauth_clients SET scopes_json='[\"tools.read\"]'")
    elif change == "client_revision":
        paged["db"].execute("UPDATE gate_oauth_clients SET revision=revision+1")
    elif change == "grant_revision":
        paged["db"].execute("UPDATE gate_oauth_grants SET revision=revision+1")
    elif change == "resource_revision":
        paged["db"].execute("UPDATE gate_oauth_config SET revision=revision+1")
    else:
        paged["db"].execute("UPDATE gate_oauth_grants SET expires_at=1")
    prior = dict(paged["db"].query_one("SELECT * FROM gate_oauth_grants"))
    page = paged["browser"].get(paged["path"] + "/scope-catalog", params={"limit": 1, "cursor": offered["next_cursor"]})
    assert page.status_code == 409, page.text
    assert select(paged, offered).status_code == 409
    check = paged["browser"].post(paged["path"] + "/scope-preview", json={**target(paged, offered, ["mcp.A.read"]),
        "csrf": offered["csrf"]}, headers={"Origin": ISSUER})
    assert check.status_code == 409
    save = paged["browser"].post(paged["path"] + "/scope", json={**target(paged, offered, preview["tool_ids"]),
        "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER})
    assert save.status_code == 409
    assert dict(paged["db"].query_one("SELECT * FROM gate_oauth_grants")) == prior


def test_cursor_filters_session_binding_invisibility_and_withdrawn_ids(paged):
    offered = catalog(paged, limit=1)
    changed = paged["browser"].get(paged["path"] + "/scope-catalog", params={"limit": 1,
        "view": "groups", "cursor": offered["next_cursor"]})
    assert changed.status_code == 409 and changed.json()["error"] == "scope_catalog_cursor_invalid"
    invisible = select(paged, offered, ids=["mcp.A.read", "mcp.B.read", "mcp.hidden.guessed"],
        metadata_ids=["mcp.B.read", "mcp.hidden.guessed"]).json()
    assert invisible["unavailable_ids"] == ["mcp.B.read", "mcp.hidden.guessed"]
    assert invisible["tools"] == [] and invisible["available_ids"] == ["mcp.A.read"]
    assert catalog(paged, server_id="B")["items"] == []
    _, session, _ = paged["auth"].login(username="alice", password=PASSWORD)
    paged["browser"].cookies.set(paged["auth"].cookie_name, session)
    assert select(paged, offered).status_code == 403
    assert paged["browser"].get(paged["path"] + "/scope-catalog", params={"limit": 1,
        "cursor": offered["next_cursor"]}).status_code == 403


def test_single_confirmation_limits_and_explicit_invalid_selection_removal(paged):
    offered = catalog(paged)
    rejected = paged["browser"].post(paged["path"] + "/scope-preview", json={**target(paged, offered, ["mcp.A.write"]),
        "csrf": offered["csrf"], "rate_per_minute": 31}, headers={"Origin": ISSUER})
    assert rejected.status_code == 400 and rejected.json()["error"] == "grant_limits_can_only_narrow"
    mixed = select(paged, offered, ids=["mcp.A.write", "mcp.unknown.id"]).json()
    assert mixed["tool_ids"] == ["mcp.A.write", "mcp.unknown.id"] and mixed["unavailable_ids"] == ["mcp.unknown.id"]
    blocked = paged["browser"].post(paged["path"] + "/scope-preview", json={**target(paged, offered, mixed["tool_ids"]),
        "csrf": offered["csrf"]}, headers={"Origin": ISSUER})
    assert blocked.status_code == 409
    preview = prepared(paged, offered, mixed["available_ids"])
    body = {**target(paged, offered, mixed["available_ids"]), "confirmation": preview["confirmation"]}
    assert paged["browser"].post(paged["path"] + "/scope", json=body, headers={"Origin": ISSUER}).status_code == 200
    assert paged["browser"].post(paged["path"] + "/scope", json=body, headers={"Origin": ISSUER}).status_code == 409


@pytest.mark.parametrize("reason", ["classification_not_published", "grant_scope_ceiling", "client_scope_ceiling"])
def test_unavailable_reasons_are_paged_owner_visible_and_follow_exact_ceilings(paged, reason):
    paged["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE server_id='B'")
    if reason == "classification_not_published":
        paged["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE tool_id='mcp.A.write'")
    elif reason == "grant_scope_ceiling":
        paged["db"].execute("UPDATE gate_oauth_grants SET scopes_json='[\"tools.read\"]'")
    else:
        paged["db"].execute("UPDATE gate_oauth_clients SET scopes_json='[\"tools.read\"]'")
    offered = catalog(paged)
    if reason == "classification_not_published":
        # A non-admin writer loses current invocation authority for pending
        # tools. Diagnostics must not disclose definitions it cannot access.
        assert offered["unavailable_counts"] == {"tools": 0, "read": 0, "write": 0, "mcps": 0}
        assert catalog(paged, view="unavailable")["items"] == []
        return
    assert offered["unavailable_counts"] == {"tools": 1, "read": 0, "write": 1, "mcps": 1}
    missing = catalog(paged, view="unavailable", limit=1)
    assert missing["items"] == [{"server_id": "A", "server_name": None, "reasons": [{"code": reason, "count": 1}]}]
    assert catalog(paged, view="unavailable", server_id="B")["items"] == []
    assert "B.write" not in json.dumps(missing)


def test_admin_api_token_calls_unpublished_new_mcp_and_paged_catalog_explains_it(gate):
    principal, session, _, _, grant, tokens = admin_grant(gate)
    index = ToolCatalog(gate["registry"], gate["access"])
    gate["server"].candidate_catalog = OAuthCandidateCatalog(index, gate["access"])
    discover(gate)
    calls = []

    class SyntheticRuntime:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, **kwargs):
            calls.append((server_id, tool_name, user_id))
            return {"content": [{"type": "text", "text": "Synthetic successful invocation"}]}

    gate["access"].attach_mcp_runtime(SyntheticRuntime())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"], gate["auth"].authenticate_mcp_request,
        McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    api = gate["auth"].create_api_token(principal=principal, name="Synthetic scope comparison",
        scopes=["tools.read", "tools.invoke"])
    path = f"/v1/auth/oauth/grants/{grant['id']}"
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        params, headers = build_protocol_request("tools/call", {"name": "mcp__synthetic-plane__project", "arguments": {}},
            client_name="Synthetic", client_version="1", protocol_version="2026-07-28")
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
        called = browser.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer " + str(api["token"])})
        assert called.status_code == 200 and not called.json()["result"].get("isError", False)
        assert calls == [("synthetic-plane", "project", principal.id)]
        denied = browser.post("/mcp", json=body, headers={**headers, "Authorization": "Bearer " + tokens["access_token"]})
        assert denied.json()["result"]["isError"] and len(calls) == 1
        response = browser.get(path + "/scope-catalog", headers={"Authorization": "Bearer " + str(api["token"])})
        assert response.status_code == 403 and response.json()["error"] == "permission_denied"
        browser.cookies.set(gate["auth"].cookie_name, session)
        offered = browser.get(path + "/scope-catalog").json()
        missing = browser.get(path + "/scope-catalog", params={"view": "unavailable", "limit": 1}).json()
        assert missing["items"] == [{"server_id": "synthetic-plane", "server_name": None,
            "reasons": [{"code": "classification_not_published", "count": 2}]}]
        assert offered["unavailable_counts"]["tools"] == 2 and offered["can_review_classifications"] is True
        publish(gate)
        fresh = browser.get(path + "/scope-catalog", params={"server_id": "synthetic-plane"}).json()
        assert {tool["id"]: tool["access"] for tool in fresh["items"]} == {
            "mcp.synthetic-plane.list": "read", "mcp.synthetic-plane.project": "write"}
        assert fresh["catalog_revision"] != offered["catalog_revision"]
        selection = browser.post(path + "/scope-selection", json={"csrf": fresh["csrf"],
            "catalog_revision": fresh["catalog_revision"], "expected_revision": grant["revision"],
            "mode": "read", "tool_ids": list(grant["tools"])}, headers={"Origin": ISSUER})
        assert selection.status_code == 200 and "mcp.synthetic-plane.project" not in selection.json()["tool_ids"]
        assert selection.json()["selected_counts"]["write"] == 0
    assert gate["server"].store.grants(principal.id)[0]["tools"] == grant["tools"]


@pytest.mark.parametrize("operation", ["page", "selection", "preview", "save"])
def test_registry_delta_after_index_sync_fails_closed_until_a_fresh_retry(paged, monkeypatch, operation):
    offered = catalog(paged)
    preview = prepared(paged, offered, ["mcp.A.read"])
    prior = dict(paged["db"].query_one("SELECT * FROM gate_oauth_grants"))
    synchronize = paged["index"].synchronize

    def late_delta():
        generation = synchronize()
        paged["registry"].unregister_by_metadata("original_tool_name", "write", source="mcp")
        return generation

    monkeypatch.setattr(paged["index"], "synchronize", late_delta)
    if operation == "page":
        response = paged["browser"].get(paged["path"] + "/scope-catalog")
    elif operation == "selection":
        response = select(paged, offered)
    elif operation == "preview":
        response = paged["browser"].post(paged["path"] + "/scope-preview", json={
            **target(paged, offered, ["mcp.A.read"]), "csrf": offered["csrf"]}, headers={"Origin": ISSUER})
    else:
        response = paged["browser"].post(paged["path"] + "/scope", json={
            **target(paged, offered, ["mcp.A.read"]), "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER})
    assert response.status_code == 409 and response.json()["error"] == "tool_scope_changed"
    assert dict(paged["db"].query_one("SELECT * FROM gate_oauth_grants")) == prior
    monkeypatch.setattr(paged["index"], "synchronize", synchronize)
    fresh = catalog(paged)
    assert fresh["catalog_counts"]["write"] == 0
    assert fresh["catalog_revision"] != offered["catalog_revision"]


def test_group_deselection_does_not_resolve_or_truncate_large_membership(paged, monkeypatch):
    offered = catalog(paged)
    monkeypatch.setattr(paged["server"].candidate_catalog, "resolve", lambda *args, **kwargs: pytest.fail("Deselect must only examine draft IDs"))
    response = select(paged, offered, mode="groups", server_ids=["A"], checked=False)
    assert response.status_code == 200 and response.json()["tool_ids"] == []


@pytest.mark.parametrize("params", [{"limit": 101}, {"limit": 0}, {"view": "other"}, {"access": "admin"}, {"max_bytes": 8191}, {"query": "*"}])
def test_http_catalog_parameters_fail_closed(paged, params):
    assert paged["browser"].get(paged["path"] + "/scope-catalog", params=params).status_code == 400

"""Run the complete synthetic management chain under an external 180s deadline.

Real inbound OAuth/PKCE/JWT/ACL, temporary SQLite and fixture keys; only the
downstream HTTP peer is replaced. No socket, credential or production client.
"""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from lingshu_gate.auth import hash_secret
from lingshu_gate.domain.oauth_management import MANAGEMENT_METADATA_PATH, MANAGEMENT_TOOL_IDS
from lingshu_gate.models import ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.transports.http import build_protocol_request
from test_builtin_oauth import CHALLENGE, ISSUER, REDIRECT, RESOURCE, VERIFIER
from test_external_mcp_configuration import PASSWORD, apply_arguments, manifest, wait
from test_external_mcp_configuration import gate as gate

MANAGEMENT_RESOURCE = ISSUER + "/mcp/manage"


def protocol(browser, token, method, params=None, *, path="/mcp/manage"):
    if method == "initialize" and params is None:
        params = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "Synthetic management", "version": "1"}}
    prepared, headers = build_protocol_request(method, params, client_name="Synthetic management", client_version="1",
                                              protocol_version="2025-11-25" if method == "initialize" else MCP_PROTOCOL_VERSION)
    return browser.post(path, headers={**headers, **({"Authorization": "Bearer " + token} if token else {})},
                        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared})


def call(browser, token, tool, arguments):
    response = protocol(browser, token, "tools/call", {"name": tool, "arguments": arguments})
    assert response.status_code == 200, response.status_code
    return response.json()["result"]


def output(result):
    assert not result.get("isError", False), result
    return result["structuredContent"]


def consent_code(browser, created, *, resource=MANAGEMENT_RESOURCE, scope="operations.manage tools.invoke",
                 targets=None, tools=None):
    params = {"client_id": created["client"]["id"], "redirect_uri": REDIRECT, "response_type": "code", "resource": resource,
              "scope": scope, "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "synthetic-management-state", "ui_locales": "zh-CN"}
    response = browser.get("/oauth/authorize", params=params, follow_redirects=False)
    assert response.status_code == 303 and "/oauth/consent#" in response.headers["location"]
    ticket = parse_qs(urlsplit(response.headers["location"]).fragment)["request"][0]
    context = browser.get("/oauth/context", params={"request_id": ticket}).json()
    logged = browser.post("/oauth/login", json={"request_id": ticket, "csrf": context["csrf"],
                          "username": "synthetic-admin", "password": PASSWORD}, headers={"Origin": ISSUER})
    assert logged.status_code == 200
    context = logged.json()
    selected = tools if tools is not None else sorted(item["id"] for item in context["tools"])
    body = {"request_id": ticket, "csrf": context["csrf"], "tool_ids": selected, "rate_per_minute": 10000, "concurrency": 8}
    if resource == MANAGEMENT_RESOURCE:
        body["management_targets"] = targets or {"synthetic-a": ["create", "update"]}
    decision = browser.post("/oauth/decision", json=body, headers={"Origin": ISSUER})
    assert decision.status_code == 200
    query = parse_qs(urlsplit(decision.json()["redirect"]).query)
    assert query["state"] == ["synthetic-management-state"] and query["iss"] == [ISSUER]
    return query["code"][0]


def tokens(browser, created, *, resource=MANAGEMENT_RESOURCE, **kwargs):
    code = consent_code(browser, created, resource=resource, **kwargs)
    response = browser.post("/oauth/token", data={"grant_type": "authorization_code", "resource": resource, "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER, "client_id": created["client"]["id"], "client_secret": created["client_secret"], "code": code})
    assert response.status_code == 200
    return response.json()


def enable_management(gate, browser, *, resources=None, readonly=False):
    server = gate["app"].state.oauth_server
    if not server.store.config()["enabled"]:
        server.save_config({"enabled": False, "issuer": ISSUER, "resource": RESOURCE}, 0)
        server.rotate_key()
        server.save_config({"enabled": True, "issuer": ISSUER, "resource": RESOURCE}, 1)
    if not server.store.management_config()["active"]:
        body = {"enabled": True, "expected_revision": server.store.management_config()["revision"]}
        digest = hash_secret(json.dumps(body, sort_keys=True, separators=(",", ":")))
        issued = browser.post("/v1/auth/oauth/management/csrf", params={"action": "config", "request_digest": digest}, headers={"Origin": ISSUER})
        assert issued.status_code == 200
        enabled = browser.post("/v1/auth/oauth/management/config", json=body, headers={"Origin": ISSUER, "X-CSRF-Token": issued.json()["csrf"]})
        assert enabled.status_code == 200 and enabled.json()["active"]
    scopes = ["operations.manage"] + ([] if readonly else ["tools.invoke"])
    if resources == ["business", "management"]:
        scopes.append("tools.read")
    return server.create_client("Synthetic management", [REDIRECT], scopes, resources=resources or ["management"])


@pytest.fixture
def browser(gate):
    cookie = gate["client"].cookies.get(gate["auth"].cookie_name)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        client.cookies.set(gate["auth"].cookie_name, cookie)
        yield client


def target_edit(browser, grant, targets, *, save=True):
    path = f"/v1/auth/oauth/grants/{grant['id']}/management-targets"
    offered = browser.get(path)
    assert offered.status_code == 200
    options = offered.json()
    body = {"expected_revision": options["expected_revision"], "expected_target_revision": options["expected_target_revision"], "targets": targets}
    prepared = browser.post(path + "/preview", json={**body, "csrf": options["csrf"]}, headers={"Origin": ISSUER})
    assert prepared.status_code == 200
    if not save:
        return path, body, prepared.json()
    result = browser.post(path, json={**body, "confirmation": prepared.json()["confirmation"]}, headers={"Origin": ISSUER})
    assert result.status_code == 200
    return result.json()


def business_fixture(gate):
    app, actor = gate["app"], gate["principal"].id
    tool = ToolDefinition(id="mcp.synthetic_business.read", name="synthetic_read", source="mcp", description="Synthetic business tool",
                          permission="read", metadata={"server_id": "synthetic_business", "original_tool_name": "read"})
    app.state.registry.register(tool, lambda arguments: {"synthetic": True})
    app.state.access_store.synchronize_tools([tool])
    app.state.access_store.set_classification(server_id="synthetic_business", tool_id=tool.id, access="read", destructive=False,
                                             idempotent=True, reviewer_id=actor)
    app.state.access_store.publish_classifications(server_id="synthetic_business", reviewer_id=actor)
    return app.state.oauth_server.create_client("Synthetic business", [REDIRECT], ["tools.read", "tools.invoke"])


def test_complete_management_chain_and_target_confirmation_preserve_business_family(gate, browser):
    server, db = gate["app"].state.oauth_server, gate["service"].database
    assert browser.get(MANAGEMENT_METADATA_PATH).status_code == 404
    assert protocol(browser, None, "tools/list").status_code == 404 and not gate["calls"]
    created = enable_management(gate, browser)
    for method in ("initialize", "tools/list"):
        challenged = protocol(browser, None, method)
        assert challenged.status_code == 401 and MANAGEMENT_METADATA_PATH in challenged.headers["www-authenticate"]
        assert 'scope="operations.manage tools.invoke"' in challenged.headers["www-authenticate"]
    assert browser.get("/.well-known/oauth-protected-resource/mcp").json()["scopes_supported"] == ["tools.read", "tools.invoke"]
    assert browser.get("/.well-known/oauth-authorization-server").json()["scopes_supported"] == ["tools.invoke", "tools.read"]
    ordinary = tokens(browser, business_fixture(gate), resource=RESOURCE, scope="tools.read", tools=["mcp.synthetic_business.read"])
    business_claims = jwt.decode(ordinary["access_token"], options={"verify_signature": False})
    original_family = tuple(db.query_one("SELECT * FROM gate_oauth_families WHERE id=?", (business_claims["fid"],)))
    original_grant = tuple(db.query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (business_claims["gid"],)))
    issued = tokens(browser, created, targets={"synthetic-a": ["create"]})
    bearer = issued["access_token"]
    assert protocol(browser, bearer, "initialize").status_code == 200
    assert protocol(browser, bearer, "server/discover").status_code == 200
    assert {item["name"] for item in protocol(browser, bearer, "tools/list").json()["result"]["tools"]} == MANAGEMENT_TOOL_IDS
    for tool in ("gate_project_upload_begin", "gate_tool_classification_list", "mcp__synthetic_business__read"):
        assert call(browser, bearer, tool, {}).get("isError")
    planned = output(call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-a"), "connect": True, "refresh_tools": True}))
    assert planned["probe"]["network_contacted"] is False and not gate["calls"]
    operation = output(call(browser, bearer, "gate_mcp_config_apply", apply_arguments(planned)))
    result = wait(gate, operation["operation_id"])
    reported = output(call(browser, bearer, "gate_mcp_config_status", {"operation_id": operation["operation_id"]}))
    assert reported["status"] == result["status"] == "success" and reported["terminal"]
    assert reported["counts"]["needs_review"] == 1 and reported["classification_state"] == "needs_review"
    assert len([item for item in gate["calls"] if item[0] == "discover"]) == 1
    assert reported["effective_permissions_expanded"] is False and reported["remote_process_started"] is False
    assert output(call(browser, bearer, "gate_mcp_config_apply", apply_arguments(planned)))["idempotent_replay"]
    management_claims = jwt.decode(bearer, options={"verify_signature": False})
    grant = next(item for item in server.store.grants(gate["principal"].id) if item["id"] == management_claims["gid"])
    assert call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-a-queued")}).get("isError")
    assert call(browser, bearer, "gate_mcp_config_plan", {"mode": "update", "manifest": manifest("synthetic-a"), "expected_config_digest": result["config_digest"]}).get("isError")
    path, body, preview = target_edit(browser, grant, {"synthetic-a": ["create", "update"], "synthetic-b": ["create"]}, save=False)
    assert preview["scopes_unchanged"] and preview["tools_unchanged"]
    assert browser.post(path, json={**body, "confirmation": preview["confirmation"]}, headers={"Origin": "https://foreign.example.test"}).status_code == 403
    assert browser.post(path, json={**body, "targets": {}, "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER}).status_code == 409
    saved = browser.post(path, json={**body, "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER})
    assert saved.status_code == 200 and saved.json()["target_revision"] == 2
    assert browser.post(path, json={**body, "confirmation": preview["confirmation"]}, headers={"Origin": ISSUER}).status_code == 409
    assert call(browser, bearer, "gate_mcp_config_apply", apply_arguments(planned)).get("isError")  # cached result checks revision too.
    plan_b = output(call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-b")}))
    current = saved.json()
    updated = target_edit(browser, current, {"synthetic-b": ["create"]})
    assert updated["target_revision"] == 3
    assert call(browser, bearer, "gate_mcp_config_apply", apply_arguments(plan_b, "synthetic-stale-revision")).get("isError")
    assert call(browser, bearer, "gate_mcp_config_status", {"server_id": "synthetic-a"}).get("isError")
    plan_b = output(call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-b")}))
    applied_b = output(call(browser, bearer, "gate_mcp_config_apply", apply_arguments(plan_b, "synthetic-current-revision")))
    assert wait(gate, applied_b["operation_id"])["status"] == "success"
    other = tokens(browser, created, targets={"synthetic-b": ["create"]})["access_token"]
    assert call(browser, other, "gate_mcp_config_apply", apply_arguments(plan_b, "synthetic-current-revision")).get("isError")
    assert call(browser, other, "gate_mcp_config_status", {"operation_id": applied_b["operation_id"]}).get("isError")
    assert tuple(db.query_one("SELECT * FROM gate_oauth_families WHERE id=?", (business_claims["fid"],))) == original_family
    assert tuple(db.query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (business_claims["gid"],))) == original_grant
    assert {item["name"] for item in protocol(browser, ordinary["access_token"], "tools/list", path="/mcp").json()["result"]["tools"]} == {"mcp__synthetic_business__read"}
    journal = db.query_one("SELECT status,result_json FROM mcp_idempotent_operations WHERE id=?", (applied_b["operation_id"],))
    assert journal["status"] == "succeeded" and json.loads(journal["result_json"])["terminal"]


def test_read_management_grant_cannot_apply_cancel_or_probe_and_unlisted_target_is_private(gate, browser, caplog):
    created = enable_management(gate, browser, readonly=True)
    bearer = tokens(browser, created, scope="operations.manage", tools=["gate_mcp_config_plan", "gate_mcp_config_status"])["access_token"]
    assert {tool["name"] for tool in protocol(browser, bearer, "tools/list").json()["result"]["tools"]} == {"gate_mcp_config_plan", "gate_mcp_config_status"}
    plan = output(call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-a")}))
    assert call(browser, bearer, "gate_mcp_config_apply", apply_arguments(plan)).get("isError")
    assert call(browser, bearer, "gate_mcp_config_cancel", {"operation_id": "0" * 32, "idempotency_key": "synthetic-cancel", "confirmed": True}).get("isError")
    assert call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-a"), "probe": True, "probe_confirmed": True}).get("isError")
    for tool, args in (("gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-other")}),
                       ("gate_mcp_config_status", {"server_id": "synthetic-other"})):
        assert call(browser, bearer, tool, args).get("isError")
    invalid = manifest("synthetic-a")
    invalid["transport"]["headers"] = {"Authorization": "Bearer Synthetic-Never-Persisted-Secret"}
    rejected = call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": invalid})
    assert rejected.get("isError") and "Synthetic-Never-Persisted-Secret" not in json.dumps(rejected) + caplog.text
    assert not gate["calls"] and not gate["app"].state.mcp_config_store.list_configs().configs


@pytest.mark.parametrize("direction", ["business_to_management", "management_to_business"])
def test_asgi_code_jwt_and_refresh_reject_bidirectional_resource_substitution(gate, browser, direction):
    created = enable_management(gate, browser, resources=["business", "management"])
    business_fixture(gate)
    source, target = (MANAGEMENT_RESOURCE, RESOURCE) if direction == "management_to_business" else (RESOURCE, MANAGEMENT_RESOURCE)
    scope = "operations.manage tools.invoke" if source == MANAGEMENT_RESOURCE else "tools.read"
    selected = sorted(MANAGEMENT_TOOL_IDS) if source == MANAGEMENT_RESOURCE else ["mcp.synthetic_business.read"]
    code = consent_code(browser, created, resource=source, scope=scope, tools=selected)
    fields = {"grant_type": "authorization_code", "client_id": created["client"]["id"], "client_secret": created["client_secret"],
              "redirect_uri": REDIRECT, "code_verifier": VERIFIER, "code": code}
    assert browser.post("/oauth/token", data={**fields, "resource": target}).status_code == 400
    issued = browser.post("/oauth/token", data={**fields, "resource": source})
    assert issued.status_code == 200
    issued = issued.json()
    assert protocol(browser, issued["access_token"], "tools/list", path=urlsplit(target).path).status_code == 401
    refresh = {"grant_type": "refresh_token", "refresh_token": issued["refresh_token"],
               "client_id": created["client"]["id"], "client_secret": created["client_secret"]}
    assert browser.post("/oauth/token", data={**refresh, "resource": target}).status_code == 400
    assert browser.post("/oauth/token", data={**refresh, "resource": source}).status_code == 200
    assert not gate["calls"]


@pytest.mark.parametrize("mutation", ["client", "grant", "family", "token_expiry", "grant_expiry", "family_expiry", "role", "scope", "tool", "targets", "operations_permission", "write_permission"])
def test_queued_work_rechecks_all_authority_before_first_side_effect(gate, browser, monkeypatch, mutation):
    created = enable_management(gate, browser)
    bearer = tokens(browser, created)["access_token"]
    claims = jwt.decode(bearer, options={"verify_signature": False})
    db, service = gate["service"].database, gate["service"]
    plan = output(call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-a"), "connect": True}))
    with service.configs.mutation_lock:
        operation = output(call(browser, bearer, "gate_mcp_config_apply", apply_arguments(plan)))
        if mutation == "client":
            db.execute("UPDATE gate_oauth_clients SET enabled=0 WHERE id=?", (claims["client_id"],))
        elif mutation == "grant":
            db.execute("UPDATE gate_oauth_grants SET revoked_at=? WHERE id=?", (int(time.time()), claims["gid"]))
        elif mutation == "family":
            db.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE id=?", (int(time.time()), claims["fid"]))
        elif mutation == "grant_expiry":
            db.execute("UPDATE gate_oauth_grants SET expires_at=0 WHERE id=?", (claims["gid"],))
        elif mutation == "family_expiry":
            db.execute("UPDATE gate_oauth_families SET expires_at=0 WHERE id=?", (claims["fid"],))
        elif mutation == "token_expiry":
            original = time.time
            monkeypatch.setattr("lingshu_gate.oauth_server.time.time", lambda: original() + 601)
        elif mutation == "role":
            db.execute("DELETE FROM user_roles WHERE user_id=? AND role_id IN (SELECT id FROM roles WHERE code='admin')", (claims["sub"],))
        elif mutation == "scope":
            db.execute("UPDATE gate_oauth_families SET scopes_json='[\"operations.manage\"]' WHERE id=?", (claims["fid"],))
        elif mutation == "tool":
            row = db.query_one("SELECT tools_json FROM gate_oauth_grants WHERE id=?", (claims["gid"],))
            tools = json.loads(row[0])
            tools.pop("gate_mcp_config_apply")
            db.execute("UPDATE gate_oauth_grants SET tools_json=? WHERE id=?", (json.dumps(tools), claims["gid"]))
        elif mutation == "targets":
            db.execute("UPDATE gate_oauth_grants SET management_targets_json='{}',target_revision=target_revision+1 WHERE id=?", (claims["gid"],))
        else:
            permission = "operations.manage" if mutation == "operations_permission" else "tools.invoke"
            db.execute("DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE code='admin') "
                       "AND permission_id IN (SELECT id FROM control_permissions WHERE code=?)", (permission,))
    # The invalid bearer is deliberately unusable for status. Read the local
    # operation record as test evidence instead of manufacturing a fresh token.
    deadline = time.monotonic() + 5
    result = None
    while time.monotonic() < deadline:
        row = db.query_one("SELECT result_json FROM external_mcp_config_operations WHERE id=?", (operation["operation_id"],))
        result = json.loads(row[0])
        if result["terminal"]:
            break
        time.sleep(.01)
    assert result and result["terminal"] and result["status"] == "failed" and result["config_applied"] is False
    assert result["error_code"] == "external_config_oauth_denied"
    assert not gate["calls"] and not service.configs.list_configs().configs


def test_cancel_and_terminal_race_keep_saved_configuration_and_do_not_claim_remote_stop(gate, browser):
    created = enable_management(gate, browser)
    bearer = tokens(browser, created)["access_token"]
    started, release = threading.Event(), threading.Event()
    gate["mode"]["wait"] = (started, release)
    plan = output(call(browser, bearer, "gate_mcp_config_plan", {"mode": "create", "manifest": manifest("synthetic-a"), "connect": True}))
    operation = output(call(browser, bearer, "gate_mcp_config_apply", apply_arguments(plan)))
    assert started.wait(2)
    args = {"operation_id": operation["operation_id"], "idempotency_key": "synthetic-cancel-one", "confirmed": True}
    cancelled = output(call(browser, bearer, "gate_mcp_config_cancel", args))
    assert cancelled["status"] == "cancel_requested" and cancelled["terminal"] is False
    release.set()
    result = wait(gate, operation["operation_id"])
    assert result["status"] == "cancelled" and result["config_applied"] and not result["remote_process_started"]
    assert output(call(browser, bearer, "gate_mcp_config_cancel", args))["idempotent_replay"]
    terminal = output(call(browser, bearer, "gate_mcp_config_cancel", {**args, "idempotency_key": "synthetic-cancel-terminal"}))
    assert terminal["status"] == "already_terminal" and terminal["terminal"]
    assert gate["app"].state.mcp_config_store.get_config("synthetic-a")


def test_foreign_issuer_grant_family_and_nonadmin_never_gain_management_authority(gate, browser):
    created = enable_management(gate, browser)
    first, second = tokens(browser, created), tokens(browser, created)
    server = gate["app"].state.oauth_server
    claims = jwt.decode(first["access_token"], options={"verify_signature": False})
    other = jwt.decode(second["access_token"], options={"verify_signature": False})
    key = server.store.database.query_one("SELECT * FROM gate_oauth_keys WHERE active=1")
    private = serialization.load_pem_private_key(server._fernet().decrypt(key["encrypted_private"].encode()), password=None)
    for change in ({"iss": "https://external-issuer.example.test"}, {"fid": other["fid"]}, {"gid": other["gid"]}, {"sub": "synthetic-foreign-owner"}):
        forged = jwt.encode({**claims, **change}, private, algorithm="RS256", headers={"kid": key["kid"], "typ": "at+jwt"})
        assert protocol(browser, forged, "tools/list").status_code == 401
    gate["auth"].create_user(username="synthetic-operator", password=PASSWORD, role="operator")
    params = {"client_id": created["client"]["id"], "redirect_uri": REDIRECT, "response_type": "code", "resource": MANAGEMENT_RESOURCE,
        "scope": "operations.manage tools.invoke", "code_challenge": CHALLENGE, "code_challenge_method": "S256"}
    redirected = browser.get("/oauth/authorize", params=params, follow_redirects=False)
    ticket = parse_qs(urlsplit(redirected.headers["location"]).fragment)["request"][0]
    context = browser.get("/oauth/context", params={"request_id": ticket}).json()
    denied = browser.post("/oauth/login", json={"request_id": ticket, "csrf": context["csrf"], "username": "synthetic-operator", "password": PASSWORD}, headers={"Origin": ISSUER})
    assert denied.status_code == 403 and denied.json()["error"] == "management_admin_required"
    assert not gate["calls"]


def test_target_confirmation_is_owner_session_cas_bound_atomic_and_expiring(gate, browser, monkeypatch):
    created = enable_management(gate, browser)
    issued = tokens(browser, created)
    server, db = gate["app"].state.oauth_server, gate["service"].database
    claims = jwt.decode(issued["access_token"], options={"verify_signature": False})
    grant = next(grant for grant in server.store.grants(gate["principal"].id) if grant["id"] == claims["gid"])
    path, body, pending = target_edit(browser, grant, {"synthetic-b": ["create"]}, save=False)
    snapshot = tuple(db.query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (grant["id"],)))
    families = [tuple(row) for row in db.query_all("SELECT * FROM gate_oauth_families WHERE grant_id=?", (grant["id"],))]
    assert browser.post(path, json={**body, "expected_target_revision": body["expected_target_revision"] + 1, "confirmation": pending["confirmation"]}, headers={"Origin": ISSUER}).status_code == 409
    _, foreign_session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
    original_cookie = browser.cookies.get(gate["auth"].cookie_name)
    browser.cookies.set(gate["auth"].cookie_name, foreign_session)
    assert browser.post(path, json={**body, "confirmation": pending["confirmation"]}, headers={"Origin": ISSUER}).status_code == 403
    browser.cookies.set(gate["auth"].cookie_name, original_cookie)
    original_emit = ObservabilityStore.emit_event

    def fail_audit(self, event_type, **kwargs):
        if event_type == "gate.oauth.management_targets_updated":
            raise RuntimeError("Synthetic audit failure")
        return original_emit(self, event_type, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(ObservabilityStore, "emit_event", fail_audit)
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            browser.post(path, json={**body, "confirmation": pending["confirmation"]}, headers={"Origin": ISSUER})
    assert tuple(db.query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (grant["id"],))) == snapshot
    assert [tuple(row) for row in db.query_all("SELECT * FROM gate_oauth_families WHERE grant_id=?", (grant["id"],))] == families
    assert db.query_one("SELECT * FROM gate_oauth_scope_confirmations WHERE grant_id=?", (grant["id"],))
    original = time.time
    monkeypatch.setattr("lingshu_gate.oauth_server.time.time", lambda: original() + 601)
    assert browser.post(path, json={**body, "confirmation": pending["confirmation"]}, headers={"Origin": ISSUER}).status_code == 403
    assert tuple(db.query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (grant["id"],))) == snapshot

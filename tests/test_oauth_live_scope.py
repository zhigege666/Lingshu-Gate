"""Owner-confirmed live grant updates with synthetic HTTP MCP execution."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.auth import hash_secret
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.external_connection_store import ExternalConnectionStore
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.mcp_http_trust import McpHttpTrustStore, McpHttpTrustUpdate, TrustedHttpOrigin
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.oauth_server import OAuthError, SCOPE_CONFIRMATION_TTL
from lingshu_gate.oauth_store import OAuthStore, _interaction_capacity_schema, _schema
from lingshu_gate.persistence.migrations import Migration, MigrationRunner
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, REDIRECT, RESOURCE, VERIFIER, enable, exchange, issue_code, refresh
from test_builtin_oauth import gate as gate


def initial(gate, *, both=False):
    client, secret = enable(gate)
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client, tools=["mcp.A.read", "mcp.A.write"] if both else None))
    grant = gate["server"].store.grants(gate["users"]["alice"]["id"])[0]
    return client, secret, grant, tokens


def allow_b(gate):
    gate["access"].save_grant(subject_type="user", subject_id=gate["users"]["alice"]["id"], server_id="B",
                              permission_type_code="write", created_by=gate["admin"]["id"])


def options(gate, grant):
    return gate["server"].scope_options(gate["principals"]["alice"], grant["id"], gate["sessions"]["alice"])


def preview(gate, grant, *, ids=None, offered=None, **limits):
    offered = offered or options(gate, grant)
    return gate["server"].preview_scope(gate["principals"]["alice"], grant["id"], gate["sessions"]["alice"], offered["csrf"],
        grant["revision"], ids if ids is not None else ["mcp.A.read", "mcp.B.read"],
        limits.get("expires_at", grant["expires_at"]), limits.get("rate", grant["rate_per_minute"]), limits.get("concurrency", grant["concurrency"]))


def apply(gate, grant, offered, **overrides):
    return gate["server"].update_scope(gate["principals"]["alice"], grant["id"], gate["sessions"]["alice"], offered["confirmation"],
        grant["revision"], overrides.get("ids", offered["tool_ids"]), overrides.get("expires_at", offered["expires_at"]),
        overrides.get("rate", offered["rate_per_minute"]), overrides.get("concurrency", offered["concurrency"]))


@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
@pytest.mark.parametrize("access", ["read", "write"])
def test_same_http_bearer_lists_and_calls_new_mcp_after_owner_confirmation_and_refresh(gate, protocol, access):
    client, secret = enable(gate)
    allow_b(gate)
    calls = []

    class SafeDownstream:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, **kwargs):
            calls.append((server_id, tool_name, arguments, user_id))
            return {"content": [{"type": "text", "text": "isolated synthetic " + server_id}]}

    gate["access"].attach_mcp_runtime(SafeDownstream())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"], gate["auth"].authenticate_mcp_request,
                              McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    original_ids = ["mcp.A.read"] if access == "read" else ["mcp.A.read", "mcp.A.write"]
    original_names = {"mcp__A__" + key.rsplit(".", 1)[1] for key in original_ids}
    code = issue_code(gate, client, tools=original_ids)
    grant = gate["server"].store.grants(gate["users"]["alice"]["id"])[0]
    other_code = issue_code(gate, client, tools=original_ids)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        token_fields = {"grant_type": "authorization_code", "resource": RESOURCE, "redirect_uri": REDIRECT,
                        "code_verifier": VERIFIER, "client_id": client["id"], "client_secret": secret}
        issued = browser.post("/oauth/token", data={**token_fields, "code": code})
        assert issued.status_code == 200
        original = issued.json()
        other = browser.post("/oauth/token", data={**token_fields, "code": other_code}).json()
        before_family = [tuple(row) for row in gate["db"].query_all("SELECT * FROM gate_oauth_families ORDER BY id")]

        def mcp(token, method, params=None):
            prepared, headers = build_protocol_request(method, params, client_name="Synthetic", client_version="1", protocol_version=protocol)
            return browser.post("/mcp", headers={**headers, "Authorization": "Bearer " + token},
                                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared})

        def names(token):
            result = mcp(token, "tools/list")
            assert result.status_code == 200
            return {item["name"] for item in result.json()["result"]["tools"]}

        bearer = original["access_token"]
        assert names(bearer) == original_names
        denied = mcp(bearer, "tools/call", {"name": "mcp__B__" + access, "arguments": {}})
        assert denied.json()["result"]["isError"] and calls == []
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        path = f"/v1/auth/oauth/grants/{grant['id']}"
        offered = browser.get(path + "/scope-options").json()
        body = {"expected_revision": grant["revision"], "tool_ids": original_ids + ["mcp.B." + access],
                "expires_at": grant["expires_at"], "rate_per_minute": 30, "concurrency": 1}
        prepared = browser.post(path + "/scope-preview", json={**body, "csrf": offered["csrf"]}, headers={"Origin": ISSUER})
        assert prepared.status_code == 200 and prepared.json()["added"] == ["mcp.B." + access]
        assert names(bearer) == original_names  # Preview grants nothing.
        saved = browser.post(path + "/scope", json={**body, "confirmation": prepared.json()["confirmation"]}, headers={"Origin": ISSUER})
        assert saved.status_code == 200 and saved.json()["revision"] == 2 and saved.json()["scopes"] == grant["scopes"]
        assert [tuple(row) for row in gate["db"].query_all("SELECT * FROM gate_oauth_families ORDER BY id")] == before_family
        assert names(bearer) == original_names | {"mcp__B__" + access}
        called = mcp(bearer, "tools/call", {"name": "mcp__B__" + access, "arguments": {"synthetic": True}})
        assert called.status_code == 200 and not called.json()["result"].get("isError", False)
        assert calls == [("B", access, {"synthetic": True}, grant["user_id"])]
        assert names(other["access_token"]) == original_names
        assert mcp(other["access_token"], "tools/call", {"name": "mcp__B__" + access}).json()["result"]["isError"]
        rotated = browser.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": original["refresh_token"],
            "resource": RESOURCE, "client_id": client["id"], "client_secret": secret})
        assert rotated.status_code == 200 and set(rotated.json()["scope"].split()) == set(grant["scopes"])
        assert names(rotated.json()["access_token"]) == original_names | {"mcp__B__" + access}
        assert not mcp(rotated.json()["access_token"], "tools/call", {"name": "mcp__B__" + access}).json()["result"].get("isError", False)
        event = gate["db"].query_one("SELECT * FROM events WHERE type='gate.oauth.grant_scope_updated'")
        audit = json.loads(event["payload_json"])
        assert event["subject_id"] == grant["id"] and audit["actor_id"] == grant["user_id"]
        assert audit["added_tool_ids"] == ["mcp.B." + access] and audit["scopes_unchanged"] is True
        assert bearer not in event["payload_json"] and secret not in event["payload_json"]


def test_scope_ceiling_stays_after_removing_last_write_tool_but_narrowed_family_is_not_widened(gate):
    client, secret, grant, tokens = initial(gate, both=True)
    allow_b(gate)
    reduced = refresh(gate["server"], client, secret, tokens["refresh_token"], scope="tools.read")
    before_family = dict(gate["db"].query_one("SELECT * FROM gate_oauth_families"))
    read_only = apply(gate, grant, preview(gate, grant, ids=["mcp.A.read"]))
    assert read_only["scopes"] == ["tools.invoke", "tools.read"]
    assert options(gate, read_only)["family_scope_limits"] == [{"scopes": ["tools.read"], "count": 1}]
    mixed = apply(gate, read_only, preview(gate, read_only, ids=["mcp.A.read", "mcp.B.write"]))
    assert set(mixed["tools"]) == {"mcp.A.read", "mcp.B.write"} and mixed["scopes"] == grant["scopes"]
    assert dict(gate["db"].query_one("SELECT * FROM gate_oauth_families")) == before_family
    assert gate["server"].verify(reduced["access_token"]).external_tool_ids == ("mcp.A.read",)
    with pytest.raises(OAuthError, match="invalid_scope"):
        refresh(gate["server"], client, secret, reduced["refresh_token"], scope="tools.read tools.invoke")


def test_scope_options_never_guess_missing_original_scope_from_client_configuration(gate):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    offered = options(gate, grant)
    assert offered["scopes"] == offered["effective_scopes"] == ["tools.read"]
    assert {tool["id"] for tool in offered["tools"]} == {"mcp.A.read", "mcp.B.read"}
    assert gate["db"].query_all("SELECT * FROM gate_oauth_scope_confirmations") == []
    with pytest.raises(OAuthError, match="grant_scope_insufficient"):
        preview(gate, grant, ids=["mcp.A.read", "mcp.B.write"], offered=offered)


@pytest.mark.parametrize("stage", ["preview", "apply"])
@pytest.mark.parametrize("mutation", ["session", "user", "role", "tool", "client", "configuration", "grant", "resource"])
def test_update_rechecks_live_identity_permissions_and_revisions(gate, stage, mutation):
    client, _, grant, _ = initial(gate)
    allow_b(gate)
    offered = options(gate, grant)
    prepared = preview(gate, grant, offered=offered) if stage == "apply" else None
    if mutation == "session":
        gate["auth"].logout(gate["sessions"]["alice"])
    elif mutation == "user":
        gate["db"].execute("UPDATE users SET status='disabled' WHERE id=?", (grant["user_id"],))
    elif mutation == "role":
        gate["access"].save_role(code="no-personal-credentials", name="Synthetic reduced role", description="",
                                 permissions=["console.view", "tools.read"])
        gate["access"].set_user_roles(grant["user_id"], ["no-personal-credentials"])
    elif mutation == "tool":
        gate["registry"].unregister_by_metadata("server_id", "B", source="mcp")
    elif mutation == "client":
        gate["server"].update_client(client["id"], 1, name=client["name"], redirects=client["redirect_uris"], scopes=client["scopes"], enabled=False)
    elif mutation == "configuration":
        gate["server"].save_config({"enabled": True, "issuer": ISSUER, "resource": RESOURCE}, 2)
    elif mutation == "grant":
        gate["server"].narrow_grant(grant["user_id"], grant["id"], 1, ["mcp.A.read"], grant["expires_at"], 20, 1)
    else:
        gate["db"].execute("UPDATE gate_oauth_grants SET resource='https://other.example.test/mcp' WHERE id=?", (grant["id"],))
    with pytest.raises(OAuthError):
        apply(gate, grant, prepared) if prepared else preview(gate, grant, offered=offered)
    assert "mcp.B.read" not in gate["server"].store.grants(grant["user_id"])[0]["tools"]
    assert not gate["db"].query_all("SELECT * FROM events WHERE type='gate.oauth.grant_scope_updated'")


@pytest.mark.parametrize("field,value", [("ids", ["mcp.B.read"]), ("rate", 20), ("concurrency", 2), ("expires_at", 1)])
def test_confirmation_binds_target_content(gate, field, value):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    prepared = preview(gate, grant)
    with pytest.raises(OAuthError):
        apply(gate, grant, prepared, **{field: value})
    assert gate["server"].store.grants(grant["user_id"])[0] == grant


def test_replaced_and_replayed_confirmation_cannot_apply(gate):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    first = preview(gate, grant)
    second = preview(gate, grant, ids=["mcp.B.read"])
    with pytest.raises(OAuthError, match="scope_confirmation_changed"):
        apply(gate, grant, first)
    saved = apply(gate, grant, second)
    assert list(saved["tools"]) == ["mcp.B.read"]
    with pytest.raises(OAuthError, match="revision_conflict"):
        apply(gate, grant, second)
    assert len(gate["db"].query_all("SELECT * FROM events WHERE type='gate.oauth.grant_scope_updated'")) == 1


def test_audit_failure_rolls_back_grant_and_confirmation_consumption(gate, monkeypatch):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    prepared = preview(gate, grant)
    before = dict(gate["db"].query_one("SELECT * FROM gate_oauth_scope_confirmations"))

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic audit failure")

    with monkeypatch.context() as patch:
        patch.setattr(ObservabilityStore, "emit_event", fail)
        with pytest.raises(sqlite3.OperationalError, match="synthetic audit failure"):
            apply(gate, grant, prepared)
    assert gate["server"].store.grants(grant["user_id"])[0] == grant
    assert dict(gate["db"].query_one("SELECT * FROM gate_oauth_scope_confirmations")) == before
    assert set(apply(gate, grant, prepared)["tools"]) == {"mcp.A.read", "mcp.B.read"}


def test_concurrent_confirmation_has_one_commit_and_one_audit(gate):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    prepared = preview(gate, grant)
    barrier = threading.Barrier(2)

    def attempt(_):
        barrier.wait(timeout=3)
        try:
            return apply(gate, grant, prepared)
        except OAuthError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1 and results.count("revision_conflict") == 1
    assert len(gate["db"].query_all("SELECT * FROM events WHERE type='gate.oauth.grant_scope_updated'")) == 1


def test_expired_options_and_confirmation_fail_closed(gate, monkeypatch):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    offered = options(gate, grant)
    prepared = preview(gate, grant, offered=offered)
    instant = int(time.time())
    monkeypatch.setattr("lingshu_gate.oauth_server.time.time", lambda: instant + SCOPE_CONFIRMATION_TTL + 1)
    with pytest.raises(OAuthError, match="invalid_csrf"):
        preview(gate, grant, offered=offered)
    with pytest.raises(OAuthError, match="scope_confirmation_changed"):
        apply(gate, grant, prepared)


def test_http_owner_console_origin_csrf_and_strict_fields(gate):
    _, _, grant, tokens = initial(gate)
    allow_b(gate)
    path = f"/v1/auth/oauth/grants/{grant['id']}"
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        assert browser.get(path + "/scope-options").status_code == 401
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["bob"])
        assert browser.get(path + "/scope-options").status_code == 404
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        assert browser.get(path + "/scope-options", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert browser.get(path + "/scope-options", headers={"Authorization": "Bearer " + tokens["access_token"]}).status_code == 401
        api = gate["auth"].create_api_token(principal=gate["principals"]["alice"], name="synthetic", scopes=["credentials.manage.self"])
        assert browser.get(path + "/scope-options", headers={"Authorization": "Bearer " + str(api["token"])}).json()["error"] == "session_required"
        offered = browser.get(path + "/scope-options").json()
        body = {"expected_revision": 1, "csrf": offered["csrf"], "tool_ids": ["mcp.A.read", "mcp.B.read"],
                "expires_at": grant["expires_at"], "rate_per_minute": 30, "concurrency": 1}
        for headers in [{}, {"Origin": "https://other.example.test"}, {"Origin": ISSUER, "Sec-Fetch-Site": "none"}]:
            assert browser.post(path + "/scope-preview", json=body, headers=headers).status_code == 403
        assert browser.post(path + "/scope-preview", json={**body, "csrf": "synthetic-invalid-" * 4}, headers={"Origin": ISSUER}).status_code == 403
        assert browser.post(path + "/scope-preview", json={**body, "client_id": "other"}, headers={"Origin": ISSUER}).status_code == 400
        prepared = browser.post(path + "/scope-preview", json=body, headers={"Origin": ISSUER}).json()
        write = {key: value for key, value in body.items() if key != "csrf"} | {"confirmation": prepared["confirmation"]}
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["bob"])
        assert browser.post(path + "/scope", json=write, headers={"Origin": ISSUER}).status_code == 403
        browser.cookies.set(gate["auth"].cookie_name, gate["oauth_sessions"]["alice"])
        assert browser.post(path + "/scope", json=write, headers={"Origin": ISSUER}).status_code == 401
        browser.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        assert browser.post(path + "/scope", json=write).status_code == 403
        assert browser.post(path + "/scope", json=write, headers={"Origin": ISSUER}).status_code == 200


@pytest.mark.parametrize("bad_ids", [[], ["mcp.A.read", "mcp.A.read"], ["mcp.missing.read"], ["mcp.A.read"] * 5001])
def test_invalid_selection_never_creates_confirmation(gate, bad_ids):
    _, _, grant, _ = initial(gate)
    with pytest.raises(OAuthError):
        preview(gate, grant, ids=bad_ids)
    assert not gate["db"].query_all("SELECT * FROM gate_oauth_scope_confirmations")


def test_confirmation_migration_is_idempotent_and_old_draft_migration_was_never_published(gate):
    _, _, grant, _ = initial(gate)
    before = gate["server"].store.grants(grant["user_id"])
    OAuthStore(gate["db"])
    assert gate["server"].store.grants(grant["user_id"]) == before
    assert gate["db"].query_one("SELECT COUNT(*) FROM schema_migrations WHERE id='0009_oauth_scope_confirmations'")[0] == 1
    assert not gate["db"].query_one("SELECT name FROM sqlite_master WHERE name='gate_oauth_reauthorization_drafts'")


@pytest.mark.parametrize("historical_server", ["0", "Z"])
def test_same_tool_id_classifications_are_bound_to_current_resource_and_reconfirmed(gate, historical_server):
    client, _, grant, tokens = initial(gate, both=True)
    previous = gate["registry"].get_definition("mcp.A.write")
    relocated = previous.model_copy(update={"metadata": {**previous.metadata, "server_id": historical_server}})
    gate["registry"].register(relocated, lambda arguments: None, replace=True)
    gate["access"].save_grant(subject_type="user", subject_id=grant["user_id"], server_id=historical_server,
                              permission_type_code="write", created_by=gate["admin"]["id"])
    gate["access"].synchronize_tools(gate["registry"].list_definitions())
    gate["access"].set_classification(server_id=historical_server, tool_id=relocated.id, access="write", destructive=False,
                                     idempotent=False, reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id=historical_server, reviewer_id=gate["admin"]["id"])
    current = gate["server"].catalog(gate["principals"]["alice"], client["scopes"])[relocated.id]
    classification = next(item for item in gate["access"].list_classifications(server_id=historical_server) if item["tool_id"] == relocated.id)
    assert current["server_id"] == historical_server
    assert current["snapshot"] == hash_secret(json.dumps([classification["fingerprint"], "write", classification["reviewed_at"]], sort_keys=True))
    assert "mcp.A.write" not in gate["server"].verify(tokens["access_token"]).external_tool_ids
    prepared = preview(gate, grant, ids=["mcp.A.read", "mcp.A.write"])
    assert prepared["added"] == prepared["removed"] == ["mcp.A.write"]
    assert "mcp.A.write" not in gate["server"].verify(tokens["access_token"]).external_tool_ids
    apply(gate, grant, prepared)
    assert "mcp.A.write" in gate["server"].verify(tokens["access_token"]).external_tool_ids


def test_live_resource_permission_revocation_after_preview_cannot_commit(gate):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    prepared = preview(gate, grant)
    gate["db"].execute("DELETE FROM mcp_resource_grants WHERE subject_type='user' AND subject_id=? AND server_id='B'", (grant["user_id"],))
    with pytest.raises(OAuthError, match="tool_scope_changed"):
        apply(gate, grant, prepared)


@pytest.mark.parametrize("limit,value", [("expires_at", 9999999999), ("rate", 31), ("concurrency", 2)])
def test_live_scope_update_cannot_increase_expiry_or_quotas(gate, limit, value):
    _, _, grant, _ = initial(gate)
    allow_b(gate)
    with pytest.raises(OAuthError, match="grant_limits_can_only_narrow"):
        preview(gate, grant, **{limit: value})


def test_confirmation_capacity_replacement_and_expiry_cleanup_are_bounded(gate, monkeypatch):
    client, _, grant, _ = initial(gate)
    allow_b(gate)
    monkeypatch.setattr("lingshu_gate.oauth_server.MAX_SCOPE_CONFIRMATIONS", 1)
    monkeypatch.setattr("lingshu_gate.oauth_server.MAX_USER_SCOPE_CONFIRMATIONS", 1)
    first = preview(gate, grant)
    replacement = preview(gate, grant, ids=["mcp.B.read"])
    assert replacement["confirmation"] != first["confirmation"]
    issue_code(gate, client)
    other = next(item for item in gate["server"].store.grants(grant["user_id"]) if item["id"] != grant["id"])
    with pytest.raises(OAuthError, match="scope_confirmation_capacity"):
        preview(gate, other)
    gate["db"].execute("UPDATE gate_oauth_scope_confirmations SET expires_at=?", (int(time.time()) - 1,))
    assert preview(gate, other)["added"] == ["mcp.B.read"]
    assert gate["db"].query_one("SELECT COUNT(*) FROM gate_oauth_scope_confirmations")[0] == 1


def test_published_v042_nonempty_database_upgrade_and_second_start_preserve_existing_data(gate, tmp_path, monkeypatch):
    # main assembles its module-level app on import; keep that donor instance
    # inside the same temporary fixture before constructing the legacy DB.
    for key, value in {"DB_URL": gate["settings"].db_url, "DATA_DIR": str(gate["settings"].data_dir),
                       "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path)}.items():
        monkeypatch.setenv("LINGSHU_GATE_" + key, value)
    import lingshu_gate.main as main_module

    client, secret, grant, old_tokens = initial(gate)
    outstanding_code = issue_code(gate, client)
    api_token = gate["auth"].create_api_token(principal=gate["principals"]["alice"], name="Synthetic upgrade token", scopes=["tools.read"])
    ExternalConnectionStore(gate["db"])
    trust = McpHttpTrustStore(gate["db"])
    trust.update("synthetic-upgrade-private", McpHttpTrustUpdate(expected_revision=0, confirmed=True,
        origins=[TrustedHttpOrigin(ip="10.23.45.67", port=8080)]), actor_id=gate["admin"]["id"])

    # The published 0.4.2 source registers exactly these two immutable OAuth
    # migrations and 0009_mcp_http_trust. Build that schema before copying
    # synthetic legacy records; the new confirmation migration has never run here.
    legacy_url = f"sqlite:///{tmp_path / 'published-v042.db'}"
    legacy = SQLiteDatabase(legacy_url, gate["settings"].data_dir)
    MigrationRunner(legacy.connect, (Migration("0006_builtin_oauth", _schema),
        Migration("0008_oauth_interaction_capacity", _interaction_capacity_schema))).run()
    McpHttpTrustStore(legacy)
    ExternalConnectionStore(legacy)
    tables = [row[0] for row in legacy.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    with legacy.session() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in tables:
            connection.execute(f'DELETE FROM "{table}"')
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            fields = ",".join(f'"{column}"' for column in columns)
            rows = gate["db"].query_all(f'SELECT {fields} FROM "{table}"')
            if table == "schema_migrations":
                rows = [row for row in rows if row["id"] != "0009_oauth_scope_confirmations"]
            connection.executemany(f'INSERT INTO "{table}" ({fields}) VALUES ({",".join("?" for _ in columns)})',
                                   [tuple(row) for row in rows])
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not legacy.query_one("SELECT name FROM sqlite_master WHERE name='gate_oauth_scope_confirmations'")
    before_migrations = {row["id"]: row["applied_at"] for row in legacy.query_all("SELECT * FROM schema_migrations")}
    assert {"0006_builtin_oauth", "0008_oauth_interaction_capacity", "0009_mcp_http_trust"} <= set(before_migrations)
    assert "0009_oauth_scope_confirmations" not in before_migrations
    preserved = ("users", "roles", "user_roles", "role_permissions", "control_permissions", "permission_types",
                 "mcp_resource_grants", "auth_sessions", "api_tokens", "gate_oauth_config", "gate_oauth_keys",
                 "gate_oauth_clients", "gate_oauth_grants", "gate_oauth_codes", "gate_oauth_families",
                 "gate_oauth_refresh", "gate_mcp_http_trust")

    def snapshot():
        result = {}
        for table in preserved:
            width = len(legacy.query_all(f'PRAGMA table_info("{table}")'))
            order = ",".join(str(index + 1) for index in range(width))
            result[table] = [tuple(row) for row in legacy.query_all(f'SELECT * FROM "{table}" ORDER BY {order}')]
        return result

    before = snapshot()
    definitions = gate["registry"].list_definitions()
    factory = main_module.create_registry

    def synthetic_registry():
        registry = factory()
        for definition in definitions:
            registry.register(definition, lambda arguments: None)
        return registry

    monkeypatch.setattr(main_module, "create_registry", synthetic_registry)
    for key, value in {"DB_URL": legacy_url, "DATA_DIR": str(gate["settings"].data_dir),
                       "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path)}.items():
        monkeypatch.setenv("LINGSHU_GATE_" + key, value)
    first_app = main_module.create_app()
    assert snapshot() == before
    after_migrations = {row["id"]: row["applied_at"] for row in legacy.query_all("SELECT * FROM schema_migrations")}
    assert {key: value for key, value in after_migrations.items() if key != "0009_oauth_scope_confirmations"} == before_migrations
    assert set(after_migrations) - set(before_migrations) == {"0009_oauth_scope_confirmations"}
    assert legacy.query_all("SELECT * FROM gate_oauth_scope_confirmations") == []
    upgraded = {**gate, "server": first_app.state.oauth_server, "db": legacy, "auth": first_app.state.auth_store}
    confirmation = preview(upgraded, grant, ids=["mcp.A.read"])
    confirmation_row = dict(legacy.query_one("SELECT * FROM gate_oauth_scope_confirmations WHERE grant_id=?", (grant["id"],)))
    assert confirmation_row["token_hash"] == hash_secret(confirmation["confirmation"])

    second_app = main_module.create_app()
    assert snapshot() == before
    assert {row["id"]: row["applied_at"] for row in legacy.query_all("SELECT * FROM schema_migrations")} == after_migrations
    assert dict(legacy.query_one("SELECT * FROM gate_oauth_scope_confirmations WHERE grant_id=?", (grant["id"],))) == confirmation_row
    server, auth = second_app.state.oauth_server, second_app.state.auth_store
    assert auth._principal_from_session(gate["sessions"]["alice"]).id == grant["user_id"]
    assert server.session_principal(gate["oauth_sessions"]["alice"]).id == grant["user_id"]
    assert auth._principal_from_api_token(str(api_token["token"])).id == grant["user_id"]
    second_app.state.mcp_config_store.http_trust_store.require_endpoint("synthetic-upgrade-private", "http://10.23.45.67:8080/mcp")
    assert server.verify(old_tokens["access_token"]).external_tool_ids == ("mcp.A.read",)
    exchanged = exchange(server, client, secret, outstanding_code)
    assert server.verify(exchanged["access_token"]).external_tool_ids == ("mcp.A.read",)
    with pytest.raises(OAuthError, match="invalid_scope"):
        refresh(server, client, secret, old_tokens["refresh_token"], scope="tools.read tools.invoke")
    rotated = refresh(server, client, secret, old_tokens["refresh_token"])
    assert server.verify(rotated["access_token"]).external_tool_ids == ("mcp.A.read",)
    assert dict(legacy.query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (grant["id"],))) == dict(gate["db"].query_one("SELECT * FROM gate_oauth_grants WHERE id=?", (grant["id"],)))

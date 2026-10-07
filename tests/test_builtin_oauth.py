"""Executable built-in OAuth security/regression tests with synthetic credentials.

ASGI requests and SQLite concurrency only; no external accounts or socket servers.
These tests must be run separately from a static-only implementation review.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthStore, hash_secret
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.external_connection_store import ExternalConnectionStore
from lingshu_gate.external_jwt import ExternalJwtVerifier
from lingshu_gate.interfaces.control_api.auth_routes import register_auth_routes
from lingshu_gate.interfaces.control_api.external_connection_routes import register_external_connection_routes
from lingshu_gate.interfaces.control_api.oauth_routes import OAuthRateBoundary, register_oauth_routes
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.logging import OAuthAccessLogFilter
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_server import ACCESS_TTL, BROWSER_COOKIE, SESSION_COOKIE, OAuthError, OAuthServer
from lingshu_gate.oauth_store import OAuthStore
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.persistence.migrations import Migration, MigrationRunner
from lingshu_gate.persistence.session_purpose_migration import SESSION_PURPOSE_MIGRATION_ID, apply_session_purpose_migration
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.redaction import REDACTED, redact_command, redact_text, redact_value
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata

ISSUER = "https://gate.example.test"
RESOURCE = ISSUER + "/mcp"
REDIRECT = "https://client.example.test/oauth/callback?environment=synthetic"
PASSWORD = "Synthetic-Only-123!"
VERIFIER = "synthetic-verifier-" + "a" * 48
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", PASSWORD)
    settings = Settings(data_dir=tmp_path, db_url=f"sqlite:///{tmp_path / 'oauth.db'}", auth_cookie_secure=True)
    db = SQLiteDatabase(settings.db_url, tmp_path)
    access = AccessControlStore(db)
    auth = AuthStore(settings, db)
    admin = auth.list_users()[0]
    auth.change_password(admin["id"], PASSWORD)
    access.save_role(code="writer", name="Writer", description="", permissions=[
        "console.view", "tools.read", "tools.invoke", "credentials.manage.self"])
    users, sessions, oauth_sessions, principals = {}, {}, {}, {}
    for name, role in (("alice", "writer"), ("bob", "writer"), ("reader", "viewer")):
        users[name] = auth.create_user(username=name, password=PASSWORD, role=role)
        principals[name], sessions[name], _ = auth.login(username=name, password=PASSWORD)
        _, oauth_sessions[name], _ = auth.login(username=name, password=PASSWORD, purpose="oauth_consent")
        access.save_grant(subject_type="user", subject_id=users[name]["id"], server_id="A",
                          permission_type_code="read" if name == "reader" else "write", created_by=admin["id"])
    registry = ToolRegistry()
    for server_id in "AB":
        for level in ("read", "write"):
            tool = ToolDefinition(id=f"mcp.{server_id}.{level}", name=f"{server_id}.{level}", source="mcp",
                                  description="Synthetic test tool", permission=level,
                                  metadata={"server_id": server_id, "server_name": f"Synthetic service {server_id}",
                                            "original_tool_name": level})
            registry.register(tool, lambda arguments: None)
    access.synchronize_tools(registry.list_definitions())
    for server_id in "AB":
        for level in ("read", "write"):
            access.set_classification(server_id=server_id, tool_id=f"mcp.{server_id}.{level}", access=level,
                                      destructive=False, idempotent=level == "read", reviewer_id=admin["id"])
        access.publish_classifications(server_id=server_id, reviewer_id=admin["id"])
    store = OAuthStore(db)
    server = OAuthServer(store, auth, access, registry, tmp_path)
    auth.builtin_oauth = server
    observability = ObservabilityStore(db)
    app = FastAPI()
    register_oauth_routes(app, server=server, observability=observability)
    register_auth_routes(app, settings=settings, auth_store=auth, observability_store=observability,
                         require_viewer=auth.authenticate_request)
    return {"server": server, "db": db, "auth": auth, "access": access, "registry": registry,
            "app": app, "settings": settings, "users": users, "sessions": sessions,
            "oauth_sessions": oauth_sessions, "principals": principals, "admin": admin}


def enable(gate):
    server = gate["server"]
    server.save_config({"enabled": False, "issuer": ISSUER, "resource": RESOURCE}, 0)
    server.rotate_key()
    created = server.create_client("Synthetic client", [REDIRECT], ["tools.read", "tools.invoke"])
    server.save_config({"enabled": True, "issuer": ISSUER, "resource": RESOURCE}, 1)
    return created["client"], created["client_secret"]


def parameters(client, **overrides):
    return {"client_id": client["id"], "redirect_uri": REDIRECT, "response_type": "code",
            "resource": RESOURCE, "scope": "tools.read tools.invoke", "code_challenge": CHALLENGE,
            "code_challenge_method": "S256", "state": "synthetic-state", **overrides}


def issue_code(gate, client, user="alice", tools=None, days=7):
    server, browser = gate["server"], "synthetic-browser-" + "b" * 32
    interaction = server.start_authorization(parameters(client), browser)
    context = server.consent_context(interaction, browser, gate["oauth_sessions"][user])
    redirect = server.consent(interaction, browser, context["csrf"], gate["principals"][user],
                              tools or ["mcp.A.read"], days, 30, 1)
    query = parse_qs(urlsplit(redirect).query)
    assert query["iss"] == [ISSUER] and query["state"] == ["synthetic-state"]
    return query["code"][0]


def exchange(server, client, secret, code, **overrides):
    return server.token({"grant_type": "authorization_code", "code": code, "resource": RESOURCE,
                         "redirect_uri": REDIRECT, "code_verifier": VERIFIER, **overrides}, client["id"], secret)


def refresh(server, client, secret, token, **overrides):
    return server.token({"grant_type": "refresh_token", "refresh_token": token, "resource": RESOURCE, **overrides},
                        client["id"], secret)


def mcp_request(token, path="/mcp"):
    return Request({"type": "http", "method": "POST", "path": path, "query_string": b"", "scheme": "https",
                    "server": ("gate.example.test", 443), "headers": [(b"authorization", ("Bearer " + token).encode())]})


def test_default_disabled_has_no_keys_clients_or_metadata(gate):
    server = gate["server"]
    assert not server.store.config()["enabled"] and not server.store.clients()
    assert not server.key_path.exists()
    assert not gate["db"].query_all("SELECT * FROM gate_oauth_keys")
    with TestClient(gate["app"], base_url=ISSUER) as client:
        assert client.get("/.well-known/oauth-authorization-server").status_code == 404
        assert client.get("/oauth/jwks").status_code == 404
    # Migration re-entry preserves data and does not generate any credentials.
    OAuthStore(gate["db"])
    assert not server.key_path.exists()


def test_admin_can_save_urls_without_keys_but_cannot_enable_without_an_active_key(gate):
    server = gate["server"]
    _, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        client.cookies.set(gate["auth"].cookie_name, session)
        payload = {"enabled": False, "issuer": ISSUER, "resource": RESOURCE, "expected_revision": 0}
        saved = client.put("/v1/auth/oauth/config", json=payload, headers={"Origin": ISSUER})
        assert saved.status_code == 200 and saved.json()["revision"] == 1
        assert saved.json()["signing_keys"] == []
        rejected = client.put("/v1/auth/oauth/config", json={**payload, "enabled": True, "expected_revision": 1}, headers={"Origin": ISSUER})
        assert rejected.status_code == 409 and rejected.json()["error"] == "signing_key_required"
        assert server.store.config() == {"enabled": False, "issuer": ISSUER, "resource": RESOURCE, "revision": 1}
        assert not server.key_path.exists() and not server.store.clients()


def test_legacy_console_session_purpose_migration_preserves_identity_and_expiry(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_sessions(id TEXT PRIMARY KEY,user_id TEXT,token_hash TEXT,expires_at TEXT)")
        connection.execute("INSERT INTO auth_sessions VALUES('legacy','alice','synthetic-digest','2030-01-01T00:00:00+00:00')")
    runner = MigrationRunner(lambda: sqlite3.connect(path),
                             (Migration(SESSION_PURPOSE_MIGRATION_ID, apply_session_purpose_migration),))
    assert runner.run() == (SESSION_PURPOSE_MIGRATION_ID,)
    assert runner.run() == ()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM auth_sessions").fetchone() == (
            "legacy", "alice", "synthetic-digest", "2030-01-01T00:00:00+00:00", "console")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE auth_sessions SET purpose='untrusted'")


def test_cookie_values_cannot_cross_console_and_public_oauth_purposes(gate):
    info, _ = enable(gate)
    auth, server = gate["auth"], gate["server"]
    console, consent = gate["sessions"]["alice"], gate["oauth_sessions"]["alice"]
    browser = "synthetic-purpose-browser"
    ticket = server.start_authorization(parameters(info), browser)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        # Deliberately copy the public cookie value to the private cookie name.
        client.cookies.set(auth.cookie_name, consent)
        assert client.get("/v1/auth/me").status_code == 401
        assert client.get("/v1/auth/oauth/clients").status_code == 401
        client.cookies.set(auth.cookie_name, console)
        assert client.get("/v1/auth/me").json()["id"] == gate["users"]["alice"]["id"]
        # The converse copy must not turn a private session into consent login.
        client.cookies.set(SESSION_COOKIE, console)
        client.cookies.set(BROWSER_COOKIE, browser)
        context = client.get("/oauth/context", params={"request_id": ticket}).json()
        assert context["user"] is None and context["phase"] == "preauth"
        client.cookies.set(SESSION_COOKIE, consent)
        context = client.get("/oauth/context", params={"request_id": ticket}).json()
        assert context["user"]["id"] == gate["users"]["alice"]["id"]
        assert context["phase"] == "authenticated"
    auth.logout(consent)  # Console logout cannot delete a public session.
    auth.logout(console, purpose="oauth_consent")
    assert server.session_principal(consent) is not None
    assert auth._principal_from_session(console) is not None
    assert auth._principal_from_session(consent) is None
    SQLiteDatabase(gate["settings"].db_url, gate["settings"].data_dir)
    assert server.session_principal(consent) is not None


def test_missing_username_runs_same_pbkdf2_work_and_uniform_error(gate, monkeypatch):
    calls = []
    original = hashlib.pbkdf2_hmac
    def observed(algorithm, password, salt, iterations):
        calls.append((algorithm, len(salt), iterations))
        return original(algorithm, password, salt, iterations)
    monkeypatch.setattr("lingshu_gate.auth.hashlib.pbkdf2_hmac", observed)
    errors = []
    for username in ("alice", "unknown-synthetic-user"):
        with pytest.raises(HTTPException) as failed:
            gate["auth"].login(username=username, password="synthetic-wrong", purpose="oauth_consent")
        errors.append((failed.value.status_code, failed.value.detail))
    assert calls == [("sha256", 32, 200_000)] * 2
    assert errors == [(401, "invalid username or password")] * 2


def test_lookup_digest_preserves_existing_sha256_encoding():
    assert hash_secret("public lookup regression metadata") == "289326bc4c5f3d6ef66ff2d8f6829e85267369b519c064c488ff21f8354e4f4d"


@pytest.mark.parametrize("purpose", ["console", "oauth_consent"])
def test_session_lookup_preserves_generated_token_sha256_identity(gate, monkeypatch, purpose):
    generated_sizes = []
    original = secrets.token_urlsafe

    def observed(size):
        generated_sizes.append(size)
        return original(size)

    monkeypatch.setattr("lingshu_gate.auth.secrets.token_urlsafe", observed)
    principal, token, _ = gate["auth"].login(username="alice", password=PASSWORD, purpose=purpose)
    assert generated_sizes == [32]
    row = gate["db"].query_one("SELECT token_hash, purpose FROM auth_sessions WHERE id=?", (principal.session_id,))
    assert row["token_hash"] == hash_secret(token)
    assert row["token_hash"] != token and row["purpose"] == purpose

    reopened = AuthStore(gate["settings"], gate["db"])
    assert reopened._principal_from_session(token, purpose=purpose).id == principal.id
    assert reopened._principal_from_session(token + "invalid", purpose=purpose) is None
    reopened.logout(token, purpose=purpose)
    assert reopened._principal_from_session(token, purpose=purpose) is None


def test_api_token_lookup_preserves_generated_token_sha256_identity(gate, monkeypatch):
    generated_sizes = []
    original = secrets.token_urlsafe

    def observed(size):
        generated_sizes.append(size)
        return original(size)

    monkeypatch.setattr("lingshu_gate.auth.secrets.token_urlsafe", observed)
    created = gate["auth"].create_api_token(principal=gate["principals"]["alice"], name="Synthetic hash regression", scopes=["tools.read"])
    token = created["token"]
    assert generated_sizes == [32] and token.startswith("lgt_")
    row = gate["db"].query_one("SELECT token_hash FROM api_tokens WHERE id=?", (created["id"],))
    assert row["token_hash"] == hash_secret(token)
    assert row["token_hash"] != token

    reopened = AuthStore(gate["settings"], gate["db"])
    assert reopened._principal_from_api_token(token).token_id == created["id"]
    assert reopened._principal_from_api_token(token + "invalid") is None
    reopened.revoke_api_token(created["id"], user_id=gate["users"]["alice"]["id"])
    assert reopened._principal_from_api_token(token) is None


def test_client_secret_is_generated_from_48_bytes_and_keeps_lookup_identity(gate, monkeypatch):
    generated_sizes = []
    original = secrets.token_urlsafe

    def observed(size):
        generated_sizes.append(size)
        return original(size)

    monkeypatch.setattr("lingshu_gate.oauth_server.secrets.token_urlsafe", observed)
    created = gate["server"].create_client("Synthetic hash regression", [REDIRECT], ["tools.read"])
    assert generated_sizes == [24, 48]
    secret = created["client_secret"]
    with gate["db"].session() as connection:
        row = connection.execute("SELECT secret_hash FROM gate_oauth_clients WHERE id=?", (created["client"]["id"],)).fetchone()
        assert row["secret_hash"] == hash_secret(secret)
        assert row["secret_hash"] != secret
        assert gate["server"].authenticate_client(connection, created["client"]["id"], secret)["id"] == created["client"]["id"]
        with pytest.raises(OAuthError) as rejected:
            gate["server"].authenticate_client(connection, created["client"]["id"], secret + "invalid")
        assert rejected.value.code == "invalid_client"


def test_create_change_and_login_password_paths_keep_salted_pbkdf2(gate, monkeypatch):
    calls = []
    original = hashlib.pbkdf2_hmac

    def observed(algorithm, password, salt, iterations):
        calls.append((algorithm, len(salt), iterations))
        return original(algorithm, password, salt, iterations)

    monkeypatch.setattr("lingshu_gate.auth.hashlib.pbkdf2_hmac", observed)
    fast_digest = hash_secret

    def tokens_only(value):
        assert value not in {PASSWORD, "Synthetic-Replacement-456!"}
        return fast_digest(value)

    monkeypatch.setattr("lingshu_gate.auth.hash_secret", tokens_only)
    user = gate["auth"].create_user(username="synthetic-hash-owner", password=PASSWORD, role="viewer")
    initial = gate["db"].query_one("SELECT password_hash FROM users WHERE id=?", (user["id"],))["password_hash"]
    gate["auth"].login(username="synthetic-hash-owner", password=PASSWORD)
    gate["auth"].change_password(user["id"], "Synthetic-Replacement-456!")
    changed = gate["db"].query_one("SELECT password_hash FROM users WHERE id=?", (user["id"],))["password_hash"]
    with pytest.raises(HTTPException) as rejected:
        gate["auth"].login(username="synthetic-hash-owner", password=PASSWORD)
    assert rejected.value.status_code == 401
    gate["auth"].login(username="synthetic-hash-owner", password="Synthetic-Replacement-456!")
    assert calls == [("sha256", 32, 200_000)] * 5
    assert initial.split("$")[0] == changed.split("$")[0] == "pbkdf2_sha256"
    assert initial.split("$")[1] != changed.split("$")[1]


def test_new_public_login_cleans_expired_public_sessions_without_changing_console_sessions(gate):
    auth, db = gate["auth"], gate["db"]
    console, consent = gate["sessions"]["alice"], gate["oauth_sessions"]["alice"]
    expired = datetime.fromtimestamp(int(time.time()) - 1, timezone.utc).isoformat()
    db.execute("UPDATE auth_sessions SET expires_at=? WHERE token_hash IN (?,?)", (expired, hash_secret(console), hash_secret(consent)))
    _, fresh, _ = auth.login(username="alice", password=PASSWORD, purpose="oauth_consent")
    assert db.query_one("SELECT purpose FROM auth_sessions WHERE token_hash=?", (hash_secret(consent),)) is None
    assert db.query_one("SELECT purpose FROM auth_sessions WHERE token_hash=?", (hash_secret(console),))["purpose"] == "console"
    assert gate["server"].session_principal(fresh).id == gate["users"]["alice"]["id"]


def test_public_login_uniform_error_and_rate_limit_precedes_password_work(gate, monkeypatch):
    info, _ = enable(gate)
    original = gate["auth"].login
    attempts = []
    def observed(**kwargs):
        attempts.append(kwargs["username"])
        return original(**kwargs)
    monkeypatch.setattr(gate["auth"], "login", observed)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.get("/oauth/authorize", params=parameters(info), follow_redirects=False)
        ticket = parse_qs(urlsplit(response.headers["location"]).fragment)["request"][0]
        context = client.get("/oauth/context", params={"request_id": ticket}).json()
        responses = []
        for index in range(11):
            responses.append(client.post("/oauth/login", headers={"Origin": ISSUER}, json={
                "request_id": ticket, "csrf": context["csrf"], "username": "alice" if index % 2 else "unknown",
                "password": "synthetic-wrong"}))
        assert [(response.status_code, response.json()["error"]) for response in responses[:10]] == [(401, "login_failed")] * 10
        assert responses[10].status_code == 429 and len(attempts) == 10


def test_anonymous_ticket_flood_cannot_fill_authenticated_interaction_pool(gate):
    info, _ = enable(gate)
    server, db = gate["server"], gate["db"]
    browser = "synthetic-active-browser"
    active = server.start_authorization(parameters(info), browser)
    context = server.consent_context(active, browser, gate["oauth_sessions"]["alice"])
    for index in range(250):
        anonymous_browser = f"synthetic-rotating-browser-{index}"
        ticket = server.start_authorization(parameters(info), anonymous_browser)
        assert server.consent_context(ticket, anonymous_browser, None)["phase"] == "preauth"
    assert db.query_one("SELECT COUNT(*) AS n FROM gate_oauth_interactions")["n"] == 1
    assert server.consent(active, browser, context["csrf"], gate["principals"]["alice"], ["mcp.A.read"], 7, 30, 1)
    row = db.query_one("SELECT * FROM gate_oauth_interactions")
    assert row["completed"] == 1 and row["catalog_json"] == "{}"
    assert "scopes" not in row["request_json"]
    with pytest.raises(OAuthError, match="authorization_completed"):
        server.consent(active, browser, context["csrf"], gate["principals"]["alice"], ["mcp.A.read"], 7, 30, 1)


def test_interaction_user_quota_survives_cookie_rotation_and_completion_releases_slot(gate):
    info, _ = enable(gate)
    server, db = gate["server"], gate["db"]
    pending = []
    for index in range(5):
        browser = f"synthetic-alice-browser-{index}"
        ticket = server.start_authorization(parameters(info), browser)
        context = server.consent_context(ticket, browser, gate["oauth_sessions"]["alice"])
        pending.append((ticket, browser, context))
    extra_browser = "synthetic-new-cookie"
    extra = server.start_authorization(parameters(info), extra_browser)
    with pytest.raises(OAuthError, match="authorization_capacity"):
        server.consent_context(extra, extra_browser, gate["oauth_sessions"]["alice"])
    bob = server.start_authorization(parameters(info), "synthetic-bob")
    assert server.consent_context(bob, "synthetic-bob", gate["oauth_sessions"]["bob"])["user"]["username"] == "bob"
    ticket, browser, context = pending[0]
    server.consent(ticket, browser, context["csrf"], gate["principals"]["alice"], [], 7, 30, 1, deny=True)
    extra_context = server.consent_context(extra, extra_browser, gate["oauth_sessions"]["alice"])
    assert extra_context["phase"] == "authenticated"
    assert db.query_one("SELECT COUNT(*) AS n FROM gate_oauth_interactions WHERE completed=0")["n"] == 6
    server.release_interaction(extra, extra_browser, extra_context["csrf"])
    assert db.query_one("SELECT COUNT(*) AS n FROM gate_oauth_interactions WHERE completed=0")["n"] == 5


@pytest.mark.parametrize("ceiling", ["client", "global", "anonymous_completed", "user_completed"])
def test_layered_capacity_is_separate_and_expired_records_release_capacity(gate, ceiling):
    info, _ = enable(gate)
    server, db = gate["server"], gate["db"]
    alice, bob = gate["users"]["alice"]["id"], gate["users"]["bob"]["id"]
    count = {"client": 50, "global": 200, "anonymous_completed": 1024, "user_completed": 64}[ceiling]
    completed = int("completed" in ceiling)
    owner = None if ceiling == "anonymous_completed" else alice if ceiling == "user_completed" else bob
    with server.store.transaction() as connection:
        connection.executemany("INSERT INTO gate_oauth_interactions "
            "(id_hash,browser_hash,request_json,expires_at,completed,user_id,client_id) VALUES(?,?,?,?,?,?,?)",
            [(f"synthetic-capacity-{index}", "synthetic", "{}", int(time.time()) + 600, completed, owner,
              info["id"] if ceiling != "global" else f"synthetic-other-client-{index}") for index in range(count)])
    browser = "synthetic-capacity-browser"
    ticket = server.start_authorization(parameters(info), browser)
    if ceiling in {"client", "global"}:
        with pytest.raises(OAuthError, match="authorization_capacity"):
            server.consent_context(ticket, browser, gate["oauth_sessions"]["alice"])
        if ceiling == "client":
            other = server.create_client("Other capacity client", [REDIRECT], ["tools.read"])["client"]
            other_ticket = server.start_authorization(parameters(other, scope="tools.read"), browser)
            assert server.consent_context(other_ticket, browser, gate["oauth_sessions"]["alice"])["phase"] == "authenticated"
    elif ceiling == "anonymous_completed":
        context = server.consent_context(ticket, browser, None)
        with pytest.raises(OAuthError, match="authorization_capacity"):
            server.consent(ticket, browser, context["csrf"], None, [], 7, 30, 1, deny=True)
        authenticated = server.consent_context(ticket, browser, gate["oauth_sessions"]["alice"])
        assert server.consent(ticket, browser, authenticated["csrf"], gate["principals"]["alice"], ["mcp.A.read"], 7, 30, 1)
    else:
        context = server.consent_context(ticket, browser, gate["oauth_sessions"]["alice"])
        with pytest.raises(OAuthError, match="authorization_capacity"):
            server.consent(ticket, browser, context["csrf"], gate["principals"]["alice"], ["mcp.A.read"], 7, 30, 1)
        assert server.store.grants(alice) == []  # The failed completion rolls back the code and grant.
    db.execute("UPDATE gate_oauth_interactions SET expires_at=? WHERE id_hash LIKE 'synthetic-capacity-%'", (int(time.time()) - 1,))
    next_ticket = server.start_authorization(parameters(info), browser)
    next_context = server.consent_context(next_ticket, browser, gate["oauth_sessions"]["alice"])
    assert server.consent(next_ticket, browser, next_context["csrf"], gate["principals"]["alice"], ["mcp.A.read"], 7, 30, 1)


def test_stateless_ticket_tamper_browser_and_csrf_fail_closed(gate):
    info, _ = enable(gate)
    server, browser = gate["server"], "synthetic-ticket-browser"
    ticket = server.start_authorization(parameters(info), browser)
    with pytest.raises(OAuthError, match="authorization_expired"):
        server.consent_context(ticket[:20] + ("A" if ticket[20] != "A" else "B") + ticket[21:], browser, None)
    with pytest.raises(OAuthError, match="invalid_browser"):
        server.consent_context(ticket, "synthetic-other-browser", None)
    with pytest.raises(OAuthError, match="invalid_csrf"):
        server.consent(ticket, browser, "synthetic-wrong-csrf", None, [], 7, 30, 1, deny=True)
    assert not gate["db"].query_all("SELECT * FROM gate_oauth_interactions")


def test_disabling_and_reenabling_invalidates_stateless_tickets(gate):
    info, _ = enable(gate)
    server, browser = gate["server"], "synthetic-reenable-browser"
    ticket = server.start_authorization(parameters(info), browser)
    server.save_config({"enabled": False, "issuer": ISSUER, "resource": RESOURCE}, 2)
    server.save_config({"enabled": True, "issuer": ISSUER, "resource": RESOURCE}, 3)
    with pytest.raises(OAuthError, match="authorization_changed"):
        server.consent_context(ticket, browser, gate["oauth_sessions"]["alice"])


def test_real_mcp_display_name_change_does_not_expand_or_revoke_tool_scope(gate):
    info, secret = enable(gate)
    code = issue_code(gate, info)
    definition = gate["registry"].get_definition("mcp.A.read")
    definition.metadata["server_name"] = "Renamed actual catalog"
    gate["registry"].update_definition(definition)
    principal = gate["server"].verify(exchange(gate["server"], info, secret, code)["access_token"])
    assert principal.external_tool_ids == ("mcp.A.read",)
    current = gate["server"].catalog(principal, ["tools.read"])
    assert current["mcp.A.read"]["server_name"] == "Renamed actual catalog"


def test_public_rate_lanes_cannot_consume_authenticated_or_refresh_admission(gate):
    boundary = OAuthRateBoundary()
    for index in range(150):
        request = mcp_request("synthetic", "/oauth/authorize")
        request.scope["client"] = (f"192.0.2.{index}", 1234)
        boundary.check(request, "authorize", 30)
    with pytest.raises(OAuthError, match="rate_limit_exceeded"):
        boundary.check(request, "authorize", 30)
    boundary.check(request, "context", 60, gate["principals"]["alice"])
    boundary.check(request, "decision", 30, gate["principals"]["alice"])
    boundary.protocol_inbound(request, "token")
    boundary.protocol_client("synthetic-validated-client", "refresh")
    assert len(boundary.global_windows["authorize"]) == 150
    assert len(boundary.global_windows["authenticated"]) == 2
    assert len(boundary.global_windows["protocol-client-refresh"]) == 1


@pytest.mark.parametrize("endpoint", ["token", "revoke"])
@pytest.mark.parametrize("attack", ["malformed", "wrong_secret", "invalid_basic"])
def test_unauthenticated_protocol_flood_preserves_legitimate_exchange_refresh_and_revoke(gate, monkeypatch, endpoint, attack):
    info, secret = enable(gate)
    admissions = []
    original = OAuthRateBoundary.protocol_client
    def observed(boundary, client_id, operation):
        admissions.append((client_id, operation))
        return original(boundary, client_id, operation)
    monkeypatch.setattr(OAuthRateBoundary, "protocol_client", observed)
    # Exceed the previous shared 600/min ceiling from distinct resolved sources,
    # including wrong-secret attempts naming the legitimate client's exact ID.
    for source in range(20):
        with TestClient(gate["app"], base_url=ISSUER, client=(f"192.0.2.{source + 1}", 1234)) as client:
            for _ in range(32):
                if attack == "malformed":
                    response = client.post("/oauth/" + endpoint, content="malformed", headers={"Content-Type": "application/x-www-form-urlencoded"})
                    assert response.status_code == 400
                elif attack == "invalid_basic":
                    response = client.post("/oauth/" + endpoint, content="", headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": "Basic !!synthetic-invalid!!"})
                    assert response.status_code in {401, 429}
                else:
                    response = client.post("/oauth/" + endpoint, data={"client_id": info["id"], "client_secret": "synthetic-wrong-secret"})
                    assert response.status_code in {401, 429}
    assert admissions == []
    code = issue_code(gate, info)
    with TestClient(gate["app"], base_url=ISSUER, client=("198.51.100.1", 1234)) as client:
        exchanged = client.post("/oauth/token", data={"grant_type": "authorization_code", "client_id": info["id"],
            "client_secret": secret, "code": code, "code_verifier": VERIFIER, "resource": RESOURCE, "redirect_uri": REDIRECT})
        assert exchanged.status_code == 200, exchanged.text
        rotated = client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": info["id"],
            "client_secret": secret, "refresh_token": exchanged.json()["refresh_token"], "resource": RESOURCE})
        assert rotated.status_code == 200, rotated.text
        revoked = client.post("/oauth/revoke", data={"client_id": info["id"], "client_secret": secret, "token": rotated.json()["refresh_token"]})
        assert revoked.status_code == 200
        with pytest.raises(OAuthError):
            gate["server"].verify(rotated.json()["access_token"])
    assert admissions == [(info["id"], operation) for operation in ("exchange", "refresh", "revoke")]


@pytest.mark.parametrize("operation,own_limit,clients", [("exchange", 30, 6), ("refresh", 60, 5), ("revoke", 30, 4)])
def test_verified_client_operation_capacity_is_reserved_and_per_client_bounded(operation, own_limit, clients):
    boundary = OAuthRateBoundary()
    for index in range(clients):
        client_id = f"synthetic-validated-{index}"
        for _ in range(own_limit):
            boundary.protocol_client(client_id, operation)
        with pytest.raises(OAuthError, match="rate_limit_exceeded"):
            boundary.protocol_client(client_id, operation)
    with pytest.raises(OAuthError, match="rate_limit_exceeded"):
        boundary.protocol_client("another-validated-client", operation)
    for other in {"exchange", "refresh", "revoke"} - {operation}:
        boundary.protocol_client("legitimate-other-operation", other)
    assert len(boundary.global_windows["protocol-client-" + operation]) == own_limit * clients


def test_protocol_source_tracking_is_bounded_without_rejecting_all_new_sources(monkeypatch):
    monkeypatch.setattr("lingshu_gate.interfaces.control_api.oauth_routes.time.monotonic", lambda: 100.0)
    boundary = OAuthRateBoundary()
    request = mcp_request("synthetic", "/oauth/token")
    for index in range(4100):
        request.scope["client"] = (f"synthetic-source-{index}", 1234)
        boundary.protocol_inbound(request, "token")
        boundary.protocol_failed(request, "token")
    assert len(boundary.windows["protocol-inbound-token"]) == 4096
    assert len(boundary.windows["protocol-failure-token"]) == 4096
    request.scope["client"] = ("synthetic-new-legitimate-source", 1234)
    boundary.protocol_inbound(request, "token")
    boundary.protocol_client("synthetic-validated-client", "exchange")
    assert set(boundary.global_windows) == {"protocol-client-exchange"}
    assert len(boundary.windows["protocol-inbound-token"]) == 4096


@pytest.mark.parametrize("endpoint", ["token", "revoke"])
def test_protocol_failure_limit_is_uniform_and_valid_credentials_do_not_spend_it(gate, endpoint):
    info, secret = enable(gate)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        for index in range(10):
            response = client.post("/oauth/" + endpoint, data={"client_id": info["id"] if index % 2 else "unknown-synthetic-client", "client_secret": "synthetic-wrong"})
            assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
        limited = client.post("/oauth/" + endpoint, data={"client_id": info["id"], "client_secret": "synthetic-wrong"})
        assert limited.status_code == 429 and limited.json() == {"error": "rate_limit_exceeded"}
        # A failure budget does not reject valid credentials at this same source.
        if endpoint == "token":
            code = issue_code(gate, info)
            data = {"client_id": info["id"], "client_secret": secret, "grant_type": "authorization_code",
                    "code": code, "code_verifier": VERIFIER, "redirect_uri": REDIRECT, "resource": RESOURCE}
        else:
            data = {"client_id": info["id"], "client_secret": secret, "token": "unknown-synthetic-token"}
        assert client.post("/oauth/" + endpoint, data=data).status_code == 200


@pytest.mark.parametrize("mutation", ["disabled", "rotated"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
def test_protocol_revalidates_client_after_read_only_admission_before_mutation(gate, monkeypatch, mutation, endpoint):
    info, secret = enable(gate)
    server = gate["server"]
    code = issue_code(gate, info)
    token = exchange(server, info, secret, code)["access_token"] if endpoint == "revoke" else None
    original = server.validate_client_credentials
    def invalidate(client_id, client_secret):
        original(client_id, client_secret)
        server.update_client(info["id"], info["revision"], name=info["name"], redirects=info["redirect_uris"],
                             scopes=info["scopes"], enabled=mutation != "disabled", rotate=mutation == "rotated")
    monkeypatch.setattr(server, "validate_client_credentials", invalidate)
    if endpoint == "revoke":
        monkeypatch.setattr(server, "_claims", lambda _: pytest.fail("JWT validation preceded current client authentication"))
        data = {"client_id": info["id"], "client_secret": secret, "token": token}
    else:
        data = {"client_id": info["id"], "client_secret": secret, "grant_type": "authorization_code",
                "code": code, "code_verifier": VERIFIER, "redirect_uri": REDIRECT, "resource": RESOURCE}
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.post("/oauth/" + endpoint, data=data)
        assert response.status_code == 401 and response.json() == {"error": "invalid_client"}
    if endpoint == "token":
        assert not gate["db"].query_all("SELECT * FROM gate_oauth_families")


def test_protocol_credential_admission_uses_no_oauth_write_transaction(gate, monkeypatch):
    info, secret = enable(gate)
    server = gate["server"]
    monkeypatch.setattr(server.store, "transaction", lambda: pytest.fail("unauthenticated admission acquired a write transaction"))
    server.validate_client_credentials(info["id"], secret)
    with pytest.raises(OAuthError, match="invalid_client"):
        server.validate_client_credentials(info["id"], "synthetic-wrong")


@pytest.mark.parametrize("endpoint", ["token", "revoke"])
def test_protocol_ingress_limit_precedes_body_reading_and_client_validation(gate, monkeypatch, endpoint):
    reads = []
    from lingshu_gate.interfaces.control_api import oauth_routes
    original = oauth_routes.read_body
    async def observed(request, maximum=32768):
        reads.append(request.url.path)
        return await original(request, maximum)
    monkeypatch.setattr(oauth_routes, "read_body", observed)
    monkeypatch.setattr(gate["server"], "validate_client_credentials", lambda *args: pytest.fail("malformed or rate-rejected ingress reached client authentication"))
    with TestClient(gate["app"], base_url=ISSUER) as client:
        for _ in range(60):
            response = client.post("/oauth/" + endpoint, content="malformed", headers={"Content-Type": "application/x-www-form-urlencoded"})
            assert response.status_code == 400
        response = client.post("/oauth/" + endpoint, content="malformed", headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert response.status_code == 429 and len(reads) == 60
        other = "revoke" if endpoint == "token" else "token"
        response = client.post("/oauth/" + other, content="malformed", headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert response.status_code == 400 and len(reads) == 61


@pytest.mark.parametrize("mutation", ["client_disabled", "grant_revoked", "user_disabled", "role_removed"])
@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
def test_full_mcp_transport_reauthenticates_each_call_before_downstream(gate, mutation, protocol):
    info, secret = enable(gate)
    server = gate["server"]
    tokens = exchange(server, info, secret, issue_code(gate, info))
    token = tokens["access_token"]
    calls = []
    class Downstream:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, **kwargs):
            calls.append((server_id, tool_name, arguments, user_id))
            return {"content": [{"type": "text", "text": "synthetic result"}]}
    gate["access"].attach_mcp_runtime(Downstream())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
                               gate["auth"].authenticate_mcp_request,
                               McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    def post(client, method, params=None):
        prepared, headers = build_protocol_request(method, params, client_name="Synthetic", client_version="1", protocol_version=protocol)
        return client.post("/mcp", headers={**headers, "Authorization": "Bearer " + token},
                           json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared})
    with TestClient(gate["app"], base_url=ISSUER) as client:
        method = "initialize" if protocol == "2025-11-25" else "server/discover"
        params = {"protocolVersion": protocol, "capabilities": {}, "clientInfo": {"name": "Synthetic", "version": "1"}} if method == "initialize" else None
        assert post(client, method, params).status_code == 200
        assert post(client, "tools/list").status_code == 200
        first = post(client, "tools/call", {"name": "mcp__A__read", "arguments": {}})
        assert first.status_code == 200 and not first.json()["result"].get("isError", False)
        assert calls == [("A", "read", {}, gate["users"]["alice"]["id"])]
        if mutation == "client_disabled":
            server.update_client(info["id"], info["revision"], name=info["name"], redirects=info["redirect_uris"], scopes=info["scopes"], enabled=False)
        elif mutation == "grant_revoked":
            grant = server.store.grants(gate["users"]["alice"]["id"])[0]
            server.narrow_grant(grant["user_id"], grant["id"], grant["revision"], [], 0, 0, 0, revoke=True)
        elif mutation == "user_disabled":
            gate["db"].execute("UPDATE users SET status='disabled' WHERE id=?", (gate["users"]["alice"]["id"],))
        else:
            gate["db"].execute("DELETE FROM user_roles WHERE user_id=?", (gate["users"]["alice"]["id"],))
        denied_status = 403 if mutation == "role_removed" else 401
        # Gate is stateless: even a retained legacy session header carries no
        # authority and cannot revive a revoked bearer on a live HTTP client.
        client.headers["Mcp-Session-Id"] = "synthetic-retained-http-session"
        assert post(client, "tools/call", {"name": "mcp__A__read", "arguments": {}}).status_code == denied_status
        assert post(client, "tools/list").status_code == denied_status
        assert len(calls) == 1
        if mutation == "grant_revoked":
            denied_refresh = client.post("/oauth/token", data={"grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"], "client_id": info["id"],
                "client_secret": secret, "resource": RESOURCE})
            assert denied_refresh.status_code == 400
            assert denied_refresh.json()["error"] == "invalid_grant"


def test_mcp_rechecks_after_request_body_before_dispatch(gate, monkeypatch):
    info, secret = enable(gate)
    server = gate["server"]
    token = exchange(server, info, secret, issue_code(gate, info))["access_token"]
    grant = server.store.grants(gate["users"]["alice"]["id"])[0]
    original_json = Request.json
    async def revoke_after_body(request):
        body = await original_json(request)
        server.narrow_grant(grant["user_id"], grant["id"], grant["revision"], [], 0, 0, 0, revoke=True)
        return body
    monkeypatch.setattr(Request, "json", revoke_after_body)
    monkeypatch.setattr(gate["access"], "invoke_tool", lambda *args, **kwargs: pytest.fail("revoked credential reached dispatch"))
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
                               gate["auth"].authenticate_mcp_request,
                               McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    prepared, headers = build_protocol_request("tools/call", {"name": "mcp__A__read", "arguments": {}},
                                               client_name="Synthetic", client_version="1")
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.post("/mcp", headers={**headers, "Authorization": "Bearer " + token},
                               json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": prepared})
        assert response.status_code == 401 and "resource_metadata=" in response.headers["www-authenticate"]


@pytest.mark.parametrize("uri", ["http://client.example.test/callback", REDIRECT + "#fragment",
                                    "https://*.example.test/callback", "https://user:pass@example.test/callback",
                                    "https://client.example.test/callback?code=anything"])
def test_client_rejects_unsafe_callback(gate, uri):
    with pytest.raises(OAuthError, match="invalid_client_configuration"):
        gate["server"].create_client("Synthetic", [uri], ["tools.read"])


@pytest.mark.parametrize("overrides", [{"redirect_uri": REDIRECT + "&extra=1"}, {"code_challenge_method": "plain"},
    {"code_challenge": "short"}, {"resource": "https://other.example.test/mcp"}, {"scope": "admin"}])
def test_authorize_rejects_callback_pkce_resource_and_scope(gate, overrides):
    client, _ = enable(gate)
    with pytest.raises(OAuthError):
        gate["server"].start_authorization(parameters(client, **overrides), "synthetic-browser")


@pytest.mark.parametrize("overrides", [{"redirect_uri": REDIRECT + "&extra=1"}, {"code_verifier": "b" * 64},
                                       {"code_verifier": "short"}, {"resource": "https://other.example.test/mcp"}])
def test_code_bad_bindings_cannot_consume_valid_code(gate, overrides):
    client, secret = enable(gate)
    code = issue_code(gate, client)
    with pytest.raises(OAuthError):
        exchange(gate["server"], client, secret, code, **overrides)
    assert gate["server"].verify(exchange(gate["server"], client, secret, code)["access_token"]).id == gate["users"]["alice"]["id"]


def test_code_client_binding_expiry_and_replay(gate):
    client, secret = enable(gate)
    server = gate["server"]
    code = issue_code(gate, client)
    other = server.create_client("Other synthetic client", [REDIRECT], ["tools.read"])
    with pytest.raises(OAuthError, match="invalid_grant"):
        exchange(server, other["client"], other["client_secret"], code)
    result = exchange(server, client, secret, code)
    # A spent code still detects replay after its short exchange deadline,
    # while the retained digest record exists.
    gate["db"].execute("UPDATE gate_oauth_codes SET expires_at=? WHERE code_hash=?", (int(time.time()) - 1, hash_secret(code)))
    with pytest.raises(OAuthError, match="invalid_grant"):
        exchange(server, client, secret, code)
    with pytest.raises(OAuthError):
        server.verify(result["access_token"])
    expired = issue_code(gate, client)
    gate["db"].execute("UPDATE gate_oauth_codes SET expires_at=? WHERE code_hash=?", (int(time.time()) - 1, hash_secret(expired)))
    with pytest.raises(OAuthError):
        exchange(server, client, secret, expired)


def test_concurrent_code_exchange_and_refresh_replay_revoke_family(gate):
    client, secret = enable(gate)
    server = gate["server"]
    for grant_type in ("code", "refresh"):
        code = issue_code(gate, client)
        initial = exchange(server, client, secret, code) if grant_type == "refresh" else None
        barrier = threading.Barrier(2)
        def run():
            barrier.wait(timeout=10)
            try:
                return (refresh(server, client, secret, initial["refresh_token"]) if initial
                        else exchange(server, client, secret, code))
            except OAuthError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        assert results.count("invalid_grant") == 1
        winner = next(result for result in results if isinstance(result, dict))
        with pytest.raises(OAuthError):
            server.verify(winner["access_token"])
        with pytest.raises(OAuthError):
            refresh(server, client, secret, winner["refresh_token"])


def test_refresh_absolute_expiry_scope_reduction_and_bad_scope_replay(gate):
    client, secret = enable(gate)
    server = gate["server"]
    initial = exchange(server, client, secret, issue_code(gate, client, tools=["mcp.A.read", "mcp.A.write"], days=1))
    family_before = dict(gate["db"].query_one("SELECT * FROM gate_oauth_families"))
    reduced = refresh(server, client, secret, initial["refresh_token"], scope="tools.read")
    assert reduced["scope"] == "tools.read"
    family_after = dict(gate["db"].query_one("SELECT * FROM gate_oauth_families"))
    assert family_after["expires_at"] == family_before["expires_at"]
    assert family_after["expires_at"] <= int(time.time()) + 86400
    with pytest.raises(OAuthError, match="invalid_scope"):
        refresh(server, client, secret, reduced["refresh_token"], scope="tools.read tools.invoke")
    # Malformed scope on a replay must not roll back family revocation.
    with pytest.raises(OAuthError):
        refresh(server, client, secret, initial["refresh_token"], scope="admin")
    assert gate["db"].query_one("SELECT revoked_at FROM gate_oauth_families")["revoked_at"] is not None
    with pytest.raises(OAuthError):
        server.verify(reduced["access_token"])


def test_rs256_claims_secrets_at_rest_and_local_verification(gate, monkeypatch):
    client, secret = enable(gate)
    server = gate["server"]
    code = issue_code(gate, client)
    result = exchange(server, client, secret, code)
    claims = jwt.decode(result["access_token"], options={"verify_signature": False})
    assert claims["sub"] == gate["users"]["alice"]["id"] and claims["client_id"] == client["id"]
    assert claims["iss"] == ISSUER and claims["aud"] == RESOURCE and claims["exp"] - claims["iat"] <= ACCESS_TTL
    assert jwt.get_unverified_header(result["access_token"])["alg"] == "RS256"
    dump = " ".join(str(dict(row)) for table in ("gate_oauth_keys", "gate_oauth_clients", "gate_oauth_codes", "gate_oauth_refresh")
                    for row in gate["db"].query_all("SELECT * FROM " + table))
    assert "BEGIN PRIVATE KEY" not in dump
    for value in (code, result["access_token"], result["refresh_token"], secret):
        assert value not in dump
    if os.name == "posix":
        assert server.key_path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr("lingshu_gate.external_jwt.fetch_jwks", lambda _: pytest.fail("local verification used network"))
    principal = gate["auth"].authenticate_mcp_request(mcp_request(result["access_token"]))
    assert principal.external_tool_ids == ("mcp.A.read",)
    with pytest.raises(HTTPException):
        gate["auth"].authenticate_request(mcp_request(result["access_token"], "/v1/auth/me"))


@pytest.mark.parametrize("mutation", ["user_disabled", "client_disabled", "secret_rotated", "grant_revoked", "role_removed", "service_disabled"])
def test_next_request_rechecks_live_user_client_grant_and_role(gate, mutation):
    client, secret = enable(gate)
    server = gate["server"]
    result = exchange(server, client, secret, issue_code(gate, client))
    server.verify(result["access_token"])
    if mutation == "user_disabled":
        gate["db"].execute("UPDATE users SET status='disabled' WHERE id=?", (gate["users"]["alice"]["id"],))
    elif mutation in {"client_disabled", "secret_rotated"}:
        server.update_client(client["id"], client["revision"], name=client["name"], redirects=client["redirect_uris"],
                             scopes=client["scopes"], enabled=mutation != "client_disabled", rotate=mutation == "secret_rotated")
    elif mutation == "role_removed":
        gate["db"].execute("DELETE FROM user_roles WHERE user_id=?", (gate["users"]["alice"]["id"],))
    elif mutation == "service_disabled":
        server.save_config({"enabled": False, "issuer": ISSUER, "resource": RESOURCE}, 2)
    else:
        grant = server.store.grants(gate["users"]["alice"]["id"])[0]
        server.narrow_grant(grant["user_id"], grant["id"], grant["revision"], [], 0, 0, 0, revoke=True)
    with pytest.raises((OAuthError, HTTPException)):
        gate["auth"].authenticate_mcp_request(mcp_request(result["access_token"]))


def test_tool_grant_only_narrows_and_never_adds_new_or_reclassified_tools(gate):
    client, secret = enable(gate)
    server = gate["server"]
    result = exchange(server, client, secret, issue_code(gate, client, tools=["mcp.A.read", "mcp.A.write"]))
    grant = server.store.grants(gate["users"]["alice"]["id"])[0]
    with pytest.raises(OAuthError, match="grant_not_found"):
        server.narrow_grant(gate["users"]["bob"]["id"], grant["id"], 1, ["mcp.A.read"], grant["expires_at"], 30, 1)
    with pytest.raises(OAuthError, match="grant_can_only_narrow"):
        server.narrow_grant(grant["user_id"], grant["id"], 1, ["mcp.A.read", "mcp.B.read"], grant["expires_at"], 30, 1)
    server.narrow_grant(grant["user_id"], grant["id"], 1, ["mcp.A.read"], grant["expires_at"], 10, 1)
    assert server.verify(result["access_token"]).external_tool_ids == ("mcp.A.read",)
    # Even a grant containing both access levels must not auto-upgrade a read tool.
    result2 = exchange(server, client, secret, issue_code(gate, client, tools=["mcp.A.read", "mcp.A.write"]))
    gate["access"].set_classification(server_id="A", tool_id="mcp.A.read", access="write", destructive=False,
                                      idempotent=False, reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id="A", reviewer_id=gate["admin"]["id"])
    assert "mcp.A.read" not in server.verify(result2["access_token"]).external_tool_ids
    assert "mcp.B.read" not in server.verify(result2["access_token"]).external_tool_ids


def test_current_resource_permissions_and_newly_discovered_tools_intersect_old_grant(gate):
    client, secret = enable(gate)
    server, access, registry = gate["server"], gate["access"], gate["registry"]
    result = exchange(server, client, secret, issue_code(gate, client))
    later = ToolDefinition(id="mcp.B.later", name="Later discovered", description="Synthetic newly discovered tool", source="mcp", permission="read",
                           metadata={"server_id": "B"})
    registry.register(later, lambda arguments: None)
    access.synchronize_tools(registry.list_definitions())
    access.set_classification(server_id="B", tool_id=later.id, access="read", destructive=False,
                              idempotent=True, reviewer_id=gate["admin"]["id"])
    access.publish_classifications(server_id="B", reviewer_id=gate["admin"]["id"])
    access.save_grant(subject_type="user", subject_id=gate["users"]["alice"]["id"], server_id="B",
                      permission_type_code="write", created_by=gate["admin"]["id"])
    principal = server.verify(result["access_token"])
    assert principal.external_tool_ids == ("mcp.A.read",)
    assert not access.evaluate(principal, later)["allowed"]
    for grant in access.list_grants(subject_type="user", subject_id=principal.id, server_id="A"):
        access.delete_grant(grant["id"])
    principal = gate["auth"].authenticate_mcp_request(mcp_request(result["access_token"]))
    assert principal.external_tool_ids == ()
    assert not access.evaluate(principal, registry.get_definition("mcp.A.read"))["allowed"]


@pytest.mark.parametrize("conflict", ["resource", "issuer"])
def test_builtin_and_external_configurations_reject_ambiguous_coexistence_in_both_directions(gate, conflict):
    enable(gate)
    server = gate["server"]
    server.save_config({"enabled": False, "issuer": ISSUER, "resource": RESOURCE}, 2)
    store = ExternalConnectionStore(gate["db"])
    gate["auth"].external_connections = store
    external_resource = "https://other.example.test/mcp" if conflict == "resource" else RESOURCE
    external_issuer = "https://issuer.example.test" if conflict == "resource" else ISSUER
    payload = {"enabled": True, "mode": "direct", "endpoint": external_resource,
               "canonical_resource_url": external_resource, "trusted_issuers": [external_issuer],
               "issuer_jwks": [[external_issuer, external_issuer + "/jwks"]],
               "resource_mappings": [[external_resource, external_resource]], "client_allowlist": ["synthetic"]}
    store.save_config(payload, 0)
    error = conflict + "_configuration_conflict"
    with pytest.raises(OAuthError, match=error):
        server.save_config({"enabled": True, "issuer": ISSUER, "resource": RESOURCE}, 3)
    assert not server.store.config()["enabled"] and server.store.config()["revision"] == 3
    store.save_config({**payload, "enabled": False}, 1)
    server.save_config({"enabled": True, "issuer": ISSUER, "resource": RESOURCE}, 3)
    register_external_connection_routes(gate["app"], auth_store=gate["auth"], access_store=gate["access"],
        registry=gate["registry"], store=store, observability_store=ObservabilityStore(gate["db"]))
    with TestClient(gate["app"], base_url=ISSUER) as client:
        _, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
        client.cookies.set(gate["auth"].cookie_name, session)
        response = client.put("/v1/auth/external-connection/config", json={**payload, "expected_revision": 2},
                              headers={"Origin": ISSUER})
        assert response.status_code == 409 and response.json()["detail"] == error
    assert not store.configuration().enabled


def test_key_rotation_keeps_old_public_key_then_retires_and_never_exposes_private(gate):
    client, secret = enable(gate)
    server = gate["server"]
    initial = exchange(server, client, secret, issue_code(gate, client))
    old_kid = jwt.get_unverified_header(initial["access_token"])["kid"]
    new_kid = server.rotate_key()
    assert old_kid != new_kid
    server.verify(initial["access_token"])
    rotated = refresh(server, client, secret, initial["refresh_token"])
    assert jwt.get_unverified_header(rotated["access_token"])["kid"] == new_kid
    assert "private" not in json.dumps(server.jwks())
    gate["db"].execute("UPDATE gate_oauth_keys SET retire_at=? WHERE kid=?", (int(time.time()) - 1, old_kid))
    with pytest.raises(OAuthError):
        server.verify(initial["access_token"])
    assert server.verify(rotated["access_token"]).id == gate["users"]["alice"]["id"]


def test_revoke_is_client_bound_and_unknown_token_is_success(gate):
    client, secret = enable(gate)
    server = gate["server"]
    result = exchange(server, client, secret, issue_code(gate, client))
    other = server.create_client("Other", [REDIRECT], ["tools.read"])
    server.revoke_token(result["refresh_token"], other["client"]["id"], other["client_secret"])
    server.verify(result["access_token"])
    server.revoke_token("unknown-synthetic-token", client["id"], secret)
    server.revoke_token(result["access_token"], client["id"], secret)
    with pytest.raises(OAuthError):
        server.verify(result["access_token"])


def test_authorize_only_issues_a_new_random_browser_cookie_and_preserves_parallel_tickets(gate):
    client_info, _ = enable(gate)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.get("/oauth/authorize", params=parameters(client_info), follow_redirects=False)
        assert response.status_code == 303
        browser = client.cookies.get(BROWSER_COOKIE)
        assert browser and len(browser) == 43
        first = parse_qs(urlsplit(response.headers["location"]).fragment)["request"][0]
        response = client.get("/oauth/authorize", params=parameters(client_info), follow_redirects=False)
        assert response.status_code == 303
        assert "set-cookie" not in response.headers
        assert client.cookies.get(BROWSER_COOKIE) == browser
        second = parse_qs(urlsplit(response.headers["location"]).fragment)["request"][0]
        for interaction in (first, second):
            assert client.get("/oauth/context", params={"request_id": interaction}).status_code == 200
        client.cookies.clear()
        client.cookies.set(BROWSER_COOKIE, "synthetic-other-browser")
        for interaction in (first, second):
            rejected = client.get("/oauth/context", params={"request_id": interaction})
            assert rejected.status_code == 403 and rejected.json()["error"] == "invalid_browser"


@pytest.mark.parametrize("ui_locales", [None, "zh-CN", "en-US"])
def test_public_login_consent_csrf_cancel_repeat_and_console_isolation(gate, ui_locales):
    client_info, secret = enable(gate)
    authorize_params = parameters(client_info)
    if ui_locales is not None:
        authorize_params["ui_locales"] = ui_locales
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.get("/oauth/authorize", params=authorize_params, follow_redirects=False)
        assert response.status_code == 303
        request_id = parse_qs(urlsplit(response.headers["location"]).fragment)["request"][0]
        assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
        assert client.cookies.get(BROWSER_COOKIE)
        context = client.get("/oauth/context", params={"request_id": request_id}).json()
        body = {"request_id": request_id, "csrf": context["csrf"], "username": "alice", "password": PASSWORD}
        assert client.post("/oauth/login", json=body).status_code == 403
        assert client.post("/oauth/login", json={**body, "csrf": "wrong" * 10}, headers={"Origin": ISSUER}).status_code == 403
        signed_in = client.post("/oauth/login", json=body, headers={"Origin": ISSUER})
        assert signed_in.status_code == 200, signed_in.text
        assert client.cookies.get(SESSION_COOKIE)
        assert client.get("/v1/auth/me").status_code == 401
        context = signed_in.json()
        base = {"request_id": request_id, "csrf": context["csrf"], "tool_ids": ["mcp.A.read"]}
        assert client.post("/oauth/decision", json={**base, "tool_ids": ["mcp.B.read"]}, headers={"Origin": ISSUER}).status_code == 409
        decision = client.post("/oauth/decision", json=base, headers={"Origin": ISSUER})
        assert decision.status_code == 200
        code = parse_qs(urlsplit(decision.json()["redirect"]).query)["code"][0]
        replay = client.post("/oauth/decision", json=base, headers={"Origin": ISSUER})
        assert replay.status_code == 409 and replay.json()["error"] == "authorization_completed"
        token = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
            "client_id": client_info["id"], "client_secret": secret, "code_verifier": VERIFIER,
            "resource": RESOURCE, "redirect_uri": REDIRECT})
        assert token.status_code == 200, token.text
        assert token.headers["cache-control"] == "no-store"
        # Cancel returns the exact registered callback, state and issuer.
        response = client.get("/oauth/authorize", params=authorize_params, follow_redirects=False)
        request_id = parse_qs(urlsplit(response.headers["location"]).fragment)["request"][0]
        context = client.get("/oauth/context", params={"request_id": request_id}).json()
        denied = client.post("/oauth/decision", json={"request_id": request_id, "csrf": context["csrf"], "deny": True}, headers={"Origin": ISSUER})
        assert parse_qs(urlsplit(denied.json()["redirect"]).query)["error"] == ["access_denied"]


def test_http_boundaries_management_permissions_duplicates_sizes_and_host(gate):
    client_info, _ = enable(gate)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        assert client.get("/v1/auth/oauth/clients").status_code == 401
        client.cookies.set(gate["auth"].cookie_name, gate["sessions"]["reader"])
        assert client.get("/v1/auth/oauth/clients").status_code == 403
        principal, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
        client.cookies.set(gate["auth"].cookie_name, session)
        assert client.get("/v1/auth/oauth/clients").status_code == 200
        created = client.post("/v1/auth/oauth/clients", json={"name": "HTTP synthetic", "redirect_uris": [REDIRECT], "scopes": ["tools.read"]}, headers={"Origin": ISSUER})
        assert created.status_code == 201 and created.json()["client_secret"]
        assert "client_secret" not in client.get("/v1/auth/oauth/clients").text
        assert client.post("/v1/auth/oauth/keys/rotate", json={}).status_code == 403
        assert client.get("/oauth/authorize?client_id=a&client_id=b").status_code == 400
        assert client.post("/oauth/token", content="x" * 33000, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 413
        metadata = client.get("/.well-known/oauth-authorization-server", headers={"Host": "attacker.example.test"}).json()
        assert metadata["issuer"] == ISSUER and metadata["authorization_endpoint"].startswith(ISSUER)
        invalid = client.get("/oauth/authorize", params=parameters(client_info, redirect_uri="https://attacker.example.test/callback"), follow_redirects=False)
        assert invalid.status_code == 400 and "location" not in invalid.headers
        safe_error = client.get("/oauth/authorize", params=parameters(client_info, code_challenge_method="plain"), follow_redirects=False)
        assert safe_error.status_code == 303 and parse_qs(urlsplit(safe_error.headers["location"]).query)["iss"] == [ISSUER]
        assert principal.id == gate["admin"]["id"]


@pytest.mark.parametrize("hint,expected", [(None, None), ("zh-CN", "zh-CN"), ("en-US", "en-US"),
    ("fr-CA en-US zh-CN", "en-US"), ("de-DE zh-Hans-CN en-US", "zh-CN"),
    ("fr-CA de-DE", None), ("zh_CN", None), ("<script>", None), ("", None)])
def test_authorization_ui_locales_reaches_consent_without_entering_the_security_envelope(gate, hint, expected):
    info, _ = enable(gate)
    values = parameters(info)
    if hint is not None:
        values["ui_locales"] = hint
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.get("/oauth/authorize", params=values, follow_redirects=False)
        assert response.status_code == 303
        location = urlsplit(response.headers["location"])
        assert location.scheme + "://" + location.netloc == ISSUER and location.path == "/oauth/consent"
        fields = parse_qs(location.fragment)
        assert fields.get("ui_locales") == ([expected] if expected else None)
        ticket = fields["request"][0]
        payload = gate["server"]._ticket(ticket, client.cookies.get(BROWSER_COOKIE))
        assert payload["request"] == {**parameters(info), "scopes": ["tools.invoke", "tools.read"],
                                      "client_revision": info["revision"], "configuration_revision": 2, "issuer": ISSUER}
        assert "ui_locales" not in json.dumps(payload)
        assert client.get("/oauth/consent").status_code == 200
        context = client.get("/oauth/context", params={"request_id": ticket})
        assert context.status_code == 200 and context.json()["resource"] == RESOURCE
        assert context.json()["client"]["id"] == info["id"] and context.json()["user"] is None


@pytest.mark.parametrize("mutation,error,status", [("missing_resource", "invalid_target", 303),
    ("wrong_pkce", "invalid_authorization_request", 303), ("bad_challenge", "invalid_authorization_request", 303),
    ("bad_redirect", "invalid_client_or_redirect", 400), ("unknown_parameter", "invalid_request", 400),
    ("duplicate_locale", "invalid_request", 400), ("duplicate_state", "invalid_request", 400),
    ("long_locale", "invalid_request", 400), ("long_state", "invalid_request", 400),
    ("too_many_fields", "invalid_request", 400), ("large_query", "request_too_large", 413)])
def test_ui_locales_never_relaxes_authorization_and_parser_boundaries(gate, mutation, error, status):
    info, _ = enable(gate)
    values = {**parameters(info), "ui_locales": "zh-CN"}
    if mutation == "missing_resource":
        values.pop("resource")
    elif mutation == "wrong_pkce":
        values["code_challenge_method"] = "plain"
    elif mutation == "bad_challenge":
        values["code_challenge"] = "short"
    elif mutation == "bad_redirect":
        values["redirect_uri"] = "https://other.example.test/callback"
    elif mutation == "unknown_parameter":
        values["unsupported"] = "synthetic"
    elif mutation == "long_locale":
        values["ui_locales"] = "z" * 129
    elif mutation == "long_state":
        values["state"] = "s" * 2049
    pairs = list(values.items())
    if mutation == "duplicate_locale":
        pairs.append(("ui_locales", "en-US"))
    elif mutation == "duplicate_state":
        pairs.append(("state", "synthetic-second-state"))
    elif mutation == "too_many_fields":
        pairs.extend(("ui_locales", "en-US") for _ in range(12))
    elif mutation == "large_query":
        pairs.append(("ui_locales", "s" * 8193))
    with TestClient(gate["app"], base_url=ISSUER) as client:
        response = client.get("/oauth/authorize?" + urlencode(pairs), follow_redirects=False)
        assert response.status_code == status
        if status == 303:
            query = parse_qs(urlsplit(response.headers["location"]).query)
            assert query["error"] == [error] and query["iss"] == [ISSUER] and query["state"] == ["synthetic-state"]
        else:
            assert response.json()["error"] == error and "location" not in response.headers
        assert not gate["db"].query_all("SELECT * FROM gate_oauth_interactions")


def test_api_token_and_external_jwt_modes_remain_available(gate):
    enable(gate)
    api = gate["auth"].create_api_token(principal=gate["principals"]["alice"], name="Synthetic regression", scopes=["tools.read"])
    assert gate["auth"].authenticate_mcp_request(mcp_request(api["token"])).auth_type == "token"
    issuer, jwks_uri = "https://issuer.example.test", "https://issuer.example.test/jwks"
    store = ExternalConnectionStore(gate["db"])
    store.save_config({"enabled": True, "mode": "direct", "endpoint": RESOURCE, "canonical_resource_url": RESOURCE,
        "trusted_issuers": [issuer], "issuer_jwks": [[issuer, jwks_uri]], "resource_mappings": [[RESOURCE, RESOURCE]],
        "client_allowlist": ["external-synthetic"]}, 0)
    store.create_subject_link({"issuer": issuer, "subject": "external-alice", "user_id": gate["users"]["alice"]["id"], "enabled": True})
    store.create_grant(gate["users"]["alice"]["id"], {"enabled": True, "client_id": "external-synthetic",
        "server_allowlist": ["A"], "tool_allowlist": ["mcp.A.read"], "access": ["read"], "policy_version": 1,
        "expires_at": datetime.fromtimestamp(int(time.time()) + 3600, timezone.utc).isoformat(), "rate_per_minute": 30, "concurrency": 1})
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="external-synthetic", alg="RS256", use="sig")
    gate["auth"].external_connections = store
    gate["auth"].external_verifier = ExternalJwtVerifier(store.configuration, jwks_fetcher=lambda uri: {"keys": [public]})
    token = jwt.encode({"iss": issuer, "sub": "external-alice", "aud": RESOURCE, "client_id": "external-synthetic",
                        "scope": "tools.read", "exp": int(time.time()) + 600, "token_use": "access"}, key,
                       algorithm="RS256", headers={"kid": "external-synthetic", "typ": "at+jwt"})
    principal = gate["auth"].authenticate_mcp_request(mcp_request(token))
    assert principal.id == gate["users"]["alice"]["id"] and principal.auth_type == "oauth"
    assert principal.external_tool_ids == ("mcp.A.read",)


def test_access_log_removes_oauth_query_and_unknown_path_secrets():
    for path in ("/oauth/authorize?code=synthetic-secret&state=private", "/oauth/synthetic-secret?token=private"):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %s',
                                   ("127.0.0.1", "GET", path, "1.1", 200), None)
        OAuthAccessLogFilter().filter(record)
        assert "synthetic-secret" not in record.getMessage() and "private" not in record.getMessage()
    assert redact_value({"code": "private", "code_verifier": "private", "csrf": "private", "status_code": 400}) == {
        "code": REDACTED, "code_verifier": REDACTED, "csrf": REDACTED, "status_code": 400}
    text = redact_text("code=private code_verifier=private csrf=private status_code=400")
    assert "private" not in text and "status_code=400" in text
    assert redact_command(["oauth", "--code", "private", "--code-verifier=private", "--csrf=private"]) == [
        "oauth", "--code", REDACTED, "--code-verifier=" + REDACTED, "--csrf=" + REDACTED]


def test_reserved_json_rpc_errors_remain_usable_without_exposing_oauth_codes():
    for code in (-32700, -32600, -32601, -32602, -32603, -32000):
        safe = redact_value({"error": {"code": code, "message": "code=private code_verifier=private"}, "auth_code": code})
        assert safe["error"]["code"] == code
        assert "private" not in safe["error"]["message"] and safe["auth_code"] == REDACTED
        assert redact_value({"code": code}, known_secrets=(str(code),)) == {"code": REDACTED}
    for code in (123456, -1, -32769, "-32601", "private", True):
        assert redact_value({"code": code}) == {"code": REDACTED}


def test_browser_ttl_session_expiry_and_changed_consent_snapshot(gate, monkeypatch):
    client, _ = enable(gate)
    server, browser = gate["server"], "synthetic-browser-ttl"
    request_id = server.start_authorization(parameters(client), browser)
    context = server.consent_context(request_id, browser, gate["oauth_sessions"]["alice"])
    gate["access"].set_classification(server_id="A", tool_id="mcp.A.read", access="write", destructive=False,
                                      idempotent=False, reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id="A", reviewer_id=gate["admin"]["id"])
    with pytest.raises(OAuthError, match="tool_scope_changed"):
        server.consent(request_id, browser, context["csrf"], gate["principals"]["alice"], ["mcp.A.read"], 7, 30, 1)
    gate["db"].execute("UPDATE auth_sessions SET expires_at=? WHERE token_hash=?",
                       (datetime.fromtimestamp(int(time.time()) - 1, timezone.utc).isoformat(), hash_secret(gate["oauth_sessions"]["alice"])))
    refreshed = server.consent_context(request_id, browser, gate["oauth_sessions"]["alice"])
    assert refreshed["user"] is None and refreshed["tools"] == []
    with pytest.raises(OAuthError, match="login_required"):
        server.consent(request_id, browser, refreshed["csrf"], None, ["mcp.A.read"], 7, 30, 1)
    # No preauthenticated row survives the expired session. Expire the ticket
    # itself, which is the authoritative ten-minute browser deadline.
    admitted_at = int(time.time()) + 601
    monkeypatch.setattr("lingshu_gate.oauth_server.time.time", lambda: admitted_at)
    with pytest.raises(OAuthError, match="authorization_expired"):
        server.consent_context(request_id, browser, None)


def test_http_grant_ownership_and_basic_client_authentication(gate):
    info, secret = enable(gate)
    server = gate["server"]
    code = issue_code(gate, info)
    grant = server.store.grants(gate["users"]["alice"]["id"])[0]
    with TestClient(gate["app"], base_url=ISSUER) as client:
        client.cookies.set(gate["auth"].cookie_name, gate["sessions"]["bob"])
        assert client.get("/v1/auth/oauth/grants").json()["grants"] == []
        body = {"expected_revision": grant["revision"], "tool_ids": ["mcp.A.read"],
                "expires_at": grant["expires_at"], "rate_per_minute": 30, "concurrency": 1}
        assert client.patch(f"/v1/auth/oauth/grants/{grant['id']}", json=body, headers={"Origin": ISSUER}).status_code == 404
        assert client.post(f"/v1/auth/oauth/grants/{grant['id']}/revoke", json={"expected_revision": 1}, headers={"Origin": ISSUER}).status_code == 404
        basic = base64.b64encode((info["id"] + ":" + secret).encode()).decode()
        result = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code,
            "code_verifier": VERIFIER, "resource": RESOURCE, "redirect_uri": REDIRECT},
            headers={"Authorization": "Basic " + basic})
        assert result.status_code == 200
        assert server.verify(result.json()["access_token"]).id == gate["users"]["alice"]["id"]
        # Two authentication mechanisms in the same request are rejected.
        assert client.post("/oauth/revoke", data={"token": "synthetic", "client_secret": secret},
                           headers={"Authorization": "Basic " + basic}).status_code == 401


def test_grant_expiry_key_loss_and_refresh_expiry_fail_closed(gate):
    info, secret = enable(gate)
    server = gate["server"]
    result = exchange(server, info, secret, issue_code(gate, info))
    server.key_path.unlink()
    with pytest.raises(OAuthError, match="signing_key_unavailable"):
        refresh(server, info, secret, result["refresh_token"])
    # Failed signing rolls back consumption, allowing recovery with the exact
    # backed-up encryption key; inventing a new key is not a recovery path.
    assert gate["db"].query_one("SELECT consumed_at FROM gate_oauth_refresh")["consumed_at"] is None
    with pytest.raises(OAuthError, match="signing_key_unavailable"):
        server.rotate_key()
    gate["db"].execute("UPDATE gate_oauth_families SET expires_at=?", (int(time.time()) - 1,))
    with pytest.raises(OAuthError):
        server.verify(result["access_token"])
    with pytest.raises(OAuthError):
        refresh(server, info, secret, result["refresh_token"])


@pytest.mark.parametrize("deadline", ["code", "access"])
def test_deadlines_are_rechecked_after_sqlite_transaction_admission(gate, monkeypatch, deadline):
    info, secret = enable(gate)
    server = gate["server"]
    code = issue_code(gate, info)
    token = exchange(server, info, secret, code)["access_token"] if deadline == "access" else None
    original_transaction = server.store.transaction
    admitted_at = int(time.time()) + (ACCESS_TTL + 1 if deadline == "access" else 61)

    @contextmanager
    def delayed_admission():
        with original_transaction() as connection:
            # Model lock contention without sleeping or opening a socket.
            monkeypatch.setattr("lingshu_gate.oauth_server.time.time", lambda: admitted_at)
            yield connection

    monkeypatch.setattr(server.store, "transaction", delayed_admission)
    with pytest.raises(OAuthError):
        if token:
            server.verify(token)
        else:
            exchange(server, info, secret, code)
    if not token:
        assert gate["db"].query_one("SELECT consumed_at FROM gate_oauth_codes")["consumed_at"] is None

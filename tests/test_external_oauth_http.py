"""OHTTP: real socket Gate/JWKS/downstream OAuth acceptance with synthetic keys.

Only the injected JWKS transport maps one preconfigured HTTPS URL to a local
HTTP test server. Production URL validation, token validation, authentication,
policy and downstream dispatch remain real. No production credential is used.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.transports.http import build_protocol_request

ISSUER = "https://issuer.example.test"
JWKS_URL = ISSUER + "/jwks"
CANONICAL = "https://gate.example.test/mcp"
TUNNEL = "https://tunnel.example.test/tunnel-synthetic/mcp"
CLIENT_ID = "synthetic-client"
PASSWORD = "Synthetic-OAuth-only-123!"


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def integer(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@dataclass
class OAuthHTTP:
    client: httpx.Client
    state: Any
    key: Any
    users: dict[str, dict[str, Any]]
    grants: dict[str, dict[str, Any]]
    links: dict[str, dict[str, Any]]
    calls: Counter
    downstream_credentials: list[tuple[str, str | None]]
    fetches: list[str]
    jwks_requests: list[str]
    verifier: Any
    entered: threading.Event
    release: threading.Event

    def token(self, user: str = "alice", *, claims: dict[str, Any] | None = None,
              header: dict[str, Any] | None = None, signing_key: Any = None) -> str:
        now = int(time.time())
        payload = {"iss": ISSUER, "sub": user, "aud": TUNNEL, "client_id": CLIENT_ID,
                   "scope": "tools.read tools.invoke", "iat": now, "nbf": now - 1, "exp": now + 120}
        payload.update(claims or {})
        payload = {name: value for name, value in payload.items() if value is not None}
        protected = {"alg": "RS256", "kid": "synthetic-kid", "typ": "at+jwt"}
        protected.update(header or {})
        encoded = b64(json.dumps(protected).encode()) + "." + b64(json.dumps(payload).encode())
        signature = (signing_key or self.key).sign(encoded.encode(), padding.PKCS1v15(), hashes.SHA256())
        return encoded + "." + b64(signature)

    def rpc(self, method: str, *, token: str, params: dict[str, Any] | None = None):
        body, headers = build_protocol_request(method, params or {}, client_name="oauth-http-synthetic",
                                               client_version="1", protocol_version="2026-07-28")
        headers["Authorization"] = "Bearer " + token
        return self.client.post("/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": body})

    def call(self, tool: str, token: str):
        return self.rpc("tools/call", token=token, params={"name": tool.replace(".", "__"), "arguments": {}})

    def names(self, token: str) -> set[str]:
        response = self.rpc("tools/list", token=token)
        assert response.status_code == 200, response.text
        assert "error" not in response.json(), response.text
        return {item["name"] for item in response.json()["result"]["tools"]}

    def assert_denied_without_dispatch(self, token: str, tool: str = "mcp.A.read"):
        before = self.calls.copy()
        response = self.call(tool, token)
        assert response.status_code in {200, 401, 403}, response.text
        if response.status_code == 200:
            value = response.json()
            assert "error" in value or value.get("result", {}).get("isError") is True, value
        assert self.calls == before
        return response


@pytest.fixture
def oauth_http(tmp_path, monkeypatch, request):
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    for name, value in {"DATA_DIR": str(tmp_path), "DB_URL": f"sqlite:///{tmp_path / 'oauth-http.db'}",
        "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path), "AUTH_ENABLED": "true",
        "RUNTIME_ROLE": "local"}.items():
        monkeypatch.setenv("LINGSHU_GATE_" + name, value)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    jwks = {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "synthetic-kid",
                      "n": integer(public.n), "e": integer(public.e)}]}
    calls: Counter = Counter()
    credentials: list[tuple[str, str | None]] = []
    jwks_requests: list[str] = []
    entered, release = threading.Event(), threading.Event()

    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_json(self, value):
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            jwks_requests.append(self.path)
            assert self.path == "/jwks"
            self.send_json(jwks)

        def do_POST(self):  # noqa: N802
            server_id = self.path.strip("/").split("/")[0]
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = message["method"]
            if method == "server/discover":
                result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}, "resultType": "complete"}
            elif method == "tools/list":
                result = {"tools": [{"name": level, "description": "Synthetic " + level,
                    "inputSchema": {"type": "object"}} for level in ("read", "write")]}
            elif method == "tools/call":
                tool_id = f"mcp.{server_id}.{message['params']['name']}"
                calls[tool_id] += 1
                credentials.append((tool_id, self.headers.get("Authorization")))
                if message["params"].get("arguments", {}).get("block"):
                    entered.set()
                    assert release.wait(3), "test did not release the synthetic tool"
                result = {"content": [{"type": "text", "text": "synthetic call"}], "isError": False}
            else:
                raise AssertionError(method)
            self.send_json({"jsonrpc": "2.0", "id": message["id"], "result": result})

    peer = ThreadingHTTPServer(("127.0.0.1", 0), Peer)
    peer_thread = threading.Thread(target=lambda: peer.serve_forever(poll_interval=0.05), daemon=True)
    peer_thread.start()
    def cleanup_peer():
        peer.shutdown()
        peer.server_close()
        peer_thread.join(timeout=3)
    request.addfinalizer(cleanup_peer)
    fetches: list[str] = []

    def fetch_jwks(url: str):
        fetches.append(url)
        # No token-controlled URL can leave this assertion or reach another host.
        assert url == JWKS_URL
        with httpx.Client(timeout=2, trust_env=False) as transport:
            response = transport.get(f"http://127.0.0.1:{peer.server_port}/jwks")
            response.raise_for_status()
            return response.json()

    from lingshu_gate.main import create_app
    from lingshu_gate.external_jwt import ExternalJwtVerifier
    app = create_app()
    state = app.state
    store = state.external_connection_store
    store.save_config({"enabled": True, "mode": "direct", "endpoint": CANONICAL,
        "trusted_issuers": [ISSUER], "issuer_jwks": [[ISSUER, JWKS_URL]],
        "client_allowlist": [CLIENT_ID], "resource_mappings": [[TUNNEL, CANONICAL], [CANONICAL, CANONICAL]]}, 0)
    verifier = ExternalJwtVerifier(store.configuration, jwks_fetcher=fetch_jwks)
    # The production auth adapter remains real; only its key-fetch transport differs.
    state.auth_store.external_verifier = verifier
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=listener.getsockname()[1],
                                          lifespan="on", log_level="critical"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert server.started, "temporary Gate did not start within five seconds"
        with httpx.Client(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=5, trust_env=False) as client:
            admin = state.auth_store.list_users()[0]
            state.auth_store.change_password(admin["id"], PASSWORD)
            state.access_store.save_role(code="oauth-caller", name="Synthetic caller", description="", permissions=[
                "console.view", "tools.read", "tools.invoke", "credentials.manage.self"])
            users = {"admin": admin}
            for name in ("alice", "bob", "unlinked", "nogrant"):
                users[name] = state.auth_store.create_user(username=name, password=PASSWORD, role="oauth-caller")
            for server_id in "ABC":
                manifest = McpServerManifest.model_validate({"id": server_id, "launch": {"type": "external"},
                    "transport": {"type": "streamable_http", "endpoint": f"http://127.0.0.1:{peer.server_port}/{server_id}/mcp",
                                  "protocol_version": "2026-07-28"}, "timeout_seconds": 2,
                    "user_credentials": [{"id": "personal", "name": "Synthetic personal credential", "required": True,
                        "injection": {"type": "http_header", "name": "Authorization", "template": "Bearer {value}"}}]})
                assert state.mcp_runtime.apply_manifest(manifest, start=True).status == "running"
                state.access_store.synchronize_tools(state.registry.list_definitions())
                for level in ("read", "write"):
                    state.access_store.set_classification(server_id=server_id, tool_id=f"mcp.{server_id}.{level}",
                        access=level, destructive=False, idempotent=level == "read", reviewer_id=admin["id"])
                state.access_store.publish_classifications(server_id=server_id, reviewer_id=admin["id"])
                for name, user in users.items():
                    state.user_credential_store.save_binding(user_id=user["id"], server_id=server_id,
                                                             slot_id="personal", value=f"synthetic-personal-{name}")
                    if name != "admin" and server_id != "C":
                        state.access_store.save_grant(subject_type="user", subject_id=user["id"], server_id=server_id,
                            permission_type_code="write" if server_id == "B" else "read", created_by=admin["id"])
            links = {}
            for name in ("alice", "bob", "admin", "nogrant"):
                links[name] = store.create_subject_link({"issuer": ISSUER, "subject": name,
                    "user_id": users[name]["id"], "enabled": True})
            grants = {}
            for name, tools, levels in (("alice", ["mcp.A.read", "mcp.B.read", "mcp.B.write"], ["read", "write"]),
                                        ("bob", ["mcp.B.read"], ["read"]),
                                        ("admin", ["mcp.A.read"], ["read"])):
                grants[name] = store.create_grant(users[name]["id"], {"enabled": True, "client_id": CLIENT_ID,
                    "server_allowlist": sorted({tool.split(".")[1] for tool in tools}), "tool_allowlist": tools,
                    "access": levels, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "rate_per_minute": 500, "concurrency": 10, "policy_version": 1})
            yield OAuthHTTP(client, state, key, users, grants, links, calls, credentials, fetches, jwks_requests, verifier, entered, release)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "temporary Gate did not shut down"


def test_ohttp01_scope_intersection_real_dispatch_and_personal_credentials(oauth_http):
    env = oauth_http
    alice, bob = env.token("alice"), env.token("bob")
    assert env.names(alice) == {"mcp__A__read", "mcp__B__read", "mcp__B__write"}
    assert env.names(bob) == {"mcp__B__read"}
    for identity, token in (("alice", alice), ("bob", bob)):
        response = env.call("mcp.B.read", token)
        assert response.status_code == 200 and response.json()["result"].get("isError") is not True, response.text
        assert env.downstream_credentials[-1] == ("mcp.B.read", f"Bearer synthetic-personal-{identity}")
    assert env.call("mcp.B.write", alice).json()["result"].get("isError") is not True
    for tool, token in (("mcp.B.write", bob), ("mcp.A.write", alice), ("mcp.C.read", alice), ("mcp.A.read", bob)):
        env.assert_denied_without_dispatch(token, tool)
    env.assert_denied_without_dispatch(env.token("alice", claims={"scope": "tools.read"}), "mcp.B.write")


@pytest.mark.parametrize("case", ["expired", "future_nbf", "missing_exp", "empty_scope", "scope_type", "id_token", "issuer", "audience", "signature", "algorithm", "unknown_kid", "client", "azp", "subject", "no_grant"])
def test_ohttp02_invalid_tokens_never_dispatch(oauth_http, case):
    env = oauth_http
    claims, header, key, user = {}, {}, None, "alice"
    if case == "expired":
        claims["exp"] = int(time.time()) - 300
    if case == "future_nbf":
        claims["nbf"] = int(time.time()) + 300
    if case == "missing_exp":
        claims["exp"] = None
    if case == "empty_scope":
        claims["scope"] = ""
    if case == "scope_type":
        claims["scope"] = ["tools.read"]
    if case == "azp":
        claims["azp"] = "wrong-client"
    if case == "id_token":
        header["typ"] = "JWT"
        claims["token_use"] = "id"
    if case == "issuer":
        claims["iss"] = "http://127.0.0.1:9/untrusted-issuer"
    if case == "audience":
        claims["aud"] = "https://other.example.test/mcp"
    if case == "signature":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    if case == "algorithm":
        header["alg"] = "HS256"
    if case == "unknown_kid":
        header["kid"] = "missing-key"
    if case == "client":
        claims["client_id"] = "different-client"
    if case == "subject":
        user = "unlinked"
    if case == "no_grant":
        user = "nogrant"
    env.assert_denied_without_dispatch(env.token(user, claims=claims, header=header, signing_key=key))
    assert all(url == JWKS_URL for url in env.fetches)


def test_ohttp03_revocation_and_disable_rechecked_on_same_client(oauth_http):
    env = oauth_http
    token = env.token("alice")
    # Current Streamable HTTP is stateless: reuse a previously discovered client/token,
    # not a server-side session principal, and verify authorization is re-read.
    assert env.rpc("server/discover", token=token).status_code == 200
    assert env.call("mcp.A.read", token).json()["result"].get("isError") is not True
    env.state.external_connection_store.revoke_grant(env.users["alice"]["id"], env.grants["alice"]["id"])
    env.assert_denied_without_dispatch(token)
    token = env.token("bob")
    assert env.call("mcp.B.read", token).json()["result"].get("isError") is not True
    config = env.state.external_connection_store.config()
    revision = config.pop("revision")
    config.pop("updated_at", None)
    config["enabled"] = False
    env.state.external_connection_store.save_config(config, revision)
    env.assert_denied_without_dispatch(token, "mcp.B.read")


def test_ohttp04_admin_read_delegation_does_not_bypass_scope_or_tool_policy(oauth_http):
    env = oauth_http
    token = env.token("admin", claims={"scope": "tools.read"})
    assert env.names(token) == {"mcp__A__read"}
    wildcard = env.token("admin", claims={"scope": "*"})
    assert env.names(wildcard) == {"mcp__A__read"}
    env.assert_denied_without_dispatch(wildcard, "mcp.C.write")
    env.assert_denied_without_dispatch(token, "mcp.A.write")
    env.assert_denied_without_dispatch(token, "mcp.C.read")
    env.state.access_store.set_classification(server_id="A", tool_id="mcp.A.read", access="read",
        destructive=False, idempotent=True, reviewer_id=env.users["admin"]["id"])
    env.assert_denied_without_dispatch(token, "mcp.A.read")


def test_ohttp05_invalid_bearer_cannot_inherit_cookie_and_jwt_cannot_enter_console(oauth_http):
    env = oauth_http
    response = env.client.post("/v1/auth/login", json={"username": env.users["admin"]["username"], "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert env.client.get("/v1/auth/me").status_code == 200
    env.assert_denied_without_dispatch("invalid.invalid.invalid")
    assert env.client.get("/v1/auth/me", headers={"Authorization": "Bearer " + env.token("admin")}).status_code == 401
    assert env.client.get("/v1/auth/me").status_code == 200


def test_ohttp06_untrusted_key_urls_and_unknown_key_refresh_are_bounded(oauth_http):
    env = oauth_http
    assert env.names(env.token("alice"))
    baseline = len(env.fetches)
    for field in ("jku", "x5u"):
        response = env.rpc("tools/list", token=env.token(header={field: "http://127.0.0.1:9/forbidden"}))
        assert response.status_code in {200, 401, 403}
    env.assert_denied_without_dispatch(env.token(claims={"iss": "http://127.0.0.1:9/untrusted"}))
    for index in range(8):
        env.assert_denied_without_dispatch(env.token(header={"kid": f"unknown-{index}"}))
    assert set(env.fetches) == {JWKS_URL}
    assert len(env.fetches) <= baseline + 1
    assert len(env.jwks_requests) == len(env.fetches)


def test_ohttp07_self_asserted_user_grant_email_cannot_change_owner(oauth_http):
    env = oauth_http
    token = env.token("alice", claims={"user_id": env.users["admin"]["id"],
        "grant_id": env.grants["admin"]["id"], "email": "admin@example.test"})
    assert env.names(token) == {"mcp__A__read", "mcp__B__read", "mcp__B__write"}
    response = env.call("mcp.B.read", token)
    assert response.status_code == 200 and response.json()["result"].get("isError") is not True, response.text
    assert env.downstream_credentials[-1] == ("mcp.B.read", "Bearer synthetic-personal-alice")
    env.assert_denied_without_dispatch(token, "mcp.C.write")



def update_grant(env: OAuthHTTP, user: str, **changes):
    store = env.state.external_connection_store
    current = store.get_grant(env.users[user]["id"], env.grants[user]["id"])
    fields = {"enabled", "client_id", "server_allowlist", "tool_allowlist", "access", "expires_at", "rate_per_minute", "concurrency", "policy_version"}
    payload = {key: value for key, value in current.items() if key in fields}
    payload.update(changes)
    return store.update_grant(env.users[user]["id"], current["id"], payload, current["revision"])


@pytest.mark.parametrize("change", ["expired_grant", "disabled_grant", "disabled_link", "disabled_user", "resource_revoke", "role_revoke"])
def test_ohttp08_current_authority_rechecked_after_previous_success(oauth_http, change):
    env = oauth_http
    token = env.token("alice")
    assert env.rpc("server/discover", token=token).status_code == 200
    assert env.call("mcp.A.read", token).json()["result"].get("isError") is not True
    if change == "expired_grant":
        update_grant(env, "alice", expires_at=(datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat())
    elif change == "disabled_grant":
        update_grant(env, "alice", enabled=False)
    elif change == "disabled_link":
        link = env.links["alice"]
        env.state.external_connection_store.update_subject_link(link["id"], enabled=False, expected_revision=link["revision"])
    elif change == "disabled_user":
        env.state.database.execute("UPDATE users SET status='disabled' WHERE id=?", (env.users["alice"]["id"],))
    elif change == "resource_revoke":
        for grant in env.state.access_store.list_grants():
            if grant["subject_id"] == env.users["alice"]["id"] and grant["server_id"] == "A":
                env.state.access_store.delete_grant(grant["id"])
    else:
        env.state.access_store.save_role(code="observer-http", name="Observer", description="", permissions=["console.view"])
        env.state.access_store.set_user_roles(env.users["alice"]["id"], ["observer-http"])
    env.assert_denied_without_dispatch(token)


def test_ohttp09_delegation_cannot_expand_current_resource_grants(oauth_http):
    env = oauth_http
    update_grant(env, "alice", server_allowlist=["A", "B", "C"],
                 tool_allowlist=["mcp.A.read", "mcp.B.read", "mcp.B.write", "mcp.C.read"])
    token = env.token("alice")
    assert "mcp__C__read" not in env.names(token)
    env.assert_denied_without_dispatch(token, "mcp.C.read")


def test_ohttp10_rate_quota_rejection_does_not_dispatch(oauth_http):
    env = oauth_http
    update_grant(env, "alice", rate_per_minute=1)
    token = env.token("alice")
    assert env.call("mcp.A.read", token).json()["result"].get("isError") is not True
    assert env.calls["mcp.A.read"] == 1
    env.assert_denied_without_dispatch(token)


def test_ohttp11_concurrency_quota_and_release_use_real_overlapping_calls(oauth_http):
    env = oauth_http
    update_grant(env, "alice", concurrency=1)
    token = env.token("alice")
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(env.rpc, "tools/call", token=token,
            params={"name": "mcp__A__read", "arguments": {"block": True}})
        try:
            assert env.entered.wait(1.5), "first call did not reach the real downstream peer"
            env.assert_denied_without_dispatch(token)
        finally:
            env.release.set()
        first = pending.result(timeout=4)
        assert first.status_code == 200 and first.json()["result"].get("isError") is not True, first.text
    assert env.call("mcp.A.read", token).json()["result"].get("isError") is not True
    assert env.calls["mcp.A.read"] == 2


def test_ohttp12_personal_grant_http_disable_reenable_and_narrow_takes_effect(oauth_http):
    env = oauth_http
    token = env.token("alice")
    assert env.call("mcp.B.write", token).json()["result"].get("isError") is not True
    login = env.client.post("/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200, login.text
    grant_url = f"/v1/auth/external-grants/{env.grants['alice']['id']}"
    current_response = env.client.get(grant_url)
    assert current_response.status_code == 200, current_response.text
    current = current_response.json()
    payload = {"enabled": False, "client_id": CLIENT_ID, "server_allowlist": ["A"],
        "tool_allowlist": ["mcp.A.read"], "access": ["read"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "rate_per_minute": 100, "concurrency": 2, "expected_revision": current["revision"]}
    disabled = env.client.patch(grant_url, json=payload)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    env.assert_denied_without_dispatch(token, "mcp.B.write")
    payload.update(enabled=True, expected_revision=disabled.json()["revision"])
    enabled = env.client.patch(grant_url, json=payload)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert env.names(token) == {"mcp__A__read"}
    assert env.call("mcp.A.read", token).json()["result"].get("isError") is not True
    env.assert_denied_without_dispatch(token, "mcp.B.write")
    deleted = env.client.delete(grant_url)
    assert deleted.status_code == 200, deleted.text
    env.assert_denied_without_dispatch(token, "mcp.A.read")


def test_ohttp13_spoofed_host_cannot_change_resource_or_challenge(oauth_http):
    env = oauth_http
    headers = {"Host": "attacker.example.test"}
    response = env.client.get("/.well-known/oauth-protected-resource/mcp", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["resource"] == CANONICAL
    assert "attacker.example.test" not in response.text
    before = env.calls.copy()
    response = env.client.post("/mcp", headers={**headers, "Authorization": "Bearer invalid"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    assert "attacker.example.test" not in challenge
    assert "https://gate.example.test/.well-known/oauth-protected-resource/mcp" in challenge
    assert env.calls == before

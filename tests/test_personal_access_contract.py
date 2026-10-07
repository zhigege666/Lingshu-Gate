"""P01–P11: real HTTP authorization with isolated synthetic identities and tools."""
from __future__ import annotations

import os
import sys
from collections import Counter

import pytest
from fastapi.testclient import TestClient



@pytest.fixture
def contract(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(key)
    for key, value in {
        "DATA_DIR": str(tmp_path), "DB_URL": f"sqlite:///{tmp_path / 'isolated.db'}",
        "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path),
        "AUTH_ENABLED": "true",
    }.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{key}", value)
    from lingshu_gate.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as client:
        state = client.app.state
        auth, access = state.auth_store, state.access_store
        admin = auth.list_users()[0]
        auth.change_password(admin["id"], "Synthetic-admin-123!")
        access.save_role(code="observer", name="Observer", description="", permissions=["console.view"])
        access.save_role(code="caller", name="Caller", description="", permissions=[
            "console.view", "tools.read", "tools.invoke", "credentials.manage.self",
        ])
        users = {}
        for name, role in (("observer", "observer"), ("reader", "viewer"),
                           ("writer", "caller"), ("other", "caller"), ("operator", "operator")):
            users[name] = auth.create_user(username=name, password="Synthetic-pass-123!", role=role)
        from lingshu_gate.mcp_manifest import McpServerManifest
        peer = tmp_path / "synthetic_peer.py"
        peer.write_text(SYNTHETIC_PEER)
        dispatch_log = tmp_path / "dispatch.log"
        class DispatchCounts:
            def __getitem__(self, key):
                lines = dispatch_log.read_text().splitlines() if dispatch_log.exists() else []
                return Counter(lines)[key]
        calls = DispatchCounts()
        for server in "ABC":
            manifest = McpServerManifest.model_validate({"id": server,
                "launch": {"type": "managed_process", "command": sys.executable,
                    "args": [str(peer), server, str(dispatch_log)]},
                "transport": {"type": "stdio", "protocol_version": "2025-06-18"},
                "timeout_seconds": 3})
            runtime = state.mcp_runtime.apply_manifest(manifest, start=True)
            assert runtime.status == "running", runtime
            access.synchronize_tools(state.registry.list_definitions())
            for level in ("read", "write"):
                access.set_classification(server_id=server, tool_id=f"mcp.{server}.{level}", access=level,
                    destructive=False, idempotent=level == "read", reviewer_id=admin["id"])
            access.publish_classifications(server_id=server, reviewer_id=admin["id"])
        for name in users:
            for server in "AB":
                access.save_grant(subject_type="user", subject_id=users[name]["id"],
                    server_id=server, permission_type_code="write" if name in {"writer", "other"}
                    and server == "B" else "read", created_by=admin["id"])
        def login(name):
            client.cookies.clear()
            result = client.post("/v1/auth/login", json={"username": name,
                "password": "Synthetic-admin-123!" if name == "admin" else "Synthetic-pass-123!"})
            assert result.status_code == 200, result.text
        yield client, state, users, calls, login


def invoke(client, tool):
    return client.post(f"/v1/tools/{tool}/invoke", json={"arguments": {}})


@pytest.mark.parametrize("identity,expected", [
    ("admin", {f"mcp.{s}.{a}" for s in "ABC" for a in ("read", "write")}),
    ("observer", set()), ("reader", {"mcp.A.read", "mcp.B.read"}),
    ("writer", {"mcp.A.read", "mcp.B.read", "mcp.B.write"}),
])
def test_p01_identity_discovery_and_guessed_id_zero_dispatch(contract, identity, expected):
    client, state, users, calls, login = contract
    login(identity)
    visible = {tool["id"] for tool in client.get("/v1/tools").json()
               if tool["id"].startswith("mcp.")}
    assert visible == expected
    for server in "ABC":
        for level in ("read", "write"):
            tool = f"mcp.{server}.{level}"
            response = invoke(client, tool)
            assert response.status_code == (200 if tool in expected else 403)
            if tool in expected:
                assert response.json()["ok"] is True, response.text
            assert calls[tool] == (1 if tool in expected else 0)
            assert client.get(f"/v1/tools/{tool}").status_code == (200 if tool in expected else 404)
    if identity != "admin":
        for path in ("/v1/mcp/servers", "/v1/builds", "/v1/access/invocation-audits"):
            assert client.get(path).status_code == 403
        for path in ("/v1/mcp/configs", "/v1/builds/synthetic/deploy", "/v1/projects/upload"):
            assert client.post(path, json={}).status_code == 403
        assert client.put("/v1/mcp/configs/A", json={}).status_code == 403
        for action in ("start", "stop", "restart"):
            assert client.post(f"/v1/mcp/servers/A/{action}").status_code == 403


def test_p02_personal_summary_counts_search_and_projection(contract):
    client, state, users, calls, login = contract
    login("writer")
    result = client.get("/v1/me/mcp-servers", params={"limit": 1}).json()
    assert result["total"] == 2
    assert len(result["servers"]) == 1
    assert result["servers"][0] == {"id": "A", "name": "A", "tool_count": 1,
                                   "read_tool_count": 1, "write_tool_count": 0}
    assert client.get("/v1/me/mcp-servers", params={"q": "C"}).json()["total"] == 0
    assert client.get("/v1/me/mcp-servers/C").status_code == 404
    detail = client.get("/v1/me/mcp-servers/B").json()
    assert detail["tool_count"] == 2
    assert set(detail["tools"][0]) == {"id", "name", "description", "required_access"}


def test_p03_personal_audits_cannot_select_another_user(contract):
    client, state, users, calls, login = contract
    login("other")
    assert invoke(client, "mcp.B.write").status_code == 200
    login("writer")
    assert invoke(client, "mcp.A.read").status_code == 200
    audits = client.get("/v1/me/invocations", params={"user_id": users["other"]["id"]}).json()["audits"]
    assert [item["tool_id"] for item in audits] == ["mcp.A.read"]
    assert "payload" not in audits[0]
    assert "user_id" not in audits[0]


def test_p04_existing_session_rechecks_revoked_and_expired_grants(contract):
    client, state, users, calls, login = contract
    login("writer")
    assert invoke(client, "mcp.B.write").status_code == 200
    access = state.access_store
    for grant in access.list_grants(subject_type="user", subject_id=users["writer"]["id"]):
        access.delete_grant(grant["id"])
    assert invoke(client, "mcp.B.write").status_code == 403
    assert calls["mcp.B.write"] == 1
    access.save_grant(subject_type="user", subject_id=users["writer"]["id"], server_id="B",
        permission_type_code="write", expires_at="2000-01-01T00:00:00+00:00", created_by="synthetic")
    assert invoke(client, "mcp.B.write").status_code == 403
    assert client.get("/v1/me/mcp-servers").json()["total"] == 0


def test_p05_token_scope_and_publication_intersection(contract):
    client, state, users, calls, login = contract
    login("writer")
    token = client.post("/v1/auth/tokens", json={"name": "read-only", "scopes": ["tools.read"]})
    assert token.status_code == 200, token.text
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    assert invoke(client, "mcp.B.read").status_code == 200
    assert invoke(client, "mcp.B.write").status_code == 403
    state.access_store.set_classification(server_id="B", tool_id="mcp.B.read", access="read",
        destructive=False, idempotent=True, reviewer_id="synthetic")
    assert invoke(client, "mcp.B.read").status_code == 403
    assert calls["mcp.B.read"] == 1



def test_p06_mcp_protocol_discovery_and_guessed_call(contract):
    client, state, users, calls, login = contract
    login("writer")
    listing = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listing.status_code == 200, listing.text
    tools = listing.json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {name for name in names if name.startswith("mcp__")} == {
        "mcp__A__read", "mcp__B__read", "mcp__B__write",
    }
    denied = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "mcp__C__write", "arguments": {}}})
    assert denied.status_code == 200
    assert denied.json()["result"]["isError"] is True
    assert calls["mcp.C.write"] == 0


def test_p07_personal_credentials_are_owner_bound(contract):
    from lingshu_gate.mcp_manifest import McpServerManifest

    client, state, users, calls, login = contract
    manifest = McpServerManifest.model_validate({"id": "B", "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": "https://synthetic.invalid/mcp"},
        "user_credentials": [{"id": "access", "name": "Personal", "required": True,
            "injection": {"type": "http_header", "name": "Authorization", "template": "Bearer {value}"}}]})
    state.mcp_runtime.apply_manifest(manifest, start=False)
    for name in ("writer", "other"):
        login(name)
        result = client.put("/v1/auth/downstream-credentials/B/access",
            json={"value": f"synthetic-{name}", "user_id": users["other"]["id"]})
        assert result.status_code == 200, result.text
        assert f"synthetic-{name}" not in result.text
    for name in ("writer", "other"):
        values, missing = state.user_credential_store.resolve_slots(
            user_id=users[name]["id"], server_id="B", slots=manifest.user_credentials)
        assert not missing
        assert values == {"access": f"synthetic-{name}"}
    login("writer")
    assert "synthetic-other" not in client.get("/v1/auth/downstream-credentials").text
    assert client.delete("/v1/auth/downstream-credentials/B/access").status_code == 200
    values, missing = state.user_credential_store.resolve_slots(
        user_id=users["other"]["id"], server_id="B", slots=manifest.user_credentials)
    assert values == {"access": "synthetic-other"}
    assert not missing


SYNTHETIC_PEER = """import json, sys, os
from pathlib import Path
for line in sys.stdin:
    message = json.loads(line)
    method = message['method']
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'synthetic', 'version': '1'}}
    elif method == 'notifications/initialized':
        continue
    elif method == 'tools/list':
        result = {'tools': [{'name': name, 'description': sys.argv[1] + ' ' + name,
            'inputSchema': {'type': 'object'}} for name in ['read', 'write']]}
    elif method == 'tools/call':
        with Path(sys.argv[2]).open('a') as log:
            log.write('mcp.' + sys.argv[1] + '.' + message['params']['name'] + '\\n')
        result = {'content': [{'type': 'text', 'text': 'shared-configured' if os.environ.get('SYNTHETIC_SHARED') == 'synthetic-runtime-value' else 'synthetic ok'}], 'isError': False}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': message.get('id'),
            'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)
"""


def test_p08_existing_session_role_revoke_and_expired_token(contract):
    client, state, users, calls, login = contract
    login("writer")
    assert invoke(client, "mcp.B.write").json()["ok"] is True
    state.access_store.set_user_roles(users["writer"]["id"], ["observer"])
    assert invoke(client, "mcp.B.write").status_code == 403
    assert calls["mcp.B.write"] == 1
    login("reader")
    token = client.post("/v1/auth/tokens", json={"name": "expires", "scopes": ["tools.read"]})
    assert token.status_code == 200
    state.auth_store.database.execute("UPDATE api_tokens SET expires_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", token.json()["id"]))
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token.json()['token']}"
    assert invoke(client, "mcp.B.read").status_code == 401
    assert calls["mcp.B.read"] == 0


def test_p09_shared_credential_admin_capability_boundary(contract):
    client, state, users, calls, login = contract
    login("admin")
    saved = client.post("/v1/credentials", json={"name": "Synthetic shared", "value": "synthetic-only"})
    assert saved.status_code == 200, saved.text
    credential_id = saved.json()["id"]
    for identity in ("observer", "reader", "writer", "operator"):
        login(identity)
        assert client.get("/v1/credentials").status_code == 403
        assert client.get(f"/v1/credentials/{credential_id}").status_code == 403
        assert client.post("/v1/credentials", json={"name": "denied", "value": "synthetic"}).status_code == 403
        assert client.put(f"/v1/credentials/{credential_id}",
            json={"name": "denied", "value": "synthetic"}).status_code == 403
        assert client.delete(f"/v1/credentials/{credential_id}").status_code == 403
    login("admin")
    assert client.get(f"/v1/credentials/{credential_id}").status_code == 200


def test_p10_shared_credential_crud_restriction_does_not_block_runtime_resolution(contract):
    client, state, users, calls, login = contract
    state.credential_store.save_credential(name="Synthetic runtime", credential_id="synthetic-shared",
        value="synthetic-runtime-value")
    current = state.mcp_runtime.iter_manifests()["B"].model_copy(deep=True)
    current.launch.env["SYNTHETIC_SHARED"] = "${credential:synthetic-shared}"
    assert state.mcp_runtime.apply_manifest(current, start=True).status == "running"
    login("operator")
    assert client.get("/v1/credentials/synthetic-shared").status_code == 403
    response = invoke(client, "mcp.B.read")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert "shared-configured" in response.text
    assert "synthetic-runtime-value" not in response.text
    assert calls["mcp.B.read"] == 1


def test_p11_disabled_role_rejects_existing_session_without_internal_error(contract):
    client, state, users, calls, login = contract
    login("writer")
    assert invoke(client, "mcp.B.write").json()["ok"] is True
    state.access_store.database.execute("UPDATE roles SET enabled = 0 WHERE code = 'caller'")
    response = invoke(client, "mcp.B.write")
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "No enabled role is assigned; contact an administrator"
    assert calls["mcp.B.write"] == 1
    assert client.get("/v1/me/mcp-servers").status_code == 403
    login("admin")
    listing = client.get("/v1/access/users")
    assert listing.status_code == 200, listing.text
    revoked_user = next(user for user in listing.json()["users"] if user["id"] == users["writer"]["id"])
    assert revoked_user["roles"] == []
    assert revoked_user["role"] == ""

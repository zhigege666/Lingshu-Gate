"""IP01–IP08: bounded recording and real HTTP owner/capability isolation."""
from __future__ import annotations

import json

import pytest

from lingshu_gate.invocation_payloads import MAX_PAYLOAD_BYTES, snapshot
import test_personal_access_contract as fixtures

payload_contract = fixtures.contract
invoke = fixtures.invoke


def test_ip01_scalar_fidelity_and_credentials():
    value = snapshot({"null": None, "false": False, "zero": 0, "nested": {"api_key": "secret-value"},
                      "text": "Bearer bearer-value", "headers": "Cookie: first=value; second=private\nAuthorization: Basic abc"})
    assert value["status"] == "recorded"
    assert snapshot("x" * 20_000)["status"] == "recorded"
    assert snapshot("x" * 20_000)["value"] == "x" * 20_000
    assert value["value"]["null"] is None
    assert value["value"]["false"] is False
    assert value["value"]["zero"] == 0
    for secret in ("secret-value", "bearer-value", "first=value", "second=private", "Basic abc"):
        assert secret not in json.dumps(value)


@pytest.mark.parametrize("value,reason", [(["x" * 100_000], "bytes"), (list(range(10_000)), "nodes")])
def test_ip02_bounded_capture(value, reason):
    result = snapshot(value)
    assert result["status"] == "truncated"
    assert reason in result["reasons"]
    assert len(json.dumps(result).encode()) <= MAX_PAYLOAD_BYTES


def test_ip03_depth_cycle_and_object_never_repr():
    nested: dict = {}
    current = nested
    for _ in range(20):
        current["next"] = {}
        current = current["next"]
    assert "depth" in snapshot(nested)["reasons"]
    nested["self"] = nested
    assert snapshot(nested)["status"] == "serialization_error"
    class Unsafe:
        def __repr__(self):
            raise AssertionError("must not evaluate")
    assert snapshot(Unsafe()) == {"status": "serialization_error", "value": "[UNSUPPORTED]", "reasons": ["unsupported_type"]}


def enable_recording(state):
    # Exact migration-owned field; isolated synthetic DB only.
    state.access_store.database.execute("UPDATE retention_policy SET payload_mode = 'redacted'")


def latest(client):
    return client.get("/v1/me/invocations").json()["audits"][0]["id"]


def test_ip04_default_off_and_history_not_relabelled(payload_contract):
    client, state, users, calls, login = payload_contract
    login("writer")
    assert invoke(client, "mcp.A.read").json()["ok"]
    audit_id = latest(client)
    enable_recording(state)
    detail = client.get(f"/v1/me/invocations/{audit_id}").json()
    assert detail["recording_mode"] == "metadata_only"
    assert detail["input"] == detail["output"] == {"status": "not_recorded"}


def test_ip05_owner_guessing_and_admin_explicit_capability(payload_contract):
    client, state, users, calls, login = payload_contract
    enable_recording(state)
    login("writer")
    response = client.post("/v1/tools/mcp.A.read/invoke", json={"arguments": {"password": "synthetic-private", "zero": 0}})
    assert response.json()["ok"]
    audit_id = latest(client)
    path = f"/v1/me/invocations/{audit_id}"
    detail = client.get(path)
    assert detail.status_code == 200
    assert "synthetic-private" not in detail.text
    assert detail.json()["input"]["value"]["zero"] == 0
    login("other")
    assert client.get(path, params={"user_id": users["writer"]["id"]}).status_code == 404
    login("operator")
    assert client.get(f"/v1/access/invocation-audits/{audit_id}").status_code == 403
    login("admin")
    assert client.get(f"/v1/access/invocation-audits/{audit_id}").status_code == 200
    assert client.get(path).status_code == 404  # own endpoint never expands for admin
    token = client.post("/v1/auth/tokens", json={"name": "metadata-only", "scopes": ["audit.read"]}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get(f"/v1/access/invocation-audits/{audit_id}").status_code == 403


def test_ip06_denial_records_no_values_and_zero_dispatch(payload_contract):
    client, state, users, calls, login = payload_contract
    enable_recording(state)
    login("writer")
    denied = client.post("/v1/tools/mcp.C.write/invoke", json={"arguments": {"arbitrary": "must-not-record"}})
    assert denied.status_code == 403
    assert calls["mcp.C.write"] == 0
    detail = client.get(f"/v1/me/invocations/{latest(client)}").json()
    assert detail["input"] == detail["output"] == {"status": "not_invoked"}
    assert not state.access_store.database.query_all("SELECT * FROM invocation_payloads")


def test_ip07_old_session_rechecks_user_and_admin_capability(payload_contract):
    client, state, users, calls, login = payload_contract
    enable_recording(state)
    login("writer")
    assert invoke(client, "mcp.A.read").json()["ok"]
    audit_id = latest(client)
    state.auth_store.database.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (users["writer"]["id"],))
    assert client.get(f"/v1/me/invocations/{audit_id}").status_code in (401, 403)
    access = state.access_store
    role = access.save_role(code="content-auditor", name="Content", description="", permissions=["console.view", "audit.payload.read"])
    access.set_user_roles(users["operator"]["id"], ["content-auditor"])
    login("operator")
    assert client.get(f"/v1/access/invocation-audits/{audit_id}").status_code == 200
    access.save_role(role_id=role["id"], code="content-auditor", name="Content", description="", permissions=["console.view"])
    assert client.get(f"/v1/access/invocation-audits/{audit_id}").status_code == 403


def test_ip08_before_dispatch_snapshot_and_redacted_error(payload_contract, monkeypatch):
    client, state, users, calls, login = payload_contract
    enable_recording(state)
    login("writer")
    def mutate(server_id, tool_name, arguments, **kwargs):
        arguments["injected"] = "must-not-record-in-input"
        raise RuntimeError("Authorization: Basic private-value\nCookie: a=private; b=secret")
    monkeypatch.setattr(state.mcp_runtime, "invoke_mcp_tool_for_user", mutate)
    result = client.post("/v1/tools/mcp.A.read/invoke", json={"arguments": {"zero": 0}})
    assert result.json()["ok"] is False
    detail = client.get(f"/v1/me/invocations/{latest(client)}").json()
    assert detail["input"]["value"] == {"zero": 0}
    assert detail["output"]["value"]["ok"] is False
    assert "private-value" not in json.dumps(detail)
    assert "a=private" not in json.dumps(detail)


@pytest.mark.parametrize("fails", [False, True])
def test_ip09_known_personal_secret_echo_never_persisted(payload_contract, monkeypatch, fails):
    from lingshu_gate.mcp_manifest import McpServerManifest
    from lingshu_gate.mcp_runtime import McpServerRuntime, McpServerState
    client, state, users, calls, login = payload_contract
    enable_recording(state)
    login("writer")
    secret = "synthetic-private-echo-value"
    manifest = McpServerManifest.model_validate({"id": "B", "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": "https://synthetic.invalid/mcp"},
        "user_credentials": [{"id": "access", "name": "Personal", "required": True,
            "injection": {"type": "http_header", "name": "Authorization", "template": "Bearer {value}"}}]})
    state.user_credential_store.save_binding(user_id=users["writer"]["id"], server_id="B", slot_id="access", value=secret)
    runtime = McpServerRuntime(manifest=manifest, state=McpServerState.RUNNING, client=object())
    original_get = state.mcp_runtime._get_runtime
    monkeypatch.setattr(state.mcp_runtime, "_get_runtime", lambda server: runtime if server == "B" else original_get(server))
    class EchoClient:
        def __init__(self, manifest, *args, **kwargs):
            assert manifest.transport.headers["Authorization"] == "Bearer " + secret
        def start(self):
            pass
        def stop(self):
            pass
        def call_tool(self, name, arguments):
            if fails:
                raise RuntimeError("unlabelled " + secret)
            return {"arbitrary": secret}
    monkeypatch.setattr("lingshu_gate.mcp_runtime.StreamableHttpMcpClient", EchoClient)
    response = invoke(client, "mcp.B.read")
    assert response.json()["ok"] is not fails
    # User's actual result is unchanged; only the durable audit is redacted.
    assert secret in response.text
    detail = client.get(f"/v1/me/invocations/{latest(client)}")
    assert secret not in detail.text
    assert "[REDACTED]" in detail.text
    stored = state.access_store.database.query_one("SELECT output_json FROM invocation_payloads")
    assert secret not in stored["output_json"]


def test_ip10_known_secret_at_truncation_boundary():
    secret = "known-value-" * 30
    result = snapshot("x" * (MAX_PAYLOAD_BYTES - 1100) + secret, known_secrets=[secret])
    assert "known-value" not in json.dumps(result)
    assert len(json.dumps(result).encode()) <= MAX_PAYLOAD_BYTES


@pytest.mark.parametrize("header", ["authorization", "cookie", "cookie-second"])
def test_ip11_shared_header_echo_not_persisted(payload_contract, monkeypatch, header):
    from lingshu_gate.mcp_manifest import McpServerManifest
    from lingshu_gate.mcp_runtime import McpServerRuntime, McpServerState
    client, state, users, calls, login = payload_contract
    enable_recording(state)
    login('writer')
    secret = 'synthetic-shared-private-echo-value'
    manifest = McpServerManifest.model_validate({'id':'B','launch':{'type':'external'},
        'transport':{'type':'streamable_http','endpoint':'https://synthetic.invalid/mcp',
                     'headers': ({'Authorization':'Bearer '+secret} if header == 'authorization' else {'Cookie': ('session='+secret+'; mode=test' if header == 'cookie' else 'mode=test; session='+secret)})}})
    class EchoClient:
        def call_tool(self, name, arguments):
            return {'arbitrary':secret}
    runtime = McpServerRuntime(manifest=manifest,state=McpServerState.RUNNING,client=EchoClient())
    original=state.mcp_runtime._get_runtime
    monkeypatch.setattr(state.mcp_runtime,'_get_runtime',lambda server:runtime if server=='B' else original(server))
    response=fixtures.invoke(client,'mcp.B.read')
    assert response.json()['ok'], response.text
    detail=client.get('/v1/me/invocations/'+latest(client))
    assert secret not in detail.text, detail.text
    assert secret not in state.access_store.database.query_one('SELECT output_json FROM invocation_payloads')['output_json']

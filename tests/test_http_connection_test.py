"""Real loopback sockets and synthetic secrets; diagnostics must not save state."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lingshu_gate.credential_store import canonical_http_origin
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_http_trust import McpHttpTrustUpdate
from lingshu_gate.registry import ToolExecutionError

from test_external_mcp_configuration import gate as gate
from test_oauth_management_e2e import browser as browser

SECRET = "Synthetic-probe-token-only-123"


@pytest.fixture
def peer():
    state = {"requests": [], "status": 200, "legacy": False, "html": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((body["method"], self.headers.get("Authorization"), self.headers.get("Cookie")))
            status = state["status"]
            if self.headers.get("Authorization") != "Bearer " + SECRET:
                status = 401
            if status != 200:
                payload = json.dumps({"error": SECRET}).encode()  # malicious upstream echo must not escape
                self.send_response(status)
                self.send_header("WWW-Authenticate", 'Bearer realm="Synthetic HTTP MCP"')
                self.send_header("Location", "http://127.0.0.1:1/do-not-follow")
            elif state["html"]:
                payload = ("<html>" + SECRET + "</html>").encode()
                self.send_response(200)
            else:
                method = body["method"]
                if method == "server/discover":
                    result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}},
                              "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Synthetic HTTP MCP", "version": "test"}}}
                elif method == "initialize":
                    result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "Synthetic HTTP MCP", "version": "test"}}
                elif method == "notifications/initialized":
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                elif method == "tools/list":
                    result = {"tools": [{"name": "read", "inputSchema": {"type": "object"}}]}
                else:
                    raise AssertionError("Probe must never call business tools")
                payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200)
            self.send_header("Content-Type", "text/html" if state["html"] else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state["endpoint"] = f"http://127.0.0.1:{server.server_port}/mcp"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def arguments(gate, peer, *, endpoint=None):
    url = endpoint or peer["endpoint"]
    gate["service"].credentials.create_credential(credential_id="probe-key", name="Synthetic test",
        value=SECRET, http_scopes=[{"server_id": "probe-peer", "origin": canonical_http_origin(url)}])
    return {"manifest": {"id": "probe-peer", "enabled": True, "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": url,
                      "headers": {"Authorization": "Bearer ${credential:probe-key}"}}},
        "confirmed": True, "timeout_seconds": 3}


def run(gate, body):
    return gate["service"].http_test(body, gate["context"])


@pytest.mark.parametrize("legacy", [False, True])
def test_unsaved_test_uses_real_protocol_and_does_not_save_or_publish(gate, peer, legacy):
    body = arguments(gate, peer)
    if legacy:
        body["manifest"]["transport"]["protocol_version"] = "2025-11-25"
    service = gate["service"]
    before = service.configs.http_trust_store.get("probe-peer")
    tools_before = [tool.id for tool in service.runtime.registry.list_definitions()]
    result = run(gate, body)
    assert result["ok"], result
    assert result["tool_count"] == 1
    assert "service_hint" not in result
    assert all(stage["status"] == "passed" for stage in result["stages"])
    assert not any(result[key] for key in ("config_saved", "trust_changed", "registry_changed", "business_permissions_verified"))
    assert not service.configs.list_configs().configs
    assert before == service.configs.http_trust_store.get("probe-peer")
    assert [tool.id for tool in service.runtime.registry.list_definitions()] == tools_before
    assert service.credentials.get_credential("probe-key").http_scopes[0].server_binding is None
    assert all(cookie is None for _, _, cookie in peer["requests"])
    assert "tools/call" not in [method for method, *_ in peer["requests"]]
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize(("status", "code", "stage"), [
    (401, "authentication_required", "authentication"), (403, "access_denied", "authentication"),
    (404, "endpoint_not_found", "http"), (405, "http_method_not_allowed", "http"),
    (302, "redirect_blocked", "http"), (429, "rate_limited", "http"), (503, "upstream_failed", "http"),
])
def test_structured_failure_never_echoes_secrets(gate, peer, status, code, stage, caplog):
    peer["status"] = status
    result = run(gate, arguments(gate, peer))
    assert not result["ok"] and result["code"] == code and result["failed_stage"] == stage, result
    assert SECRET not in json.dumps(result) and SECRET not in caplog.text
    assert len(peer["requests"]) == 1
    if status == 401:
        assert result["auth_scheme"] == "bearer" and not result["oauth_advertised"]


def test_html_200_is_not_a_successful_mcp_handshake(gate, peer):
    peer["html"] = True
    result = run(gate, arguments(gate, peer))
    assert result["code"] == "mcp_protocol_failed" and result["failed_stage"] == "handshake"
    assert result["stages"][1]["status"] == "passed"
    assert result["stages"][2]["status"] == "skipped"


@pytest.mark.parametrize("mutation", ["raw_secret", "duplicate", "newline", "reserved", "disabled", "personal"])
def test_invalid_inputs_are_blocked_before_network(gate, peer, mutation):
    body = arguments(gate, peer)
    headers = body["manifest"]["transport"]["headers"]
    if mutation == "raw_secret":
        headers["Authorization"] = "Bearer " + SECRET
    elif mutation == "duplicate":
        headers["authorization"] = headers["Authorization"]
    elif mutation == "newline":
        headers["X-Label"] = "a\r\nb"
    elif mutation == "reserved":
        headers["Host"] = "elsewhere.invalid"
    elif mutation == "disabled":
        body["manifest"]["enabled"] = False
    else:
        body["manifest"]["user_credentials"] = [{"id": "personal", "name": "Personal", "injection": {"name": "Authorization"}}]
    result = run(gate, body)
    assert not result["ok"] and not result["network_attempted"], result
    assert not peer["requests"]


def test_wrong_credential_scope_cannot_be_used_to_test_other_targets(gate, peer):
    body = arguments(gate, peer)
    body["manifest"]["id"] = "another-peer"
    result = run(gate, body)
    assert result["code"] == "credential_scope_denied" and not peer["requests"]


def test_revoked_permission_is_not_restored_by_unsaved_test(gate, peer):
    body = arguments(gate, peer, endpoint="http://10.23.45.67:8080/mcp")
    trust = gate["service"].configs.http_trust_store
    trust.update("probe-peer", McpHttpTrustUpdate(origins=[], expected_revision=0, confirmed=True), actor_id=gate["context"].actor_id)
    before = trust.get("probe-peer")
    result = run(gate, body)
    assert result["code"] == "http_trust_revoked" and not result["network_attempted"]
    assert trust.get("probe-peer") == before


def test_rotation_between_handshake_and_discovery_aborts(gate, peer, monkeypatch):
    body = arguments(gate, peer)
    original = StreamableHttpMcpClient.list_tools
    def rotate(client):
        store = gate["service"].credentials
        revision = store.get_credential("probe-key").updated_at
        store.update_credential("probe-key", expected_revision=revision, value="Synthetic-rotated")
        return original(client)
    monkeypatch.setattr(StreamableHttpMcpClient, "list_tools", rotate)
    result = run(gate, body)
    assert result["code"] == "credential_changed"
    assert len(peer["requests"]) == 1


def test_test_requires_explicit_action_and_current_management_authority(gate, peer):
    body = arguments(gate, peer)
    with pytest.raises(ToolExecutionError, match="Explicitly"):
        run(gate, {**body, "confirmed": False})
    denied = replace(gate["context"], permissions=("operations.manage",))
    with pytest.raises(ToolExecutionError):
        gate["service"].http_test(body, denied)
    assert not peer["requests"]


def test_console_csrf_ticket_and_no_store(gate, peer):
    body = arguments(gate, peer)
    client = gate["client"]
    client.headers["Origin"] = "http://testserver"
    assert client.post("/v1/mcp/external-configs/test", json=body).status_code == 403
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    ticket = client.post("/v1/mcp/external-configs/csrf", params={"action": "test", "request_digest": digest})
    assert ticket.status_code == 200, ticket.text
    headers = {"X-CSRF-Token": ticket.json()["csrf"]}
    response = client.post("/v1/mcp/external-configs/test", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["ok"], response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/v1/mcp/external-configs/test", json=body, headers=headers).status_code == 403


def test_lan_ticket_is_same_origin_single_use_and_bound_to_the_entire_body(gate, peer):
    body = arguments(gate, peer)
    client = gate["client"]
    path = "/v1/mcp/external-configs/test/csrf"
    assert client.post(path, json=body).status_code == 403
    assert client.post(path, json=body, headers={"Origin": "https://elsewhere.invalid"}).status_code == 403
    client.headers["Origin"] = "http://testserver"
    ticket = client.post(path, json=body)
    assert ticket.status_code == 200 and ticket.headers["cache-control"] == "no-store"
    denied = client.post("/v1/mcp/external-configs/test", json={**body, "timeout_seconds": 2},
                         headers={"X-CSRF-Token": ticket.json()["csrf"]})
    assert denied.status_code == 403 and not peer["requests"]
    fresh = client.post(path, json=body)
    headers = {"X-CSRF-Token": fresh.json()["csrf"]}
    response = client.post("/v1/mcp/external-configs/test", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["ok"], response.text
    count = len(peer["requests"])
    assert client.post("/v1/mcp/external-configs/test", json=body, headers=headers).status_code == 403
    assert len(peer["requests"]) == count


def test_saved_draft_requires_original_digest_and_never_changes_runtime(gate, peer):
    body = arguments(gate, peer)
    client = gate["client"]
    saved = client.post("/v1/mcp/configs", json={"manifest": body["manifest"], "apply": False, "start": False})
    assert saved.status_code in {200, 201}, saved.text
    record = saved.json()["config"]
    body.update(existing_server_id="probe-peer", expected_config_digest=record["digest"])
    body["manifest"]["name"] = "Unsaved name remains a draft"
    result = run(gate, body)
    assert result["ok"], result
    assert gate["service"].configs.get_config("probe-peer").digest == record["digest"]
    assert not gate["calls"]
    peer["requests"].clear()
    body["expected_config_digest"] = "0" * 64
    assert run(gate, body)["code"] == "config_changed"
    assert not peer["requests"]


def test_creation_test_cannot_impersonate_an_existing_id(gate, peer):
    body = arguments(gate, peer)
    gate["service"].configs.save_config(body["manifest"])
    assert run(gate, body)["code"] == "config_changed"
    assert not peer["requests"]


def test_rotation_does_not_leave_a_busy_slot_and_concurrency_is_bounded(gate, peer):
    body = arguments(gate, peer)
    semaphore = gate["service"]._connection_tests
    assert semaphore.acquire(blocking=False) and semaphore.acquire(blocking=False)
    try:
        with pytest.raises(ToolExecutionError, match="already running"):
            run(gate, body)
        assert not peer["requests"]
    finally:
        semaphore.release()
        semaphore.release()
    assert run(gate, body)["ok"]


@pytest.mark.parametrize("failure", ["tls", "timeout"])
def test_transport_failures_have_safe_categories(gate, peer, monkeypatch, failure):
    import ssl
    import urllib.error
    import urllib.request
    body = arguments(gate, peer)
    def fail(*args, **kwargs):
        if failure == "tls":
            raise urllib.error.URLError(ssl.SSLCertVerificationError(SECRET))
        raise TimeoutError(SECRET)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fail)
    result = run(gate, body)
    assert result["code"] == ("tls_failed" if failure == "tls" else "timeout"), result
    assert SECRET not in json.dumps(result)
    assert not peer["requests"]


def test_connection_tool_is_registered_as_network_action_not_business_write(gate):
    tool = gate["app"].state.registry.get_definition("gate_http_mcp_test")
    assert tool.permission == "write"
    assert "confirmed" in tool.input_schema["required"]


def test_real_management_oauth_mcp_entry_runs_ephemeral_diagnostic(gate, browser, peer, caplog):
    from test_builtin_oauth import REDIRECT
    from test_oauth_management_e2e import call, enable_management, output, tokens
    body = arguments(gate, peer)
    enable_management(gate, browser)
    created = gate["app"].state.oauth_server.create_client("Synthetic connection test", [REDIRECT],
        ["operations.manage", "tools.invoke"], resources=["management"])
    bearer = tokens(browser, created, tools=["gate_http_mcp_test"],
                    targets={"probe-peer": ["test"]})["access_token"]
    result = output(call(browser, bearer, "gate_http_mcp_test", body))
    assert result["ok"] and result["tool_count"] == 1, result
    assert not gate["service"].configs.list_configs().configs
    assert "tools/call" not in [request[0] for request in peer["requests"]]
    assert SECRET not in json.dumps(result) and SECRET not in caplog.text

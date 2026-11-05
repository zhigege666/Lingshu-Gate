"""Authenticated late-response recovery through the real runtime and adapters."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from threading import Thread
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.request_recovery import RequestRecoveryCapacityError, RequestRecoveryStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.mcp_request_outcome import McpRequestTimeout
from lingshu_gate.interfaces.control_api.catalog_routes import register_catalog_routes
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.mcp_stdio_client import McpProtocolError
from lingshu_gate.models import ToolDefinition
from lingshu_gate.protocol.tool_namespace import public_tool_name
from lingshu_gate.registry import ToolExecutionError, ToolRegistry
from lingshu_gate.telemetry import exception_outcome
from lingshu_gate.tool_catalog import CatalogInvoke, ToolCatalog, schema_revision
from lingshu_gate.transports.http import build_protocol_request

from test_mcp_request_outcomes import _client


@pytest.fixture
def recovery(tmp_path, monkeypatch, request):
    client = _client(tmp_path)
    request.addfinalizer(client.stop)
    database = SQLiteDatabase("", client.settings.data_dir)
    access = AccessControlStore(database)
    registry = ToolRegistry()
    runtime = McpRuntimeManager(client.settings, registry)
    server = McpServerRuntime(manifest=client.manifest, client=client, state=McpServerState.RUNNING)
    runtime._servers[client.manifest.id] = server
    access.attach_mcp_runtime(runtime)
    principal = AuthPrincipal(id="alice", username="alice", role="operator", roles=("operator",),
        auth_type="session", session_id="session-one", permissions=("tools.read", "tools.invoke"))
    database.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) "
                     "VALUES('alice','alice','unused','now','now')")
    definition = ToolDefinition(id="mcp.request-outcome-peer.delayed", name="Delayed", description="Controlled peer", source="mcp",
        input_schema={"type": "object"}, metadata={"server_id": client.manifest.id, "original_tool_name": "delayed"})
    registry.register(definition, lambda _: pytest.fail("Runtime should own MCP dispatch"))
    catalog = ToolCatalog(registry, access)
    catalog.synchronize()
    database.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published',required_access='read',access_policy_source='local_override'")
    access.save_grant(subject_type="user", subject_id="alice", server_id=client.manifest.id,
                      permission_type_code="read", created_by="alice")
    monkeypatch.setattr(client, "call_tool", lambda name, arguments: client.request(
        "tools/call", {"name": name, "arguments": arguments}, timeout=0.03)["result"])
    client.start()
    invocation = CatalogInvoke(tool_ref=definition.id, schema_revision=schema_revision(definition), arguments={})
    response = catalog.invoke(principal, invocation)
    assert not response.ok
    details = response.output["error"]["details"]
    assert details["recovery_supported"] is True
    env = SimpleNamespace(client=client, runtime=runtime, server=server, database=database, access=access,
        registry=registry, catalog=catalog, principal=principal, definition=definition,
        handle=details["request_handle"], response=response, root=tmp_path)
    yield env


def status(env, **arguments):
    return env.catalog.call("gate_request_status", {"request_handle": env.handle, **arguments}, env.principal).output


def test_late_reply_can_be_paged_without_waiting_on_execution_lock_or_replaying(recovery):
    env = recovery
    error = env.response.output["error"]
    assert error["code"] == "mcp_request_timeout" and error["retryable"] is False
    assert error["details"]["execution_state"] == "unknown"
    assert error["details"]["execution_terminated"] is False
    assert error["details"]["query_path"] == "/v1/catalog/requests/status"
    assert "query_tool" not in error["details"]
    results = []
    with env.server.lock:
        thread = Thread(target=lambda: results.append(status(env)), daemon=True)
        thread.start()
        thread.join(timeout=1)
        responsive = not thread.is_alive()
    thread.join(timeout=2)
    assert responsive and results[0]["request_state"] == "waiting"
    (env.root / "release").write_text("release")
    deadline = time.monotonic() + 3
    while (page := status(env, limit=7))["request_state"] == "waiting" and time.monotonic() < deadline:
        time.sleep(0.005)
    assert page["request_state"] == "completed"
    pieces = [page["response_json"]]
    while page["has_more"]:
        page = status(env, offset=page["next_offset"], limit=7)
        pieces.append(page["response_json"])
    original = json.loads("".join(pieces))
    assert original["result"]["structuredContent"]["exit_code"] == 0
    # An arbitrary MCP result does not prove a remote process has terminated.
    assert page["exit_code"] is None and page["execution_terminated"] is False
    assert (env.root / "received-methods").read_text().splitlines().count("tools/call") == 1
    audit = env.database.query_one("SELECT outcome FROM invocation_audits ORDER BY rowid DESC LIMIT 1")
    assert audit[0] == "error"


@pytest.mark.parametrize("change", ["user", "credential", "revocation", "schema", "managed", "refresh", "connection"])
def test_receipt_is_unavailable_after_identity_authority_target_or_connection_changes(recovery, change):
    env = recovery
    if change == "user":
        env.principal = replace(env.principal, id="other")
    elif change == "credential":
        env.principal = replace(env.principal, session_id="different-session")
    elif change == "revocation":
        env.database.execute("DELETE FROM mcp_resource_grants")
    elif change == "schema":
        env.registry.update_definition(env.definition.model_copy(update={"description": "changed"}))
    elif change == "managed":
        env.access.business_credentials = SimpleNamespace(store=SimpleNamespace(is_managed_server=lambda _: True))
    elif change == "refresh":
        env.access.refresh_principal = lambda actor: replace(actor, status="disabled")
    else:
        # Even A -> B -> A on the same runtime cannot resurrect an old receipt.
        env.server.client = None
        env.server.client = env.client
    with pytest.raises(ToolExecutionError) as caught:
        status(env)
    assert caught.value.code == "request_outcome_unavailable"


def test_reader_rechecks_authority_after_copying_response(recovery):
    env = recovery
    def revoke_during_read():
        env.database.execute("DELETE FROM mcp_resource_grants")
        return {"state": "completed", "response": {"result": {"private": "must-not-return"}}}
    env.handle = env.access.request_recovery.retain(env.principal, env.definition.id,
        schema_revision(env.definition), revoke_during_read)
    with pytest.raises(ToolExecutionError, match="unavailable"):
        status(env)


def test_recovery_unavailable_for_calls_without_complete_provenance(recovery):
    env = recovery
    for grouped, managed, actor in [
        (True, False, env.principal), (False, True, env.principal),
        (False, False, replace(env.principal, auth_type="oauth", oauth_builtin=False)),
    ]:
        env.access.business_credentials = SimpleNamespace(store=SimpleNamespace(is_managed_server=lambda _: managed))
        timeout = McpRequestTimeout(method="tools/call", timeout_seconds=1, outcome_reader=lambda: None)
        normalized = env.access._recoverable_timeout(timeout, actor, env.definition, grouped=grouped)
        assert normalized.details["recovery_supported"] is False
        assert "query_tool" not in normalized.details


def test_catalog_mcp_and_rest_expose_status_and_uniform_unavailable(recovery):
    env = recovery
    app = FastAPI()
    def require(request: Request) -> AuthPrincipal:
        return env.principal
    register_catalog_routes(app, catalog=env.catalog, require_authenticated=require)
    register_mcp_gateway_route(app, env.client.settings, env.registry, env.access, require, catalog=env.catalog)
    web = TestClient(app)
    request_body = {"request_handle": env.handle}
    assert web.post("/v1/catalog/requests/status", json=request_body).json()["request_state"] == "waiting"
    params, headers = build_protocol_request("tools/call", {"name": "gate_request_status", "arguments": request_body},
                                            client_name="recovery-test", client_version="1.0")
    response = web.post("/mcp?tool_mode=on_demand", headers=headers,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["request_state"] == "waiting"
    for mode in ("on_demand", "direct"):
        invocation = ({"tool_ref": env.definition.id, "schema_revision": schema_revision(env.definition), "arguments": {}}
                      if mode == "on_demand" else {})
        name = "gate_tool_invoke" if mode == "on_demand" else public_tool_name(env.definition)
        params, headers = build_protocol_request("tools/call", {"name": name, "arguments": invocation},
                                                client_name="recovery-test", client_version="1.0")
        failed = web.post("/mcp?tool_mode=" + mode, headers=headers,
                          json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params}).json()
        details = failed["result"]["structuredContent"]["error"]["details"]
        assert details["query_path"] == "/v1/catalog/requests/status"
        assert ("query_tool" in details) is (mode == "on_demand")
    env.principal = replace(env.principal, session_id="another-session")
    denied = web.post("/v1/catalog/requests/status", json=request_body)
    absent = web.post("/v1/catalog/requests/status", json={"request_handle": "x" * 43})
    assert denied.status_code == absent.status_code == 404
    assert denied.json() == absent.json()
    assert web.post("/v1/catalog/requests/status", json={**request_body, "limit": 65_537}).status_code == 400


def test_receipt_capacity_expiry_and_identity_do_not_invoke_reader():
    now = [100.0]
    store = RequestRecoveryStore(clock=lambda: now[0])
    actor = AuthPrincipal("alice", "alice", "operator", auth_type="token", token_id="one")
    def reader():
        pytest.fail("Cache lookup must not invoke a reader")
    handles = [store.retain(actor, "tool", "revision", reader, ttl_seconds=600) for _ in range(16)]
    with pytest.raises(RequestRecoveryCapacityError):
        store.retain(actor, "tool", "revision", reader)
    assert store.get(handles[0], replace(actor, token_id="two")) is None
    assert store.get(handles[0], actor).expires_at == 400.0
    now[0] = 400.0
    assert store.get(handles[0], actor) is None
    for i in range(128):
        store.retain(replace(actor, id=str(i)), "tool", "revision", reader)
    with pytest.raises(RequestRecoveryCapacityError):
        store.retain(replace(actor, id="extra"), "tool", "revision", reader)


def test_registry_preserves_structured_http_timeout_and_telemetry_without_wrapper_secrets():
    registry = ToolRegistry()
    def invoke(_):
        raise McpProtocolError("private transport detail") from McpRequestTimeout(
            method="tools/call", timeout_seconds=3, transport="streamable_http", recovery_supported=False,
            dispatch_state="unknown", phase="connect_or_send")
    registry.register(ToolDefinition(id="test.timeout", name="Timeout", description="test"), invoke)
    response = registry.invoke("test.timeout", {})
    assert not response.ok
    assert response.output["error"]["code"] == "mcp_request_timeout"
    assert response.output["error"]["details"]["dispatch_state"] == "unknown"
    assert response.output["error"]["details"]["recovery_supported"] is False
    assert "private transport detail" not in response.model_dump_json()
    assert exception_outcome(ToolExecutionError("mcp_request_timeout", "safe")) == "timeout"

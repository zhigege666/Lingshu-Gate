"""Synthetic external-management contract: no external sockets or real credentials."""
from __future__ import annotations

import json
import hashlib
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext
from lingshu_gate.transports.http import build_protocol_request

PASSWORD = "Synthetic-External-123!"


def context(principal) -> ToolInvocationContext:
    return ToolInvocationContext(actor_id=principal.id, username=principal.username, auth_type=principal.auth_type,
        token_id=principal.token_id, correlation_id="synthetic-external-test", roles=principal.roles,
        permissions=principal.permissions, scopes=principal.scopes, delegated_scopes=principal.delegated_scopes, session_id=principal.session_id)


@pytest.fixture
def gate(tmp_path, monkeypatch):
    import os
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LINGSHU_GATE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LINGSHU_GATE_CONFIG_DIR", str(tmp_path / "mcp.d"))
    monkeypatch.setenv("LINGSHU_GATE_DB_URL", f"sqlite:///{tmp_path / 'gate.db'}")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("LINGSHU_GATE_AUTH_ENABLED", "true")
    monkeypatch.setenv("LINGSHU_GATE_MCP_ALLOWED_ORIGINS", "http://testserver")
    from lingshu_gate.main import create_app
    app = create_app()
    auth = app.state.auth_store
    auth.change_password(str(auth.list_users()[0]["id"]), PASSWORD)
    principal, cookie, _ = auth.login(username="synthetic-admin", password=PASSWORD)
    client = TestClient(app)
    client.cookies.set(auth.cookie_name, cookie)
    calls = []
    mode = {"failure": None, "wait": None, "discover_count": 0, "schema": {"type": "object"}}

    class FakeHttp(StreamableHttpMcpClient):
        def start(self):
            self._check_operation()
            self._resolve_headers()
            calls.append(("connect", self.manifest.id))
            if mode["failure"]:
                raise mode["failure"]
            self.initialized = True

        def list_tools(self):
            calls.append(("discover", self.manifest.id))
            mode["discover_count"] += 1
            if mode["wait"] is not None:
                started, release = mode["wait"]
                started.set()
                assert release.wait(3), "Synthetic peer release timed out"
            self._check_operation()
            return [{"name": "synthetic_read", "description": "Synthetic only",
                     "inputSchema": mode["schema"], "annotations": {"readOnlyHint": True}}]

        def stop(self):
            calls.append(("disconnect", self.manifest.id))
            self.initialized = False

    monkeypatch.setattr("lingshu_gate.mcp_runtime.StreamableHttpMcpClient", FakeHttp)
    monkeypatch.setattr("lingshu_gate.application.external_mcp_configuration.StreamableHttpMcpClient", FakeHttp)
    yield {"app": app, "auth": auth, "client": client, "principal": principal, "context": context(principal),
           "service": app.state.external_mcp_configuration_service, "calls": calls, "mode": mode}
    app.state.external_mcp_configuration_service.shutdown()
    app.state.mcp_runtime.shutdown()
    client.close()


def manifest(server_id="synthetic-external", endpoint="https://mcp.example.test/mcp"):
    return {"id": server_id, "launch": {"type": "external"}, "transport": {"type": "streamable_http", "endpoint": endpoint}}


def planned(gate, **options):
    return gate["service"].plan({"mode": "create", "manifest": manifest(), **options}, gate["context"])


def apply_arguments(plan, key="synthetic-apply-1"):
    return {"plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"], "connect": plan["connect"],
            "refresh_tools": plan["refresh_tools"], "idempotency_key": key, "confirmed": True}


def session_headers(gate, body, *, action="plan", operation_id=None):
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    query = {"action": action, "request_digest": digest}
    if operation_id is not None:
        query["operation_id"] = operation_id
    response = gate["client"].post("/v1/mcp/external-configs/csrf", params=query, headers={"Origin": "http://testserver"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf"]}


def wait(gate, operation_id):
    cutoff = time.monotonic() + 5
    while time.monotonic() < cutoff:
        result = gate["service"].status({"operation_id": operation_id}, gate["context"])
        if result["terminal"]:
            return result
        time.sleep(.01)
    pytest.fail("Synthetic external operation did not terminate")


def generic_call(client, entry, tool_id, arguments, *, origin=None, authorization=None):
    headers = {"Origin": origin} if origin else {}
    if authorization:
        headers["Authorization"] = authorization
    if entry == "mcp":
        params, protocol_headers = build_protocol_request("tools/call", {"name": tool_id, "arguments": arguments},
            client_name="Synthetic", client_version="1", protocol_version=MCP_PROTOCOL_VERSION)
        return client.post("/mcp", headers={**protocol_headers, **headers},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    body = {"arguments": arguments, **({"tool_id": tool_id} if entry == "invoke" else {})}
    return client.post("/v1/invoke" if entry == "invoke" else f"/v1/tools/{tool_id}/invoke", headers=headers, json=body)


@pytest.mark.parametrize("entry", ["tool", "invoke", "mcp"])
@pytest.mark.parametrize("origin", [None, "https://foreign.example.test", "http://testserver"])
@pytest.mark.parametrize("action", ["plan", "apply", "status", "cancel"])
def test_console_cookie_cannot_invoke_configuration_tools_through_generic_entries(gate, entry, origin, action):
    # Prepare valid actor-owned arguments: rejection must precede the service,
    # rather than depend on an invalid plan, missing target or terminal race.
    plan = planned(gate)
    operation = gate["service"].apply(apply_arguments(plan), gate["context"])
    wait(gate, operation["operation_id"])
    another_plan = planned(gate, manifest=manifest("synthetic-other-target"))
    arguments = {
        "plan": {"mode": "create", "manifest": manifest("synthetic-other-target")},
        "apply": apply_arguments(another_plan, "synthetic-generic-apply"),
        "status": {"operation_id": operation["operation_id"]},
        "cancel": {"operation_id": operation["operation_id"], "idempotency_key": "synthetic-generic-cancel", "confirmed": True},
    }[action]
    database = gate["service"].database
    def journal_counts():
        return tuple(len(database.query_all(f"SELECT id FROM {table}")) for table in
                     ("external_mcp_config_plans", "external_mcp_config_operations", "mcp_idempotent_operations"))
    before, calls = journal_counts(), list(gate["calls"])
    response = generic_call(gate["client"], entry, "gate_mcp_config_" + action, arguments, origin=origin)
    if entry == "mcp" and origin == "https://foreign.example.test":
        assert response.status_code == 403
    else:
        assert response.status_code == 200
        result = response.json().get("result", {}) if entry == "mcp" else response.json()
        assert result.get("isError", False) if entry == "mcp" else not result["ok"]
        assert "external_config_session_entry_denied" in json.dumps(result)
    assert journal_counts() == before and gate["calls"] == calls
    assert "synthetic-other-target" not in {item.id for item in gate["app"].state.mcp_config_store.list_configs().configs}


def generic_output(response, entry):
    assert response.status_code == 200
    result = response.json()["result"] if entry == "mcp" else response.json()
    if entry == "mcp":
        assert not result.get("isError", False), result
        return result["structuredContent"]
    assert result["ok"], result
    return result["output"]


@pytest.mark.parametrize("entry", ["tool", "invoke", "mcp"])
def test_api_token_can_use_all_configuration_tools_through_generic_entries(gate, entry):
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic management",
        scopes=["tools.read", "tools.invoke", "operations.manage"])
    with TestClient(gate["app"]) as client:
        def invoke(action, arguments):
            return generic_output(generic_call(client, entry, "gate_mcp_config_" + action,
                arguments, authorization="Bearer " + token["token"]), entry)
        plan = invoke("plan", {"mode": "create", "manifest": manifest()})
        operation = invoke("apply", apply_arguments(plan))
        cutoff = time.monotonic() + 5
        while time.monotonic() < cutoff:
            result = invoke("status", {"operation_id": operation["operation_id"]})
            if result["terminal"]:
                break
            time.sleep(.01)
        assert result["terminal"] and result["status"] == "success" and result["config_applied"]
        cancelled = invoke("cancel", {"operation_id": operation["operation_id"],
            "confirmed": True, "idempotency_key": "synthetic-token-cancel"})
        assert cancelled["target_operation_id"] == operation["operation_id"]
        assert cancelled["status"] == "already_terminal"


@pytest.mark.parametrize("entry", ["tool", "invoke", "mcp"])
def test_console_cookie_can_still_use_ordinary_tools_through_generic_entries(gate, entry):
    from lingshu_gate.models import ToolDefinition
    registry = gate["app"].state.registry
    tool = ToolDefinition(id="gate_synthetic_echo", name="Synthetic echo", source="builtin",
        input_schema={"type": "object"}, description="Synthetic only")
    registry.register(tool, lambda arguments: {"echo": arguments["message"]})
    gate["service"].access.synchronize_tools(registry.list_definitions())
    result = generic_output(generic_call(gate["client"], entry, tool.id, {"message": "synthetic"},
        origin="http://testserver"), entry)
    assert result == {"echo": "synthetic"}


def test_offline_plan_and_save_do_not_connect_or_start_remote(gate):
    plan = planned(gate)
    assert plan["validation"]["ok"] and plan["probe"]["network_contacted"] is False
    assert plan["manifest"]["enabled"] is True and plan["manifest"]["auto_start"] is False
    assert not gate["calls"] and not gate["app"].state.mcp_config_store.list_configs().configs
    result = wait(gate, gate["service"].apply(apply_arguments(plan), gate["context"])["operation_id"])
    assert result["status"] == "success" and result["config_applied"] is True
    assert result["connection_state"] == "not_requested" and not result["remote_process_started"]
    assert not gate["calls"]


def test_connect_discover_requires_review_and_idempotent_replay_does_not_create_again(gate):
    plan = planned(gate, connect=True, refresh_tools=True)
    args = apply_arguments(plan)
    operation = gate["service"].apply(args, gate["context"])
    result = wait(gate, operation["operation_id"])
    assert result["status"] == "success" and result["config_applied"] is True
    assert result["connection_state"] == "connected" and result["discovery_state"] == "succeeded"
    assert result["classification_state"] == "needs_review" and result["counts"]["needs_review"] == 1
    assert result["counts"]["new"] == 1 and len(result["tool_snapshot_digest"]) == 64
    assert sum(action == "discover" for action, _ in gate["calls"]) == 1
    assert result["effective_permissions_expanded"] is False and result["remote_process_started"] is False
    before = list(gate["calls"])
    replay = gate["service"].apply(args, gate["context"])
    assert replay["idempotent_replay"] is True and replay["operation_id"] == operation["operation_id"]
    assert gate["calls"] == before
    assert len(gate["app"].state.mcp_config_store.list_configs().configs) == 1
    with pytest.raises(ToolExecutionError, match="expired or already consumed"):
        gate["service"].apply(apply_arguments(plan, "synthetic-second-key"), gate["context"])


@pytest.mark.parametrize("mutation", ["command", "path", "inline_secret", "permissions", "unknown"])
def test_external_entry_rejects_commands_paths_inline_secrets_and_permission_changes(gate, mutation, caplog):
    data = manifest()
    if mutation == "command":
        data["launch"]["command"] = "synthetic-command"
    elif mutation == "path":
        data["launch"]["cwd"] = "/synthetic/path"
    elif mutation == "inline_secret":
        data["transport"]["headers"] = {"Authorization": "Bearer Synthetic-Secret-Value"}
    elif mutation == "permissions":
        data["permissions"] = {"default": "write"}
    else:
        data["unsupported"] = "Synthetic-Secret-Value"
    result = gate["app"].state.registry.invoke("gate_mcp_config_plan", {"mode": "create", "manifest": data}, context=gate["context"])
    assert not result.ok and not gate["calls"]
    assert "Synthetic-Secret-Value" not in json.dumps(result.model_dump()) + caplog.text


def test_private_http_needs_separate_trust_and_no_probe_is_silently_run(gate):
    with pytest.raises(ToolExecutionError):
        planned(gate, manifest=manifest(endpoint="http://10.23.45.67:8080/mcp"))
    assert not gate["calls"]
    assert not gate["service"].database.query_all("SELECT * FROM gate_mcp_http_trust")
    with pytest.raises(ToolExecutionError, match="Confirm"):
        planned(gate, probe=True)
    assert not gate["calls"]
    plan = planned(gate, probe=True, probe_confirmed=True)
    assert plan["probe"]["status"] == "reachable" and plan["probe"]["registry_changed"] is False
    assert not gate["app"].state.mcp_runtime.has_server(plan["server_id"])


def test_managed_reference_only_and_revision_drift_blocks_before_saving(gate, caplog):
    store = gate["app"].state.credential_store
    store.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Secret-Value")
    data = manifest()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-binding}"}
    plan = planned(gate, manifest=data, connect=True)
    assert "Synthetic-Secret-Value" not in json.dumps(plan)
    store.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Changed-Secret")
    result = wait(gate, gate["service"].apply(apply_arguments(plan), gate["context"])["operation_id"])
    assert result["error_code"] == "external_config_credential_changed" and result["config_applied"] is False
    assert not gate["calls"]
    assert "Synthetic-Secret-Value" not in caplog.text + json.dumps(result)


@pytest.mark.parametrize("auth_type", ["oauth", "disabled"])
def test_oauth_and_disabled_contexts_are_not_management_authority(gate, auth_type):
    with pytest.raises(ToolExecutionError) as error:
        gate["service"].plan({"mode": "create", "manifest": manifest()}, replace(gate["context"], auth_type=auth_type))
    assert error.value.code == "external_config_admin_required"


def test_non_admin_and_connection_scope_limits_are_enforced(gate):
    user = gate["auth"].create_user(username="synthetic-operator", password=PASSWORD, role="operator")
    principal, _, _ = gate["auth"].login(username=user["username"], password=PASSWORD)
    with pytest.raises(ToolExecutionError) as error:
        gate["service"].plan({"mode": "create", "manifest": manifest()}, context(principal))
    assert error.value.code == "external_config_admin_required"
    with pytest.raises(ToolExecutionError):
        gate["service"].plan({"mode": "create", "manifest": manifest()}, replace(gate["context"], delegated_scopes=("tools.read",)))


def test_rest_session_api_token_and_mcp_token_share_the_same_plan_contract(gate):
    client, auth, principal = gate["client"], gate["auth"], gate["principal"]
    body = {"mode": "create", "manifest": manifest()}
    plan = client.post("/v1/mcp/external-configs/plan", json=body, headers=session_headers(gate, body))
    assert plan.status_code == 200
    forbidden = client.post("/v1/mcp/external-configs/apply", json=apply_arguments(plan.json()), headers={"Origin": "https://other.example.test"})
    assert forbidden.status_code == 403
    limited = auth.create_api_token(principal=principal, name="Synthetic read only", scopes=["tools.read"])
    full = auth.create_api_token(principal=principal, name="Synthetic management", scopes=["tools.read", "tools.invoke", "operations.manage"])
    with TestClient(gate["app"]) as token_client:
        denied = token_client.post("/v1/mcp/external-configs/plan", json={"mode": "create", "manifest": manifest()},
                                  headers={"Authorization": "Bearer " + limited["token"]})
        assert denied.status_code == 403
        token_rest = token_client.post("/v1/mcp/external-configs/plan", json=body,
            headers={"Authorization": "Bearer " + full["token"], "Origin": "https://other.example.test", "Sec-Fetch-Site": "cross-site"})
        assert token_rest.status_code == 200 and token_rest.json()["manifest_digest"] == plan.json()["manifest_digest"]
        params, headers = build_protocol_request("tools/call", {"name": "gate_mcp_config_plan", "arguments": {"mode": "create", "manifest": manifest()}},
                                                client_name="Synthetic", client_version="1", protocol_version=MCP_PROTOCOL_VERSION)
        result = token_client.post("/mcp", headers={**headers, "Authorization": "Bearer " + full["token"]},
                                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
        assert result.status_code == 200 and not result.json()["result"].get("isError", False)
        token_plan = result.json()["result"]["structuredContent"]
        assert token_plan["manifest_digest"] == plan.json()["manifest_digest"]
        # A session cannot consume a token-bound plan even for the same user.
        with pytest.raises(ToolExecutionError):
            gate["service"].apply(apply_arguments(token_plan), gate["context"])


def test_old_digest_and_changed_target_reject_update_and_create(gate):
    initial = planned(gate)
    store = gate["app"].state.mcp_config_store
    store.save_config(manifest())
    conflict = wait(gate, gate["service"].apply(apply_arguments(initial), gate["context"])["operation_id"])
    assert conflict["config_applied"] is False and conflict["error_code"] == "config_digest_conflict"
    old = store.get_config("synthetic-external").digest
    updated = manifest()
    updated["name"] = "Synthetic updated"
    plan = gate["service"].plan({"mode": "update", "manifest": updated, "expected_config_digest": old}, gate["context"])
    store.save_config({**manifest(), "name": "Synthetic concurrent edit"}, overwrite=True)
    result = wait(gate, gate["service"].apply(apply_arguments(plan, "synthetic-update-key"), gate["context"])["operation_id"])
    assert result["error_code"] == "config_digest_conflict"
    assert store.get_config("synthetic-external").manifest["name"] == "Synthetic concurrent edit"


@pytest.mark.parametrize("failure", [RuntimeError("Synthetic failed peer"), TimeoutError("Synthetic timeout")])
def test_saved_configuration_is_retained_when_connect_fails_or_times_out(gate, failure):
    gate["mode"]["failure"] = failure
    plan = planned(gate, connect=True)
    operation = gate["service"].apply(apply_arguments(plan), gate["context"])
    result = wait(gate, operation["operation_id"])
    assert result["config_applied"] is True and result["connection_state"] in {"failed", "timed_out"}
    assert result["status"] in {"partial", "timed_out"} and result["operation_id"] == operation["operation_id"]
    assert gate["app"].state.mcp_config_store.get_config(plan["server_id"]).digest == result["config_digest"]
    assert len(gate["app"].state.mcp_config_store.list_configs().configs) == 1


def test_cancel_pending_discovery_and_retry_keep_one_saved_configuration(gate):
    started, release = threading.Event(), threading.Event()
    gate["mode"]["wait"] = started, release
    plan = planned(gate, connect=True, refresh_tools=True)
    args = apply_arguments(plan)
    operation = gate["service"].apply(args, gate["context"])
    assert started.wait(2)
    replay = gate["service"].apply(args, gate["context"])
    assert replay["operation_id"] == operation["operation_id"] and replay["idempotent_replay"]
    cancelled = gate["service"].cancel({"operation_id": operation["operation_id"], "idempotency_key": "synthetic-cancel-key", "confirmed": True}, gate["context"])
    assert cancelled["status"] == "cancel_requested"
    release.set()
    result = wait(gate, operation["operation_id"])
    assert result["status"] == "cancelled" and result["config_applied"] is True
    assert result["connection_state"] == "disconnected"
    assert len(gate["app"].state.mcp_config_store.list_configs().configs) == 1
    assert sum(action == "connect" for action, _ in gate["calls"]) == 1


def test_expired_plan_and_changed_action_do_not_apply(gate):
    plan = planned(gate)
    gate["service"].database.execute("UPDATE external_mcp_config_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (plan["plan_id"],))
    with pytest.raises(ToolExecutionError):
        gate["service"].apply(apply_arguments(plan), gate["context"])
    plan = planned(gate)
    args = {**apply_arguments(plan, "synthetic-other-plan"), "connect": True}
    with pytest.raises(ToolExecutionError):
        gate["service"].apply(args, gate["context"])
    assert not gate["app"].state.mcp_config_store.list_configs().configs


@pytest.mark.parametrize("change", ["logout", "session_expiry", "role", "permission", "password_change", "token_revocation", "token_scope"])
def test_queued_operation_rechecks_live_management_authority_before_save(gate, change):
    auth, service = gate["auth"], gate["service"]
    ctx = gate["context"]
    token = None
    if change.startswith("token"):
        token = auth.create_api_token(principal=gate["principal"], name="Synthetic queued manager",
                                     scopes=["operations.manage", "tools.invoke", "tools.read"])
        ctx = context(auth._principal_from_api_token(token["token"]))
    plan = service.plan({"mode": "create", "manifest": manifest(), "connect": True}, ctx)
    with service.configs.mutation_lock:
        op = service.apply(apply_arguments(plan), ctx)
        worker = service._threads[op["operation_id"]]
        if change == "logout":
            auth.logout(gate["client"].cookies.get(auth.cookie_name))
        elif change == "session_expiry":
            service.database.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (ctx.session_id,))
        elif change == "role":
            service.access.set_user_roles(ctx.actor_id, ["operator"])
        elif change == "permission":
            service.database.execute("DELETE FROM role_permissions WHERE role_id=(SELECT id FROM roles WHERE code='admin') "
                                     "AND permission_id=(SELECT id FROM control_permissions WHERE code='tools.invoke')")
        elif change == "password_change":
            service.database.execute("UPDATE users SET must_change_password=1 WHERE id=?", (ctx.actor_id,))
        elif change == "token_revocation":
            auth.revoke_api_token(token["id"], user_id=ctx.actor_id)
        else:
            service.database.execute("UPDATE api_tokens SET scopes_json='[\"tools.read\"]' WHERE id=?", (ctx.token_id,))
    worker.join(3)
    assert not worker.is_alive()
    if change == "role":
        service.access.set_user_roles(ctx.actor_id, ["admin"])
    if change == "password_change":
        auth.change_password(ctx.actor_id, PASSWORD)
    principal, _, _ = auth.login(username=gate["principal"].username, password=PASSWORD)
    result = service.status({"operation_id": op["operation_id"]}, context(principal))
    assert result["status"] == "failed" and result["config_applied"] is False
    assert not service.configs.list_configs().configs and not gate["calls"]


def test_waiting_runtime_lock_rechecks_logout_before_loading_or_connecting(gate, monkeypatch):
    service, runtime = gate["service"], gate["app"].state.mcp_runtime
    saved = threading.Event()
    progress = service._progress
    def observe(operation_id, result):
        progress(operation_id, result)
        if result["config_applied"]:
            saved.set()
    monkeypatch.setattr(service, "_progress", observe)
    plan = planned(gate, connect=True)
    with runtime._manager_lock:
        op = service.apply(apply_arguments(plan), gate["context"])
        worker = service._threads[op["operation_id"]]
        assert saved.wait(2)
        gate["auth"].logout(gate["client"].cookies.get(gate["auth"].cookie_name))
    worker.join(3)
    assert not worker.is_alive()
    principal, _, _ = gate["auth"].login(username=gate["principal"].username, password=PASSWORD)
    result = service.status({"operation_id": op["operation_id"]}, context(principal))
    assert result["config_applied"] is True and result["status"] == "partial"
    assert result["error_code"] == "external_config_session_invalid"
    assert not runtime.has_server(plan["server_id"]) and not gate["calls"]


def test_waiting_runtime_lock_rechecks_credential_revision_before_loading_or_connecting(gate, monkeypatch, caplog):
    from lingshu_gate.credential_store import CredentialStore
    service, runtime = gate["service"], gate["app"].state.mcp_runtime
    service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Original-Secret")
    data = manifest()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-binding}"}
    saved = threading.Event()
    progress = service._progress
    def observe(operation_id, result):
        progress(operation_id, result)
        if result["config_applied"]:
            saved.set()
    monkeypatch.setattr(service, "_progress", observe)
    resolved_refs = []
    original_resolve = CredentialStore.resolve_value
    def resolve(store, credential_id, **options):
        resolved_refs.append(credential_id)
        return original_resolve(store, credential_id, **options)
    monkeypatch.setattr(CredentialStore, "resolve_value", resolve)
    plan = planned(gate, manifest=data, connect=True)
    with runtime._manager_lock:
        op = service.apply(apply_arguments(plan), gate["context"])
        worker = service._threads[op["operation_id"]]
        assert saved.wait(2)
        service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Rotated-Secret")
    worker.join(3)
    assert not worker.is_alive()
    result = wait(gate, op["operation_id"])
    assert result["config_applied"] and result["status"] == "partial"
    assert result["error_code"] == "external_config_credential_changed"
    assert not runtime.has_server(plan["server_id"]) and not gate["calls"] and not resolved_refs
    assert service.configs.get_config(plan["server_id"]).digest == result["config_digest"]
    assert "Synthetic-Original-Secret" not in caplog.text + json.dumps(result)
    assert "Synthetic-Rotated-Secret" not in caplog.text + json.dumps(result)


@pytest.mark.parametrize("probe", [False, True])
def test_rotation_at_header_resolution_cannot_consume_new_value_for_old_plan(gate, monkeypatch, caplog, probe):
    from lingshu_gate.application import external_mcp_configuration
    service = gate["service"]
    service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Original-Secret")
    data = manifest()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-binding}"}
    client_type = external_mcp_configuration.StreamableHttpMcpClient
    original_start = client_type.start
    def rotate_then_start(client):
        service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Rotated-Secret")
        return original_start(client)
    monkeypatch.setattr(client_type, "start", rotate_then_start)
    if probe:
        result = planned(gate, manifest=data, probe=True, probe_confirmed=True)
        assert result["status"] == "blocked" and result["probe"]["network_contacted"] is False
        assert not service.database.query_all("SELECT id FROM external_mcp_config_plans")
        assert not service.configs.list_configs().configs
    else:
        plan = planned(gate, manifest=data, connect=True)
        result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
        assert result["status"] == "partial" and result["config_applied"]
        assert result["cleanup_state"] == "disconnected"
    assert result["error_code"] == "external_config_credential_changed"
    assert all(action == "disconnect" for action, _ in gate["calls"])
    assert "Synthetic-Original-Secret" not in caplog.text + json.dumps(result)
    assert "Synthetic-Rotated-Secret" not in caplog.text + json.dumps(result)


def test_revision_check_and_decryption_use_the_same_stored_record(gate, monkeypatch):
    from lingshu_gate.credential_store import CredentialRevisionConflict
    store = gate["service"].credentials
    approved = store.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Original-Secret")
    assert store.resolve_value(approved.id, expected_revision=approved.updated_at) == "Synthetic-Original-Secret"
    store.save_credential(name="Synthetic binding", credential_id=approved.id, value="Synthetic-Rotated-Secret")
    def reject_decryption():
        pytest.fail("An unapproved credential revision must not be decrypted")
    monkeypatch.setattr(store, "_fernet", reject_decryption)
    with pytest.raises(CredentialRevisionConflict):
        store.resolve_value(approved.id, expected_revision=approved.updated_at)


def test_probe_rotation_during_discovery_cannot_rebind_its_plan(gate, monkeypatch):
    from lingshu_gate.application import external_mcp_configuration
    service = gate["service"]
    service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Original-Secret")
    data = manifest()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-binding}"}
    client_type = external_mcp_configuration.StreamableHttpMcpClient
    original_list = client_type.list_tools
    def rotate_then_list(client):
        service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Rotated-Secret")
        return original_list(client)
    monkeypatch.setattr(client_type, "list_tools", rotate_then_list)
    with pytest.raises(ToolExecutionError) as error:
        planned(gate, manifest=data, probe=True, probe_confirmed=True)
    assert error.value.code == "external_config_credential_changed"
    assert not service.database.query_all("SELECT id FROM external_mcp_config_plans")
    assert not gate["app"].state.mcp_runtime.has_server(data["id"])


@pytest.mark.parametrize("cancel", [False, True])
def test_config_lock_wait_is_bounded_and_cancellable_before_save(gate, cancel):
    service = gate["service"]
    plan = planned(gate, timeout_seconds=1)
    with service.configs.mutation_lock:
        op = service.apply(apply_arguments(plan), gate["context"])
        worker = service._threads[op["operation_id"]]
        if cancel:
            service.cancel({"operation_id": op["operation_id"], "confirmed": True,
                            "idempotency_key": "synthetic-lock-cancel"}, gate["context"])
        worker.join(2)
        assert not worker.is_alive()
    result = wait(gate, op["operation_id"])
    assert result["status"] == ("cancelled" if cancel else "timed_out")
    assert result["config_applied"] is False and not gate["calls"]


def test_same_user_new_session_cannot_consume_old_session_plan(gate):
    plan = planned(gate)
    principal, _, _ = gate["auth"].login(username=gate["principal"].username, password=PASSWORD)
    with pytest.raises(ToolExecutionError) as error:
        gate["service"].apply(apply_arguments(plan), context(principal))
    assert error.value.code == "external_config_plan_conflict"
    assert not gate["calls"]


def test_masked_saved_target_is_editable_without_reading_endpoint_or_credentials(gate):
    service = gate["service"]
    service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Secret-Value")
    data = manifest()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-binding}"}
    plan = planned(gate, manifest=data)
    wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    response = gate["client"].get("/v1/mcp/external-configs/targets/synthetic-external")
    assert response.status_code == 200
    target = response.json()
    assert target["manifest"]["transport"]["endpoint"] == "[REDACTED]"
    assert target["manifest"]["transport"]["headers"]["Authorization"] == "***"
    assert target["discovery_state"] == "not_observed"
    edited = {**target["manifest"], "name": "Synthetic saved edit"}
    updated = service.plan({"mode": "update", "manifest": edited,
                            "expected_config_digest": target["config_digest"]}, gate["context"])
    result = wait(gate, service.apply(apply_arguments(updated, "synthetic-masked-edit"), gate["context"])["operation_id"])
    assert result["status"] == "success" and result["config_digest"] != target["config_digest"]
    saved = service.configs.load_manifest(plan["server_id"])
    assert saved.transport.endpoint == data["transport"]["endpoint"]
    assert saved.transport.headers == data["transport"]["headers"]
    assert "Synthetic-Secret-Value" not in json.dumps(target) + json.dumps(updated)


@pytest.mark.parametrize("cleanup", ["normal", "superseded", "failure"])
def test_post_discovery_failure_closes_only_own_connection_and_reports_unknown_cleanup(gate, monkeypatch, cleanup):
    service, runtime = gate["service"], gate["app"].state.mcp_runtime
    original_progress = service._progress
    def fail_after_discovery(operation_id, result):
        if result["connection_state"] == "connected":
            raise RuntimeError("Synthetic failure after committed discovery")
        original_progress(operation_id, result)
    monkeypatch.setattr(service, "_progress", fail_after_discovery)
    if cleanup != "normal":
        original = runtime.disconnect_external_operation
        def cleanup_connection(server_id, digest, operation_id, *, deadline):
            if cleanup == "failure":
                raise TimeoutError("Synthetic cleanup unavailable")
            # A newer connection took ownership, even with the same manifest.
            runtime._servers[server_id].connection_operation_id = "synthetic-successor"
            return original(server_id, digest, operation_id, deadline=deadline)
        monkeypatch.setattr(runtime, "disconnect_external_operation", cleanup_connection)
    plan = planned(gate, connect=True, refresh_tools=True)
    result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    assert result["config_applied"] and result["status"] == "partial"
    assert result["discovery_state"] == "succeeded" and result["counts"]["new"] == 1
    assert result["connection_state"] == {"normal": "disconnected", "superseded": "superseded", "failure": "unknown"}[cleanup]
    if cleanup != "normal":
        assert result["requires_reconciliation"]
        assert not any(action == "disconnect" for action, _ in gate["calls"])


def test_connection_failure_redacts_resolved_credentials_and_endpoint(gate, caplog):
    service = gate["service"]
    service.credentials.save_credential(name="Synthetic binding", credential_id="synthetic-binding", value="Synthetic-Secret-Value")
    data = manifest()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-binding}"}
    gate["mode"]["failure"] = RuntimeError("Synthetic-Secret-Value " + data["transport"]["endpoint"])
    plan = planned(gate, manifest=data, connect=True)
    result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    server = service.runtime.get_server(plan["server_id"]).model_dump()
    encoded = caplog.text + json.dumps(result) + json.dumps(server)
    assert "Synthetic-Secret-Value" not in encoded and data["transport"]["endpoint"] not in encoded


def test_terminal_journal_failure_is_atomic_and_status_recovers_without_replay(gate, monkeypatch):
    service = gate["service"]
    def fail_finalization(*args, **kwargs):
        raise RuntimeError("Synthetic database completion failure")
    monkeypatch.setattr(service.delivery, "_complete_operation", fail_finalization)
    plan = planned(gate)
    args = apply_arguments(plan)
    result = wait(gate, service.apply(args, gate["context"])["operation_id"])
    assert result["status"] == "interrupted" and result["config_applied"] is None
    assert result["connection_state"] == "unknown" and result["requires_reconciliation"]
    journal = service.database.query_one("SELECT status FROM mcp_idempotent_operations WHERE id=?", (result["operation_id"],))
    assert journal["status"] == "failed"
    assert len(service.configs.list_configs().configs) == 1
    with pytest.raises(ToolExecutionError) as error:
        service.apply(args, gate["context"])
    assert error.value.code == "operation_interrupted" and not gate["calls"]


def test_restart_recovery_and_foreign_actor_status_do_not_replay_or_disclose(gate):
    service = gate["service"]
    plan = planned(gate)
    result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    service.database.execute("UPDATE external_mcp_config_operations SET status='running',result_json=? WHERE id=?",
                             (json.dumps({**result, "status": "running", "terminal": False}), result["operation_id"]))
    service.database.execute("UPDATE mcp_idempotent_operations SET status='pending' WHERE id=?", (result["operation_id"],))
    service._recover_interrupted()
    recovered = service.status({"operation_id": result["operation_id"]}, gate["context"])
    assert recovered["status"] == "interrupted" and recovered["config_applied"] is None
    user = gate["auth"].create_user(username="synthetic-other-admin", password=PASSWORD, role="admin")
    principal, _, _ = gate["auth"].login(username=user["username"], password=PASSWORD)
    with pytest.raises(ToolExecutionError) as error:
        service.status({"operation_id": result["operation_id"]}, context(principal))
    assert error.value.code == "external_config_operation_unavailable" and not gate["calls"]


def test_connection_operation_deadline_does_not_poison_later_business_calls(gate):
    from lingshu_gate.mcp_manifest import McpServerManifest
    client = StreamableHttpMcpClient(McpServerManifest.model_validate(manifest()), gate["service"].settings)
    cancel = threading.Event()
    with pytest.raises(InterruptedError):
        with client.operation_bounds(cancel, time.monotonic() + 1):
            cancel.set()
    # The connection operation ended; later ordinary calls get their own timeout.
    client._check_operation()


@pytest.mark.parametrize("confirmed", [False, 1, "true"])
def test_confirmation_cannot_be_absent_or_coerced_from_non_boolean(gate, confirmed):
    plan = planned(gate)
    with pytest.raises(ToolExecutionError):
        gate["service"].apply({**apply_arguments(plan), "confirmed": confirmed}, gate["context"])
    assert not gate["service"].configs.list_configs().configs


def test_queue_failure_is_terminal_and_does_not_leak_a_worker_or_replay(gate, monkeypatch):
    service = gate["service"]
    plan = planned(gate)
    args = apply_arguments(plan)
    def fail_start(thread):
        raise RuntimeError("Synthetic thread start unavailable")
    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(ToolExecutionError) as error:
        service.apply(args, gate["context"])
    operation_id = error.value.details["operation_id"]
    result = service.status({"operation_id": operation_id}, gate["context"])
    assert result["status"] == "failed" and result["terminal"] and result["config_applied"] is False
    assert not service._threads and not service._cancels and not service.configs.list_configs().configs
    with pytest.raises(ToolExecutionError):
        service.apply(args, gate["context"])


def test_additive_migration_can_be_reopened_without_losing_existing_auth_and_plan(gate):
    from lingshu_gate.database import SQLiteDatabase
    service = gate["service"]
    plan = planned(gate)
    reopened = SQLiteDatabase(service.settings.db_url, service.settings.data_dir)
    reopened.initialize()
    assert reopened.query_one("SELECT id FROM users WHERE id=?", (gate["principal"].id,))
    assert reopened.query_one("SELECT id FROM auth_sessions WHERE id=?", (gate["context"].session_id,))
    assert reopened.query_one("SELECT id FROM external_mcp_config_plans WHERE id=?", (plan["plan_id"],))
    assert len(reopened.query_all("SELECT id FROM schema_migrations WHERE id='0010_gate_external_mcp_config'")) == 1


@pytest.mark.parametrize("refresh", [False, True])
def test_initial_discovery_quarantines_changed_published_schema_without_a_second_list(gate, refresh):
    service = gate["service"]
    plan = planned(gate, connect=True, refresh_tools=refresh)
    result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    assert result["counts"]["new"] == 1 and result["classification_state"] == "needs_review"
    assert sum(action == "discover" for action, _ in gate["calls"]) == 1
    tool_id = "mcp.synthetic-external.synthetic_read"
    service.access.set_classification(server_id=plan["server_id"], tool_id=tool_id, access="read",
                                      destructive=False, idempotent=True, reviewer_id=gate["principal"].id)
    service.access.publish_classifications(server_id=plan["server_id"], tool_ids=[tool_id], reviewer_id=gate["principal"].id)
    assert service.access.list_classifications(server_id=plan["server_id"])[0]["status"] == "published"
    gate["mode"]["schema"] = {"type": "object", "properties": {"synthetic_changed": {"type": "string"}}}
    edited = {**manifest(), "name": "Synthetic changed schema target"}
    updated = service.plan({"mode": "update", "manifest": edited, "expected_config_digest": result["config_digest"],
                            "connect": True, "refresh_tools": refresh}, gate["context"])
    after = wait(gate, service.apply(apply_arguments(updated, "synthetic-schema-update"), gate["context"])["operation_id"])
    classification = service.access.list_classifications(server_id=plan["server_id"])[0]
    assert after["status"] == "success" and after["counts"]["changed"] == 1
    assert after["tool_snapshot_digest"] != result["tool_snapshot_digest"]
    assert sum(action == "discover" for action, _ in gate["calls"]) == 2
    assert classification["status"] == "stale" and classification["effective_access"] == "unknown"
    assert after["effective_permissions_expanded"] is False


def test_expired_consumed_plan_follows_existing_operation_retention(gate):
    service = gate["service"]
    plan = planned(gate)
    result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    service.database.execute("UPDATE external_mcp_config_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (plan["plan_id"],))
    # An expired plan stays while its terminal operation still references it.
    service.plan({"mode": "create", "manifest": manifest("synthetic-next")}, gate["context"])
    assert service.database.query_one("SELECT id FROM external_mcp_config_plans WHERE id=?", (plan["plan_id"],))
    service.database.execute("DELETE FROM mcp_idempotent_operations WHERE id=?", (result["operation_id"],))
    assert not service.database.query_one("SELECT id FROM external_mcp_config_operations WHERE id=?", (result["operation_id"],))
    service.plan({"mode": "create", "manifest": manifest("synthetic-after-retention")}, gate["context"])
    assert not service.database.query_one("SELECT id FROM external_mcp_config_plans WHERE id=?", (plan["plan_id"],))


@pytest.mark.parametrize("action", ["plan", "apply", "cancel"])
def test_rest_session_mutations_require_origin_and_single_use_request_bound_csrf(gate, action):
    client = gate["client"]
    operation_id = None
    if action == "plan":
        body = {"mode": "create", "manifest": manifest()}
    elif action == "apply":
        body = apply_arguments(planned(gate))
    else:
        operation_id = gate["service"].apply(apply_arguments(planned(gate)), gate["context"])["operation_id"]
        wait(gate, operation_id)
        body = {"idempotency_key": "synthetic-rest-cancel", "confirmed": True}
    path = (f"/v1/mcp/external-configs/operations/{operation_id}/cancel" if action == "cancel"
            else f"/v1/mcp/external-configs/{action}")
    headers = session_headers(gate, body, action=action, operation_id=operation_id)
    assert client.post(path, json=body, headers={"X-CSRF-Token": headers["X-CSRF-Token"]}).status_code == 403
    assert client.post(path, json=body, headers={"Origin": "http://testserver"}).json()["detail"]["code"] == "invalid_csrf"
    assert client.post(path, json=body, headers={**headers, "Origin": "https://other.example.test"}).status_code == 403
    accepted = client.post(path, json=body, headers=headers)
    assert accepted.status_code == 200
    replay = client.post(path, json=body, headers=headers)
    assert replay.status_code == 403 and replay.json()["detail"]["code"] == "invalid_csrf"
    if action == "apply":
        wait(gate, accepted.json()["operation_id"])
        retry = client.post(path, json=body, headers=session_headers(gate, body, action=action))
        assert retry.status_code == 200 and retry.json()["idempotent_replay"] is True


@pytest.mark.parametrize("headers", [{}, {"Origin": "null"}, {"Origin": "http://testserver/"},
    {"Origin": "http://testserver", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "http://testserver", "Sec-Fetch-Site": "none"}])
def test_csrf_issuance_and_mutation_reject_missing_or_unsafe_browser_origin(gate, headers):
    body = {"mode": "create", "manifest": manifest()}
    response = gate["client"].post("/v1/mcp/external-configs/csrf", params={"action": "plan", "request_digest": "a" * 64}, headers=headers)
    assert response.status_code == 403
    ticket = session_headers(gate, body)
    response = gate["client"].post("/v1/mcp/external-configs/plan", json=body, headers={**headers, "X-CSRF-Token": ticket["X-CSRF-Token"]})
    assert response.status_code == 403 and not gate["calls"]


@pytest.mark.parametrize("change", ["body", "action", "new_session", "other_user", "expired", "logout"])
def test_csrf_cannot_cross_request_action_session_actor_or_expiry(gate, change):
    body = {"mode": "create", "manifest": manifest()}
    headers = session_headers(gate, body, action="apply" if change == "action" else "plan")
    if change == "body":
        body = {**body, "connect": True}
    elif change in {"new_session", "other_user"}:
        username = gate["principal"].username
        if change == "other_user":
            username = gate["auth"].create_user(username="synthetic-csrf-other", password=PASSWORD, role="admin")["username"]
        _, cookie, _ = gate["auth"].login(username=username, password=PASSWORD)
        gate["client"].cookies.set(gate["auth"].cookie_name, cookie)
    elif change == "expired":
        gate["service"].database.execute("UPDATE console_csrf_tickets SET expires_at=0")
    elif change == "logout":
        gate["service"].database.execute("DELETE FROM auth_sessions WHERE id=?", (gate["context"].session_id,))
        assert not gate["service"].database.query_all("SELECT * FROM console_csrf_tickets")
    response = gate["client"].post("/v1/mcp/external-configs/plan", json=body, headers=headers)
    assert response.status_code == (401 if change == "logout" else 403)
    assert not gate["service"].database.query_all("SELECT * FROM external_mcp_config_plans") and not gate["calls"]


def test_single_use_csrf_survives_reopen_and_concurrent_consumption(gate):
    from concurrent.futures import ThreadPoolExecutor
    from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf
    from lingshu_gate.auth import AuthStore
    from lingshu_gate.database import SQLiteDatabase
    auth, principal = gate["auth"], gate["principal"]
    session = gate["client"].cookies.get(auth.cookie_name)
    issuer = ConsoleSessionCsrf(auth)
    ticket = issuer.issue(principal, session, "synthetic-target", "a" * 64)
    settings = gate["service"].settings
    reopened = AuthStore(settings, SQLiteDatabase(settings.db_url, settings.data_dir))
    consumer = ConsoleSessionCsrf(reopened)
    def consume():
        try:
            consumer.consume(principal, session, ticket["csrf"], "synthetic-target", "a" * 64)
            return "accepted"
        except ConsoleCsrfError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(outcomes) == ["accepted", "invalid_csrf"]


def test_console_csrf_capacity_and_expiry_are_bounded(gate):
    from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf, MAX_SESSION_CSRF
    csrf = ConsoleSessionCsrf(gate["auth"])
    session = gate["client"].cookies.get(gate["auth"].cookie_name)
    for _ in range(MAX_SESSION_CSRF):
        csrf.issue(gate["principal"], session, "synthetic-target", "a" * 64)
    with pytest.raises(ConsoleCsrfError, match="csrf_capacity"):
        csrf.issue(gate["principal"], session, "synthetic-target", "a" * 64)
    gate["service"].database.execute("UPDATE console_csrf_tickets SET expires_at=0")
    csrf.issue(gate["principal"], session, "synthetic-target", "a" * 64)
    assert len(gate["service"].database.query_all("SELECT * FROM console_csrf_tickets")) == 1


@pytest.mark.parametrize("owner,state,closed", [("successor", "failed", False), ("successor", "starting", False),
                                              (None, "loaded", False), ("synthetic-owner", "failed", True)])
def test_cleanup_without_a_client_still_requires_exact_operation_ownership(gate, owner, state, closed):
    from lingshu_gate.mcp_runtime import McpServerState
    service, runtime = gate["service"], gate["app"].state.mcp_runtime
    plan = planned(gate)
    wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    target = runtime._servers[plan["server_id"]]
    with runtime._manager_lock, target.lock:
        target.connection_operation_id = owner
        target.state = McpServerState(state)
        runtime._set_desired_state_locked(plan["server_id"], "running", source="synthetic-successor")
    assert target.client is None
    result = runtime.disconnect_external_operation(plan["server_id"], plan["manifest_digest"], "synthetic-owner", deadline=time.monotonic() + 1)
    assert result is closed
    assert runtime.state_store.get(plan["server_id"]).desired_state == ("stopped" if closed else "running")
    assert target.connection_operation_id == (None if closed else owner)
    assert target.state == (McpServerState.STOPPED if closed else McpServerState(state))
    assert not gate["calls"]


def test_cancellation_during_runtime_apply_retains_unknown_state_and_reconciliation(gate, monkeypatch):
    service, runtime = gate["service"], gate["app"].state.mcp_runtime
    original = runtime.apply_external_configuration
    def cancelled_after_apply(manifest, **kwargs):
        original(manifest, **kwargs)
        kwargs["cancel"].set()
        raise InterruptedError("Synthetic interrupted runtime apply")
    monkeypatch.setattr(runtime, "apply_external_configuration", cancelled_after_apply)
    plan = planned(gate, connect=True)
    result = wait(gate, service.apply(apply_arguments(plan), gate["context"])["operation_id"])
    assert result["status"] == "cancelled" and result["config_applied"] is True
    assert result["connection_state"] == result["discovery_state"] == result["cleanup_state"] == "unknown"
    assert result["requires_reconciliation"] is True and not gate["calls"]


def test_cancel_rechecks_completion_after_the_initial_status_read(gate, monkeypatch):
    service = gate["service"]
    started, release = threading.Event(), threading.Event()
    gate["mode"]["wait"] = (started, release)
    operation = service.apply(apply_arguments(planned(gate, connect=True)), gate["context"])
    operation_id = operation["operation_id"]
    worker = service._threads[operation_id]
    assert started.wait(2)
    original = service.status
    def stale_status(arguments, ctx):
        observed = original(arguments, ctx)
        assert observed["terminal"] is False
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        return observed
    monkeypatch.setattr(service, "status", stale_status)
    cancelled = service.cancel({"operation_id": operation_id, "idempotency_key": "synthetic-terminal-race", "confirmed": True}, gate["context"])
    assert cancelled["status"] == "already_terminal" and cancelled["terminal"] is True
    row = service.database.query_one("SELECT status,cancel_requested FROM external_mcp_config_operations WHERE id=?", (operation_id,))
    assert row["status"] == "success" and row["cancel_requested"] == 0
    assert original({"operation_id": operation_id}, gate["context"])["connection_state"] == "connected"
    assert not any(action == "disconnect" for action, _ in gate["calls"])

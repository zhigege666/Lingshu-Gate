"""Policy restrictions through actual HTTP gateways and production dispatch locks."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.argument_policy import ArgumentPolicy, ArgumentPolicyDenied, PolicyWrite, check_policy, validate_rules
from lingshu_gate.interfaces.control_api.argument_policy_routes import register_argument_policy_routes
from lingshu_gate.interfaces.control_api.tool_routes import register_tool_routes
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.tool_catalog import CatalogDescribe, ToolCatalog
from test_authorization_discovery import ISSUER, browser as browser, gate as gate, legacy, rpc, set_mode
from test_builtin_oauth import PASSWORD
from test_tool_preferences import update


def rule(operator="number_range", pointer="/limit", **values):
    return {"id": "limit-rule", "pointer": pointer, "operator": operator, **(values or {"minimum": 1, "maximum": 3})}


def save_policy(gate, rules, *, enabled=True, tool_id="mcp.A.read"):
    store = gate["access"].argument_policies
    old = store.current(tool_id)
    return store.save(tool_id, PolicyWrite(expected_revision=old.revision, enabled=enabled, rules=rules),
        actor_id=gate["admin"]["id"], authorize=lambda _: None, observability=ObservabilityStore(gate["db"]))


@pytest.fixture
def configured(gate):
    calls = []
    definition = gate["registry"].get_definition("mcp.A.read")
    definition.input_schema = {"type": "object", "properties": {"limit": {"type": "integer", "default": 2},
        "secret": {"type": "string"}, "fileRef": {"type": "string"}}, "additionalProperties": True}
    gate["registry"].register(definition, lambda arguments: calls.append(arguments) or {"count": len(calls)}, replace=True)
    gate["access"].synchronize_tools([definition])
    gate["access"].set_classification(server_id="A", tool_id=definition.id, access="read", destructive=False, idempotent=True,
                                     reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id="A", reviewer_id=gate["admin"]["id"])
    gate["access"].refresh_principal = lambda actor: current_tool_principal(gate["auth"], actor)
    observability = ObservabilityStore(gate["db"])
    register_tool_routes(gate["app"], registry=gate["registry"], access_store=gate["access"], observability_store=observability,
                         require_authenticated=gate["auth"].authenticate_request)
    register_argument_policy_routes(gate["app"], auth=gate["auth"], access=gate["access"], registry=gate["registry"], observability=observability)
    catalog = ToolCatalog(gate["registry"], gate["access"])
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
                               gate["auth"].authenticate_mcp_request, catalog=catalog)
    return calls, catalog


@pytest.mark.parametrize("spec,value,allowed", [
    ({"operator": "equals", "value": True}, True, True),
    ({"operator": "equals", "value": True}, 1, False),
    ({"operator": "equals", "value": {"x": [True]}}, {"x": [1]}, False),
    ({"operator": "equals", "value": None}, None, True),
    ({"operator": "allowed_values", "values": [1, 2]}, 2, True),
    ({"operator": "allowed_values", "values": [1, 2]}, True, False),
    ({"operator": "number_range", "minimum": 1, "maximum": 3}, 2.5, True),
    ({"operator": "number_range", "minimum": 1}, "2", False),
    ({"operator": "number_range", "minimum": 1}, True, False),
    ({"operator": "number_range", "maximum": 10 ** 400}, 2, True),
    ({"operator": "string_prefix", "prefix": "/approved/"}, "/approved/item", True),
    ({"operator": "string_prefix", "prefix": "/approved/"}, "/other/item", False),
])
def test_typed_finite_rules(spec, value, allowed):
    policy = ArgumentPolicy(True, 7, tuple(validate_rules([{"id": "rule", "pointer": "/a~1b/~0/0", **spec}])))
    arguments = {"a/b": {"~": [value]}}
    if allowed:
        check_policy(policy, arguments)
    else:
        with pytest.raises(ArgumentPolicyDenied) as error:
            check_policy(policy, arguments)
        assert error.value.details["policy_revision"] == 7
    with pytest.raises(ArgumentPolicyDenied, match="effective"):
        check_policy(policy, {})


@pytest.mark.parametrize("entry", ["rest", "rest_tool", "direct", "directory", "pin"])
def test_every_gateway_restricts_before_side_effect_and_denials_keep_no_values(browser, gate, configured, entry, caplog):
    calls, catalog = configured
    token = legacy(gate)
    save_policy(gate, [rule()])
    headers = {"Authorization": "Bearer " + token["token"]}
    name = ""
    if entry == "direct":
        set_mode(browser, "api", token["id"], "direct")
    if entry == "pin":
        update(browser, token, pinned_tools=[{"kind": "tool", "tool_ref": "mcp.A.read"}])
        name = next(item["name"] for item in rpc(browser, token["token"]).json()["result"]["tools"] if item["name"].startswith("gate_pinned_"))
    revision = catalog.describe(gate["principals"]["alice"], CatalogDescribe(tool_ref="mcp.A.read"))["schema_revision"]
    def invoke(arguments):
        if entry in {"rest", "rest_tool"}:
            result = browser.post("/v1/invoke" if entry == "rest" else "/v1/tools/mcp.A.read/invoke", headers=headers,
                json={"arguments": arguments, **({"tool_id": "mcp.A.read"} if entry == "rest" else {})})
            assert result.status_code == 200, result.text
            return result.json()["ok"]
        selected_name = name if entry == "pin" else "mcp__A__read" if entry == "direct" else "gate_tool_invoke"
        values = arguments if entry != "directory" else {"tool_ref": "mcp.A.read", "schema_revision": revision, "arguments": arguments}
        result = rpc(browser, token["token"], "tools/call", {"name": selected_name, "arguments": values})
        assert result.status_code == 200, result.text
        return not result.json()["result"].get("isError", False)
    assert invoke({"limit": 2})
    assert not invoke({"limit": 99, "secret": "synthetic-sensitive-policy-denial"})
    assert not invoke({})
    assert calls == [{"limit": 2}]
    denied = gate["db"].query_all("SELECT decision,outcome,payload_json FROM invocation_audits WHERE decision='deny'")
    assert len(denied) == 2 and all(row["outcome"] == "not_invoked" for row in denied)
    assert all(json.loads(row["payload_json"])["values_recorded"] is False for row in denied)
    assert "synthetic-sensitive-policy-denial" not in caplog.text
    assert "synthetic-sensitive-policy-denial" not in json.dumps([dict(row) for row in denied])


def ticket(client, path, body):
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = client.post(path + "/csrf", params={"request_digest": digest}, headers={"Origin": ISSUER})
    assert result.status_code == 200, result.text
    return {"Origin": ISSUER, "X-CSRF-Token": result.json()["csrf"]}


def test_management_permission_csrf_revision_preview_and_atomic_audit(gate, configured):
    path = "/v1/tools/mcp.A.read/argument-policy"
    admin, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        assert client.get(path).status_code == 401
        client.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        assert client.get(path).status_code == 403
        client.cookies.set(gate["auth"].cookie_name, session)
        assert client.get(path).json()["revision"] == 0
        body = {"expected_revision": 0, "enabled": True, "rules": [rule()]}
        assert client.put(path, json=body, headers={"Origin": ISSUER}).status_code == 403
        headers = ticket(client, path, body)
        assert client.put(path, json={**body, "enabled": False}, headers=headers).status_code == 403
        assert client.put(path, json=body, headers=headers).status_code == 200
        assert client.put(path, json=body, headers=headers).status_code == 403
        assert client.put(path, json=body, headers=ticket(client, path, body)).status_code == 409
        preview = client.post(path + "/preview", json={**body, "arguments": {"limit": 99}})
        assert preview.status_code == 200 and preview.json()["allowed"] is False
        assert preview.json()["execution"] == "not_invoked" and configured[0] == []
        narrow = gate["auth"].create_api_token(principal=admin, name="Synthetic narrow manager", scopes=["tools.read"])
        assert client.get(path, headers={"Authorization": "Bearer " + narrow["token"]}).status_code == 403
        gate["db"].execute("CREATE TRIGGER reject_policy_audit BEFORE INSERT ON events WHEN NEW.type='gate.tool.argument_policy.updated' BEGIN SELECT RAISE(ABORT,'synthetic policy audit failure'); END")
        next_body = {**body, "expected_revision": 1, "enabled": False}
        with pytest.raises(Exception, match="synthetic policy audit failure"):
            client.put(path, json=next_body, headers=ticket(client, path, next_body))
        assert client.get(path).json()["enabled"] is True
        assert client.get(path).json()["revision"] == 1


@pytest.mark.parametrize("stored", ["not-json", '[{"id":"r","pointer":"/limit","operator":"equals","value":1,"value":2}]',
    '[{"id":"r","pointer":"/limit","operator":"equals","value":{"x":1,"x":2}}]'])
def test_corrupt_policy_never_becomes_disabled_or_uses_duplicate_member(gate, configured, stored):
    gate["db"].execute("INSERT INTO tool_argument_policies VALUES('mcp.A.read',0,1,?)", (stored,))
    result = gate["access"].invoke_tool(gate["registry"], gate["principals"]["alice"], "mcp.A.read", {"limit": 2})
    assert not result.ok and result.output["error"]["code"] == "argument_policy_denied"
    assert configured[0] == []


@pytest.mark.parametrize("initial_policy", [False, True])
def test_policy_enabled_or_tightened_while_waiting_runtime_lock_is_current(gate, configured, monkeypatch, initial_policy):
    if initial_policy:
        save_policy(gate, [rule(maximum=100)])
    entered = Event()
    old_prepare = gate["registry"].prepare
    def prepare(*args, **kwargs):
        result = old_prepare(*args, **kwargs)
        entered.set()
        return result
    monkeypatch.setattr(gate["registry"], "prepare", prepare)
    calls = []
    class Peer:
        def call_tool(self, name, arguments):
            calls.append(arguments)
            return {}
    manager = McpRuntimeManager(gate["settings"], gate["registry"])
    manifest = McpServerManifest(id="A", launch={"type": "managed_process", "command": "synthetic-never-spawned"}, transport={"type": "stdio"})
    runtime = McpServerRuntime(manifest, state=McpServerState.RUNNING, client=Peer())
    manager._servers["A"] = runtime
    gate["access"].attach_mcp_runtime(manager)
    with ThreadPoolExecutor(max_workers=1) as pool:
        runtime.lock.acquire()
        try:
            pending = pool.submit(gate["access"].invoke_tool, gate["registry"], gate["principals"]["alice"], "mcp.A.read", {"limit": 99})
            assert entered.wait(3)
            save_policy(gate, [rule()])
        finally:
            runtime.lock.release()
        response = pending.result(timeout=8)
    assert not response.ok and response.output["error"]["code"] == "argument_policy_denied" and calls == []


@pytest.mark.parametrize("entry", ["direct", "catalog"])
def test_file_reference_checks_schema_and_policy_after_owned_runtime_resolution(gate, configured, tmp_path, entry):
    from lingshu_gate.tool_files import ToolFileStore
    from lingshu_gate.tool_catalog import CatalogInvoke

    tool_id = "mcp.A.read"
    definition = gate["registry"].get_definition(tool_id)
    definition.input_schema = {"type": "object", "properties": {"filePath": {"type": "string"}},
                               "required": ["filePath"], "additionalProperties": False}
    gate["registry"].update_definition(definition)
    gate["access"].synchronize_tools([definition])
    gate["access"].set_classification(server_id="A", tool_id=tool_id, access="read", destructive=False, idempotent=True,
                                     reviewer_id=gate["admin"]["id"])
    gate["access"].publish_classifications(server_id="A", reviewer_id=gate["admin"]["id"])
    files = ToolFileStore(gate["db"], tmp_path)
    actor = gate["principals"]["alice"]
    content = b"synthetic-file-policy"
    digest = hashlib.sha256(content).hexdigest()
    upload = files.begin(actor_id=actor.id, filename="policy.txt", size_bytes=len(content), sha256=digest,
                         idempotency_key="policy-file-begin")
    files.append_chunk(actor_id=actor.id, transfer_id=upload["transfer_id"], offset=0, data=content,
                       chunk_sha256=digest, idempotency_key="policy-file-chunk")
    committed = files.commit(actor_id=actor.id, transfer_id=upload["transfer_id"], idempotency_key="policy-file-commit")
    path = files.resolve(actor_id=actor.id, file_ref=committed["fileRef"])
    calls = []
    class Peer:
        def call_tool(self, name, arguments):
            calls.append(arguments)
            return {}
    manager = McpRuntimeManager(gate["settings"], gate["registry"], tool_file_store=files)
    manifest = McpServerManifest(id="A", launch={"type": "managed_process", "command": "synthetic-never-spawned"}, transport={"type": "stdio"})
    manager._servers["A"] = McpServerRuntime(manifest, state=McpServerState.RUNNING, client=Peer())
    gate["access"].attach_mcp_runtime(manager)
    catalog = configured[1]
    revision = catalog.describe(actor, CatalogDescribe(tool_ref=tool_id))["schema_revision"]
    raw = {"fileRef": committed["fileRef"]}
    def invoke():
        if entry == "direct":
            return gate["access"].invoke_tool(gate["registry"], actor, tool_id, raw)
        return catalog.invoke(actor, CatalogInvoke(tool_ref=tool_id, schema_revision=revision, arguments=raw))
    assert invoke().ok
    save_policy(gate, [rule("string_prefix", "/filePath", prefix=str(path.parent) + "/")])
    assert invoke().ok
    assert calls == [{"filePath": str(path)}, {"filePath": str(path)}]
    assert raw == {"fileRef": committed["fileRef"]}
    save_policy(gate, [rule("string_prefix", "/filePath", prefix="/synthetic-unapproved/")])
    assert not invoke().ok and len(calls) == 2
    # The manager still resolves with the authenticated owner before the policy.
    denied = gate["access"].invoke_tool(gate["registry"], gate["principals"]["bob"], tool_id, raw)
    assert not denied.ok and len(calls) == 2


@pytest.mark.parametrize("denial", ["authorization", "catalog", "policy"])
def test_real_read_session_retry_denial_preserves_attempt_count_without_snapshots(tmp_path, denial):
    from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
    from lingshu_gate.auth import AuthPrincipal
    from lingshu_gate.database import SQLiteDatabase
    from lingshu_gate.registry import ToolExecutionError
    from test_mcp_session_recovery import connected_runtime

    with connected_runtime(tmp_path) as (manager, runtime, client, state):
        access = AccessControlStore(SQLiteDatabase(manager.settings.db_url, tmp_path))
        access.attach_mcp_runtime(manager)
        access.database.execute("UPDATE retention_policy SET payload_mode='redacted'")
        tool_id = "mcp.legacy-http.echo"
        access.synchronize_tools([manager.registry.get_definition(tool_id)])
        access.set_classification(server_id=runtime.manifest.id, tool_id=tool_id, access="read",
                                  destructive=False, idempotent=True, reviewer_id="synthetic-admin")
        access.publish_classifications(server_id=runtime.manifest.id, reviewer_id="synthetic-admin")
        actor = AuthPrincipal(id="synthetic-admin", username="admin", role="admin", auth_type="session")
        guard_checks = 0
        def guard():
            nonlocal guard_checks
            guard_checks += 1
            if state["writes"] != 1:
                return
            if denial == "authorization":
                raise AccessDeniedError("synthetic revoked", required_access="read", granted_access="none")
            if denial == "catalog":
                raise ToolExecutionError("catalog_target_unavailable", "The target is unavailable.")
            if access.argument_policies.current(tool_id).revision == 0:
                access.argument_policies.save(tool_id,
                    PolicyWrite(expected_revision=0, enabled=True, rules=[rule("equals", "/marker", value="allowed")]),
                    actor_id=actor.id, authorize=lambda _: None, observability=ObservabilityStore(access.database))
        response = access.invoke_tool(manager.registry, actor, tool_id,
                                      {"marker": "synthetic-retry-private-value"}, dispatch_guard=guard)
        assert not response.ok and guard_checks >= 2 and state["writes"] == 1
        assert len(state["sessions"]) == 2
        audit = access.database.query_one("SELECT decision,reason,outcome,payload_json FROM invocation_audits")
        assert audit["decision"] == "deny" and audit["outcome"] == "error"
        summary = json.loads(audit["payload_json"])
        assert summary["dispatch_attempts"] == 1 and summary["values_recorded"] is False
        assert "synthetic-retry-private-value" not in audit["payload_json"]
        assert not access.database.query_all("SELECT * FROM invocation_payloads")


def test_builtin_explicit_defaults_and_coercion_restrict_effective_arguments(gate, configured):
    from pydantic import BaseModel
    from lingshu_gate.argument_preparation import model_preparer
    from lingshu_gate.models import ToolDefinition

    class BuiltinInput(BaseModel):
        limit: int = 100
    calls = []
    tool_id = "gate_synthetic_policy_default"
    definition = ToolDefinition(id=tool_id, name=tool_id, description="Synthetic known first-party default",
        source="builtin", permission="tools.read", input_schema=BuiltinInput.model_json_schema())
    gate["registry"].register(definition, lambda arguments: calls.append(arguments) or {},
                              argument_preparer=model_preparer(BuiltinInput))
    save_policy(gate, [rule(maximum=3)], tool_id=tool_id)
    actor, _, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
    assert not gate["access"].invoke_tool(gate["registry"], actor, tool_id, {}).ok
    assert gate["access"].invoke_tool(gate["registry"], actor, tool_id, {"limit": "2"}).ok
    assert calls == [{"limit": 2}]

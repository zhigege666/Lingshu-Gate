"""以真实授权存储和调用治理核对持续范围、生命周期及独立令牌配额。"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.mcp_authorization_policy import bind_server_policies, server_binding
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_http_trust import McpHttpTrustStore
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.transports.http import build_protocol_request
from test_builtin_oauth import ISSUER, gate as gate, mcp_request
from test_oauth_continuous_scope import discover, publish
from test_token_authorizations import save, tokens as tokens


def token_actor(gate, token):
    return gate["auth"].authenticate_request(mcp_request(token["token"]))


def test_api_token_continuous_range_includes_only_future_published_allowed_tools(tokens, gate):
    token = save(tokens, gate, scopes=["tools.read", "tools.invoke"],
        server_policies=[{"server_id": "A", "mode": "continuous", "access": "write"}])
    actor = token_actor(gate, token)
    access, registry = gate["access"], gate["registry"]
    assert access.evaluate(actor, registry.get_definition("mcp.A.read"))["allowed"]
    assert access.evaluate(actor, registry.get_definition("mcp.A.write"))["allowed"]
    assert not access.evaluate(actor, registry.get_definition("mcp.B.read"))["allowed"]
    later = discover(gate)
    assert not access.evaluate(token_actor(gate, token), registry.get_definition(later))["allowed"]
    publish(gate, later)
    assert access.evaluate(token_actor(gate, token), registry.get_definition(later))["allowed"]
    access.save_grant(subject_type="user", subject_id=actor.id, server_id="A", tool_id=later,
                      permission_type_code="none", created_by=gate["admin"]["id"])
    assert not access.evaluate(token_actor(gate, token), registry.get_definition(later))["allowed"]


def test_same_api_bearer_lists_and_calls_new_tool_only_after_publication(tokens, gate):
    created = save(tokens, gate, server_policies=[{"server_id": "A", "mode": "continuous", "access": "read"}])
    # 此用例专门覆盖完整列表合同，显式配置授权，不依赖旧默认值。
    gate["db"].execute("INSERT INTO authorization_discovery VALUES('api',?,'direct',1)", (created["id"],))
    calls = []

    class SyntheticPeer:
        def invoke_mcp_tool_for_user(self, server_id, tool_name, arguments, *, user_id, dispatch_guard=None, **kwargs):
            if dispatch_guard is not None:
                dispatch_guard()
            if kwargs.get("arguments_guard"):
                kwargs["arguments_guard"](arguments)
            if kwargs.get("dispatch_started"):
                kwargs["dispatch_started"]()
            calls.append((server_id, tool_name, user_id))
            return {"content": [{"type": "text", "text": "Synthetic response"}]}

    gate["access"].attach_mcp_runtime(SyntheticPeer())
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
                               gate["auth"].authenticate_mcp_request)
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        def rpc(method, params=None):
            prepared, headers = build_protocol_request(method, params, client_name="Synthetic", client_version="1")
            response = browser.post("/mcp", headers={**headers, "Authorization": "Bearer " + created["token"]},
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared})
            assert response.status_code == 200
            return response.json()["result"]

        assert {item["name"] for item in rpc("tools/list")["tools"]} == {"mcp__A__read"}
        later = discover(gate)
        rejected = rpc("tools/call", {"name": "mcp__A__later", "arguments": {}})
        assert rejected["isError"] and not calls
        publish(gate, later)
        assert "mcp__A__later" in {item["name"] for item in rpc("tools/list")["tools"]}
        assert not rpc("tools/call", {"name": "mcp__A__later", "arguments": {}}).get("isError", False)
        assert calls == [("A", "later", gate["users"]["alice"]["id"])]


def test_empty_independent_token_is_not_admin_business_bypass(tokens, gate):
    empty = save(tokens, gate)
    actor = replace(token_actor(gate, empty), role="admin", roles=("admin",))
    assert not gate["access"].evaluate(actor, gate["registry"].get_definition("mcp.A.read"))["allowed"]


def test_token_selected_snapshot_invalidates_after_reclassification(tokens, gate):
    token = save(tokens, gate, tool_ids=["mcp.A.read"])
    access = gate["access"]
    tool = gate["registry"].get_definition("mcp.A.read")
    assert access.evaluate(token_actor(gate, token), tool)["allowed"]
    access.set_classification(server_id="A", tool_id=tool.id, access="read", destructive=False,
                              idempotent=True, reviewer_id=gate["admin"]["id"])
    assert not access.evaluate(token_actor(gate, token), tool)["allowed"]


def test_api_token_quota_shares_counter_after_owner_changes_limits(tokens, gate):
    token = save(tokens, gate, tool_ids=["mcp.A.read"], rate_per_minute=2, concurrency=1)
    access = gate["access"]
    first = access._acquire_external_invocation(token_actor(gate, token))
    with pytest.raises(AccessDeniedError, match="concurrency"):
        access._acquire_external_invocation(token_actor(gate, token))
    access._release_external_invocation(first)
    save(tokens, gate, token["id"], rate_per_minute=3, concurrency=100)
    second = access._acquire_external_invocation(token_actor(gate, token))
    access._release_external_invocation(second)
    save(tokens, gate, token["id"], rate_per_minute=2, concurrency=100)
    with pytest.raises(AccessDeniedError, match="rate"):
        access._acquire_external_invocation(token_actor(gate, token))


def external_manifest(endpoint="https://first.example.test/mcp"):
    return {"id": "lifecycle", "name": "Synthetic", "launch": {"type": "external"},
            "transport": {"type": "streamable_http", "endpoint": endpoint}}


def binding(gate):
    with gate["db"].session() as connection:
        return server_binding(connection, "lifecycle")


def test_config_update_preserves_binding_but_target_replace_and_recreate_rotate(gate, tmp_path):
    configs = McpConfigStore(tmp_path / "configs", http_trust_store=McpHttpTrustStore(gate["db"]))
    configs.save_config(external_manifest())
    original = binding(gate)
    updated = external_manifest()
    updated["name"] = "Updated display name"
    configs.save_config(updated, overwrite=True)
    assert binding(gate) == original
    configs.save_config(external_manifest("https://other.example.test/mcp"), overwrite=True)
    changed = binding(gate)
    assert changed != original
    configs.delete_config("lifecycle")
    with pytest.raises(ValueError, match="unavailable"):
        binding(gate)
    configs.save_config(external_manifest("https://other.example.test/mcp"))
    assert binding(gate) != changed


def test_external_same_length_manifest_rewrite_fails_closed(gate, tmp_path):
    configs = McpConfigStore(tmp_path / "configs", http_trust_store=McpHttpTrustStore(gate["db"]))
    configs.save_config(external_manifest())
    original = binding(gate)
    path = tmp_path / "configs" / "lifecycle.yaml"
    content = path.read_bytes()
    # first/other 等长，在 Windows 创建时间和文件长度均可能保持不变。
    path.write_bytes(content.replace(b"first.example.test", b"other.example.test"))
    with pytest.raises(ValueError, match="server_scope_changed"):
        binding(gate)
    McpConfigStore(tmp_path / "configs", http_trust_store=McpHttpTrustStore(gate["db"]))
    assert binding(gate) != original


@pytest.mark.parametrize("continuous", [True, False])
def test_token_selected_and_continuous_scopes_do_not_survive_same_id_recreation(tokens, gate, tmp_path, continuous):
    configs = McpConfigStore(tmp_path / "configs", http_trust_store=McpHttpTrustStore(gate["db"]))
    manifest = external_manifest()
    manifest["id"] = "A"
    configs.save_config(manifest)
    scope = {"server_policies": [{"server_id": "A", "mode": "continuous", "access": "read"}]} if continuous else {
        "tool_ids": ["mcp.A.read"]}
    token = save(tokens, gate, **scope)
    tool = gate["registry"].get_definition("mcp.A.read")
    assert gate["access"].evaluate(token_actor(gate, token), tool)["allowed"]
    configs.delete_config("A")
    configs.save_config(manifest)
    assert not gate["access"].evaluate(token_actor(gate, token), tool)["allowed"]


def test_bound_policies_reject_replaced_identity_and_unknown_fields(gate):
    policy = [{"server_id": "A", "mode": "continuous", "access": "read"}]
    with gate["db"].session() as connection:
        bound = bind_server_policies(connection, policy)
        connection.execute("UPDATE gate_mcp_authorization_identities SET binding='replacement' WHERE server_id='A'")
        with pytest.raises(ValueError, match="server_scope_changed"):
            bind_server_policies(connection, bound)
        with pytest.raises(ValueError, match="invalid_server_policy"):
            bind_server_policies(connection, [{**policy[0], "all_future_servers": True}])

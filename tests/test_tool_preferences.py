from __future__ import annotations

import json
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from starlette.testclient import TestClient

from lingshu_gate.demo_mcp import create_demo_app
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.protocol.sdk_adapter import SERVER_INFO_META_KEY
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.result_budget import META_KEY, ResultCache, ResultRead
from lingshu_gate.tool_catalog import ToolCatalog
from lingshu_gate.transports.http import build_protocol_request
from test_authorization_discovery import browser as browser, gate as gate, tokens as tokens
from test_authorization_discovery import ISSUER, legacy, preview, rpc, save, set_mode, setting_path


def update(browser, token, **changes):
    path = setting_path("api", token["id"])
    old = browser.get(path).json()
    body = {"tool_discovery_mode": old["tool_discovery_mode"], "expected_revision": old["discovery_revision"], "csrf": old["csrf"], **changes}
    response = browser.post(path + "-preview", json=body, headers={"Origin": ISSUER})
    assert response.status_code == 200, response.text
    response = browser.post(path, json={**body, "csrf": response.json()["csrf"]}, headers={"Origin": ISSUER})
    assert response.status_code == 200, response.text
    return response.json()


def gateway(gate, output=None, cache_options=None):
    calls = []
    if output is not None:
        definition = gate["registry"].get_definition("mcp.A.read")
        def handler(arguments):
            calls.append(arguments)
            return output
        gate["registry"].register(definition, handler, replace=True)
    catalog = ToolCatalog(gate["registry"], gate["access"])
    cache = ResultCache(gate["registry"], gate["access"], catalog, **(cache_options or {}))
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request, catalog=catalog, result_cache=cache)
    return calls, cache


def test_settings_preserve_omitted_fields_and_bind_independent_policy(browser, tokens, gate):
    token = save(tokens, gate, tool_ids=["mcp.A.read"])
    pin = [{"kind": "tool", "tool_ref": "mcp.A.read"}]
    budget = {"schema_version": 1, "enabled": True, "max_characters": 2048}
    update(browser, token, pinned_tools=pin, result_budget=budget)
    next_setting = set_mode(browser, "api", token["id"], "direct")
    assert next_setting["pinned_tools"] == pin and next_setting["result_budget"] == budget
    confirmation = preview(browser, "api", token["id"], "on_demand")
    gate["db"].execute("UPDATE api_token_authorizations SET revision=revision+1 WHERE token_id=?", (token["id"],))
    assert browser.post(setting_path("api", token["id"]), json=confirmation, headers={"Origin": ISSUER}).status_code == 409
    assert update(browser, token, pinned_tools=[])["pinned_tools"] == []


@pytest.mark.parametrize("fields", [
    {"pinned_tools": None}, {"result_budget": None}, {"result_budget": {"max_characters": True}},
    {"result_budget": {"max_characters": 100}}, {"result_budget": {"schema_version": True}},
    {"pinned_tools": [{"kind": "tool", "tool_ref": "hidden"}] * 2},
    {"pinned_tools": [{"kind": "tool", "tool_ref": str(i)} for i in range(21)]},
])
def test_preference_input_is_strict(browser, gate, fields):
    token = legacy(gate)
    path = setting_path("api", token["id"])
    old = browser.get(path).json()
    response = browser.post(path + "-preview", json={"tool_discovery_mode": "on_demand", "expected_revision": 0,
        "csrf": old["csrf"], **fields}, headers={"Origin": ISSUER})
    assert response.status_code == 422


def test_pin_is_permission_filtered_and_old_name_cannot_execute(browser, gate):
    token = legacy(gate)
    calls, _ = gateway(gate, {"content": [{"type": "text", "text": "read"}]})
    update(browser, token, pinned_tools=[{"kind": "tool", "tool_ref": "mcp.A.read"}, {"kind": "tool", "tool_ref": "mcp.B.read"}])
    tools = rpc(browser, token["token"]).json()["result"]["tools"]
    assert len(tools) == 7
    pin = tools[-1]
    assert pin["name"].startswith("gate_pinned_")
    assert "B.read" not in json.dumps(tools)
    assert not rpc(browser, token["token"], "tools/call", {"name": pin["name"], "arguments": {}}).json()["result"]["isError"]
    update(browser, token, pinned_tools=[])
    denied = rpc(browser, token["token"], "tools/call", {"name": pin["name"], "arguments": {}}).json()["result"]
    assert denied["isError"] and len(calls) == 1


@pytest.mark.parametrize("mode", ["on_demand", "direct"])
def test_text_pages_are_exact_and_isolated_without_reexecution(browser, gate, mode):
    text = "hello 世界👩🏽‍💻\n" * 800
    token, other = legacy(gate), legacy(gate, "Other credential")
    calls, _ = gateway(gate, {"content": [{"type": "text", "text": text}]})
    budget = {"enabled": True, "max_characters": 1024}
    for record in (token, other):
        update(browser, record, tool_discovery_mode=mode, result_budget=budget, pinned_tools=[{"kind": "tool", "tool_ref": "mcp.A.read"}])
    listed = rpc(browser, token["token"]).json()["result"]["tools"]
    name = next(tool["name"] for tool in listed if tool["name"].startswith("gate_pinned_") or tool["name"] == "mcp__A__read")
    response = rpc(browser, token["token"], "tools/call", {"name": name, "arguments": {}}).json()["result"]
    metadata = response["_meta"][META_KEY]
    assert metadata["applied"] and len(response["content"][0]["text"]) <= 1024
    assert response["content"][0]["text"][:metadata["preview_characters"]] == text[:metadata["preview_characters"]]
    request = {"name": "gate_result_read", "arguments": {"result_ref": metadata["result_ref"], "limit": 901}}
    denied = rpc(browser, other["token"], "tools/call", request).json()["result"]
    assert denied["isError"] and denied["structuredContent"]["error"]["code"] == "result_unavailable"
    chunks, offset = [], 0
    while True:
        result = rpc(browser, token["token"], "tools/call", {**request, "arguments": {**request["arguments"], "offset": offset}}).json()["result"]
        page = result["structuredContent"]
        chunks.append(page["text"])
        offset = page["next_offset"]
        if not page["has_more"]:
            break
    assert "".join(chunks) == text and len(calls) == 1
    update(browser, token, result_budget={"enabled": False})
    assert rpc(browser, token["token"], "tools/call", request).json()["result"]["isError"]
    update(browser, token, result_budget=budget)
    assert rpc(browser, token["token"], "tools/call", request).json()["result"]["isError"]
    assert len(calls) == 1


def test_capacity_preserves_original_result(browser, gate):
    token = legacy(gate)
    text = "x" * 5000
    calls, _ = gateway(gate, {"content": [{"type": "text", "text": text}]}, {"entry_bytes": 2000})
    update(browser, token, tool_discovery_mode="direct", result_budget={"enabled": True, "max_characters": 1024})
    result = rpc(browser, token["token"], "tools/call", {"name": "mcp__A__read", "arguments": {}}).json()["result"]
    assert result["content"][0]["text"] == text
    assert result["_meta"][META_KEY] == {"schema_version": 1, "applied": False, "reason": "capacity"}
    assert len(calls) == 1


@pytest.mark.parametrize("route", ["catalog", "pin", "direct"])
@pytest.mark.parametrize("capacity", [False, True])
def test_current_sdk_plain_text_result_keeps_protocol_envelope_and_budget(browser, gate, route, capacity):
    text = "SDK 世界🌱\n" * 400
    params, headers = build_protocol_request("tools/call", {"name": "gate_demo_echo", "arguments": {"message": text}},
                                             client_name="budget-test", client_version="1")
    with TestClient(create_demo_app(), base_url="http://127.0.0.1:18880") as demo:
        response = demo.post("/mcp", headers=headers,
                             json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
        assert response.status_code == 200
        original = response.json()["result"]
    assert original["resultType"] == "complete" and set(original["_meta"]) == {SERVER_INFO_META_KEY}
    assert original["content"] == [{"type": "text", "text": text}]
    token = legacy(gate)
    calls, cache = gateway(gate, original, {"entry_bytes": 2000} if capacity else None)
    update(browser, token, tool_discovery_mode="direct" if route == "direct" else "on_demand",
           pinned_tools=[{"kind": "tool", "tool_ref": "mcp.A.read"}],
           result_budget={"enabled": True, "max_characters": 1024})
    if route == "catalog":
        described = rpc(browser, token["token"], "tools/call", {
            "name": "gate_tool_describe", "arguments": {"tool_ref": "mcp.A.read"}}).json()["result"]["structuredContent"]
        call = {"name": "gate_tool_invoke", "arguments": {"tool_ref": "mcp.A.read",
                "schema_revision": described["schema_revision"], "arguments": {}}}
    else:
        tools = rpc(browser, token["token"]).json()["result"]["tools"]
        name = "mcp__A__read" if route == "direct" else next(t["name"] for t in tools if t["name"].startswith("gate_pinned_"))
        call = {"name": name, "arguments": {}}
    result = rpc(browser, token["token"], "tools/call", call).json()["result"]
    assert not result["isError"] and result["resultType"] == "complete"
    assert set(result["_meta"]) == {SERVER_INFO_META_KEY, META_KEY}
    assert len(calls) == 1
    budget = result["_meta"][META_KEY]
    if capacity:
        assert budget == {"schema_version": 1, "applied": False, "reason": "capacity"}
        assert result["content"] == original["content"]
    else:
        assert budget["applied"] and len(result["content"][0]["text"]) <= 1024
        page = rpc(browser, token["token"], "tools/call", {"name": "gate_result_read",
            "arguments": {"result_ref": budget["result_ref"], "limit": 4096}}).json()["result"]
        assert page["structuredContent"]["text"] == text and len(calls) == 1
    # The cache transformation itself must preserve the downstream stamp;
    # the gateway intentionally replaces serverInfo with its own identity.
    actor = gate["auth"]._principal_from_api_token(token["token"])
    transformed = cache.apply(original, actor, "", cache.capture(actor, "mcp.A.read"))
    assert transformed["_meta"][SERVER_INFO_META_KEY] == original["_meta"][SERVER_INFO_META_KEY]
    assert transformed["resultType"] == original["resultType"]
    assert META_KEY not in original["_meta"] and original["content"][0]["text"] == text


def test_cache_expiry_definition_revocation_and_external_proof_binding(browser, gate, monkeypatch):
    token = legacy(gate)
    _, cache = gateway(gate)
    update(browser, token, result_budget={"enabled": True, "max_characters": 1024})
    actor = gate["auth"]._principal_from_api_token(token["token"])
    target = cache.capture(actor, "mcp.A.read")
    original = {"content": [{"type": "text", "text": "x" * 4000}], "isError": False}
    response = cache.apply(original, actor, "", target)
    query = ResultRead(result_ref=response["_meta"][META_KEY]["result_ref"])
    assert cache.read(actor, "", query)["structuredContent"]["text"] == "x" * 4000
    gate["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE tool_id='mcp.A.read'")
    with pytest.raises(ToolExecutionError, match="unavailable"):
        cache.read(actor, "", query)
    external = replace(actor, auth_type="oauth", token_id=None, external_grant_id="grant", oauth_builtin=False)
    assert cache.identity(external, "Bearer first-jwt") != cache.identity(external, "Bearer second-jwt")
    monkeypatch.setattr("lingshu_gate.result_budget.time.monotonic", lambda: 1e20)
    with pytest.raises(ToolExecutionError, match="unavailable"):
        cache.read(actor, "", query)
    assert cache._total == 0


def test_noneligible_result_contracts_remain_unchanged(browser, gate):
    token = legacy(gate)
    _, cache = gateway(gate)
    update(browser, token, result_budget={"enabled": True, "max_characters": 1024})
    actor = gate["auth"]._principal_from_api_token(token["token"])
    target = cache.capture(actor, "mcp.A.read")
    text = {"type": "text", "text": "x" * 4000}
    for result in [
        {"content": [text], "isError": True}, {"content": [text, text], "isError": False},
        {"content": [{**text, "annotations": {}}], "isError": False},
        {"content": [text], "structuredContent": {"x": 1}, "isError": False},
        {"content": [text], "_meta": {"custom": "value"}, "isError": False},
        {"content": [text], "resultType": "input_required", "isError": False},
        {"content": [text], "resultType": None, "isError": False},
        {"content": [text], "_meta": None, "isError": False},
        {"content": [text], "_meta": {SERVER_INFO_META_KEY: {"name": "incomplete"}}, "isError": False},
        {"content": [text], "_meta": {SERVER_INFO_META_KEY: {"name": "demo", "version": "1", "custom": "value"}}, "isError": False},
        {"content": [text], "_meta": {SERVER_INFO_META_KEY: {"name": "demo", "version": "1",
                                    "icons": [{"src": "https://example.test/icon.png", "custom": "value"}]}}, "isError": False},
        {"content": [text], "_meta": {SERVER_INFO_META_KEY: {"name": "demo", "version": "1",
                                    "website_url": "https://example.test"}}, "isError": False},
        {"content": [text], "_meta": {SERVER_INFO_META_KEY: {"name": "demo", "version": "1"},
                                    "custom": "value"}, "isError": False},
        {"content": [{"type": "image", "data": "x", "mimeType": "image/png"}], "isError": False},
    ]:
        assert cache.apply(result, actor, "", target) is result
    assert target is not None
    result = {"content": [text], "isError": False}
    assert cache.apply(result, actor, "", replace(target, has_output_schema=True)) is result
    assert cache._total == 0 and not cache._entries
    standard_info = {"name": "demo", "version": "1", "title": "Demo", "description": "Text service",
                     "websiteUrl": "https://example.test", "icons": [{"src": "https://example.test/icon.png",
                         "mimeType": "image/png", "sizes": ["48x48"], "theme": "light"}]}
    standard = {**result, "resultType": "complete", "_meta": {SERVER_INFO_META_KEY: standard_info}}
    transformed = cache.apply(standard, actor, "", target)
    assert transformed["_meta"][META_KEY]["applied"]
    assert transformed["_meta"][SERVER_INFO_META_KEY] == standard_info
    assert standard == {**result, "resultType": "complete", "_meta": {SERVER_INFO_META_KEY: standard_info}}


@pytest.mark.parametrize("change", ["disabled", "revision", "ttl", "scopes"])
def test_result_read_rechecks_after_waiting_for_target(browser, gate, monkeypatch, change):
    token = legacy(gate)
    _, cache = gateway(gate)
    update(browser, token, result_budget={"enabled": True, "max_characters": 1024})
    actor = gate["auth"]._principal_from_api_token(token["token"])
    original = {"content": [{"type": "text", "text": "private original" * 400}], "isError": False}
    result = cache.apply(original, actor, "", cache.capture(actor, "mcp.A.read"))
    query = ResultRead(result_ref=result["_meta"][META_KEY]["result_ref"])
    entered, release = Event(), Event()
    validate = cache.validate_target
    current = [actor]
    def waited(principal, target):
        allowed = validate(principal, target)
        entered.set()
        assert release.wait(5)
        return allowed
    monkeypatch.setattr(cache, "validate_target", waited)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cache.read, actor, "", query, refresh_principal=lambda: current[0])
        try:
            assert entered.wait(5)
            if change == "disabled":
                update(browser, token, result_budget={"enabled": False})
            elif change == "revision":
                gate["db"].execute("UPDATE authorization_discovery SET revision=revision+1 WHERE kind='api' AND authorization_id=?", (token["id"],))
            elif change == "ttl":
                cache._entries[query.result_ref] = replace(cache._entries[query.result_ref], deadline=0)
            else:
                current[0] = replace(actor, scopes=())
                assert cache.identity(current[0], "") == cache.identity(actor, "")
        finally:
            release.set()
        with pytest.raises(ToolExecutionError, match="unavailable"):
            future.result(timeout=5)


@pytest.mark.parametrize("change", ["disabled", "scopes"])
def test_budget_application_after_target_wait_keeps_original_if_authority_changed(browser, gate, monkeypatch, change):
    token = legacy(gate)
    _, cache = gateway(gate)
    update(browser, token, result_budget={"enabled": True, "max_characters": 1024})
    actor = gate["auth"]._principal_from_api_token(token["token"])
    target = cache.capture(actor, "mcp.A.read")
    original = {"content": [{"type": "text", "text": "x" * 4000}], "isError": False}
    current = [actor]
    def continuation(principal, target):
        if change == "disabled":
            update(browser, token, result_budget={"enabled": False})
        else:
            current[0] = replace(actor, scopes=())
        return True
    monkeypatch.setattr(cache, "validate_target", continuation)
    assert cache.apply(original, actor, "", target, refresh_principal=lambda: current[0]) is original
    assert cache._total == 0 and not cache._entries

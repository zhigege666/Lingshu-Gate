"""Synthetic large catalogs must not expand or block a saved OAuth grant."""
from __future__ import annotations

import json
import statistics
import time
import tracemalloc

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_server import OAuthError
from lingshu_gate.transports.http import build_protocol_request
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, RESOURCE, enable, exchange, issue_code, mcp_request, refresh
from test_builtin_oauth import gate as gate


def _scaled_catalog(gate):
    """50,000 published definitions on exactly 5,000 synthetic services.

    The first 5,000 tools belong to 100 services, retaining the selection limit.
    Publish only synthetic fixture rows; no production policy is involved.
    """
    original = {tool.id: tool for tool in gate["registry"].list_definitions()}
    definitions = []
    for server_index in range(5000):
        server_id = "AB"[server_index] if server_index < 2 else f"synthetic-{server_index:04}"
        count = 50 if server_index < 100 else 10 if server_index < 1000 else 9
        for index in range(count):
            access = "read" if index % 2 == 0 else "write"
            key = f"mcp.{server_id}.{access}" if server_index < 2 and index < 2 else f"mcp.{server_id}.tool-{index}"
            definitions.append(original.get(key) or ToolDefinition(id=key, name=f"Synthetic tool {index}",
                description="Synthetic scaling fixture", source="mcp", permission=access,
                metadata={"server_id": server_id, "original_tool_name": f"fixture_{index}"}))
    assert len(definitions) == 50000 and len({tool.metadata["server_id"] for tool in definitions}) == 5000
    permission = gate["db"].query_one("SELECT id FROM permission_types WHERE code='write'")["id"]
    with gate["db"].session() as connection:
        connection.executemany("INSERT OR IGNORE INTO mcp_resource_grants "
            "(id,subject_type,subject_id,server_id,tool_id,permission_type_id,created_by,created_at,updated_at) "
            "VALUES(?,'user',?,?,'',?,?,?,?)", [(f"synthetic-grant-{index}", gate["users"]["alice"]["id"],
                tool.metadata["server_id"], permission, gate["admin"]["id"], "2026-10-05T00:00:00+00:00",
                "2026-10-05T00:00:00+00:00") for index, tool in enumerate(definitions) if index == 0
                or tool.metadata["server_id"] != definitions[index - 1].metadata["server_id"]])
    return definitions


def _install(gate, definitions):
    for tool in definitions:
        gate["registry"].register(tool, lambda arguments: {"synthetic": True}, replace=True)
    with gate["db"].session() as connection:
        gate["access"]._synchronize_tools(connection, definitions)
        connection.executemany("UPDATE mcp_tool_classifications SET effective_access=?,status='published',source='manual',"
            "reviewed_by=?,reviewed_at='2026-10-05T00:00:00+00:00' WHERE server_id=? AND tool_id=?",
            [(tool.permission, gate["admin"]["id"], tool.metadata["server_id"], tool.id) for tool in definitions])


def test_one_saved_tool_survives_more_than_5000_owner_candidates(gate, monkeypatch):
    client, secret = enable(gate)
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client))
    for index in range(5000):
        tool = ToolDefinition(id=f"mcp.A.extra-{index}", name=f"Read extra {index}",
            description="Synthetic scaling tool", source="mcp", permission="read",
            metadata={"server_id": "A", "original_tool_name": f"list_extra_{index}"})
        gate["registry"].register(tool, lambda arguments: {"synthetic": True})
    with gate["db"].session() as connection:
        gate["access"]._synchronize_tools(connection, gate["registry"].list_definitions())
        connection.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published',"
            "source='manual',reviewed_by=?,reviewed_at='2026-10-05T00:00:00+00:00' WHERE tool_id LIKE 'mcp.A.extra-%'",
            (gate["admin"]["id"],))
    register_mcp_gateway_route(gate["app"], gate["settings"], gate["registry"], gate["access"],
        gate["auth"].authenticate_mcp_request,
        McpOAuthDiscoveryBoundary(OAuthProtectedResourceMetadata(RESOURCE, (ISSUER,))))
    with TestClient(gate["app"], base_url=ISSUER) as browser:
        params, headers = build_protocol_request("server/discover", None, client_name="Synthetic", client_version="1")
        response = browser.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": params},
            headers={**headers, "Authorization": "Bearer " + tokens["access_token"]})
        assert response.status_code == 200, response.text
    def forbidden_full_catalog():
        raise AssertionError("Saved-grant verification must not read the entire registry")
    monkeypatch.setattr(gate["registry"], "list_definitions", forbidden_full_catalog)
    principal = gate["server"].verify(tokens["access_token"])
    assert principal.external_tool_ids == ("mcp.A.read",)
    rotated = refresh(gate["server"], client, secret, tokens["refresh_token"])
    assert gate["server"].verify(rotated["access_token"]).external_tool_ids == ("mcp.A.read",)


@pytest.mark.parametrize("selected_count", [1, 100, 5000])
def test_5000_services_50000_tools_verify_refresh_and_call_only_saved_targets(gate, monkeypatch, selected_count):
    definitions = _scaled_catalog(gate)
    _install(gate, definitions[:5000])
    client, secret = enable(gate)
    selected = [tool.id for tool in definitions[:selected_count]]
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client, tools=selected))
    _install(gate, definitions[5000:])
    requested = []
    lookup = gate["registry"].get_definitions
    def targeted(ids):
        ids = list(ids)
        requested.append(len(ids))
        assert len(ids) <= selected_count
        return lookup(ids)
    def forbidden(*args, **kwargs):
        raise AssertionError("Grant authentication or invocation traversed the full catalog")
    monkeypatch.setattr(gate["registry"], "get_definitions", targeted)
    monkeypatch.setattr(gate["registry"], "list_definitions", forbidden)
    monkeypatch.setattr(gate["access"], "list_classifications", forbidden)
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        principal = gate["server"].verify(tokens["access_token"])
        timings.append((time.perf_counter() - started) * 1000)
        assert set(principal.external_tool_ids) == set(selected)
    assert requested == [selected_count] * 3
    tracemalloc.start()
    gate["server"].verify(tokens["access_token"])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    started = time.perf_counter()
    rotated = refresh(gate["server"], client, secret, tokens["refresh_token"])
    refreshed = gate["server"].verify(rotated["access_token"])
    refresh_ms = (time.perf_counter() - started) * 1000
    assert set(refreshed.external_tool_ids) == set(selected)
    assert gate["access"].invoke_tool(gate["registry"], refreshed, selected[0], {}).output == {"synthetic": True}
    with pytest.raises(AccessDeniedError):
        gate["access"].invoke_tool(gate["registry"], refreshed, definitions[5001].id, {})
    assert gate["db"].query_one("SELECT COUNT(*) AS count FROM gate_oauth_families WHERE revoked_at IS NULL")["count"] == 1
    assert len(gate["server"].store.grants(gate["users"]["alice"]["id"])[0]["tools"]) == selected_count
    print("SCALING_METRIC " + json.dumps({"services": 5000, "catalog_tools": 50000, "grant_tools": selected_count,
        "full_registry_projections": 0, "definition_targets_per_verify": selected_count,
        "verify_median_ms": round(statistics.median(timings), 3), "refresh_and_verify_ms": round(refresh_ms, 3),
        "verify_incremental_peak_bytes": peak}, sort_keys=True))


@pytest.mark.parametrize("change", ["missing", "unpublished", "reclassified", "owner_grant", "client_scope", "family_scope"])
def test_targeted_grant_rechecks_current_authority_and_never_admits_other_tools(gate, monkeypatch, change):
    client, secret = enable(gate)
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client))
    if change == "missing":
        gate["registry"].unregister_by_metadata("original_tool_name", "read", source="mcp")
    elif change == "unpublished":
        gate["db"].execute("UPDATE mcp_tool_classifications SET status='pending' WHERE tool_id='mcp.A.read'")
    elif change == "reclassified":
        gate["access"].set_classification(server_id="A", tool_id="mcp.A.read", access="write", destructive=False,
            idempotent=False, reviewer_id=gate["admin"]["id"])
        gate["access"].publish_classifications(server_id="A", reviewer_id=gate["admin"]["id"])
    elif change == "owner_grant":
        gate["db"].execute("DELETE FROM mcp_resource_grants WHERE subject_type='user' AND subject_id=?",
            (gate["users"]["alice"]["id"],))
    elif change == "client_scope":
        gate["db"].execute("UPDATE gate_oauth_clients SET scopes_json='[\"tools.invoke\"]' WHERE id=?", (client["id"],))
    else:
        gate["db"].execute("UPDATE gate_oauth_families SET scopes_json='[\"tools.invoke\"]'")
    monkeypatch.setattr(gate["registry"], "list_definitions", lambda: pytest.fail("Full catalog projection"))
    if change == "client_scope":
        with pytest.raises(HTTPException) as denied:
            gate["auth"].authenticate_mcp_request(mcp_request(tokens["access_token"]))
        assert denied.value.status_code == 401
        return
    assert gate["server"].verify(tokens["access_token"]).external_tool_ids == ()
    assert not gate["access"].evaluate(gate["server"].verify(tokens["access_token"]),
        ToolDefinition(id="mcp.unoffered.read", name="Unoffered", description="Synthetic", source="mcp",
            metadata={"server_id": "unoffered"}))["allowed"]


def test_signed_jwt_tool_claims_cannot_add_database_grant_targets(gate, monkeypatch):
    client, secret = enable(gate)
    token = exchange(gate["server"], client, secret, issue_code(gate, client))["access_token"]
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["tool_ids"] = ["mcp.A.read", "mcp.A.write", "mcp.B.read"]
    claims["tools"] = {key: {"access": "write"} for key in claims["tool_ids"]}
    key = gate["db"].query_one("SELECT encrypted_private FROM gate_oauth_keys WHERE active=1")
    private = gate["server"]._fernet().decrypt(key["encrypted_private"].encode())
    signed = jwt.encode(claims, private, algorithm="RS256", headers=header)
    monkeypatch.setattr(gate["registry"], "list_definitions", lambda: pytest.fail("Full catalog projection"))
    assert gate["server"].verify(signed).external_tool_ids == ("mcp.A.read",)


@pytest.mark.parametrize("limit", ["tools", "servers"])
def test_invalid_stored_grant_cannot_bypass_selection_limits(gate, monkeypatch, limit):
    client, secret = enable(gate)
    token = exchange(gate["server"], client, secret, issue_code(gate, client))["access_token"]
    grant = gate["server"].store.grants(gate["users"]["alice"]["id"])[0]
    original = grant["tools"]["mcp.A.read"]
    count = 5001 if limit == "tools" else 101
    invalid = {f"synthetic-{index}": {**original, "id": f"synthetic-{index}",
        "server_id": "A" if limit == "tools" else f"synthetic-{index}"} for index in range(count)}
    gate["db"].execute("UPDATE gate_oauth_grants SET tools_json=? WHERE id=?", (json.dumps(invalid), grant["id"]))
    monkeypatch.setattr(gate["registry"], "get_definitions", lambda ids: pytest.fail("Invalid grant must fail before lookup"))
    with pytest.raises(OAuthError, match="invalid_grant"):
        gate["server"].verify(token)

"""Real OAuth and MCP entry points for combined HTTP/credential administration.

The fixture has an isolated database/key and fake downstream peer. This flow
never requests a connection, so no peer traffic is expected at all.
"""
from __future__ import annotations

import json
import time

import pytest

from lingshu_gate.domain.oauth_management import MANAGEMENT_SCOPES, MANAGEMENT_TOOL_IDS
from test_builtin_oauth import REDIRECT
from test_external_mcp_configuration import apply_arguments, manifest
from test_external_mcp_configuration import gate as gate
from test_oauth_management_e2e import browser as browser
from test_oauth_management_e2e import call, enable_management, output, protocol, tokens


def apply_http(browser, bearer, plan):
    started = output(call(browser, bearer, "gate_http_mcp_apply", apply_arguments(plan, "apply-" + plan["plan_id"])))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = output(call(browser, bearer, "gate_http_mcp_status", {"operation_id": started["operation_id"]}))
        if current["terminal"]:
            assert current["status"] == "success", current
            return current
        time.sleep(.01)
    pytest.fail("Synthetic HTTP MCP operation did not complete")


def test_oauth_mcp_combined_credential_and_http_lifecycle(gate, browser, caplog):
    enable_management(gate, browser)
    server = gate["app"].state.oauth_server
    created = server.create_client("Synthetic combined management", [REDIRECT], sorted(MANAGEMENT_SCOPES), resources=["management"])
    target = "synthetic-combined"
    actions = ["create", "update", "delete", "revoke_trust", "restore_trust",
               "credential.read", "credential.create", "credential.update", "credential.delete"]
    bearer = tokens(browser, created, scope=" ".join(sorted(MANAGEMENT_SCOPES)),
                    tools=sorted(MANAGEMENT_TOOL_IDS), targets={target: actions})["access_token"]
    listed = protocol(browser, bearer, "tools/list")
    assert {item["name"] for item in listed.json()["result"]["tools"]} == MANAGEMENT_TOOL_IDS
    database = gate["service"].database
    database.execute("UPDATE retention_policy SET payload_mode='redacted'")
    secret, rotated = "Synthetic-Combined-Private-Value", "Synthetic-Combined-Rotated-Value"
    credential_body = {"credential_id": target, "name": "Synthetic combined", "value": secret,
        "http_scopes": [{"server_id": target, "origin": "http://10.23.45.67:8080"}],
        "idempotency_key": "combined-credential-create"}
    credential = output(call(browser, bearer, "gate_credential_create", credential_body))
    assert credential["value_saved"] and not credential["connection_verified"]
    replay = output(call(browser, bearer, "gate_credential_create", credential_body))
    assert replay["idempotent_replay"] and replay["updated_at"] == credential["updated_at"]
    data = manifest(target, "http://10.23.45.67:8080/mcp")
    data["auto_start"] = False
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:" + target + "}"}
    planned = output(call(browser, bearer, "gate_http_mcp_plan", {"mode": "create", "manifest": data}))
    assert planned["network_contacted"] is False
    assert not gate["service"].configs.list_configs().configs and not gate["calls"]
    saved = apply_http(browser, bearer, planned)
    assert saved["config_applied"] and saved["trust_applied"]
    assert saved["http_trust"]["state"] == "active"
    credential = output(call(browser, bearer, "gate_credential_get", {"credential_id": target}))
    assert credential["http_scopes"][0]["server_binding"] == saved["http_trust"]["server_binding"]
    changed = output(call(browser, bearer, "gate_credential_update", {"credential_id": target,
        "expected_revision": credential["updated_at"], "value": rotated, "idempotency_key": "combined-rotation"}))
    assert changed["value_saved"] and not changed["connection_verified"]
    assert changed["affected_connection_count"] == 1
    assert call(browser, bearer, "gate_credential_delete", {"credential_id": target,
        "expected_revision": changed["updated_at"], "idempotency_key": "combined-in-use-delete"}).get("isError")

    def plan(mode, **fields):
        status = output(call(browser, bearer, "gate_http_mcp_status", {"server_id": target}))
        return output(call(browser, bearer, "gate_http_mcp_plan", {"mode": mode,
            "expected_config_digest": status["config_digest"], **fields}))

    revoked = apply_http(browser, bearer, plan("revoke_trust", server_id=target))
    assert revoked["http_trust"]["revoked"]
    data["name"] = "Synthetic renamed while revoked"
    preserved = apply_http(browser, bearer, plan("update", manifest=data))
    assert preserved["http_trust"]["revoked"] and preserved["connection_state"] == "revoked"
    restored = apply_http(browser, bearer, plan("restore_trust", server_id=target))
    assert restored["http_trust"]["state"] == "active"
    deleted = apply_http(browser, bearer, plan("delete", server_id=target))
    assert deleted["config_deleted"] and not deleted["shared_credentials_deleted"]
    assert not gate["service"].configs.list_configs().configs
    retained = output(call(browser, bearer, "gate_credential_get", {"credential_id": target}))
    removed = output(call(browser, bearer, "gate_credential_delete", {"credential_id": target,
        "expected_revision": retained["updated_at"], "idempotency_key": "combined-final-delete"}))
    assert removed["id"] == target
    assert output(call(browser, bearer, "gate_credential_list", {}))["credentials"] == []
    assert not gate["calls"]
    persisted = json.dumps([dict(row) for row in database.query_all("SELECT * FROM invocation_payloads")])
    journal = json.dumps([dict(row) for row in database.query_all("SELECT * FROM mcp_idempotent_operations")])
    for value in (secret, rotated, bearer):
        assert value not in persisted + journal + caplog.text

"""Group management uses the current admin boundary and existing audit path."""
from dataclasses import replace

import pytest

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.mcp_group_mcp import GROUP_MANAGEMENT_TOOL_IDS, register_mcp_group_tools

from test_mcp_groups import draft
from test_mcp_groups import gate as gate


def register(gate, scopes):
    register_mcp_group_tools(gate["registry"], gate["service"])
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic group manager", scopes=scopes)
    return gate["auth"]._principal_from_api_token(token["token"])


def invoke(gate, actor, name, arguments):
    return gate["access"].invoke_tool(gate["registry"], actor, name, arguments)


def test_admin_token_crud_is_confirmed_cas_audited_and_copies_no_credentials(gate):
    actor = register(gate, ["operations.manage", "tools.read", "tools.invoke"])
    body = draft(default_instance_id="instance-0")
    first = invoke(gate, actor, "gate_mcp_group_save", {"draft": body})
    assert first.ok and first.output["default_instance_id"] == "instance-0"
    replay = invoke(gate, actor, "gate_mcp_group_save", {"draft": body})
    assert replay.ok and replay.output["id"] == first.output["id"]
    assert invoke(gate, actor, "gate_mcp_group_list", {}).output["total"] == 1
    group_id = first.output["id"]
    assert invoke(gate, actor, "gate_mcp_group_get", {"group_id": group_id}).output["id"] == group_id
    update = draft(expected_revision=1, name="Updated by MCP")
    result = invoke(gate, actor, "gate_mcp_group_save", {"group_id": group_id, "draft": update})
    assert result.ok and result.output["revision"] == 2
    stale = invoke(gate, actor, "gate_mcp_group_delete", {"group_id": group_id, "expected_revision": 1, "confirmed": True})
    assert not stale.ok and stale.output["error"]["code"] == "group_revision_conflict"
    deleted = invoke(gate, actor, "gate_mcp_group_delete", {"group_id": group_id, "expected_revision": 2, "confirmed": True})
    assert deleted.ok and deleted.output["deleted"]
    assert not gate["database"].query_all("SELECT * FROM mcp_resource_grants")
    assert not gate["database"].query_all("SELECT * FROM user_downstream_credentials")
    assert gate["database"].query_one("SELECT COUNT(*) FROM events WHERE subject_type='mcp_group'")[0] == 3
    gate["runtime"].apply_manifest.assert_not_called()


def test_read_token_cannot_write_and_scope_revocation_is_live(gate):
    actor = register(gate, ["operations.manage", "tools.read"])
    assert invoke(gate, actor, "gate_mcp_group_list", {}).ok
    visible = gate["access"].visible_tools(actor, gate["registry"].list_definitions())
    assert {item.id for item in visible} == {"gate_mcp_group_list", "gate_mcp_group_get"}
    with pytest.raises(AccessDeniedError):
        invoke(gate, actor, "gate_mcp_group_save", {"draft": draft()})
    gate["database"].execute("UPDATE api_tokens SET revoked_at='2026-10-05T00:00:00Z' WHERE id=?", (actor.token_id,))
    response = invoke(gate, actor, "gate_mcp_group_list", {})
    assert not response.ok and response.output["error"]["code"] == "group_connection_invalid"


@pytest.mark.parametrize("change", ["session", "role", "oauth", "delegation", "confirmation", "endpoint"])
def test_group_tools_fail_closed_without_changing_existing_admin_boundary(gate, change):
    actor = register(gate, ["operations.manage", "tools.read", "tools.invoke"])
    body = {"draft": draft()}
    if change == "session":
        actor = gate["principal"]
    elif change == "role":
        gate["access"].set_user_roles(actor.id, ["operator"])
    elif change == "oauth":
        actor = replace(actor, auth_type="oauth")
    elif change == "delegation":
        actor = replace(actor, delegated_scopes=("tools.invoke",))
    elif change == "confirmation":
        body["draft"]["confirmed"] = False
    else:
        body["draft"]["endpoint"] = "https://mcp.example.test/alternate"
    try:
        result = invoke(gate, actor, "gate_mcp_group_save", body)
    except AccessDeniedError:
        pass
    else:
        assert not result.ok
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == 0
    assert len(GROUP_MANAGEMENT_TOOL_IDS) == 4

"""Live OAuth ceilings at the internal logical-routing boundary."""
import pytest

from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.domain.mcp_groups import McpGroupError

from test_builtin_oauth import enable, exchange, issue_code
from test_builtin_oauth import gate as gate


@pytest.mark.parametrize("change", ["grant", "family", "client", "config", "scopes", "physical_grant"])
def test_verified_oauth_proof_does_not_keep_revoked_or_wider_authority(gate, change):
    client, secret = enable(gate)
    tokens = exchange(gate["server"], client, secret, issue_code(gate, client))
    actor = gate["server"].verify(tokens["access_token"])
    assert current_tool_principal(gate["auth"], actor).external_tool_ids == ("mcp.A.read",)
    database = gate["db"]
    if change == "grant":
        database.execute("UPDATE gate_oauth_grants SET revoked_at=1 WHERE id=?", (actor.external_grant_id,))
    elif change == "family":
        database.execute("UPDATE gate_oauth_families SET revoked_at=1 WHERE id=?", (actor.oauth_family_id,))
    elif change == "client":
        database.execute("UPDATE gate_oauth_clients SET enabled=0 WHERE id=?", (actor.oauth_client_id,))
    elif change == "config":
        config = gate["server"].store.config()
        gate["server"].save_config({"enabled": False, "issuer": config["issuer"], "resource": config["resource"]}, config["revision"])
    elif change == "scopes":
        database.execute("UPDATE gate_oauth_clients SET scopes_json='[\"tools.invoke\"]' WHERE id=?", (actor.oauth_client_id,))
    else:
        database.execute("DELETE FROM mcp_resource_grants WHERE subject_id=?", (actor.id,))
    try:
        current = current_tool_principal(gate["auth"], actor)
    except McpGroupError as exc:
        assert exc.status == 403
    else:
        assert current.external_tool_ids == ()

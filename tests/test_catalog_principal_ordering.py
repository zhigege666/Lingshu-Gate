"""Authority order does not reject valid dispatch or conceal real revocation."""
from dataclasses import replace

import pytest

from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.domain.mcp_group_routing import logical_service_id
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.tool_catalog import CatalogDescribe, CatalogInvoke, ToolCatalog

from test_builtin_oauth import gate as _builtin_gate, enable, exchange, issue_code
from test_catalog_group_adapter import gate as gate, integrated as integrated, routing as routing, selected, opened
from test_mcp_group_external_authority import oauth_http as oauth_http, verified_actor
from test_mcp_groups import PASSWORD

builtin_gate = _builtin_gate


@pytest.mark.parametrize("logical", [False, True])
def test_system_and_custom_roles_dispatch_with_current_sorted_authority(gate, integrated, logical):
    catalog, group, peers = integrated
    gate["access"].save_role(code="aaa_custom", name="Synthetic extra role", description="", permissions=[])
    user = gate["auth"].create_user(username="synthetic-multiple-roles", password=PASSWORD, role="operator")
    gate["access"].set_user_roles(user["id"], ["operator", "aaa_custom"])
    actor, _, _ = gate["auth"].login(username=user["username"], password=PASSWORD)
    assert actor.role == "operator" and actor.roles == ("operator", "aaa_custom")
    for server in ("instance-0", logical_service_id(group["id"])):
        gate["access"].save_grant(subject_type="user", subject_id=actor.id, server_id=server,
            permission_type_code="read", created_by=gate["principal"].id)
    if logical:
        described = selected(catalog, group, actor)
        session = opened(catalog, described, actor)
    else:
        described = catalog.describe(actor, CatalogDescribe(tool_ref="mcp.instance-0.inspect"))
        session = None
    current = current_tool_principal(gate["auth"], actor)
    assert current.role == "aaa_custom" and current.roles == ("aaa_custom", "operator")
    response = catalog.invoke(actor, CatalogInvoke(tool_ref=described["tool_ref"], instance_id="instance-0",
        schema_revision=described["schema_revision"], session_id=session, arguments={}),
        refresh_principal=lambda: current_tool_principal(gate["auth"], actor))
    assert response.ok and peers["instance-0"].calls == [("inspect", {})]
    # Removing a role remains a real authority change, even if this target has a direct grant.
    gate["access"].set_user_roles(actor.id, ["operator"])
    try:
        denied = catalog.invoke(actor, CatalogInvoke(tool_ref=described["tool_ref"], instance_id="instance-0",
            schema_revision=described["schema_revision"], session_id=session, arguments={}),
            refresh_principal=lambda: current_tool_principal(gate["auth"], actor))
        assert not denied.ok and denied.output["error"]["code"] == "catalog_identity_changed"
    except ToolExecutionError as error:
        assert error.code == "catalog_tool_unavailable"
    assert len(peers["instance-0"].calls) == 1


def test_builtin_saved_reverse_tool_order_allows_public_invoke(builtin_gate):
    env = builtin_gate
    env["access"].save_grant(subject_type="user", subject_id=env["users"]["alice"]["id"], server_id="B",
        permission_type_code="read", created_by=env["admin"]["id"])
    for tool in ("mcp.A.read", "mcp.B.read"):
        env["registry"].register(env["registry"].get_definition(tool), lambda arguments: {}, replace=True)
    client, secret = enable(env)
    tokens = exchange(env["server"], client, secret, issue_code(env, client, tools=["mcp.B.read", "mcp.A.read"]))
    actor = env["server"].verify(tokens["access_token"])
    assert actor.external_tool_ids == ("mcp.B.read", "mcp.A.read")
    current = current_tool_principal(env["auth"], actor)
    assert current.external_tool_ids == ("mcp.A.read", "mcp.B.read")
    catalog = ToolCatalog(env["registry"], env["access"])
    for tool in actor.external_tool_ids:
        described = catalog.describe(actor, CatalogDescribe(tool_ref=tool))
        assert catalog.invoke(actor, CatalogInvoke(tool_ref=tool, schema_revision=described["schema_revision"],
            arguments={}), refresh_principal=lambda: current_tool_principal(env["auth"], actor)).ok
    assert env["db"].query_one("SELECT COUNT(*) FROM invocation_audits WHERE outcome='success'")[0] == 2


def test_external_grant_reverse_collections_keep_proof_and_access_ceiling(oauth_http):
    env, state = oauth_http, oauth_http.state
    store = state.external_connection_store
    saved = env.grants["alice"]
    payload = {key: value for key, value in saved.items()
        if key not in {"id", "user_id", "revision", "revoked_at", "created_at", "updated_at"}}
    payload.update(server_allowlist=list(reversed(saved["server_allowlist"])),
        tool_allowlist=list(reversed(saved["tool_allowlist"])), access=["write", "read"])
    saved = store.update_grant(env.users["alice"]["id"], saved["id"], payload, saved["revision"])
    actor = verified_actor(env)
    assert actor.external_access == ("write", "read")
    assert actor.external_tool_ids == tuple(payload["tool_allowlist"])
    actor = replace(actor, scopes=tuple(reversed(actor.scopes)),
        permissions=tuple(reversed(actor.permissions)))
    current = current_tool_principal(state.auth_store, actor)
    assert current.external_access == ("read", "write") and current.external_tool_ids != actor.external_tool_ids
    catalog = state.tool_catalog
    described = catalog.describe(actor, CatalogDescribe(tool_ref="mcp.B.read"))
    request = CatalogInvoke(tool_ref=described["tool_ref"], schema_revision=described["schema_revision"], arguments={})
    assert catalog.invoke(actor, request, refresh_principal=lambda: current_tool_principal(state.auth_store, actor)).ok
    assert env.calls["mcp.B.read"] == 1
    # A smaller delegated set or changed client proof must still fail before business dispatch.
    for changed in (replace(current, external_access=("read",)),
                    replace(current, external_tool_ids=("mcp.A.read",)),
                    replace(current, oauth_client_id="other-synthetic-client")):
        denied = catalog.invoke(actor, request, refresh_principal=lambda: changed)
        assert not denied.ok and denied.output["error"]["code"] == "catalog_identity_changed"
    assert env.calls["mcp.B.read"] == 1
    payload["tool_allowlist"].remove("mcp.B.read")
    store.update_grant(actor.id, saved["id"], payload, saved["revision"])
    denied = catalog.invoke(actor, request, refresh_principal=lambda: current_tool_principal(state.auth_store, actor))
    assert not denied.ok and denied.output["error"]["code"] == "catalog_identity_changed"
    assert env.calls["mcp.B.read"] == 1
    rows = state.access_store.database.query_all("SELECT outcome FROM invocation_audits WHERE tool_id='mcp.B.read'")
    assert [row[0] for row in rows] == ["success"] + ["not_invoked"] * 4

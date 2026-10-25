"""New management authority must not expand old grants, families or targets."""
from __future__ import annotations

from dataclasses import fields

import pytest

from lingshu_gate.domain.oauth_management import (
    CREDENTIAL_MANAGEMENT_TOOL_IDS, HTTP_MANAGEMENT_TOOL_IDS, LEGACY_MANAGEMENT_TOOL_IDS,
    MANAGEMENT_READ_TOOLS, MANAGEMENT_SCOPES, MANAGEMENT_TOOL_IDS, management_tool_server,
)
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_server import OAuthError
from lingshu_gate.registry import ToolInvocationContext
from lingshu_gate.transports.oauth import McpOAuthDiscoveryBoundary, OAuthProtectedResourceMetadata
from test_builtin_oauth import ISSUER, REDIRECT
from test_builtin_oauth import gate as gate
from test_oauth_management_resource import MANAGEMENT_RESOURCE, management_tokens, setup_management


def register_extended_tools(gate):
    for tool_id in sorted(HTTP_MANAGEMENT_TOOL_IDS | CREDENTIAL_MANAGEMENT_TOOL_IDS):
        gate["registry"].register(ToolDefinition(id=tool_id, name=tool_id, source="builtin",
            description="Synthetic extended management tool", permission="read" if tool_id in MANAGEMENT_READ_TOOLS else "write",
            metadata={"server_id": management_tool_server(tool_id)}), lambda arguments: {"synthetic": True})


def context(principal):
    names = {item.name for item in fields(ToolInvocationContext)}
    values = {name: getattr(principal, name) for name in names if hasattr(principal, name)}
    values.update(actor_id=principal.id, correlation_id="synthetic-management-authority", oauth_grant_id=principal.external_grant_id)
    return ToolInvocationContext(**values)


def extended_connection(gate, targets):
    setup_management(gate)
    register_extended_tools(gate)
    created = gate["server"].create_client("Synthetic credentials", [REDIRECT], sorted(MANAGEMENT_SCOPES), resources=["management"])
    tokens = management_tokens(gate, created["client"], created["client_secret"],
        scopes=" ".join(sorted(MANAGEMENT_SCOPES)), tools=sorted(MANAGEMENT_TOOL_IDS), targets=targets)
    return created, tokens, gate["server"].verify(tokens["access_token"], expected_resource=MANAGEMENT_RESOURCE)


def test_legacy_grant_keeps_its_four_tools_after_new_capabilities_are_registered(gate):
    client, secret, _, _ = setup_management(gate)
    tokens = management_tokens(gate, client, secret)
    before = gate["server"].verify(tokens["access_token"], expected_resource=MANAGEMENT_RESOURCE)
    register_extended_tools(gate)
    after = gate["server"].verify(tokens["access_token"], expected_resource=MANAGEMENT_RESOURCE)
    assert set(after.external_tool_ids) == LEGACY_MANAGEMENT_TOOL_IDS
    assert after.oauth_tool_snapshots == before.oauth_tool_snapshots
    with pytest.raises(OAuthError, match="management_tool_not_authorized"):
        gate["server"].management_authority(context(after), "gate_http_mcp_plan", target_id="synthetic-external", action="create")


def test_credential_tools_require_their_separate_requested_scope(gate):
    setup_management(gate)
    register_extended_tools(gate)
    owner = gate["management_principal"]
    catalog = gate["server"].catalog(owner, ["operations.manage", "tools.invoke"], resource=MANAGEMENT_RESOURCE)
    assert HTTP_MANAGEMENT_TOOL_IDS <= catalog.keys()
    assert not CREDENTIAL_MANAGEMENT_TOOL_IDS & catalog.keys()
    full = gate["server"].catalog(owner, sorted(MANAGEMENT_SCOPES), resource=MANAGEMENT_RESOURCE)
    assert CREDENTIAL_MANAGEMENT_TOOL_IDS <= full.keys()
    assert full["gate_credential_get"]["server_id"] == "gate_credentials"


@pytest.mark.parametrize("actions,allowed_tool,allowed_action,denied_tool,denied_action", [
    (["create"], "gate_http_mcp_plan", "create", "gate_credential_create", "credential.create"),
    (["credential.read"], "gate_credential_get", "credential.read", "gate_http_mcp_status", None),
    (["delete"], "gate_http_mcp_plan", "delete", "gate_credential_delete", "credential.delete"),
])
def test_service_and_credential_actions_with_identical_ids_do_not_cross(gate, actions, allowed_tool, allowed_action, denied_tool, denied_action):
    _, _, principal = extended_connection(gate, {"synthetic-same-id": actions})
    server, proof = gate["server"], context(principal)
    assert server.management_authority(proof, allowed_tool, target_id="synthetic-same-id", action=allowed_action)
    with pytest.raises(OAuthError, match="management_target_not_authorized"):
        server.management_authority(proof, denied_tool, target_id="synthetic-same-id", action=denied_action)


def test_client_scope_expansion_does_not_expand_an_existing_token_family(gate):
    client, secret, _, _ = setup_management(gate)
    tokens = management_tokens(gate, client, secret)
    register_extended_tools(gate)
    gate["server"].update_client(client["id"], client["revision"], enabled=True, name=client["name"],
        redirects=client["redirect_uris"], scopes=sorted(MANAGEMENT_SCOPES), resources=["management"])
    refreshed = gate["server"].token({"grant_type": "refresh_token", "resource": MANAGEMENT_RESOURCE,
        "refresh_token": tokens["refresh_token"]}, client["id"], secret)
    assert "credentials.manage.system" not in refreshed["scope"].split()
    principal = gate["server"].verify(refreshed["access_token"], expected_resource=MANAGEMENT_RESOURCE)
    assert set(principal.external_tool_ids) == LEGACY_MANAGEMENT_TOOL_IDS


def test_live_credential_scope_revocation_blocks_a_previously_verified_proof(gate):
    created, _, principal = extended_connection(gate, {"synthetic-credential": ["credential.read"]})
    client = created["client"]
    server, proof = gate["server"], context(principal)
    assert server.management_authority(proof, "gate_credential_get", target_id="synthetic-credential", action="credential.read")
    server.update_client(client["id"], client["revision"], enabled=True, name=client["name"], redirects=client["redirect_uris"],
        scopes=["operations.manage", "tools.invoke"], resources=["management"])
    with pytest.raises(OAuthError, match="management_scope_insufficient"):
        server.management_authority(proof, "gate_credential_get", target_id="synthetic-credential", action="credential.read")


def test_narrowing_a_grant_keeps_only_the_scopes_needed_by_retained_tools(gate):
    _, _, principal = extended_connection(gate, {"synthetic-credential": ["credential.read"]})
    server = gate["server"]
    grant = next(item for item in server.store.grants(principal.id) if item["id"] == principal.external_grant_id)
    narrowed = server.narrow_grant(principal.id, grant["id"], grant["revision"], ["gate_credential_get"],
        grant["expires_at"], grant["rate_per_minute"], grant["concurrency"])
    assert set(narrowed["scopes"]) == {"operations.manage", "credentials.manage.system"}
    assert set(server.refresh_verified_principal(principal).external_tool_ids) == {"gate_credential_get"}


def test_optional_credential_scope_is_not_added_to_the_default_challenge():
    metadata = OAuthProtectedResourceMetadata(MANAGEMENT_RESOURCE, (ISSUER,), tuple(sorted(MANAGEMENT_SCOPES)))
    boundary = McpOAuthDiscoveryBoundary(metadata, challenge_scopes=("operations.manage", "tools.invoke"))
    assert "credentials.manage.system" in metadata.document()["scopes_supported"]
    assert 'scope="operations.manage tools.invoke"' in boundary.challenge(None)
    with pytest.raises(ValueError):
        McpOAuthDiscoveryBoundary(metadata, challenge_scopes=("unoffered.scope",))


def test_connection_testing_needs_its_own_tool_snapshot_and_exact_target_action(gate):
    _, _, principal = extended_connection(gate, {"synthetic-peer": ["test"]})
    proof = context(principal)
    assert gate["server"].management_authority(proof, "gate_http_mcp_test", write=True,
                                               target_id="synthetic-peer", action="test")
    with pytest.raises(OAuthError, match="management_target_not_authorized"):
        gate["server"].management_authority(proof, "gate_http_mcp_plan", target_id="synthetic-peer", action="create")
    with pytest.raises(OAuthError, match="management_target_not_authorized"):
        gate["server"].management_authority(proof, "gate_http_mcp_test", write=True, target_id="another-peer", action="test")


def test_old_create_target_does_not_implicitly_allow_network_testing(gate):
    _, _, principal = extended_connection(gate, {"synthetic-peer": ["create"]})
    with pytest.raises(OAuthError, match="management_target_not_authorized"):
        gate["server"].management_authority(context(principal), "gate_http_mcp_test", write=True,
                                           target_id="synthetic-peer", action="test")

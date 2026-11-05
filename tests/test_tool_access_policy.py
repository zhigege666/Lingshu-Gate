"""Discovery is automatic; only trusted local policy can lower access."""
from dataclasses import replace

import pytest

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError, ClassificationConfirmationConflictError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_authorization_policy import server_binding, tool_snapshot
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.tool_access_policy import legacy_snapshot
from lingshu_gate.tool_catalog import CatalogSearch, ToolCatalog


@pytest.fixture
def policy(tmp_path):
    database = SQLiteDatabase("", tmp_path)
    access = AccessControlStore(database)
    database.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) "
                     "VALUES('writer','writer','unused','now','now')")
    actor = AuthPrincipal(id="writer", username="writer", role="operator", roles=("operator",),
                          permissions=("tools.read", "tools.invoke"))
    definition = ToolDefinition(id="mcp.example.query", name="Read records", description="Synthetic read suggestion", source="mcp", permission="default:read",
        input_schema={"type": "object"}, metadata={"server_id": "example", "original_tool_name": "query",
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}})
    registry = ToolRegistry()
    registry.register(definition, lambda arguments: {"ok": True})
    catalog = ToolCatalog(registry, access)
    catalog.synchronize()
    access.save_grant(subject_type="user", subject_id=actor.id, server_id="example",
                      permission_type_code="write", created_by=actor.id)
    return database, access, actor, definition, registry, catalog


def row(database, definition):
    return dict(database.query_one("SELECT * FROM mcp_tool_classifications WHERE tool_id=?", (definition.id,)))


def save(access, definition, level):
    return access.set_classification(server_id="example", tool_id=definition.id, access=level,
                                     destructive=False, idempotent=True, reviewer_id="writer")


def test_untrusted_read_hints_never_lower_default_write_and_new_tool_needs_no_publish(policy):
    database, access, actor, definition, registry, catalog = policy
    decision = access.evaluate(actor, definition)
    assert decision["allowed"] and decision["required_access"] == "write"
    assert decision["policy_source"] == "default_write"
    assert access.invoke_tool(registry, actor, definition.id, {}).output == {"ok": True}
    assert [item["tool_ref"] for item in catalog.search(actor, CatalogSearch())["tools"]] == [definition.id]
    classification = row(database, definition)
    assert classification["status"] == "pending" and classification["reviewed_at"] is None
    assert classification["reviewed_by"] is None and classification["effective_access"] == "unknown"
    read_token = replace(actor, auth_type="token", scopes=("tools.read",))
    assert access.visible_tools(read_token, [definition]) == []
    assert catalog.search(read_token, CatalogSearch())["tools"] == []
    access.save_grant(subject_type="user", subject_id=actor.id, server_id="example",
                      permission_type_code="read", created_by=actor.id)
    assert not access.evaluate(actor, definition)["allowed"]


def test_local_save_disable_and_restore_default_take_effect_once_without_publication(policy):
    database, access, actor, definition, _, catalog = policy
    read_actor = replace(actor, auth_type="token", scopes=("tools.read",))
    configured = save(access, definition, "read")
    assert configured["status"] == "pending" and configured["required_access"] == "read"
    assert access.evaluate(read_actor, definition)["allowed"]
    assert catalog.search(read_actor, CatalogSearch())["tools"]
    disabled = save(access, definition, "unknown")
    assert disabled["required_access"] == "none"
    assert access.visible_tools(actor, [definition]) == []
    assert access.visible_tools(replace(actor, role="admin", roles=("admin",)), [definition]) == []
    restored = access.reset_tool_access_policy(definition, reviewer_id=actor.id)
    assert restored["required_access"] == "write" and restored["policy_source"] == "default_write"
    assert restored["reviewed_at"] is None
    assert access.evaluate(actor, definition)["allowed"]
    assert not access.evaluate(read_actor, definition)["allowed"]
    assert database.query_one("SELECT COUNT(*) FROM mcp_resource_grants")[0] == 1


def test_metadata_changes_preserve_local_access_but_invalidate_safety_and_stale_editor(policy):
    database, access, actor, definition, registry, catalog = policy
    save(access, definition, "read")
    access.publish_classifications(reviewer_id=actor.id, tool_ids=[definition.id])
    before = row(database, definition)
    changed = definition.model_copy(update={"description": "Changed upstream description",
        "metadata": {**definition.metadata, "outputSchema": {"type": "object"}}})
    registry.update_definition(changed)
    catalog.synchronize()
    after = row(database, changed)
    assert after["status"] == "stale" and after["effective_access"] == "unknown"
    assert after["required_access"] == "read" and access.evaluate(actor, changed)["allowed"]
    assert tool_snapshot(definition, before) == tool_snapshot(changed, after)
    with pytest.raises(ClassificationConfirmationConflictError):
        access.set_classification(server_id="example", tool_id=definition.id, access="write", destructive=False,
            idempotent=False, reviewer_id=actor.id, expected_fingerprint=before["fingerprint"])
    with pytest.raises(ClassificationConfirmationConflictError):
        access.reset_tool_access_policy(changed, reviewer_id=actor.id, expected_fingerprint=before["fingerprint"])
    assert row(database, changed)["required_access"] == "read"


def test_legacy_valid_exact_grant_survives_upgrade_but_not_local_access_change(policy):
    database, access, actor, definition, _, _ = policy
    database.execute("UPDATE mcp_tool_classifications SET status='published',effective_access='read',source='manual',"
        "reviewed_by='writer',reviewed_at='2026-01-01',access_policy_source='unresolved',required_access='write'")
    previous = row(database, definition)
    old_snapshot = legacy_snapshot(previous)
    access.synchronize_tools([definition])
    migrated = row(database, definition)
    assert migrated["required_access"] == "read" and migrated["legacy_authorization_snapshot"] == old_snapshot
    assert migrated["reviewed_at"] == previous["reviewed_at"]
    with database.session() as connection:
        binding = server_binding(connection, "example")
    token = replace(actor, auth_type="token", scopes=("tools.read", "tools.invoke"),
        api_token_authorization_mode="independent", api_token_tool_snapshots=((definition.id, old_snapshot),),
        api_token_tool_bindings=((definition.id, binding),))
    assert access.evaluate(token, definition)["allowed"]
    changed = definition.model_copy(update={"description": "Updated harmless display metadata"})
    assert access.visible_tools(token, [changed])
    save(access, changed, "write")
    assert not access.evaluate(token, changed)["allowed"]
    assert row(database, changed)["legacy_authorization_snapshot"] == ""


def test_stale_legacy_review_does_not_become_trusted_read_policy(policy):
    database, access, actor, definition, _, _ = policy
    database.execute("UPDATE mcp_tool_classifications SET status='published',effective_access='read',source='manual',"
        "reviewed_by='writer',reviewed_at='2026-01-01',access_policy_source='unresolved',fingerprint='outdated'")
    access.synchronize_tools([definition])
    assert row(database, definition)["required_access"] == "write"
    assert row(database, definition)["legacy_authorization_snapshot"] == ""
    assert not access.evaluate(replace(actor, auth_type="token", scopes=("tools.read",)), definition)["allowed"]


def test_persisted_pre_policy_database_upgrades_without_losing_valid_exact_authority(policy, tmp_path):
    database, access, actor, definition, _, _ = policy
    save(access, definition, "read")
    access.publish_classifications(reviewer_id=actor.id, tool_ids=[definition.id])
    previous = row(database, definition)
    proof = legacy_snapshot(previous)
    with database.session() as connection:
        binding = server_binding(connection, "example")
        # Reconstruct the persisted pre-0025 schema with a real published row,
        # then reopen through the production migration runner.
        connection.execute("DROP TRIGGER gate_tool_policy_identity_changed")
        connection.execute("DROP TRIGGER gate_tool_policy_identity_deleted")
        for column in ("required_access", "access_policy_source", "access_policy_binding", "access_policy_revision", "legacy_authorization_snapshot"):
            connection.execute(f"ALTER TABLE mcp_tool_classifications DROP COLUMN {column}")
        connection.execute("DELETE FROM schema_migrations WHERE id IN ('0025_tool_access_policy','0026_tool_access_policy_revision','0027_tool_access_policy_identity_fail_closed')")
    reopened = SQLiteDatabase("", tmp_path)
    migrated_access = AccessControlStore(reopened)
    migrated_access.synchronize_tools([definition])
    token = replace(actor, auth_type="token", scopes=("tools.read",), api_token_authorization_mode="independent",
        api_token_tool_snapshots=((definition.id, proof),), api_token_tool_bindings=((definition.id, binding),))
    assert migrated_access.evaluate(token, definition)["allowed"]
    migrated = row(reopened, definition)
    assert migrated["required_access"] == "read" and migrated["legacy_authorization_snapshot"] == proof
    assert (migrated["fingerprint"], migrated["reviewed_by"], migrated["reviewed_at"]) == (
        previous["fingerprint"], previous["reviewed_by"], previous["reviewed_at"])


def test_new_tools_follow_existing_service_scope_but_never_expand_exact_or_read_scope(policy):
    database, access, actor, definition, registry, catalog = policy
    current = row(database, definition)
    with database.session() as connection:
        binding = server_binding(connection, "example")
    independent = replace(actor, auth_type="token", scopes=("tools.read", "tools.invoke"), api_token_authorization_mode="independent")
    exact = replace(independent, api_token_tool_snapshots=((definition.id, tool_snapshot(definition, current)),),
                    api_token_tool_bindings=((definition.id, binding),))
    assert not access.evaluate(replace(exact, api_token_tool_snapshots=((definition.id, ""),)), definition)["allowed"]
    writer = replace(independent, api_token_server_policies=(("example", binding, "write"),))
    reader = replace(independent, api_token_server_policies=(("example", binding, "read"),))
    added = definition.model_copy(update={"id": "mcp.example.new_read", "name": "Read more"})
    registry.register(added, lambda arguments: {})
    catalog.synchronize()
    assert access.evaluate(writer, added)["allowed"]
    assert not access.evaluate(exact, added)["allowed"]
    assert not access.evaluate(reader, added)["allowed"]
    save(access, added, "read")
    assert access.evaluate(reader, added)["allowed"]
    database.execute("UPDATE gate_mcp_authorization_identities SET binding='replacement' WHERE server_id='example'")
    assert not access.evaluate(writer, added)["allowed"]
    assert not access.evaluate(exact, definition)["allowed"]
    assert row(database, added)["required_access"] == "none"
    assert row(database, added)["policy_source"] == "unavailable"
    catalog.synchronize()
    assert row(database, added)["required_access"] == "none"
    assert row(database, added)["policy_source"] == "unavailable"


def test_concurrent_policy_edit_cannot_overwrite_a_newer_disabled_decision(policy):
    database, access, actor, definition, _, _ = policy
    before = row(database, definition)
    revision = before["access_policy_revision"]
    access.set_classification(server_id="example", tool_id=definition.id, access="unknown",
        destructive=False, idempotent=True, reviewer_id=actor.id, expected_fingerprint=before["fingerprint"],
        expected_policy_revision=revision, definition=definition)
    disabled = row(database, definition)
    assert disabled["required_access"] == "none"
    assert disabled["policy_source"] == "local_override"
    with pytest.raises(ClassificationConfirmationConflictError, match="policy changed"):
        access.set_classification(server_id="example", tool_id=definition.id, access="read",
            destructive=False, idempotent=True, reviewer_id=actor.id, expected_fingerprint=before["fingerprint"],
            expected_policy_revision=revision, definition=definition)
    assert row(database, definition)["required_access"] == "none"


def test_only_gate_owned_builtin_permission_can_supply_automatic_read(policy):
    _, access, actor, definition, _, _ = policy
    builtin = definition.model_copy(update={"source": "builtin", "id": "gate_read", "permission": "read",
                                            "metadata": {"server_id": "gate"}})
    access.synchronize_tools([builtin])
    admin_reader = replace(actor, role="admin", roles=("admin",), auth_type="token", scopes=("tools.read",))
    assert access.evaluate(admin_reader, builtin)["allowed"]
    spoof = builtin.model_copy(update={"source": "mcp", "id": "mcp.gate_read"})
    access.synchronize_tools([spoof])
    assert not access.evaluate(admin_reader, spoof)["allowed"]


def test_builtin_read_to_write_contract_change_immediately_updates_every_authorization_path(policy):
    _, access, actor, definition, registry, catalog = policy
    builtin = definition.model_copy(update={"source": "builtin", "id": "gate_changed", "permission": "read",
                                            "metadata": {"server_id": "gate"}})
    registry.register(builtin, lambda arguments: {"unexpected": True})
    catalog.synchronize()
    reader = replace(actor, role="admin", roles=("admin",), auth_type="token", scopes=("tools.read",))
    assert access.visible_tools(reader, [builtin])
    changed = builtin.model_copy(update={"permission": "write"})
    registry.update_definition(changed)
    # Even an unsynchronized request-local classification cannot override the
    # current Gate-owned automatic contract.
    assert not access.evaluate(reader, changed)["allowed"]
    catalog.synchronize()
    assert access.visible_tools(reader, [changed]) == []
    assert changed.id not in {item["tool_ref"] for item in catalog.search(reader, CatalogSearch())["tools"]}
    with pytest.raises(AccessDeniedError):
        access.invoke_tool(registry, reader, changed.id, {})


@pytest.mark.parametrize("change", ["disable_restore", "retire_reappear"])
def test_exact_scope_never_revives_when_a_local_policy_or_tool_is_recreated(policy, change):
    database, access, actor, definition, registry, catalog = policy
    previous = row(database, definition)
    with database.session() as connection:
        binding = server_binding(connection, "example")
    token = replace(actor, auth_type="token", scopes=("tools.read", "tools.invoke"),
        api_token_authorization_mode="independent", api_token_tool_snapshots=((definition.id, tool_snapshot(definition, previous)),),
        api_token_tool_bindings=((definition.id, binding),))
    assert access.evaluate(token, definition)["allowed"]
    if change == "disable_restore":
        save(access, definition, "unknown")
        access.reset_tool_access_policy(definition, reviewer_id=actor.id)
    else:
        registry.unregister_by_metadata("server_id", "example", source="mcp")
        catalog.synchronize()
        registry.register(definition, lambda arguments: {})
        catalog.synchronize()
    assert row(database, definition)["required_access"] == "write"
    assert not access.evaluate(token, definition)["allowed"]


def test_unchanged_automatic_tools_do_not_write_or_invalidate_catalog_cursors(policy):
    database, access, actor, definition, _, catalog = policy
    before = row(database, definition)
    epoch = tuple(database.query_one("SELECT * FROM gate_catalog_epochs"))
    access.visible_tools(actor, [definition])
    access.reconcile_server_tools("example", [definition], "automatic_discovery")
    catalog.synchronize()
    assert row(database, definition) == before
    assert tuple(database.query_one("SELECT * FROM gate_catalog_epochs")) == epoch

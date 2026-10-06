"""Directory reads omit large analysis data without changing current policy."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest

from lingshu_gate.application.mcp_group_structures import ToolStructureCache
from lingshu_gate.domain.mcp_group_catalog import VisibleCatalogTool, build_catalog

from test_mcp_groups import PASSWORD, catalog_path, catalog_tool, create
from test_mcp_groups import gate as gate


CATALOG_COLUMNS = {
    "server_id", "tool_id", "fingerprint", "status", "effective_access",
    "reviewed_by", "reviewed_at", "destructive", "idempotent", "open_world",
}


def test_http_catalog_and_variant_never_read_large_evidence_or_analysis_columns(gate):
    group = create(gate)
    definitions = [catalog_tool(gate, f"instance-{index}")[0] for index in range(2)]
    evidence = json.dumps({"synthetic_analysis": "x" * (2 * 1024 * 1024)})
    gate["database"].execute("UPDATE mcp_tool_classifications SET evidence_json=?", (evidence,))
    access = gate["access"]
    keys = [(definition.metadata["server_id"], definition.id) for definition in definitions]
    with gate["database"].session() as connection:
        complete = access._load_classifications(connection, keys)
        assert all(row["evidence_json"] == evidence and "source" in row and "updated_at" in row
                   for row in complete.values())
    # Replay the original complete-row path as the reference response.
    with patch.object(access, "_load_catalog_classifications", side_effect=access._load_classifications):
        expected = gate["client"].get(catalog_path(group)).json()
        variant = expected["variants"][0]["variant_id"]
        expected_members = gate["client"].get(catalog_path(group, "/" + variant)).json()
    gate["catalog"].structures = ToolStructureCache()
    original_connect = gate["database"].connect
    denied = []
    read_columns = set()

    def authorize(action, table, column, _database, _trigger):
        if action == sqlite3.SQLITE_READ and table == "mcp_tool_classifications":
            read_columns.add(column)
            if column not in CATALOG_COLUMNS:
                denied.append(column)
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def connect():
        connection = original_connect()
        connection.set_authorizer(authorize)
        return connection

    with patch.object(gate["database"], "connect", side_effect=connect), \
            patch.object(access, "_load_classifications", side_effect=AssertionError("No complete directory read")):
        for _ in range(2):
            page = gate["client"].get(catalog_path(group))
            members = gate["client"].get(catalog_path(group, "/" + variant))
            assert page.status_code == members.status_code == 200
            assert page.json() == expected and members.json() == expected_members
    assert not denied and read_columns == CATALOG_COLUMNS
    with gate["database"].session() as connection:
        assert access._load_classifications(connection, keys) == complete
    # Full synchronization still consumes its complete source/evidence data.
    assert all(row["evidence"]["synthetic_analysis"] == "x" * (2 * 1024 * 1024)
               for row in access.synchronize_tools(definitions))


@pytest.mark.parametrize("change", [
    "unchanged", "write", "pending", "stale", "unknown", "fingerprint", "registry_contract",
    "reviewer", "review_time", "destructive", "idempotent", "open_world", "grant_revoked",
    "tool_none", "grant_expired", "role_grant", "token_read", "token_no_tools", "control_permission",
    "oauth", "oauth_tool", "oauth_instance", "oauth_access", "oauth_expired", "delegated_read",
])
def test_narrow_projection_matches_full_policy_and_reviewed_variants(gate, change):
    access, database = gate["access"], gate["database"]
    definitions = [catalog_tool(gate, f"instance-{index}")[0] for index in range(2)]
    user = gate["auth"].create_user(username="synthetic-projection-reader", password=PASSWORD, role="operator")
    actor, _, _ = gate["auth"].login(username=user["username"], password=PASSWORD)
    for index in range(2):
        access.save_grant(subject_type="user", subject_id=actor.id, server_id=f"instance-{index}",
                          permission_type_code="read", created_by=gate["principal"].id)
    changed = definitions[1]
    if change in {"write", "pending", "stale", "unknown", "fingerprint", "reviewer", "review_time",
                  "destructive", "idempotent", "open_world"}:
        updates = {
            "write": ("effective_access", "write"), "pending": ("status", "pending"),
            "stale": ("status", "stale"), "unknown": ("effective_access", "unknown"),
            "fingerprint": ("fingerprint", "changed"), "reviewer": ("reviewed_by", None),
            "review_time": ("reviewed_at", None), "destructive": ("destructive", 1),
            "idempotent": ("idempotent", 1), "open_world": ("open_world", 0),
        }
        column, value = updates[change]
        database.execute(f"UPDATE mcp_tool_classifications SET {column}=? WHERE tool_id=?", (value, changed.id))
    elif change == "registry_contract":
        definitions[1] = changed.model_copy(update={"input_schema": {"type": "object"}})
    elif change == "grant_revoked":
        database.execute("DELETE FROM mcp_resource_grants WHERE subject_id=? AND server_id='instance-1'", (actor.id,))
    elif change == "tool_none":
        access.save_grant(subject_type="user", subject_id=actor.id, server_id="instance-1", tool_id=changed.id,
                          permission_type_code="none", created_by=gate["principal"].id)
    elif change == "grant_expired":
        database.execute("UPDATE mcp_resource_grants SET expires_at='2000-01-01T00:00:00Z' WHERE server_id='instance-1'")
    elif change == "role_grant":
        database.execute("DELETE FROM mcp_resource_grants WHERE subject_id=?", (actor.id,))
        role = database.query_one("SELECT id FROM roles WHERE code='operator'")[0]
        access.save_grant(subject_type="role", subject_id=role, server_id="instance-0",
                          permission_type_code="read", created_by=gate["principal"].id)
    elif change in {"token_read", "token_no_tools"}:
        actor = replace(actor, auth_type="token", scopes=("tools.read",) if change == "token_read" else ())
    elif change == "control_permission":
        actor = replace(actor, permissions=())
    elif change.startswith("oauth"):
        actor = replace(actor, auth_type="oauth", scopes=("tools.read",), external_grant_id="synthetic-grant",
                        external_tool_ids=tuple(item.id for item in definitions),
                        external_server_ids=("instance-0", "instance-1"), external_access=("read",),
                        external_expires_at="2099-01-01T00:00:00Z")
        if change == "oauth_tool":
            actor = replace(actor, external_tool_ids=(definitions[0].id,))
        elif change == "oauth_instance":
            actor = replace(actor, external_server_ids=("instance-0",))
        elif change == "oauth_access":
            actor = replace(actor, external_access=("write",))
        elif change == "oauth_expired":
            actor = replace(actor, external_expires_at="2000-01-01T00:00:00Z")
    elif change == "delegated_read":
        actor = replace(actor, delegated_scopes=("tools.read",))

    def project(connection):
        return build_catalog("synthetic-group", [VisibleCatalogTool(definition,
            definition.metadata["server_id"], definition.metadata["server_id"], classification)
            for definition, classification in access.visible_tool_contracts(actor, definitions, connection=connection)])

    with database.session() as connection:
        connection.execute("BEGIN")
        with patch.object(access, "_load_catalog_classifications", side_effect=access._load_classifications):
            complete = project(connection)
        narrow = project(connection)
    assert narrow == complete
    hidden_changes = {"write", "pending", "stale", "unknown", "fingerprint", "registry_contract", "grant_revoked",
                      "tool_none", "grant_expired", "role_grant", "oauth_tool", "oauth_instance"}
    members = [member.tool_id for variant in narrow for member in variant.members]
    assert len(members) == (1 if change in hidden_changes else 0 if change in {
        "token_no_tools", "control_permission", "oauth_access", "oauth_expired"} else 2)


def test_catalog_batches_keep_all_keys_and_preserve_duplicate_and_missing_behavior(gate):
    database, access = gate["database"], gate["access"]
    # More than two batches, mixed services, repeated keys and a missing key.
    with database.session() as connection:
        connection.executemany("INSERT INTO mcp_tool_classifications "
            "(id,server_id,tool_id,tool_name,fingerprint,suggested_access,effective_access,status,"
            "evidence_json,created_at,updated_at) VALUES(?,?,?,?,?,'read','unknown','pending',?,?,?)",
            [(f"synthetic-{index}", f"instance-{index % 3}", f"mcp.synthetic.query-{index}", "query", "fingerprint",
              json.dumps({"synthetic_analysis": "x" * 8192}), "now", "now") for index in range(501)])
        keys = [(f"instance-{index % 3}", f"mcp.synthetic.query-{index}") for index in range(501)]
        keys.extend([keys[0], ("missing", "missing")])
        complete = access._load_classifications(connection, keys)
        narrow = access._load_catalog_classifications(connection, iter(keys))
    assert len(narrow) == len(complete) == 501
    assert narrow == {key: {column: row[column] for column in CATALOG_COLUMNS} for key, row in complete.items()}

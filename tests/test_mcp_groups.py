"""Metadata-only collections: isolated files/database, no live downstream calls."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.mcp_groups import McpGroupDraft, McpGroupError
from lingshu_gate.interfaces.control_api.mcp_group_routes import register_mcp_group_routes
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import McpServerListResponse
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.persistence.mcp_groups import McpGroupStore

PASSWORD = "Synthetic-Groups-123!"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-group-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", PASSWORD)
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d", auth_enabled=True)
    database = SQLiteDatabase("", tmp_path)
    access = AccessControlStore(database)
    auth = AuthStore(settings, database)
    auth.change_password(str(auth.list_users()[0]["id"]), PASSWORD)
    principal, cookie, _ = auth.login(username="synthetic-group-admin", password=PASSWORD)
    configs = McpConfigStore(settings.config_dir)
    for index in range(3):
        configs.save_config({"id": f"instance-{index}", "name": f"Synthetic instance {index}", "launch": {"type": "external"},
                             "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}})
    runtime = Mock(spec=McpRuntimeManager)
    runtime.list_servers.return_value = McpServerListResponse(servers=[], load_errors=[])
    store = McpGroupStore(database, ObservabilityStore(database))
    service = McpGroupService(store, configs, runtime)
    app = FastAPI()
    register_mcp_group_routes(app, auth=auth, service=service)
    with TestClient(app) as client:
        client.cookies.set(auth.cookie_name, cookie)
        yield {"service": service, "store": store, "database": database, "configs": configs,
               "runtime": runtime, "auth": auth, "principal": principal, "client": client, "access": access}


def draft(**values):
    return {"name": "Synthetic group", "description": "Metadata only", "status": "active",
            "members": ["instance-0", "instance-1"], "confirmed": True, **values}


def ticket(gate, body, action="create", group_id=None):
    digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    query = {"action": action, "request_digest": digest}
    if group_id:
        query["group_id"] = group_id
    response = gate["client"].post("/v1/mcp/groups/csrf", params=query, headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf"]}


def create(gate, **values):
    body = draft(**values)
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert response.status_code == 200, response.text
    return response.json()


def test_many_to_many_stable_identity_and_metadata_only_archive_delete(gate):
    files = {path: path.read_bytes() for path in gate["configs"].config_dir.glob("*")}
    before = {table: [dict(row) for row in gate["database"].query_all(f"SELECT * FROM {table}")]
              for table in ("mcp_resource_grants", "user_downstream_credentials", "mcp_tool_classifications")}
    first = create(gate)
    second = create(gate, name="Second group", members=["instance-0"])
    assert first["id"] != second["id"] and len(first["id"]) == 32
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_members WHERE server_id='instance-0'")[0] == 2
    body = draft(name="Renamed", status="archived", expected_revision=first["revision"])
    updated = gate["client"].put(f'/v1/mcp/groups/{first["id"]}', json=body, headers=ticket(gate, body, "update", first["id"]))
    assert updated.status_code == 200 and updated.json()["id"] == first["id"] and updated.json()["revision"] == 2
    assert gate["client"].get("/v1/mcp/groups").json()["total"] == 1
    body = {"expected_revision": 2, "confirmed": True}
    assert gate["client"].request("DELETE", f'/v1/mcp/groups/{first["id"]}', json=body, headers=ticket(gate, body, "delete", first["id"])).status_code == 200
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_members WHERE group_id=?", (first["id"],))[0] == 0
    assert files == {path: path.read_bytes() for path in files}
    for table, rows in before.items():
        assert rows == [dict(row) for row in gate["database"].query_all(f"SELECT * FROM {table}")]
    gate["runtime"].remove_manifest.assert_not_called()
    gate["runtime"].apply_manifest.assert_not_called()


def test_cas_and_audit_rollback_are_atomic(gate):
    group = create(gate)
    body = draft(expected_revision=1)
    accepted = gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=body, headers=ticket(gate, body, "update", group["id"]))
    assert accepted.status_code == 200
    stale = gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=body, headers=ticket(gate, body, "update", group["id"]))
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "group_revision_conflict"
    with patch.object(gate["store"].observability, "emit_event", side_effect=RuntimeError("synthetic audit failure")):
        with pytest.raises(RuntimeError, match="audit failure"):
            gate["service"].save(McpGroupDraft(**draft(name="Not committed", members=[])), gate["principal"],
                                   group_id=group["id"], expected_revision=2)
    current = gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()
    assert current["name"] == group["name"] and current["revision"] == 2 and len(current["members"]) == 2
    assert len(gate["database"].query_all("SELECT * FROM events WHERE subject_type='mcp_group'")) == 2


def test_concurrent_revisions_have_one_winner(gate):
    group = create(gate)
    def update(index):
        try:
            gate["service"].save(McpGroupDraft(**draft(name=f"Writer {index}")), gate["principal"], group_id=group["id"], expected_revision=1)
            return "saved"
        except McpGroupError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, range(2))) == ["group_revision_conflict", "saved"]


@pytest.mark.parametrize("change", ["origin", "missing", "body", "method", "group", "replay"])
def test_csrf_binds_session_body_method_target_and_single_use(gate, change):
    group = create(gate)
    body = draft(expected_revision=1)
    headers = ticket(gate, body, "update", group["id"])
    path, method = f'/v1/mcp/groups/{group["id"]}', "PUT"
    if change == "origin":
        headers["Origin"] = "https://other.example.test"
    elif change == "missing":
        headers.pop("X-CSRF-Token")
    elif change == "body":
        body["name"] = "Changed after ticket"
    elif change == "method":
        method, body = "DELETE", {"expected_revision": 1, "confirmed": True}
    elif change == "group":
        path = "/v1/mcp/groups/" + "f" * 32
    elif change == "replay":
        assert gate["client"].put(path, json=body, headers=headers).status_code == 200
    assert gate["client"].request(method, path, json=body, headers=headers).status_code == 403


@pytest.mark.parametrize("auth_type", ["oauth", "disabled"])
def test_oauth_and_disabled_auth_do_not_gain_group_management(gate, auth_type):
    with patch.object(gate["auth"], "authenticate_request", return_value=replace(gate["principal"], auth_type=auth_type)):
        assert gate["client"].get("/v1/mcp/groups").status_code == 403
        assert gate["client"].post("/v1/mcp/groups", json=draft()).status_code == 403


@pytest.mark.parametrize("change", ["role", "permission", "session", "inactive"])
def test_mutation_rechecks_current_administrator(gate, change):
    body = draft()
    headers = ticket(gate, body)
    db, principal = gate["database"], gate["principal"]
    if change == "role":
        db.execute("DELETE FROM user_roles WHERE user_id=?", (principal.id,))
    elif change == "permission":
        db.execute("DELETE FROM role_permissions WHERE permission_id=(SELECT id FROM control_permissions WHERE code='operations.manage')")
    elif change == "session":
        db.execute("DELETE FROM auth_sessions WHERE id=?", (principal.session_id,))
    else:
        db.execute("UPDATE users SET status='disabled' WHERE id=?", (principal.id,))
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=headers)
    assert response.status_code in {401, 403}
    assert db.query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0


def test_api_token_scope_is_independent_of_console_cookie(gate):
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic limited token", scopes=["tools.read"])
    denied = gate["client"].post("/v1/mcp/groups", json=draft(), headers={"Authorization": f'Bearer {token["token"]}'})
    assert denied.status_code == 403
    scoped = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic group token", scopes=["operations.manage"])
    accepted = gate["client"].post("/v1/mcp/groups", json=draft(), headers={"Authorization": f'Bearer {scoped["token"]}'})
    assert accepted.status_code == 200


@pytest.mark.parametrize("values", [{"members": ["instance-0", "instance-0"]}, {"members": ["not-registered"]},
                                   {"endpoint": "https://arbitrary.example.test"}, {"name": " "}, {"confirmed": False}, {"members": ["instance-0"] * 1001}])
def test_validation_never_creates_or_routes_instances(gate, values):
    body = draft(**values)
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert response.status_code in {409, 422}
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0


def test_complete_group_and_instance_search_pagination_has_no_tool_schemas(gate):
    for index in range(23):
        gate["service"].save(McpGroupDraft(**draft(name=f"Group {index:02}", members=["instance-0"])), gate["principal"])
    page = gate["client"].get("/v1/mcp/groups", params={"offset": 20, "limit": 10}).json()
    assert page["total"] == 23 and len(page["groups"]) == 3
    assert gate["client"].get("/v1/mcp/groups", params={"q": "GROUP 22"}).json()["total"] == 1
    page = gate["client"].get("/v1/mcp/groups/instances", params={"q": "instance", "offset": 2, "limit": 1}).json()
    assert page["total"] == 3 and page["instances"][0]["instance_id"] == "instance-2"
    ungrouped = gate["client"].get("/v1/mcp/groups/instances?ungrouped=true").json()
    assert [item["instance_id"] for item in ungrouped["instances"]] == ["instance-1", "instance-2"]
    assert not any(key in json.dumps(page) for key in ("inputSchema", "outputSchema", "endpoint", "headers"))


def test_deleted_and_recreated_instance_requires_explicit_regrouping(gate):
    group = create(gate)
    configuration = McpConfigurationService(gate["configs"], gate["runtime"], Mock(), group_store=gate["store"])
    gate["runtime"].has_server.return_value = False
    configuration.delete("instance-0")
    current = gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()
    assert current["revision"] == 2 and current["members"][0]["available"] is False
    gate["configs"].save_config({"id": "instance-0", "launch": {"type": "external"},
                                "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}})
    assert gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()["members"][0]["available"] is False
    body = draft(expected_revision=2, reconfirm_members=["instance-0"])
    result = gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=body, headers=ticket(gate, body, "update", group["id"]))
    assert result.status_code == 200 and result.json()["members"][0]["status"] == "active"


def test_reload_missing_file_and_migration_preserve_existing_state(gate):
    group = create(gate)
    path = gate["configs"].get_config("instance-1").path
    from pathlib import Path
    Path(path).unlink()
    configuration = McpConfigurationService(gate["configs"], gate["runtime"], Mock(), group_store=gate["store"])
    configuration.reload()
    current = gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()
    assert current["members"][1]["status"] == "missing" and current["revision"] == 2
    gate["database"].initialize()
    assert gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json() == current
    assert gate["database"].query_one("SELECT COUNT(*) FROM schema_migrations WHERE id='0013_gate_mcp_groups'")[0] == 1


def test_archiving_missing_members_does_not_reactivate_or_remove_history(gate):
    group = create(gate)
    gate["store"].invalidate_instances({"instance-0"}, reason="synthetic loss")
    body = draft(expected_revision=2, status="archived")
    response = gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=body, headers=ticket(gate, body, "update", group["id"]))
    assert response.status_code == 200
    assert response.json()["members"][0]["status"] == "missing"
    assert len(response.json()["members"]) == 2


def test_session_ticket_cannot_be_consumed_by_another_administrator(gate):
    body = draft()
    headers = ticket(gate, body)
    gate["auth"].create_user(username="synthetic-other-admin", password=PASSWORD, role="admin")
    _, cookie, _ = gate["auth"].login(username="synthetic-other-admin", password=PASSWORD)
    gate["client"].cookies.set(gate["auth"].cookie_name, cookie)
    assert gate["client"].post("/v1/mcp/groups", json=body, headers=headers).status_code == 403


def test_group_upgrade_is_additive_and_keeps_existing_grants_and_files(gate):
    db = gate["database"]
    grant = gate["access"].save_grant(subject_type="user", subject_id=gate["principal"].id,
        server_id="instance-0", permission_type_code="read", created_by=gate["principal"].id)
    files = {path: path.read_bytes() for path in gate["configs"].config_dir.glob("*")}
    db.execute("DROP TABLE mcp_group_members")
    db.execute("DROP TABLE mcp_groups")
    db.execute("DELETE FROM schema_migrations WHERE id='0013_gate_mcp_groups'")
    db.initialize()
    assert db.query_one("SELECT id FROM mcp_resource_grants WHERE id=?", (grant["id"],))[0] == grant["id"]
    assert db.query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0
    assert files == {path: path.read_bytes() for path in files}


def test_thousand_members_searches_the_complete_metadata_catalog(gate):
    catalog = {f"large-{index:04}": {"instance_id": f"large-{index:04}", "name": f"Instance {index:04}", "available": True, "status": "not_loaded"} for index in range(1000)}
    with patch.object(gate["service"], "_catalog", side_effect=lambda: {key: dict(value) for key, value in catalog.items()}):
        group = gate["service"].save(McpGroupDraft(**draft(members=list(catalog))), gate["principal"])
        assert len(group["members"]) == 1000
        tail = gate["service"].instances(gate["principal"], q="", group_id=group["id"], ungrouped=False, offset=980, limit=20)
        assert tail["total"] == 1000 and tail["instances"][-1]["instance_id"] == "large-0999"
        search = gate["service"].instances(gate["principal"], q="Instance 0999", group_id=group["id"], ungrouped=False, offset=0, limit=20)
        assert search["total"] == 1 and "outputSchema" not in json.dumps(search)

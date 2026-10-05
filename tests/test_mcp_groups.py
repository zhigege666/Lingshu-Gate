"""Metadata-only collections: isolated files/database, no live downstream calls."""
from __future__ import annotations

import hashlib
import json
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.application.mcp_group_catalog import McpGroupCatalogService
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.mcp_groups import McpGroupCreate, McpGroupDraft, McpGroupError, McpGroupUpdate
from lingshu_gate.interfaces.control_api.mcp_group_routes import register_mcp_group_routes
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import McpServerListResponse, ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.persistence.mcp_groups import McpGroupStore
from lingshu_gate.registry import ToolNotFoundError, ToolRegistry

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
    registry = ToolRegistry()
    catalog = McpGroupCatalogService(service, registry, access)
    app = FastAPI()
    register_mcp_group_routes(app, auth=auth, service=service, catalog=catalog)
    with TestClient(app) as client:
        client.cookies.set(auth.cookie_name, cookie)
        yield {"service": service, "store": store, "database": database, "configs": configs,
               "runtime": runtime, "auth": auth, "principal": principal, "client": client, "access": access,
               "registry": registry, "catalog": catalog}


def draft(*, with_request=True, **values):
    return {"name": "Synthetic group", "description": "Metadata only", "status": "active",
            "members": ["instance-0", "instance-1"], "confirmed": True,
            **({"request_key": uuid4().hex} if with_request and "expected_revision" not in values else {}), **values}


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
            gate["service"].save(McpGroupDraft(**draft(name="Not committed", members=[], with_request=False)), gate["principal"],
                                   group_id=group["id"], expected_revision=2)
    current = gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()
    assert current["name"] == group["name"] and current["revision"] == 2 and len(current["members"]) == 2
    assert len(gate["database"].query_all("SELECT * FROM events WHERE subject_type='mcp_group'")) == 2


def test_concurrent_revisions_have_one_winner(gate):
    group = create(gate)
    def update(index):
        try:
            gate["service"].save(McpGroupDraft(**draft(name=f"Writer {index}", with_request=False)), gate["principal"], group_id=group["id"], expected_revision=1)
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
    readonly = {"Authorization": f'Bearer {scoped["token"]}'}
    assert gate["client"].get("/v1/mcp/groups/instances", headers=readonly).status_code == 200
    assert gate["client"].post("/v1/mcp/groups", json=draft(), headers=readonly).status_code == 403
    writer = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic writer", scopes=["operations.manage", "tools.invoke"])
    accepted = gate["client"].post("/v1/mcp/groups", json=draft(), headers={"Authorization": f'Bearer {writer["token"]}'})
    assert accepted.status_code == 200
    group = accepted.json()
    assert gate["client"].get(f'/v1/mcp/groups/{group["id"]}', headers=readonly).status_code == 200
    assert gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=draft(expected_revision=1), headers=readonly).status_code == 403
    assert gate["client"].request("DELETE", f'/v1/mcp/groups/{group["id"]}', json={"confirmed": True, "expected_revision": 1}, headers=readonly).status_code == 403


@pytest.mark.parametrize("values", [{"members": ["instance-0", "instance-0"]}, {"members": ["not-registered"]},
                                   {"endpoint": "https://arbitrary.example.test"}, {"name": " "}, {"confirmed": False}, {"members": ["instance-0"] * 1001}])
def test_validation_never_creates_or_routes_instances(gate, values):
    body = draft(**values)
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert response.status_code in {409, 422}
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0


def test_complete_group_and_instance_search_pagination_has_no_tool_schemas(gate):
    for index in range(23):
        gate["service"].save(McpGroupCreate(**draft(name=f"Group {index:02}", members=["instance-0"])), gate["principal"])
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
    with patch.object(gate["service"], "_catalog", side_effect=lambda **kwargs: {key: dict(value) for key, value in catalog.items()}):
        group = gate["service"].save(McpGroupCreate(**draft(members=list(catalog))), gate["principal"])
        assert len(group["members"]) == 1000
        tail = gate["service"].instances(gate["principal"], q="", group_id=group["id"], ungrouped=False, offset=980, limit=20)
        assert tail["total"] == 1000 and tail["instances"][-1]["instance_id"] == "large-0999"
        search = gate["service"].instances(gate["principal"], q="Instance 0999", group_id=group["id"], ungrouped=False, offset=0, limit=20)
        assert search["total"] == 1 and "outputSchema" not in json.dumps(search)


def test_five_thousand_real_manifest_queries_reuse_metadata_snapshot(gate, record_property):
    configs, client = gate["configs"], gate["client"]
    for index in range(3):
        configs.delete_config(f"instance-{index}")
    for index in range(5000):
        (configs.config_dir / f"scale-{index:04}.json").write_text(json.dumps({
            "id": f"scale-{index:04}", "name": f"Scale instance {index:04}",
            "launch": {"type": "external", "env": {"SYNTHETIC_PRIVATE_VALUE": "fixture-value-never-cached"}},
            "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}}))
    with patch.object(configs, "_load_raw", wraps=configs._load_raw) as reads:
        started = time.perf_counter()
        response = client.get("/v1/mcp/groups/instances?offset=4980&limit=20")
        cold = time.perf_counter() - started
        assert response.status_code == 200 and response.json()["total"] == 5000
        assert response.json()["instances"][-1]["instance_id"] == "scale-4999"
        assert reads.call_count == 5000
        started = time.perf_counter()
        for index in range(30):
            result = client.get("/v1/mcp/groups/instances", params={"q": f"Scale instance {index:04}", "offset": 0, "limit": 20})
            assert result.status_code == 200 and result.json()["total"] == 1
        warm = time.perf_counter() - started
        assert reads.call_count == 5000, "Warm searches/pages must perform zero additional manifest reads"
        assert cold < 15 and warm < 10, (cold, warm)
        snapshot = configs._instance_metadata
        assert snapshot is not None and len(snapshot) == 5000
        assert all(set(vars(item)) == {"instance_id", "name"} for item in snapshot)
        assert "fixture-value-never-cached" not in repr(snapshot) and "endpoint" not in response.text
        readings = {"instances": 5000, "cold_seconds": round(cold, 4), "warm_30_queries_seconds": round(warm, 4),
                    "cold_manifest_reads": 5000, "warm_manifest_reads": 0}
        record_property("metadata_query_measurements", json.dumps(readings))
        print("GROUP_METADATA_MEASUREMENTS " + json.dumps(readings))


def test_metadata_snapshot_invalidates_on_mutation_reload_refresh_and_ttl(gate):
    configs, client = gate["configs"], gate["client"]
    def names(**params):
        result = client.get("/v1/mcp/groups/instances", params=params)
        assert result.status_code == 200
        return {item["instance_id"]: item["name"] for item in result.json()["instances"]}
    assert len(names()) == 3
    manifest = configs.load_manifest("instance-0").model_dump(mode="json", exclude={"manifest_path"})
    manifest["name"] = "Updated metadata"
    configs.save_config(manifest, expected_id="instance-0", overwrite=True)
    assert names()["instance-0"] == "Updated metadata"
    manifest["id"] = "new-instance"
    configs.save_config(manifest)
    assert "new-instance" in names()
    configs.delete_config("new-instance")
    assert "new-instance" not in names()
    path = Path(configs.get_config("instance-0").path)
    path.write_text(json.dumps({**manifest, "id": "instance-0", "name": "External refresh"}))
    assert names()["instance-0"] == "Updated metadata"
    assert names(refresh=True)["instance-0"] == "External refresh"
    path.write_text(json.dumps({**manifest, "id": "instance-0", "name": "External reload"}))
    McpConfigurationService(configs, gate["runtime"], Mock(), group_store=gate["store"]).reload()
    assert names()["instance-0"] == "External reload"
    with patch("lingshu_gate.mcp_config_store.time.monotonic", return_value=configs._metadata_built_at + 30):
        path.write_text(json.dumps({**manifest, "id": "instance-0", "name": "Expired snapshot"}))
        assert names()["instance-0"] == "Expired snapshot"


def test_save_checks_current_files_even_when_read_snapshot_is_warm(gate):
    assert gate["client"].get("/v1/mcp/groups/instances").status_code == 200
    Path(gate["configs"].get_config("instance-0").path).unlink()
    body = draft()
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "group_instance_unavailable"
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0


@pytest.mark.parametrize("selected", [False, True])
def test_metadata_refresh_preserves_revision_until_metadata_or_explicit_configuration_changes(gate, selected):
    configs = gate["configs"]
    def refresh():
        if selected:
            configs._metadata_built_at -= 31
            configs.selected_instance_metadata({"instance-0"})
        else:
            configs.instance_metadata(refresh=True)
    configs.instance_metadata()
    revision = configs.metadata_revision()
    refresh()
    assert configs.metadata_snapshot_current(revision)
    manifest = configs.load_manifest("instance-0").model_copy(update={"name": "External name update"})
    configs._find_path("instance-0").write_text(manifest.model_dump_json(exclude={"manifest_path"}))
    refresh()
    assert not configs.metadata_snapshot_current(revision)
    revision = configs.metadata_revision()
    # A save invalidates even when directory IDs/names remain identical.
    configs.save_config(manifest.model_dump(exclude={"manifest_path"}), overwrite=True)
    assert not configs.metadata_snapshot_current(revision)


def test_create_receipt_replays_reconciles_and_never_resurrects(gate):
    body = draft()
    first = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body)).json()
    # First response is treated as lost by the caller; retry obtains a fresh CSRF ticket.
    replay = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert replay.status_code == 200 and replay.json() == first
    result = gate["client"].get(f'/v1/mcp/groups/requests/{body["request_key"]}')
    assert result.status_code == 200 and result.json()["id"] == first["id"]
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 1
    assert gate["database"].query_one("SELECT COUNT(*) FROM events WHERE type='gate.mcp.group_created'")[0] == 1
    changed = {**body, "description": "Different submitted body"}
    rejected = gate["client"].post("/v1/mcp/groups", json=changed, headers=ticket(gate, changed))
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "group_request_conflict"
    deletion = {"confirmed": True, "expected_revision": 1}
    assert gate["client"].request("DELETE", f'/v1/mcp/groups/{first["id"]}', json=deletion, headers=ticket(gate, deletion, "delete", first["id"])).status_code == 200
    retired = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert retired.status_code == 409 and retired.json()["detail"]["code"] == "group_request_deleted"
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 0


def test_create_receipts_are_actor_isolated_and_audit_atomic(gate):
    body = draft()
    with patch.object(gate["store"].observability, "emit_event", side_effect=RuntimeError("synthetic audit failure")):
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            gate["service"].save(McpGroupCreate(**body), gate["principal"])
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == 0
    first = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body)).json()
    gate["auth"].create_user(username="synthetic-receipt-admin", password=PASSWORD, role="admin")
    _, cookie, _ = gate["auth"].login(username="synthetic-receipt-admin", password=PASSWORD)
    gate["client"].cookies.set(gate["auth"].cookie_name, cookie)
    assert gate["client"].get(f'/v1/mcp/groups/requests/{body["request_key"]}').status_code == 404
    second = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert second.status_code == 200 and second.json()["id"] != first["id"]


def test_concurrent_create_retries_have_one_group_and_receipt(gate):
    body = McpGroupCreate(**draft())
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: gate["service"].save(body, gate["principal"]), range(3)))
    assert len({item["id"] for item in results}) == 1
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == 1


@pytest.mark.parametrize("capacity", ["actor", "global"])
def test_receipt_capacity_only_blocks_new_creation_and_keeps_tombstones(gate, monkeypatch, capacity):
    monkeypatch.setattr("lingshu_gate.persistence.mcp_groups.MCP_GROUP_REQUESTS_PER_ACTOR_LIMIT", 1 if capacity == "actor" else 10)
    monkeypatch.setattr("lingshu_gate.persistence.mcp_groups.MCP_GROUP_REQUESTS_GLOBAL_LIMIT", 1 if capacity == "global" else 10)
    body = draft()
    first = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body)).json()
    extra = draft(name="Must remain a draft")
    rejected = gate["client"].post("/v1/mcp/groups", json=extra, headers=ticket(gate, extra))
    assert rejected.status_code == 429 and rejected.json()["detail"]["code"] == "group_request_capacity"
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == 1
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == 1
    assert gate["database"].query_one("SELECT COUNT(*) FROM events WHERE subject_type='mcp_group'")[0] == 1
    assert gate["client"].get(f'/v1/mcp/groups/requests/{extra["request_key"]}').status_code == 404
    assert gate["client"].get(f'/v1/mcp/groups/requests/{body["request_key"]}').json()["id"] == first["id"]
    assert gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body)).json()["id"] == first["id"]
    changed = {**body, "description": "Changed creation"}
    conflict = gate["client"].post("/v1/mcp/groups", json=changed, headers=ticket(gate, changed))
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "group_request_conflict"
    update = draft(name="Updated at capacity", expected_revision=1)
    assert gate["client"].put(f'/v1/mcp/groups/{first["id"]}', json=update, headers=ticket(gate, update, "update", first["id"])).status_code == 200
    deletion = {"confirmed": True, "expected_revision": 2}
    assert gate["client"].request("DELETE", f'/v1/mcp/groups/{first["id"]}', json=deletion, headers=ticket(gate, deletion, "delete", first["id"])).status_code == 200
    retired = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert retired.status_code == 409 and retired.json()["detail"]["code"] == "group_request_deleted"
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == 1
    assert gate["client"].post("/v1/mcp/groups", json=extra, headers=ticket(gate, extra)).status_code == 429


@pytest.mark.parametrize("capacity", ["actor", "global"])
def test_receipt_actor_capacity_is_private_and_global_capacity_is_shared(gate, monkeypatch, capacity):
    monkeypatch.setattr("lingshu_gate.persistence.mcp_groups.MCP_GROUP_REQUESTS_PER_ACTOR_LIMIT", 1)
    monkeypatch.setattr("lingshu_gate.persistence.mcp_groups.MCP_GROUP_REQUESTS_GLOBAL_LIMIT", 1 if capacity == "global" else 10)
    create(gate)
    gate["auth"].create_user(username="synthetic-capacity-admin", password=PASSWORD, role="admin")
    _, cookie, _ = gate["auth"].login(username="synthetic-capacity-admin", password=PASSWORD)
    gate["client"].cookies.set(gate["auth"].cookie_name, cookie)
    body = draft()
    response = gate["client"].post("/v1/mcp/groups", json=body, headers=ticket(gate, body))
    assert response.status_code == (429 if capacity == "global" else 200)
    if capacity == "global":
        assert response.json()["detail"]["code"] == "group_request_capacity"


@pytest.mark.parametrize("capacity", ["actor", "global"])
def test_concurrent_new_receipts_cannot_cross_transactional_capacity(gate, monkeypatch, capacity):
    monkeypatch.setattr("lingshu_gate.persistence.mcp_groups.MCP_GROUP_REQUESTS_PER_ACTOR_LIMIT", 1 if capacity == "actor" else 10)
    monkeypatch.setattr("lingshu_gate.persistence.mcp_groups.MCP_GROUP_REQUESTS_GLOBAL_LIMIT", 1 if capacity == "global" else 10)
    barrier = threading.Barrier(2)
    def create_at_boundary(index):
        body = McpGroupCreate(**draft(name=f"Concurrent bounded {index}"))
        digest = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
        barrier.wait(timeout=3)
        try:
            gate["store"].save(body, group_id=None, expected_revision=None, actor_id=gate["principal"].id,
                authorize=lambda connection: gate["service"].authorize(connection, gate["principal"], write=True),
                available_instances={"instance-0", "instance-1"}, request_key=body.request_key, request_digest=digest)
            return "created"
        except McpGroupError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create_at_boundary, range(2))) == ["created", "group_request_capacity"]
    for table in ("mcp_groups", "mcp_group_requests"):
        assert gate["database"].query_one(f"SELECT COUNT(*) FROM {table}")[0] == 1
    assert gate["database"].query_one("SELECT COUNT(*) FROM events WHERE type='gate.mcp.group_created'")[0] == 1


@pytest.mark.parametrize("change", ["invoke_permission", "token_scopes", "token_revoked"])
@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_queued_writer_rechecks_revoked_permission_and_token_ceiling(gate, change, action):
    group = create(gate) if action != "create" else None
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic queued writer", scopes=["operations.manage", "tools.invoke"])
    principal = gate["auth"]._principal_from_api_token(str(token["token"]))
    assert principal is not None
    reached = threading.Event()
    original_check = gate["service"].check
    def checked(actor, **kwargs):
        original_check(actor, **kwargs)
        reached.set()
    with patch.object(gate["service"], "check", side_effect=checked), ThreadPoolExecutor(max_workers=1) as pool:
        with gate["database"].session() as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            if group and action == "update":
                future = pool.submit(gate["service"].save, McpGroupUpdate(**draft(expected_revision=1)), principal, group_id=group["id"], expected_revision=1)
            elif group:
                future = pool.submit(gate["service"].delete, group["id"], 1, principal)
            else:
                future = pool.submit(gate["service"].save, McpGroupCreate(**draft()), principal)
            assert reached.wait(3), "Writer must pass its initial check before revocation"
            if change == "invoke_permission":
                blocker.execute("DELETE FROM role_permissions WHERE permission_id=(SELECT id FROM control_permissions WHERE code='tools.invoke')")
            elif change == "token_scopes":
                blocker.execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage"]), token["id"]))
            else:
                blocker.execute("UPDATE api_tokens SET revoked_at='2026-10-04T00:00:00Z' WHERE id=?", (token["id"],))
        with pytest.raises(McpGroupError) as rejected:
            future.result(timeout=10)
        assert rejected.value.status == 403
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_groups")[0] == bool(group)
    assert gate["database"].query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == bool(group)
    if group:
        unchanged = gate["client"].get(f'/v1/mcp/groups/{group["id"]}')
        assert unchanged.status_code == 200 and unchanged.json()["revision"] == 1


def test_receipt_migration_preserves_preexisting_group_metadata(gate):
    group = create(gate)
    db = gate["database"]
    db.execute("DROP TABLE mcp_group_requests")
    db.execute("DELETE FROM schema_migrations WHERE id='0014_gate_mcp_group_requests'")
    db.initialize()
    current = gate["client"].get(f'/v1/mcp/groups/{group["id"]}').json()
    assert current["id"] == group["id"] and current["revision"] == group["revision"]
    assert current["members"] == [{**item, "available": True} for item in group["members"]]
    assert db.query_one("SELECT COUNT(*) FROM mcp_group_requests")[0] == 0
    assert db.query_one("SELECT COUNT(*) FROM schema_migrations WHERE id='0014_gate_mcp_group_requests'")[0] == 1


_MISSING_OUTPUT = object()


def catalog_tool(gate, instance, *, name="query", access="read", schema=None,
                 output=_MISSING_OUTPUT, metadata=None, published=True):
    definition = ToolDefinition(id=f"mcp.{instance}.{name}", name=name, description="Synthetic contract",
        source="mcp", input_schema={} if schema is None else schema,
        metadata={"server_id": instance, "original_tool_name": name, "annotations": {"readOnlyHint": True},
                  **({"outputSchema": output} if output is not _MISSING_OUTPUT else {}), **(metadata or {})})
    handler = Mock(return_value={"synthetic": True})
    gate["registry"].register(definition, handler, replace=True)
    gate["access"].synchronize_tools([definition])
    gate["access"].set_classification(server_id=instance, tool_id=definition.id, access=access,
        destructive=access == "write", idempotent=False, reviewer_id=gate["principal"].id)
    if published:
        gate["access"].publish_classifications(reviewer_id=gate["principal"].id, tool_ids=[definition.id])
    return definition, handler


def catalog_path(group, suffix=""):
    return f'/v1/mcp/groups/{group["id"]}/catalog{suffix}'


def catalog_token(gate, scopes):
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic catalog reader", scopes=scopes)
    return token, {"Authorization": f'Bearer {token["token"]}'}


def test_catalog_current_review_candidates_preserve_ids_and_do_not_mutate(gate):
    group = create(gate)
    first, first_handler = catalog_tool(gate, "instance-0", schema={"type": "object", "properties": {"x": {"type": "string"}}})
    second, second_handler = catalog_tool(gate, "instance-1", schema={"properties": {"x": {"type": "string"}}, "type": "object"})
    before = gate["database"].query_all("SELECT * FROM mcp_tool_classifications ORDER BY tool_id")
    response = gate["client"].get(catalog_path(group))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["business_equivalence"] == "unverified"
    assert body["total"] == 1 and body["visible_tool_count"] == body["visible_member_count"] == 2
    variant = body["variants"][0]
    assert variant["compatibility"] == "reviewed_contract_match" and variant["visible_member_count"] == 2
    assert "members" not in variant and "input_schema" not in variant
    detail = gate["client"].get(catalog_path(group, "/" + variant["variant_id"]), params={"offset": 1, "limit": 1})
    assert detail.status_code == 200 and detail.headers["cache-control"] == "no-store"
    assert detail.json()["total"] == 2 and [item["tool_id"] for item in detail.json()["members"]] == [second.id]
    assert before == gate["database"].query_all("SELECT * FROM mcp_tool_classifications ORDER BY tool_id")
    assert gate["registry"].get_definition(first.id) == first
    with pytest.raises(ToolNotFoundError):
        gate["registry"].get_definition(variant["variant_id"])
    first_handler.assert_not_called()
    second_handler.assert_not_called()


def test_catalog_only_counts_visible_members_variants_and_current_scopes(gate):
    group = create(gate)
    readable, _ = catalog_tool(gate, "instance-0", access="read")
    hidden, _ = catalog_tool(gate, "instance-1", access="write", output={})
    token, headers = catalog_token(gate, ["operations.manage", "tools.read"])
    response = gate["client"].get(catalog_path(group), headers=headers)
    body = response.json()
    assert response.status_code == 200 and body["visible_member_count"] == body["visible_tool_count"] == body["total"] == 1
    assert body["variants"][0]["visible_variant_count"] == 1
    assert "instance-1" not in json.dumps(body) and hidden.id not in json.dumps(body)
    assert gate["client"].get(catalog_path(group), params={"q": hidden.id}, headers=headers).json()["total"] == 0
    all_body = gate["client"].get(catalog_path(group)).json()
    hidden_variant = next(item for item in all_body["variants"] if item["safety"]["required_access"] == "write")
    assert gate["client"].get(catalog_path(group, "/" + hidden_variant["variant_id"]), headers=headers).status_code == 404
    gate["database"].execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage"]), token["id"]))
    assert gate["client"].get(catalog_path(group), headers=headers).json()["visible_tool_count"] == 0
    gate["database"].execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage", "tools.read"]), token["id"]))
    gate["access"].set_classification(server_id="instance-0", tool_id=readable.id, access="read",
        destructive=False, idempotent=False, reviewer_id=gate["principal"].id)
    body = gate["client"].get(catalog_path(group), headers=headers).json()
    assert body["variants"][0]["compatibility"] == "review_required"
    assert body["variants"][0]["safety"] is None


def test_catalog_changed_fingerprint_is_not_authorized_by_old_review_and_get_never_syncs(gate):
    group = create(gate)
    catalog_tool(gate, "instance-0")
    second, handler = catalog_tool(gate, "instance-1")
    token, headers = catalog_token(gate, ["operations.manage", "tools.read"])
    old = gate["client"].get(catalog_path(group), headers=headers).json()["variants"][0]["variant_id"]
    gate["registry"].register(second.model_copy(update={"input_schema": {"type": "object"}}), handler, replace=True)
    before = [dict(row) for row in gate["database"].query_all("SELECT * FROM mcp_tool_classifications ORDER BY tool_id")]
    response = gate["client"].get(catalog_path(group), headers=headers)
    assert response.status_code == 200 and response.json()["visible_tool_count"] == 1
    assert response.json()["variants"][0]["variant_id"] == old
    admin = gate["client"].get(catalog_path(group)).json()
    assert admin["total"] == 2 and sum(item["compatibility"] == "review_required" for item in admin["variants"]) == 1
    assert before == [dict(row) for row in gate["database"].query_all("SELECT * FROM mcp_tool_classifications ORDER BY tool_id")]
    handler.assert_not_called()


@pytest.mark.parametrize("malformed", ["cycle", "non_json"])
def test_registry_rejects_malformed_catalog_contract_without_mutating_review(gate, malformed):
    group = create(gate)
    original, handler = catalog_tool(gate, "instance-0")
    _, headers = catalog_token(gate, ["operations.manage", "tools.read"])
    schema = {"value": b"synthetic-non-json"}
    if malformed == "cycle":
        schema = {}
        schema["self"] = schema
    before = [dict(row) for row in gate["database"].query_all("SELECT * FROM mcp_tool_classifications")]
    with pytest.raises(ValueError, match="tool_structure_"):
        gate["registry"].register(original.model_copy(update={"input_schema": schema}), handler, replace=True)
    response = gate["client"].get(catalog_path(group), headers=headers)
    assert response.status_code == 200 and response.json()["visible_tool_count"] == 1
    admin = gate["client"].get(catalog_path(group))
    assert admin.status_code == 200 and admin.json()["visible_tool_count"] == 1
    assert admin.json()["variants"][0]["compatibility"] == "single_member"
    assert gate["registry"].get_definition(original.id) == original
    assert before == [dict(row) for row in gate["database"].query_all("SELECT * FROM mcp_tool_classifications")]
    handler.assert_not_called()


@pytest.mark.parametrize("change", ["tools_permission", "token_scopes", "token_revoked", "token_deleted",
                                    "token_expired", "user_disabled", "delegation"])
def test_catalog_rechecks_current_authority_after_waiting_for_configuration_lock(gate, change):
    group = create(gate)
    _, handler = catalog_tool(gate, "instance-0")
    token, _ = catalog_token(gate, ["operations.manage", "tools.read"])
    actor = gate["auth"]._principal_from_api_token(token["token"])
    if change == "delegation":
        actor = replace(actor, delegated_scopes=("operations.manage",))
    checked = threading.Event()
    original_check = gate["service"].check
    def initial_check(current, **kwargs):
        original_check(current, **kwargs)
        checked.set()
    with patch.object(gate["service"], "check", side_effect=initial_check), \
            patch.object(gate["access"], "visible_tool_contracts", wraps=gate["access"].visible_tool_contracts) as projection, \
            ThreadPoolExecutor(max_workers=1) as pool:
        with gate["configs"].mutation_lock:
            future = pool.submit(gate["catalog"].catalog, group["id"], actor)
            assert checked.wait(3), "Initial authorization must succeed before authority changes"
            assert not future.done(), "The configuration lock must still block the catalog"
            if change == "tools_permission":
                gate["database"].execute("DELETE FROM role_permissions WHERE permission_id=(SELECT id FROM control_permissions WHERE code='tools.read')")
            elif change == "token_scopes":
                gate["database"].execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage"]), token["id"]))
            elif change == "token_revoked":
                gate["database"].execute("UPDATE api_tokens SET revoked_at='2026-10-05T00:00:00Z' WHERE id=?", (token["id"],))
            elif change == "token_deleted":
                gate["database"].execute("DELETE FROM api_tokens WHERE id=?", (token["id"],))
            elif change == "token_expired":
                gate["database"].execute("UPDATE api_tokens SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (token["id"],))
            elif change == "user_disabled":
                gate["database"].execute("UPDATE users SET status='disabled' WHERE id=?", (actor.id,))
        if change in {"token_revoked", "token_deleted", "token_expired", "user_disabled"}:
            with pytest.raises(McpGroupError) as denied:
                future.result(timeout=10)
            assert denied.value.status == 403
            assert denied.value.code == ("group_admin_required" if change == "user_disabled" else "group_connection_invalid")
            projection.assert_not_called()
        else:
            result = future.result(timeout=10)
            assert result.total == result.visible_tool_count == result.visible_member_count == 0
    handler.assert_not_called()


def test_cold_selected_metadata_does_not_hold_configuration_write_lock(gate):
    reached, release = threading.Event(), threading.Event()
    load = gate["configs"]._load_manifest
    def slow_read(path):
        result = load(path)
        if threading.current_thread().name.startswith("metadata-reader") and not reached.is_set():
            reached.set()
            assert release.wait(3), "Cold reader must be released within the test budget"
        return result
    with patch.object(gate["configs"], "_load_manifest", side_effect=slow_read), \
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="metadata-reader") as readers, \
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="metadata-writer") as writers:
        future = readers.submit(gate["configs"].selected_instance_metadata, {"instance-0"})
        try:
            assert reached.wait(3)
            writer = writers.submit(gate["configs"].save_config, {"id": "instance-0", "name": "Edited synthetic name",
                "launch": {"type": "external"}, "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}},
                overwrite=True)
            assert writer.result(timeout=2).manifest["name"] == "Edited synthetic name"
        finally:
            release.set()
        revision, names = future.result(timeout=3)
        assert names == {"instance-0": "Edited synthetic name"}
        assert gate["configs"].metadata_snapshot_current(revision)


def test_catalog_excludes_other_sources_forged_ids_and_unconfirmed_recreated_members(gate):
    group = create(gate)
    original, _ = catalog_tool(gate, "instance-0")
    gate["registry"].register(original.model_copy(update={"id": "gate.synthetic", "source": "builtin"}), Mock())
    gate["registry"].register(original.model_copy(update={"id": "mcp.forged.query"}), Mock())
    assert gate["client"].get(catalog_path(group)).json()["visible_tool_count"] == 1
    configuration = McpConfigurationService(gate["configs"], gate["runtime"], Mock(), group_store=gate["store"])
    gate["runtime"].has_server.return_value = False
    configuration.delete("instance-0")
    gate["configs"].save_config({"id": "instance-0", "launch": {"type": "external"},
        "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}})
    assert gate["client"].get(catalog_path(group)).json()["visible_tool_count"] == 0
    body = draft(expected_revision=2, reconfirm_members=["instance-0"])
    assert gate["client"].put(f'/v1/mcp/groups/{group["id"]}', json=body,
        headers=ticket(gate, body, "update", group["id"])).status_code == 200
    assert gate["client"].get(catalog_path(group)).json()["visible_tool_count"] == 1


@pytest.mark.parametrize("auth_type", ["oauth", "disabled"])
def test_catalog_does_not_add_oauth_or_disabled_auth_authority(gate, auth_type):
    group = create(gate)
    with patch.object(gate["auth"], "authenticate_request", return_value=replace(gate["principal"], auth_type=auth_type)):
        assert gate["client"].get(catalog_path(group)).status_code == 403


def test_catalog_requires_current_admin_and_bounds_query_fields(gate):
    group = create(gate)
    gate["auth"].create_user(username="synthetic-catalog-viewer", password=PASSWORD, role="viewer")
    _, cookie, _ = gate["auth"].login(username="synthetic-catalog-viewer", password=PASSWORD)
    original_cookie = gate["client"].cookies.get(gate["auth"].cookie_name)
    gate["client"].cookies.set(gate["auth"].cookie_name, cookie)
    assert gate["client"].get(catalog_path(group)).status_code == 403
    gate["client"].cookies.set(gate["auth"].cookie_name, original_cookie)
    for params in [{"limit": 101}, {"limit": 0}, {"offset": -1}, {"q": "x" * 201}]:
        assert gate["client"].get(catalog_path(group), params=params).status_code == 422
    assert gate["client"].get(catalog_path(group, "/invalid")).status_code == 422


def test_catalog_5000_actual_tools_100_instances_complete_search_and_nested_paging(gate, record_property):
    members = [f"bulk-{index:03d}" for index in range(100)]
    definitions = []
    for instance in members:
        gate["configs"].save_config({"id": instance, "name": f"Synthetic {instance}", "launch": {"type": "external"},
            "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}})
        for index in range(50):
            name = f"query-{index:03d}"
            definition = ToolDefinition(id=f"mcp.{instance}.{name}", name=name, description="Synthetic catalog contract",
                source="mcp", input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
                metadata={"server_id": instance, "original_tool_name": name, "annotations": {"readOnlyHint": True}})
            gate["registry"].register(definition, Mock())
            definitions.append(definition)
    classifications = gate["access"].synchronize_tools(definitions)
    for start in range(0, len(classifications), 500):
        gate["access"].confirm_classifications(reviewer_id=gate["principal"].id, publish=True,
            items=[{"server_id": row["server_id"], "tool_id": row["tool_id"], "expected_fingerprint": row["fingerprint"]}
                   for row in classifications[start:start + 500]])
    group = create(gate, members=members)
    token, headers = catalog_token(gate, ["operations.manage", "tools.read"])
    started = time.perf_counter()
    body = gate["client"].get(catalog_path(group), params={"offset": 49, "limit": 1}, headers=headers).json()
    record_property("catalog_5000_tools_query_seconds", time.perf_counter() - started)
    assert body["visible_tool_count"] == 5000 and body["visible_member_count"] == 100 and body["total"] == 50
    assert len(body["variants"]) == 1 and body["variants"][0]["visible_member_count"] == 100
    search = gate["client"].get(catalog_path(group), params={"q": "mcp.bulk-099.query-049"}, headers=headers).json()
    assert search["total"] == 1 and search["variants"][0]["original_tool_name"] == "query-049"
    detail = gate["client"].get(catalog_path(group, "/" + search["variants"][0]["variant_id"]),
        params={"offset": 97, "limit": 100}, headers=headers).json()
    assert detail["total"] == 100
    assert [item["tool_id"] for item in detail["members"]] == [f"mcp.bulk-{index:03d}.query-049" for index in range(97, 100)]

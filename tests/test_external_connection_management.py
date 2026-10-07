"""EXT-07..12: actual HTTP draft management with isolated SQLite and policy data.

Synthetic registry definitions exercise policy, not downstream/OAuth transport.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.external_connection_store import ExternalConnectionStore
from lingshu_gate.interfaces.control_api.auth_routes import register_auth_routes
from lingshu_gate.interfaces.control_api.external_connection_routes import register_external_connection_routes
from lingshu_gate.models import ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRegistry


@pytest.fixture
def api(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", "Synthetic-Only-123!")
    monkeypatch.delenv("LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE", raising=False)
    settings = Settings(data_dir=tmp_path, db_url=f"sqlite:///{tmp_path / 'drafts.db'}")
    database = SQLiteDatabase(settings.db_url, tmp_path)
    access = AccessControlStore(database)
    auth = AuthStore(settings, database)
    admin = auth.list_users()[0]
    auth.change_password(admin["id"], "Synthetic-Only-123!")
    access.save_role(code="writer", name="Writer", description="", permissions=[
        "console.view", "tools.read", "tools.invoke", "credentials.manage.self"])
    users = {}
    for name, role in (("reader", "viewer"), ("writer", "writer"), ("other", "writer"), ("operator", "operator")):
        users[name] = auth.create_user(username=name, password="Synthetic-Only-123!", role=role)
        for server in "AB":
            access.save_grant(subject_type="user", subject_id=users[name]["id"], server_id=server,
                              permission_type_code="write" if name in {"writer", "other"} and server == "B" else "read",
                              created_by=admin["id"])
    registry = ToolRegistry()
    for server in "ABC":
        for level in ("read", "write"):
            definition = ToolDefinition(id=f"mcp.{server}.{level}", name=f"{server}.{level}", description="Synthetic",
                                        source="mcp", permission=level, metadata={"server_id": server})
            registry.register(definition, lambda arguments: None)
    access.synchronize_tools(registry.list_definitions())
    for server in "ABC":
        for level in ("read", "write"):
            access.set_classification(server_id=server, tool_id=f"mcp.{server}.{level}", access=level,
                                      destructive=False, idempotent=level == "read", reviewer_id=admin["id"])
        access.publish_classifications(server_id=server, reviewer_id=admin["id"])
    store = ExternalConnectionStore(database)
    observability = ObservabilityStore(database)
    app = FastAPI()
    app.state.external_connection_store = store
    register_auth_routes(app, settings=settings, auth_store=auth, observability_store=observability,
                         require_viewer=auth.authenticate_request)
    register_external_connection_routes(app, auth_store=auth, access_store=access, registry=registry,
                                        store=store, observability_store=observability)
    with TestClient(app) as client:
        def login(name):
            client.headers.pop("authorization", None)
            client.cookies.clear()
            response = client.post("/v1/auth/login", json={"username": name, "password": "Synthetic-Only-123!"})
            assert response.status_code == 200, response.text
        yield client, login, store, access, users, auth, database


def draft(**overrides):
    return {"enabled": False, "client_id": "synthetic-client", "server_allowlist": ["A", "B"],
            "tool_allowlist": ["mcp.A.read", "mcp.B.read"], "access": ["read"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "rate_per_minute": 30, "concurrency": 1, **overrides}


def test_ext07_admin_config_disabled_revision_and_reference_validation(api):
    client, login, store, *_ = api
    login("operator")
    assert client.get("/v1/auth/external-connection/config").status_code == 403
    login("synthetic-admin")
    assert client.get("/v1/auth/external-connection/config").json()["revision"] == 0
    payload = {"enabled": False, "mode": "secure_mcp_tunnel", "tunnel_reference": "tunnel:synthetic",
               "runtime_secret_reference": "credential:synthetic", "trusted_issuers": ["https://id.example.test"],
               "resource_mappings": [["https://tunnel.example.test/mcp", "https://gate.example.test/mcp"]],
               "expected_revision": 0}
    response = client.put("/v1/auth/external-connection/config", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["connected"] is False
    assert response.json()["revision"] == 1
    assert client.put("/v1/auth/external-connection/config", json=payload).status_code == 409
    assert client.put("/v1/auth/external-connection/config", json={**payload, "enabled": True}).status_code == 422
    assert client.put("/v1/auth/external-connection/config", json={**payload, "token": "synthetic"}).status_code == 422
    assert client.put("/v1/auth/external-connection/config", json={**payload, "endpoint": "https://user:pass@example.test"}).status_code == 422
    login("reader")
    status = client.get("/v1/auth/external-connection").json()
    assert status["mode"] == "secure_mcp_tunnel" and status["enabled"] is False
    assert "runtime_secret_reference" not in status


def test_ext08_personal_scope_intersection_and_no_implicit_admin_access(api):
    client, login, *_ = api
    login("reader")
    assert client.post("/v1/auth/external-grants", json=draft()).status_code == 201
    for patch in [{"tool_allowlist": ["mcp.A.read", "mcp.B.write"]}, {"access": ["read", "write"]},
                  {"server_allowlist": ["C"], "tool_allowlist": ["mcp.C.read"]}]:
        assert client.post("/v1/auth/external-grants", json=draft(**patch)).status_code == 403
    login("writer")
    response = client.post("/v1/auth/external-grants", json=draft(
        tool_allowlist=["mcp.A.read", "mcp.B.write"], access=["read", "write"]))
    assert response.status_code == 201, response.text
    grant_id = response.json()["id"]
    login("other")
    assert client.get(f"/v1/auth/external-grants/{grant_id}").status_code == 404
    assert client.patch(f"/v1/auth/external-grants/{grant_id}", json={**draft(), "expected_revision": 1}).status_code == 404
    assert client.delete(f"/v1/auth/external-grants/{grant_id}").status_code == 404
    assert client.get("/v1/auth/external-grants").json()["grants"] == []
    login("synthetic-admin")
    assert client.get(f"/v1/auth/external-grants/{grant_id}").status_code == 404


def test_ext09_revision_expiry_revocation_and_policy_recheck(api):
    client, login, store, access, users, *_ = api
    login("writer")
    grant = client.post("/v1/auth/external-grants", json=draft()).json()
    path = f"/v1/auth/external-grants/{grant['id']}"
    changed = client.patch(path, json={**draft(rate_per_minute=3), "expected_revision": 1})
    assert changed.status_code == 200
    assert changed.json()["policy_version"] == 2
    assert client.patch(path, json={**draft(), "expected_revision": 1}).status_code == 409
    for item in access.list_grants(subject_type="user", subject_id=users["writer"]["id"]):
        access.delete_grant(item["id"])
    assert client.get(path).json()["scope_currently_authorized"] is False
    assert client.patch(path, json={**draft(), "expected_revision": 2}).status_code == 403
    raw = store.get_grant(users["writer"]["id"], grant["id"])
    raw["expires_at"] = "2000-01-01T00:00:00+00:00"
    store.update_grant(users["writer"]["id"], grant["id"], raw, 2)
    assert client.get(path).json()["state"] == "expired"
    revoked = client.delete(path).json()
    assert revoked["state"] == "revoked" and revoked["enabled"] is False
    assert client.delete(path).json()["revision"] == revoked["revision"]


def test_ext10_reject_unconfigured_activation_wildcards_past_expiry_and_persisted_tokens(api):
    client, login, *_ = api
    login("writer")
    activation = client.post("/v1/auth/external-grants", json=draft(enabled=True))
    assert activation.status_code == 409
    assert "external_connection_disabled" in activation.json()["detail"]["activation_errors"]
    assert client.get("/v1/auth/external-grants").json()["grants"] == []
    for patch in [{"access_token": "synthetic"}, {"server_allowlist": ["*"]},
                  {"expires_at": "2000-01-01T00:00:00Z"}, {"expires_at": "2099-01-01T00:00:00"},
                  {"rate_per_minute": 0}]:
        assert client.post("/v1/auth/external-grants", json=draft(**patch)).status_code == 422


def test_ext11_token_scope_and_unpublished_admin_drafts(api):
    client, login, store, access, users, auth, database = api
    login("writer")
    principal, _, _ = auth.login(username="writer", password="Synthetic-Only-123!")
    token = auth.create_api_token(principal=principal, name="synthetic-read", scopes=["credentials.manage.self", "tools.read"])
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token['token']}"
    assert client.post("/v1/auth/external-grants", json=draft()).status_code == 201
    assert client.post("/v1/auth/external-grants", json=draft(
        tool_allowlist=["mcp.A.read", "mcp.B.write"], access=["read", "write"])).status_code == 403
    login("synthetic-admin")
    access.set_classification(server_id="A", tool_id="mcp.A.read", access="read", destructive=False,
                              idempotent=True, reviewer_id="synthetic")
    assert client.post("/v1/auth/external-grants", json=draft()).status_code == 403


def test_ext12_store_reopen_keeps_drafts_disabled(api):
    client, login, store, access, users, auth, database = api
    login("reader")
    grant = client.post("/v1/auth/external-grants", json=draft()).json()
    reopened = ExternalConnectionStore(database)
    assert reopened.get_grant(users["reader"]["id"], grant["id"])["enabled"] is False


def test_ext13_subject_links_require_admin_and_exact_immutable_identity(api):
    client, login, store, access, users, *_ = api
    path = "/v1/auth/external-subject-links"
    payload = {"issuer": "https://id.example.test", "subject": "synthetic-subject",
               "user_id": users["reader"]["id"], "enabled": True}
    login("writer")
    assert client.get(path).status_code == 403
    assert client.post(path, json=payload).status_code == 403
    login("synthetic-admin")
    assert client.post(path, json=payload).status_code == 400
    config = client.put("/v1/auth/external-connection/config", json={
        "enabled": False, "mode": "disabled", "trusted_issuers": [payload["issuer"]],
        "expected_revision": 0})
    assert config.status_code == 200, config.text
    created = client.post(path, json=payload)
    assert created.status_code == 201, created.text
    link = created.json()
    assert store.resolve_subject(payload["issuer"], payload["subject"]) == users["reader"]["id"]
    assert client.post(path, json={**payload, "user_id": users["other"]["id"]}).status_code == 409
    item = f"{path}/{link['id']}"
    assert client.patch(item, json={"enabled": True, "expected_revision": 1,
                                    "user_id": users["other"]["id"]}).status_code == 422
    disabled = client.delete(item)
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    with pytest.raises((KeyError, PermissionError)):
        store.resolve_subject(payload["issuer"], payload["subject"])
    assert client.patch(item, json={"enabled": True, "expected_revision": 1}).status_code == 409
    assert client.patch(item, json={"enabled": True, "expected_revision": disabled.json()["revision"]}).status_code == 200


def test_subject_user_labels_search_paging_and_minimal_capability(api, monkeypatch):
    client, login, store, access, users, auth, database = api
    path = "/v1/auth/external-subject-links"
    auth.update_user(users["reader"]["id"], display_name="Synthetic Read Team")
    for index in range(55):
        store.create_subject_link({"issuer": "https://id.example.test", "subject": f"subject-{index:03}",
                                   "user_id": users["reader"]["id"], "enabled": False})
    login("synthetic-admin")
    # No per-user lookup/role expansion is needed to return labels.
    monkeypatch.setattr(auth, "get_user", lambda *_: pytest.fail("N+1 user lookup"))
    queries = []
    original = database.query_all
    def tracked(sql, parameters=()):
        queries.append(sql)
        return original(sql, parameters)
    monkeypatch.setattr(database, "query_all", tracked)
    result = client.get(path, params={"q": "Synthetic Read Team", "offset": 50, "limit": 50})
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 55
    assert len(result.json()["links"]) == 5
    user = result.json()["links"][0]["user"]
    assert user == {"id": users["reader"]["id"], "username": "reader", "display_name": "Synthetic Read Team", "status": "active"}
    assert sum("LEFT JOIN users" in sql for sql in queries) == 1
    for query in ("reader", users["reader"]["id"]):
        assert client.get(path, params={"q": query}).json()["total"] == 55
    assert client.get(path, params={"q": "%"}).json()["total"] == 0  # literal, not glob
    access.save_role(code="identity-manager", name="Identity manager", description="Synthetic",
                     permissions=["console.view", "external_connections.manage"])
    access.set_user_roles(users["writer"]["id"], ["identity-manager"])
    login("writer")
    options = client.get(path + "/user-options", params={"q": "Synthetic Read Team"})
    assert options.status_code == 200 and options.json()["users"] == [user]
    assert set(options.json()["users"][0]) == {"id", "username", "display_name", "status"}
    # Removing the capability invalidates the existing session's next request.
    access.set_user_roles(users["writer"]["id"], ["writer"])
    assert client.get(path + "/user-options", params={"q": user["id"]}).status_code == 403
    for name in ("reader", "operator"):
        login(name)
        assert client.get(path + "/user-options").status_code == 403
    principal, _, _ = auth.login(username="synthetic-admin", password="Synthetic-Only-123!")
    token = auth.create_api_token(principal=principal, name="no-directory-scope", scopes=["console.view"])
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token['token']}"
    assert client.get(path + "/user-options").status_code == 403
    assert client.get(path).status_code == 403


def test_subject_user_selector_rechecks_active_and_missing_label_is_not_invented(api):
    client, login, store, access, users, auth, database = api
    path = "/v1/auth/external-subject-links"
    login("synthetic-admin")
    assert client.put("/v1/auth/external-connection/config", json={"enabled": False, "mode": "disabled",
        "trusted_issuers": ["https://id.example.test"], "expected_revision": 0}).status_code == 200
    target = users["reader"]["id"]
    assert client.get(path + "/user-options", params={"q": target}).json()["total"] == 1
    auth.update_user(target, status_value="disabled")
    assert client.get(path + "/user-options", params={"q": target}).json()["total"] == 0
    assert client.post(path, json={"issuer": "https://id.example.test", "subject": "stale-selected-user",
                                  "user_id": target, "enabled": False}).status_code == 400
    # Simulate a legacy dangling reference in this isolated database only.
    link = store.create_subject_link({"issuer": "https://id.example.test", "subject": "legacy",
                                     "user_id": target, "enabled": False})
    with database.connect() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("UPDATE external_oauth_subject_links SET user_id='missing-synthetic-user' WHERE id=?", (link["id"],))
    item = client.get(path, params={"q": "missing-synthetic-user"}).json()["links"][0]
    assert item["user"] is None and item["user_id"] == "missing-synthetic-user"
    assert client.patch(f"{path}/{link['id']}", json={"enabled": True, "expected_revision": 1}).status_code == 400

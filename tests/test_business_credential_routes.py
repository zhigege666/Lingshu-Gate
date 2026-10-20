"""Real authentication, CSRF and secret-safe HTTP contracts for business accounts."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.business_credentials import BusinessCredentialService
from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.auth import AuthStore
from lingshu_gate.business_credential_store import BusinessCredentialStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api.business_credential_routes import register_business_credential_routes
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRegistry

BASE = "/v1/business-credentials"
PASSWORD = "Synthetic-Business-Admin!"
ACCOUNT_SECRET = "Synthetic-Only-Business-Password!"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-credential-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", PASSWORD)
    settings = Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d", auth_enabled=True)
    database = SQLiteDatabase("", tmp_path)
    access = AccessControlStore(database)
    auth = AuthStore(settings, database)
    auth.change_password(str(auth.list_users()[0]["id"]), PASSWORD)
    principal, cookie, _ = auth.login(username="synthetic-credential-admin", password=PASSWORD)
    access.refresh_principal = lambda actor: current_tool_principal(auth, actor)
    store = BusinessCredentialStore(database, tmp_path)
    service = BusinessCredentialService(store, auth, access, ToolRegistry(), Mock(spec=McpRuntimeManager),
        McpConfigStore(settings.config_dir), ObservabilityStore(database))
    app = FastAPI()
    register_business_credential_routes(app, auth=auth, service=service)
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(auth.cookie_name, cookie)
        yield {"client": client, "app": app, "store": store, "service": service, "auth": auth,
               "access": access, "principal": principal, "database": database}


def draft(**extra):
    return {"name": "Synthetic test doctor", "environment": "test", "business_role": "doctor",
        "login_url": "https://business.example.test/#/login", "scope": "personal",
        "username": "synthetic-doctor", "password": ACCOUNT_SECRET, **extra}


def ticket(gate, body, method="POST", path=BASE, origin="https://testserver"):
    nonce = secrets.token_hex(32)
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(bytes.fromhex(nonce), encoded, hashlib.sha256).hexdigest()
    response = gate["client"].post(origin + BASE + "/csrf", params={"target": method + ":" + path, "request_digest": digest},
        headers={"Origin": origin})
    assert response.status_code == 200, response.text
    return {"Origin": origin, "X-CSRF-Token": response.json()["csrf"], "X-CSRF-Nonce": nonce}


def create(gate, **extra):
    body = draft(**extra)
    response = gate["client"].post(BASE, json=body, headers=ticket(gate, body))
    assert response.status_code == 200, response.text
    return response.json()


def test_http_crud_masks_secrets_preserves_blank_edit_and_is_audited(gate):
    item = create(gate)
    assert item["username_masked"] == "***" and item["password_configured"] is True
    assert ACCOUNT_SECRET not in json.dumps(item) and "synthetic-doctor" not in json.dumps(item)
    response = gate["client"].get(BASE)
    assert response.headers["cache-control"] == "no-store"
    assert ACCOUNT_SECRET not in response.text
    body = {key: value for key, value in draft().items() if key not in {"scope", "username", "password"}}
    body.update(expected_version=1, username=None, password=None, name="Updated label")
    path = BASE + "/" + item["id"]
    saved = gate["client"].put(path, json=body, headers=ticket(gate, body, "PUT", path))
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert gate["store"].resolve_secret(item["id"], expected_version=2)["password"] == ACCOUNT_SECRET
    stale = gate["client"].put(path, json=body, headers=ticket(gate, body, "PUT", path))
    assert stale.status_code == 409
    target = path + "?expected_version=2"
    deleted = gate["client"].request("DELETE", target, json={}, headers=ticket(gate, {}, "DELETE", target))
    assert deleted.status_code == 200 and deleted.json()["deleted"]
    events = gate["database"].query_all("SELECT payload_json FROM events WHERE subject_type='business_credential'")
    assert len(events) == 3 and ACCOUNT_SECRET not in str(events)


@pytest.mark.parametrize("change", ["origin", "missing", "nonce", "body", "replay"])
def test_secret_mutation_has_current_same_origin_one_use_body_bound_csrf(gate, change):
    body = draft()
    headers = ticket(gate, body)
    if change == "origin":
        headers["Origin"] = "https://other.example.test"
    elif change == "missing":
        del headers["X-CSRF-Token"]
    elif change == "nonce":
        headers["X-CSRF-Nonce"] = secrets.token_hex(32)
    elif change == "body":
        body["password"] = "Changed-Synthetic-Secret!"
    elif change == "replay":
        assert gate["client"].post(BASE, json=body, headers=headers).status_code == 200
    response = gate["client"].post(BASE, json=body, headers=headers)
    assert response.status_code == 403
    assert body["password"] not in response.text


def test_csrf_storage_contains_no_plain_secret_digest_or_random_key(gate):
    body = draft()
    headers = ticket(gate, body)
    rows = gate["database"].query_all("SELECT * FROM console_csrf_tickets")
    serialized = json.dumps([dict(row) for row in rows])
    plain_digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert plain_digest not in serialized and headers["X-CSRF-Nonce"] not in serialized
    assert body["password"] not in serialized


@pytest.mark.parametrize("values", [{"password": "***"}, {"password": {"raw": ACCOUNT_SECRET}},
    {"unknown": ACCOUNT_SECRET}, {"login_url": "https://business.example.test/?password=" + ACCOUNT_SECRET}])
def test_invalid_secret_values_and_unknown_fields_never_echo_input(gate, values):
    body = draft(**values)
    response = gate["client"].post(BASE, json=body, headers=ticket(gate, body))
    assert response.status_code == 422
    assert ACCOUNT_SECRET not in response.text and "synthetic-doctor" not in response.text
    assert not gate["store"].list_credentials()


def test_non_object_body_is_sanitized_before_framework_validation(gate):
    response = gate["client"].post(BASE, json=[ACCOUNT_SECRET])
    assert response.status_code == 422 and ACCOUNT_SECRET not in response.text


def test_http_remote_client_cannot_submit_secret(gate):
    body = draft()
    headers = ticket(gate, body, origin="http://testserver")
    response = gate["client"].post("http://testserver" + BASE, json=body, headers=headers)
    assert response.status_code == 400 and not gate["store"].list_credentials()


def test_personal_records_and_sessions_are_not_visible_to_another_user(gate):
    item = create(gate)
    auth = gate["auth"]
    auth.create_user(username="synthetic-viewer", password=PASSWORD, role="viewer")
    _, cookie, _ = auth.login(username="synthetic-viewer", password=PASSWORD)
    gate["client"].cookies.set(auth.cookie_name, cookie)
    assert gate["client"].get(BASE).json()["credentials"] == []
    assert gate["client"].get(BASE + "/" + item["id"]).status_code == 404
    assert gate["client"].get(BASE + "/" + item["id"] + "/sessions").status_code == 404
    assert gate["client"].get(BASE, params={"scope": "shared"}).status_code == 403
    assert gate["client"].get(BASE + "/targets").json() == {"servers": [], "users": [], "roles": []}


def test_disabled_auth_cannot_create_business_secret(gate):
    gate["auth"].enabled = False
    response = gate["client"].post(BASE, json=draft())
    assert response.status_code == 403 and not gate["store"].list_credentials()

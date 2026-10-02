"""EXT-01..05: disabled external integration and fail-closed policy boundaries."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.external_connection import ExternalConnectionConfig, OAuthSubjectLink, UserExternalGrant
from lingshu_gate.interfaces.control_api.auth_routes import register_auth_routes
from lingshu_gate.observability_store import ObservabilityStore


def test_ext01_disabled_status_and_rejected_enablement(monkeypatch):
    assert Settings().external_connection.status()["connected"] is False
    with pytest.raises(ValueError, match="cannot be enabled"):
        Settings(external_connection=ExternalConnectionConfig(enabled=True))
    monkeypatch.setenv("LINGSHU_GATE_EXTERNAL_CONNECTION_ENABLED", "true")
    with pytest.raises(ValueError, match="authenticated management API"):
        Settings.from_env()


def test_ext02_exact_issuer_subject_and_canonical_audience():
    config = ExternalConnectionConfig(
        trusted_issuers=("https://identity.example.test",),
        resource_mappings=(("https://tunnel.example.test/one", "https://gate.example.test/mcp"),),
    )
    link = OAuthSubjectLink("https://identity.example.test", "subject-a", "user-a", enabled=True)
    assert link.matches(verified_issuer=link.issuer, verified_subject=link.subject,
                        trusted_issuers=config.trusted_issuers)
    assert not link.matches(verified_issuer="https://impostor.example.test", verified_subject=link.subject,
                            trusted_issuers=config.trusted_issuers)
    assert not link.matches(verified_issuer=link.issuer, verified_subject="subject-b",
                            trusted_issuers=config.trusted_issuers)
    assert config.canonical_resource("https://tunnel.example.test/one") == "https://gate.example.test/mcp"
    assert config.canonical_resource("https://tunnel.example.test/two") is None
    ambiguous = replace(config, resource_mappings=config.resource_mappings * 2)
    assert ambiguous.canonical_resource("https://tunnel.example.test/one") is None


def test_ext03_grant_intersection_revocation_expiry_and_isolation():
    now = datetime.now(timezone.utc)
    grant = UserExternalGrant("user-a", "client-a", "grant-a", enabled=True,
                              server_allowlist=("A", "B"), tool_allowlist=("A.read", "B.write"),
                              access=("read", "write"), expires_at=now + timedelta(hours=1))
    args = dict(user_id="user-a", client_id="client-a", server_id="A", qualified_tool_name="A.read",
                required_access="read", oauth_scopes=("tools.read",), now=now, policy_version=1)
    assert grant.allows(**args)
    for field, value in [("user_id", "user-b"), ("client_id", "client-b"), ("server_id", "C"),
                         ("qualified_tool_name", "C.secret"), ("required_access", "write"),
                         ("oauth_scopes", ()), ("policy_version", 2)]:
        assert not grant.allows(**{**args, field: value})
    for field, value in [("enabled", False), ("revoked_at", now), ("expires_at", now),
                         ("expires_at", None), ("rate_per_minute", 0), ("concurrency", 0)]:
        assert not replace(grant, **{field: value}).allows(**args)


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-owner")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", "Synthetic-Only-123!")
    monkeypatch.delenv("LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE", raising=False)
    settings = Settings(data_dir=tmp_path, db_url=f"sqlite:///{tmp_path / 'isolated.db'}")
    database = SQLiteDatabase(settings.db_url, tmp_path)
    AccessControlStore(database)
    auth = AuthStore(settings, database)
    principal, session, _ = auth.login(username="synthetic-owner", password="Synthetic-Only-123!")
    auth.change_password(principal.id, "Synthetic-Replaced-123!")
    _, session, _ = auth.login(username="synthetic-owner", password="Synthetic-Replaced-123!")
    app = FastAPI()
    register_auth_routes(app, settings=settings, auth_store=auth,
                         observability_store=ObservabilityStore(database),
                         require_viewer=auth.authenticate_request)
    with TestClient(app) as client:
        client.cookies.set(settings.auth_session_cookie_name, session)
        yield client


def test_ext04_real_api_disabled_status_without_secrets(auth_client):
    response = auth_client.get("/v1/auth/external-connection")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False and body["state"] == "disabled"
    assert "trusted_jwks_mapping_required" in body["validation_errors"]
    assert body["oauth_verifier_ready"] is False
    assert body["provider_verified"] is False
    assert "runtime_secret_reference" not in body
    auth_client.cookies.clear()
    assert auth_client.get("/v1/auth/external-connection").status_code == 401


@pytest.mark.parametrize("authorization", ["Bearer invalid-synthetic", "Bearer ", "Basic invalid"])
def test_ext05_invalid_bearer_never_inherits_valid_session(auth_client, authorization):
    assert auth_client.get("/v1/auth/me").status_code == 200
    response = auth_client.get("/v1/auth/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_ext06_delegated_admin_cannot_mint_broader_tokens():
    from lingshu_gate.auth import AuthPrincipal

    principal = AuthPrincipal(id="synthetic-admin", username="synthetic-admin", role="admin",
                              permissions=("*",), auth_type="oauth", scopes=("*",),
                              delegated_scopes=("tools.read",))
    assert AuthStore._normalize_api_token_scopes(
        principal=principal, scopes=["tools.read"], allow_default=False) == ["tools.read"]
    for scopes in [["*"], ["tools.invoke"], ["operations.manage"]]:
        with pytest.raises(ValueError, match="scope exceeds"):
            AuthStore._normalize_api_token_scopes(principal=principal, scopes=scopes, allow_default=False)
    with pytest.raises(ValueError, match="scope exceeds"):
        AuthStore._normalize_api_token_scopes(principal=replace(principal, delegated_scopes=()),
                                              scopes=["tools.read"], allow_default=False)

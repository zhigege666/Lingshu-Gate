"""Private HTTP declarations never authorize their own downstream connection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.endpoint_security import private_http_origin
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_http_trust import (
    McpHttpTrustConflict,
    McpHttpTrustDenied,
    McpHttpTrustStore,
    McpHttpTrustUpdate,
    TrustedHttpOrigin,
)
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_manifest_validation import validate_mcp_manifest
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.registry import ToolRegistry


def _setup(tmp_path: Path):
    settings = Settings(config_dir=tmp_path / "mcp.d", data_dir=tmp_path / "data", allowed_root=tmp_path, db_url=f"sqlite:///{tmp_path / 'data' / 'gate.db'}")
    database = SQLiteDatabase(settings.db_url, settings.data_dir)
    access = AccessControlStore(database)
    auth = AuthStore(settings, database)
    actor = auth.create_user(username="synthetic-trust-admin", password="Synthetic-Trust-123!", role="admin")
    trust = McpHttpTrustStore(database)
    return settings, trust, str(actor["id"]), auth, access


def _request(revision=0, origins=None):
    return McpHttpTrustUpdate(origins=[TrustedHttpOrigin(ip="10.23.45.67", port=8080)] if origins is None else origins, expected_revision=revision, confirmed=True)


def _manifest(endpoint="http://10.23.45.67:8080/mcp", server_id="synthetic-private"):
    return {"id": server_id, "launch": {"type": "external"}, "transport": {"type": "streamable_http", "endpoint": endpoint}, "auto_start": False}


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
def test_trust_requires_an_explicit_boolean_confirmation(confirmed) -> None:
    with pytest.raises(ValidationError):
        McpHttpTrustUpdate.model_validate({"origins": [], "expected_revision": 0, "confirmed": confirmed})


@pytest.mark.parametrize("ip", ["10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.1.2"])
def test_exact_canonical_rfc1918_ranges(ip: str) -> None:
    assert TrustedHttpOrigin(ip=ip, port=80).ip == ip


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "100.100.100.200", "100.64.0.1", "172.32.0.1", "192.0.0.8", "8.8.8.8", "0.0.0.0", "224.0.0.1", "10.023.45.67", "167772161", "::1", "::ffff:10.0.0.1", "fd00::1", "private.example.test"])
def test_trust_rejects_metadata_reserved_public_dns_and_noncanonical_literals(ip: str) -> None:
    with pytest.raises(ValidationError):
        TrustedHttpOrigin(ip=ip, port=8080)


@pytest.mark.parametrize("endpoint", ["http://10.23.45.67:8080/mcp?token=synthetic", "http://user:synthetic@10.23.45.67:8080/mcp", "http://10.23.45.67:8080/mcp#fragment", "http://10.23.45.67:0/mcp", "http://10.23.45.67:8080/%0a", "http://10.023.45.67:8080/mcp"])
def test_trusted_syntax_never_weakens_url_validation(endpoint: str) -> None:
    with pytest.raises(ValueError):
        private_http_origin(endpoint)


def test_default_denial_then_exact_server_ip_port_and_live_revocation(tmp_path: Path) -> None:
    settings, trust, actor, _, _ = _setup(tmp_path)
    store = McpConfigStore(settings.config_dir, http_trust_store=trust)
    payload = _manifest()
    assert McpServerManifest.model_validate(payload).transport.endpoint == payload["transport"]["endpoint"]
    with pytest.raises(ValueError, match="administrator-approved trust"):
        store.save_config(payload)
    result = validate_mcp_manifest(settings, store, payload)
    assert result["ok"] is False
    assert any(check["name"] == "transport.endpoint" and check["severity"] == "error" for check in result["checks"])
    trust.update(payload["id"], _request(), actor_id=actor)
    assert validate_mcp_manifest(settings, store, payload)["ok"] is True
    store.save_config(payload)
    for wrong in [_manifest(server_id="other-service"), _manifest(endpoint="http://10.23.45.68:8080/mcp"), _manifest(endpoint="http://10.23.45.67:8081/mcp")]:
        with pytest.raises(ValueError, match="administrator-approved trust"):
            store.save_config(wrong, overwrite=True)
    trust.update(payload["id"], _request(1, []), actor_id=actor)
    assert validate_mcp_manifest(settings, store, payload, expected_id=payload["id"])["ok"] is False
    with pytest.raises(ValueError, match="administrator-approved trust"):
        store.save_config(payload, overwrite=True)
    manager = McpRuntimeManager(settings, ToolRegistry())
    with pytest.raises(ValueError, match="administrator-approved trust"):
        manager.apply_manifest(McpServerManifest.model_validate(payload), start=False)


def test_cached_client_checks_policy_before_request_reconnect_and_session_cleanup(tmp_path: Path) -> None:
    settings, trust, actor, _, _ = _setup(tmp_path)
    trust.update("synthetic-private", _request(), actor_id=actor)
    client = StreamableHttpMcpClient(McpServerManifest.model_validate(_manifest()), settings)
    client._opener = Mock()
    trust.update("synthetic-private", _request(1, []), actor_id=actor)
    with pytest.raises(ValueError, match="administrator-approved trust"):
        client._post({}, 1, expect_response=False, request_id=None, protocol_headers={})
    with pytest.raises(ValueError, match="administrator-approved trust"):
        client.start()
    client.session_id = "synthetic-session"
    client.stop()
    client._opener.open.assert_not_called()


def test_unavailable_policy_fails_closed_before_network(tmp_path: Path) -> None:
    settings, trust, actor, _, _ = _setup(tmp_path)
    trust.update("synthetic-private", _request(), actor_id=actor)
    client = StreamableHttpMcpClient(McpServerManifest.model_validate(_manifest()), settings)
    client._opener = Mock()
    with patch.object(McpHttpTrustStore, "get", side_effect=OSError("synthetic failure")):
        with pytest.raises(ValueError, match="trust could not be read"):
            client.start()
    client._opener.open.assert_not_called()


def test_live_admin_and_permission_boundary_and_cas_preserve_trust(tmp_path: Path) -> None:
    _, trust, actor, _, access = _setup(tmp_path)
    assert trust.update("synthetic-private", _request(), actor_id=actor)["revision"] == 1
    with pytest.raises(McpHttpTrustConflict):
        trust.update("synthetic-private", _request(), actor_id=actor)
    assert trust.get("synthetic-private")["revision"] == 1
    access.set_user_roles(actor, ["operator"])
    with pytest.raises(McpHttpTrustDenied):
        trust.update("synthetic-private", _request(1, []), actor_id=actor)
    assert trust.get("synthetic-private")["origins"] == [{"ip": "10.23.45.67", "port": 8080}]


def test_http_admin_entry_defaults_empty_rejects_operator_and_cross_site_then_live_demotion(tmp_path: Path, monkeypatch) -> None:
    for name, value in {"DATA_DIR": str(tmp_path / "data"), "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path), "AUTH_ENABLED": "true", "ADMIN_USERNAME": "synthetic-bootstrap", "ADMIN_PASSWORD": "Synthetic-Bootstrap-123!", "BOOTSTRAP_PASSWORD_FILE": ""}.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{name}", value)
    from lingshu_gate.main import create_app
    app = create_app()
    auth = app.state.auth_store
    admin = auth.create_user(username="synthetic-trust-api-admin", password="Synthetic-Admin-123!", role="admin")
    auth.create_user(username="synthetic-trust-operator", password="Synthetic-Operator-123!", role="operator")
    with TestClient(app, base_url="https://localhost") as client:
        assert client.get("/v1/mcp/http-trust/synthetic-private").status_code == 401
        assert client.post("/v1/auth/login", json={"username": "synthetic-trust-operator", "password": "Synthetic-Operator-123!"}).status_code == 200
        assert client.put("/v1/mcp/http-trust/synthetic-private", json=_request().model_dump()).status_code == 403
        assert client.post("/v1/auth/login", json={"username": "synthetic-trust-api-admin", "password": "Synthetic-Admin-123!"}).status_code == 200
        assert client.get("/v1/mcp/http-trust/synthetic-private").json() == {"server_id": "synthetic-private", "revision": 0, "origins": []}
        assert client.put("/v1/mcp/http-trust/synthetic-private", json=_request().model_dump(), headers={"Origin": "https://untrusted.example.test"}).status_code == 403
        assert client.put("/v1/mcp/http-trust/synthetic-private", json=_request().model_dump()).status_code == 200
        assert client.put("/v1/mcp/http-trust/synthetic-private", json=_request().model_dump()).status_code == 409
        assert client.post("/v1/mcp/configs", json={"manifest": _manifest(), "apply": False, "start": False}).status_code == 200
        oauth = AuthPrincipal(id=str(admin["id"]), username="synthetic-trust-api-admin", role="admin", roles=("admin",), permissions=("operations.manage",), scopes=("operations.manage",), auth_type="oauth")
        with patch.object(auth, "authenticate_request", return_value=oauth):
            assert client.get("/v1/mcp/http-trust/synthetic-private").status_code == 403
            denied = client.put("/v1/mcp/http-trust/synthetic-private", json=_request(1, []).model_dump())
            assert denied.status_code == 403
            assert "OAuth" in denied.json()["detail"]
        assert app.state.mcp_config_store.http_trust_store.get("synthetic-private")["revision"] == 1
        app.state.access_store.set_user_roles(str(admin["id"]), ["operator"])
        assert client.put("/v1/mcp/http-trust/synthetic-private", json=_request(1, []).model_dump()).status_code == 403
        assert app.state.mcp_config_store.http_trust_store.get("synthetic-private")["revision"] == 1


@pytest.mark.parametrize("ip", ["10.23.45.67", "172.16.1.2", "172.31.255.254", "192.168.1.2"])
def test_approved_private_http_request_reaches_the_exact_endpoint(tmp_path: Path, ip: str) -> None:
    settings, trust, actor, _, _ = _setup(tmp_path)
    trust.update("synthetic-private", _request(origins=[TrustedHttpOrigin(ip=ip, port=8080)]), actor_id=actor)
    endpoint = f"http://{ip}:8080/mcp"
    client = StreamableHttpMcpClient(McpServerManifest.model_validate(_manifest(endpoint)), settings)
    response = MagicMock()
    response.status = 200
    response.headers = {"Content-Type": "application/json"}
    response.read1.side_effect = [b'{"jsonrpc":"2.0","id":1,"result":{"synthetic":true}}', b""]
    client._opener = Mock()
    client._opener.open.return_value = response
    assert client._post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, 1, expect_response=True, request_id=1, protocol_headers={}) == {"jsonrpc": "2.0", "id": 1, "result": {"synthetic": True}}
    request = client._opener.open.call_args.args[0]
    assert request.full_url == endpoint
    assert request.method == "POST"


def test_omitted_port_is_exact_port_80(tmp_path: Path) -> None:
    _, trust, actor, _, _ = _setup(tmp_path)
    trust.update("synthetic-private", _request(origins=[TrustedHttpOrigin(ip="10.23.45.67", port=80)]), actor_id=actor)
    trust.require_endpoint("synthetic-private", "http://10.23.45.67/mcp")
    with pytest.raises(ValueError, match="administrator-approved trust"):
        trust.require_endpoint("synthetic-private", "http://10.23.45.67:8080/mcp")


def test_live_admin_role_without_operations_permission_cannot_change_trust(tmp_path: Path) -> None:
    _, trust, actor, _, _ = _setup(tmp_path)
    with trust.database.connect() as connection:
        connection.execute("DELETE FROM role_permissions WHERE permission_id=(SELECT id FROM control_permissions WHERE code='operations.manage')")
    with pytest.raises(McpHttpTrustDenied):
        trust.update("synthetic-private", _request(), actor_id=actor)
    assert trust.get("synthetic-private")["revision"] == 0


def test_http_allowlist_retains_https_tls_verification_and_no_redirect_handler(tmp_path: Path) -> None:
    import ssl
    import urllib.request
    settings, _, _, _, _ = _setup(tmp_path)
    client = StreamableHttpMcpClient(McpServerManifest.model_validate(_manifest("https://service.example.test/mcp")), settings)
    https = next(handler for handler in client._opener.handlers if isinstance(handler, urllib.request.HTTPSHandler))
    context = https._context or ssl.create_default_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    redirect = next(handler for handler in client._opener.handlers if isinstance(handler, urllib.request.HTTPRedirectHandler))
    request = urllib.request.Request("https://service.example.test/mcp")
    assert redirect.redirect_request(request, None, 302, "synthetic redirect", {}, "http://10.23.45.67/mcp") is None

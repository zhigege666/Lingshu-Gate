"""Built-in OAuth policy and cryptographic operations, disabled until configured.

RS256/JWT/Fernet use maintained libraries. SQLite serializes code consumption,
refresh rotation and replay revocation. HTTP, persistence and policy are separate.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal, AuthStore, hash_secret
from lingshu_gate.external_connection import _https_resource
from lingshu_gate.oauth_store import OAuthStore
from lingshu_gate.registry import ToolRegistry

SCOPES = frozenset({"tools.read", "tools.invoke"})
CODE_TTL = 60
ACCESS_TTL = 600
REFRESH_TTL = 30 * 86400
INTERACTION_TTL = 600
MAX_INTERACTION_TICKET = 16384
MAX_AUTHENTICATED_INTERACTIONS = 200
MAX_USER_INTERACTIONS = 5
MAX_CLIENT_INTERACTIONS = 50
MAX_AUTHENTICATED_COMPLETIONS = 3072
MAX_ANONYMOUS_COMPLETIONS = 1024
MAX_USER_COMPLETIONS = 64
MAX_TOOLS = 5000
BROWSER_COOKIE = "__Secure-lingshu_gate_oauth_browser"
SESSION_COOKIE = "__Secure-lingshu_gate_oauth_session"
PKCE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
PKCE_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


class OAuthError(Exception):
    """Fixed public error code; never include user-provided values."""
    def __init__(self, code: str, status: int = 400) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def scope_set(value: str) -> list[str]:
    values = value.split(" ")
    if not value or len(value) > 256 or any(item not in SCOPES for item in values):
        raise OAuthError("invalid_scope")
    return sorted(set(values))


def valid_callback(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(len(value) <= 2048 and parsed.scheme == "https" and parsed.hostname
                and not parsed.username and not parsed.password and not parsed.fragment
                and (port is None or 1 <= port <= 65535)
                and not any(ord(char) < 33 or ord(char) > 126 or char in {'\\', '"', '<', '>'} for char in value)
                and "*" not in value
                and not {key for key, _ in parse_qsl(parsed.query)} & {"code", "state", "iss", "error"})


def valid_issuer(value: str) -> bool:
    # A fixed HTTPS origin gives unambiguous well-known and browser endpoints.
    return valid_callback(value) and _https_resource(value) and urlsplit(value).path == ""


def callback(request: dict[str, Any], issuer: str, **result: str) -> str:
    parsed = urlsplit(request["redirect_uri"])
    params = parse_qsl(parsed.query, keep_blank_values=True)
    params += list(result.items()) + [("iss", issuer)]
    if request.get("state"):
        params.append(("state", request["state"]))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ""))


def tool_scope_matches(saved: dict[str, Any], current: dict[str, Any]) -> bool:
    # Display-only MCP names can change without changing a permission envelope.
    return all(saved.get(key) == current.get(key) for key in ("id", "server_id", "access", "snapshot"))


class OAuthServer:
    def __init__(self, store: OAuthStore, auth: AuthStore, access: AccessControlStore,
                 registry: ToolRegistry, data_dir: Path) -> None:
        self.store, self.auth, self.access, self.registry = store, auth, access, registry
        self.key_path = data_dir / "oauth-signing.key"

    def ready_config(self, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        config = self.store.config(connection)
        if not self.auth.enabled or not config["enabled"] or not valid_issuer(config["issuer"]):
            raise OAuthError("oauth_disabled", 404)
        return config

    def metadata(self) -> dict[str, Any]:
        config = self.ready_config()
        issuer = config["issuer"]
        return {"issuer": issuer, "authorization_endpoint": issuer + "/oauth/authorize",
                "token_endpoint": issuer + "/oauth/token", "revocation_endpoint": issuer + "/oauth/revoke",
                "jwks_uri": issuer + "/oauth/jwks", "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"], "scopes_supported": sorted(SCOPES),
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                "revocation_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                "authorization_response_iss_parameter_supported": True}

    def jwks(self) -> dict[str, Any]:
        self.ready_config()
        return {"keys": [json.loads(row["public_json"]) for row in self.store.database.query_all(
            "SELECT public_json FROM gate_oauth_keys WHERE active=1 OR retire_at>?", (int(time.time()),))]}

    def _master_key(self, *, create: bool = False) -> bytes:
        try:
            if create and not self.key_path.exists():
                if self.store.database.query_one("SELECT kid FROM gate_oauth_keys LIMIT 1"):
                    raise OAuthError("signing_key_unavailable", 503)
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(Fernet.generate_key())
                        stream.flush()
                        os.fsync(stream.fileno())
            metadata = self.key_path.lstat()
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 44
                    or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077)):
                raise OAuthError("signing_key_unavailable", 503)
            fd = os.open(self.key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                key = stream.read(45)
            Fernet(key)  # Validate the persisted encoding before deriving keys.
            return key
        except (OSError, ValueError) as exc:
            raise OAuthError("signing_key_unavailable", 503) from exc

    def _fernet(self, *, create: bool = False) -> Fernet:
        return Fernet(self._master_key(create=create))

    def _ticket_cipher(self) -> Fernet:
        # Maintained HKDF/Fernet primitives; a distinct purpose key prevents
        # browser tickets from sharing the signing-private-key encryption key.
        derived = HKDF(algorithm=hashes.SHA256(), length=32,
                       salt=b"lingshu_gate_builtin_oauth", info=b"browser_authorization_v1").derive(
                           base64.urlsafe_b64decode(self._master_key()))
        return Fernet(base64.urlsafe_b64encode(derived))

    def rotate_key(self) -> str:
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
        encrypted = self._fernet(create=True).encrypt(private).decode()
        kid = uuid4().hex
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        public.update(kid=kid, alg="RS256", use="sig")
        with self.store.transaction() as connection:
            now = int(time.time())
            connection.execute("DELETE FROM gate_oauth_keys WHERE active=0 AND retire_at<=?", (now,))
            if connection.execute("SELECT COUNT(*) FROM gate_oauth_keys").fetchone()[0] >= 10:
                raise OAuthError("key_rotation_limit", 429)
            connection.execute("UPDATE gate_oauth_keys SET active=0,retire_at=? WHERE active=1", (now + ACCESS_TTL,))
            connection.execute("INSERT INTO gate_oauth_keys VALUES(?,?,?,?,?,?)",
                               (kid, encrypted, json.dumps(public), 1, None, now))
        return kid

    def save_config(self, payload: dict[str, Any], revision: int) -> dict[str, Any]:
        if not valid_issuer(payload["issuer"]) or not _https_resource(payload["resource"]) or not valid_callback(payload["resource"]):
            raise OAuthError("invalid_configuration")
        if urlsplit(payload["resource"]).path != "/mcp":
            raise OAuthError("resource_must_use_mcp_path")
        if payload["enabled"] and not self.auth.enabled:
            raise OAuthError("authentication_required", 409)
        with self.store.transaction() as connection:
            old = self.store.config(connection)
            if old["revision"] != revision:
                raise OAuthError("revision_conflict", 409)
            changed = old["issuer"] != payload["issuer"] or old["resource"] != payload["resource"]
            if old["enabled"] and changed:
                raise OAuthError("disable_before_changing_urls", 409)
            if payload["enabled"] and not connection.execute("SELECT kid FROM gate_oauth_keys WHERE active=1").fetchone():
                raise OAuthError("signing_key_required", 409)
            external = self.auth.external_connections
            if payload["enabled"] and external is not None:
                configured = external.configuration()
                if configured.enabled and (configured.canonical_resource_url or configured.endpoint) != payload["resource"]:
                    raise OAuthError("resource_configuration_conflict", 409)
                if configured.enabled and payload["issuer"] in configured.trusted_issuers:
                    raise OAuthError("issuer_configuration_conflict", 409)
            if changed or not payload["enabled"]:
                now = int(time.time())
                connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE revoked_at IS NULL", (now,))
                connection.execute("DELETE FROM gate_oauth_codes")
                connection.execute("DELETE FROM gate_oauth_interactions")
            connection.execute("INSERT INTO gate_oauth_config VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET "
                               "payload_json=excluded.payload_json,revision=excluded.revision",
                               (json.dumps(payload), revision + 1))
        return self.store.config()

    def create_client(self, name: str, redirects: list[str], scopes: list[str]) -> dict[str, Any]:
        self._check_client_fields(name, redirects, scopes)
        client_id, secret = "lgc_" + secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        with self.store.transaction() as connection:
            if connection.execute("SELECT COUNT(*) FROM gate_oauth_clients").fetchone()[0] >= 100:
                raise OAuthError("client_limit", 409)
            connection.execute("INSERT INTO gate_oauth_clients VALUES(?,?,?,?,?,?,?,?)",
                               (client_id, name.strip(), json.dumps(redirects), json.dumps(sorted(set(scopes))),
                                hash_secret(secret), 1, 1, int(time.time())))
        return {"client": next(client for client in self.store.clients() if client["id"] == client_id),
                "client_secret": secret}

    @staticmethod
    def _check_client_fields(name: str, redirects: list[str], scopes: list[str]) -> None:
        if (not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name)
                or not 1 <= len(redirects) <= 10 or len(set(redirects)) != len(redirects)
                or not all(valid_callback(uri) for uri in redirects)
                or not scopes or not set(scopes) <= SCOPES):
            raise OAuthError("invalid_client_configuration")

    def update_client(self, client_id: str, revision: int, *, enabled: bool,
                      name: str, redirects: list[str], scopes: list[str], rotate: bool = False) -> dict[str, Any]:
        self._check_client_fields(name, redirects, scopes)
        secret = secrets.token_urlsafe(48) if rotate else None
        with self.store.transaction() as connection:
            row = connection.execute("SELECT * FROM gate_oauth_clients WHERE id=?", (client_id,)).fetchone()
            if not row:
                raise OAuthError("client_not_found", 404)
            if row["revision"] != revision:
                raise OAuthError("revision_conflict", 409)
            connection.execute("UPDATE gate_oauth_clients SET name=?,redirect_uris_json=?,scopes_json=?,"
                               "enabled=?,secret_hash=?,revision=revision+1 WHERE id=?",
                               (name.strip(), json.dumps(redirects), json.dumps(sorted(set(scopes))), int(enabled),
                                hash_secret(secret) if secret else row["secret_hash"], client_id))
            # A stale in-flight authorization must be restarted after any client edit.
            connection.execute("DELETE FROM gate_oauth_codes WHERE client_id=?", (client_id,))
            if not enabled or rotate:
                connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE grant_id IN "
                                   "(SELECT id FROM gate_oauth_grants WHERE client_id=?) AND revoked_at IS NULL",
                                   (int(time.time()), client_id))
        result: dict[str, Any] = {"client": next(item for item in self.store.clients() if item["id"] == client_id)}
        if secret:
            result["client_secret"] = secret
        return result

    def start_authorization(self, params: dict[str, str], browser: str) -> str:
        config = self.ready_config()
        row = self.store.database.query_one("SELECT * FROM gate_oauth_clients WHERE id=? AND enabled=1",
                                            (params.get("client_id", ""),))
        if not row or params.get("redirect_uri") not in json.loads(row["redirect_uris_json"]):
            # Do not redirect errors until the client and exact callback are trusted.
            raise OAuthError("invalid_client_or_redirect")
        scopes = scope_set(params.get("scope", "tools.read"))
        if (params.get("response_type") != "code" or params.get("code_challenge_method") != "S256"
                or not PKCE_CHALLENGE.fullmatch(params.get("code_challenge", ""))):
            raise OAuthError("invalid_authorization_request")
        if params.get("resource") != config["resource"]:
            raise OAuthError("invalid_target")
        if not set(scopes) <= set(json.loads(row["scopes_json"])):
            raise OAuthError("invalid_scope")
        request = {**params, "scopes": scopes, "client_revision": row["revision"],
                   "configuration_revision": config["revision"], "issuer": config["issuer"]}
        payload = {"purpose": "authorization_v1", "browser_hash": hash_secret(browser),
                   "request": request, "csrf": secrets.token_urlsafe(32), "expires_at": int(time.time()) + INTERACTION_TTL}
        interaction = self._ticket_cipher().encrypt(json.dumps(payload).encode()).decode()
        if len(interaction) > MAX_INTERACTION_TICKET:
            raise OAuthError("invalid_authorization_request")
        # Unauthenticated authorize requests create no database interaction.
        return interaction

    def _ticket(self, interaction: str, browser: str, csrf: str | None = None) -> dict[str, Any]:
        if not browser or not 40 <= len(interaction) <= MAX_INTERACTION_TICKET:
            raise OAuthError("authorization_expired", 410)
        try:
            payload = json.loads(self._ticket_cipher().decrypt(interaction.encode(), ttl=INTERACTION_TTL))
            if payload["purpose"] != "authorization_v1" or payload["expires_at"] <= int(time.time()):
                raise OAuthError("authorization_expired", 410)
            if not hmac.compare_digest(payload["browser_hash"], hash_secret(browser)):
                raise OAuthError("invalid_browser", 403)
            if csrf is not None and not hmac.compare_digest(payload["csrf"], csrf):
                raise OAuthError("invalid_csrf", 403)
            return dict(payload)
        except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise OAuthError("authorization_expired", 410) from exc

    @staticmethod
    def _cleanup_interactions(connection: sqlite3.Connection) -> None:
        now = int(time.time())
        connection.execute("DELETE FROM gate_oauth_interactions WHERE expires_at<=?", (now,))
        connection.execute("DELETE FROM gate_oauth_codes WHERE expires_at<?", (now - ACCESS_TTL,))
        connection.execute("DELETE FROM gate_oauth_families WHERE expires_at<?", (now - ACCESS_TTL,))

    def _admit_authenticated(self, connection: sqlite3.Connection, user_id: str, client_id: str) -> None:
        self._cleanup_interactions(connection)
        if (connection.execute("SELECT COUNT(*) FROM gate_oauth_interactions WHERE completed=0").fetchone()[0] >= MAX_AUTHENTICATED_INTERACTIONS
                or connection.execute("SELECT COUNT(*) FROM gate_oauth_interactions WHERE completed=0 AND user_id=?",
                                      (user_id,)).fetchone()[0] >= MAX_USER_INTERACTIONS
                or connection.execute("SELECT COUNT(*) FROM gate_oauth_interactions WHERE completed=0 AND client_id=?",
                                      (client_id,)).fetchone()[0] >= MAX_CLIENT_INTERACTIONS):
            raise OAuthError("authorization_capacity", 429)

    def _complete(self, connection: sqlite3.Connection, interaction: str, row: Any,
                  request: dict[str, Any], user_id: str | None, grant_id: str = "") -> None:
        self._cleanup_interactions(connection)
        if user_id:
            count = connection.execute("SELECT COUNT(*) FROM gate_oauth_interactions WHERE completed=1 AND user_id IS NOT NULL").fetchone()[0]
            own = connection.execute("SELECT COUNT(*) FROM gate_oauth_interactions WHERE completed=1 AND user_id=?", (user_id,)).fetchone()[0]
            if count >= MAX_AUTHENTICATED_COMPLETIONS or own >= MAX_USER_COMPLETIONS:
                raise OAuthError("authorization_capacity", 429)
        elif connection.execute("SELECT COUNT(*) FROM gate_oauth_interactions WHERE completed=1 AND user_id IS NULL").fetchone()[0] >= MAX_ANONYMOUS_COMPLETIONS:
            raise OAuthError("authorization_capacity", 429)
        # Retain only a small replay tombstone; completion immediately releases
        # the authenticated slot and the potentially large catalog/request.
        connection.execute("INSERT INTO gate_oauth_interactions "
                           "(id_hash,browser_hash,csrf_hash,request_json,catalog_json,expires_at,completed,user_id,client_id) "
                           "VALUES(?,?,?,?,?, ?,1,?,?) ON CONFLICT(id_hash) DO UPDATE SET "
                           "completed=1,request_json=excluded.request_json,catalog_json='{}',user_id=excluded.user_id",
                           (hash_secret(interaction), row["browser_hash"], row["csrf_hash"],
                            json.dumps({"grant_id": grant_id}) if grant_id else "{}", "{}", row["expires_at"], user_id, request["client_id"]))

    def interaction(self, connection: sqlite3.Connection, interaction: str, browser: str,
                    csrf: str | None = None) -> tuple[Any, dict[str, Any]]:
        payload = self._ticket(interaction, browser, csrf)
        config = self.ready_config(connection)
        row = connection.execute("SELECT * FROM gate_oauth_interactions WHERE id_hash=?",
                                 (hash_secret(interaction),)).fetchone()
        if row and row["expires_at"] <= int(time.time()):
            raise OAuthError("authorization_expired", 410)
        request = payload["request"]
        client = connection.execute("SELECT * FROM gate_oauth_clients WHERE id=? AND enabled=1",
                                    (request["client_id"],)).fetchone()
        if (not client or client["revision"] != request["client_revision"]
                or config["revision"] != request["configuration_revision"]
                or config["issuer"] != request["issuer"] or config["resource"] != request["resource"]):
            raise OAuthError("authorization_changed", 409)
        if row is None:
            row = {"browser_hash": payload["browser_hash"], "csrf_hash": hash_secret(payload["csrf"]),
                   "completed": 0, "expires_at": payload["expires_at"], "catalog_json": "{}", "user_id": None}
        return row, request

    def session_principal(self, session: str | None) -> AuthPrincipal | None:
        principal = self.auth._principal_from_session(session, purpose="oauth_consent") if session else None
        if principal is not None and (principal.must_change_password
                or not self.access.has_control_permission(principal, "credentials.manage.self")):
            raise OAuthError("user_authorization_unavailable", 403)
        return principal

    def catalog(self, principal: AuthPrincipal, scopes: list[str]) -> dict[str, dict[str, Any]]:
        visible = self.access.visible_tools(principal, self.registry.list_definitions())
        classifications = {item["tool_id"]: item for item in self.access.list_classifications()}
        result = {}
        for tool in visible:
            policy = tool.metadata.get("gate_access", {})
            access = policy.get("required_access")
            required_scope = "tools.read" if access == "read" else "tools.invoke"
            server_id = tool.metadata.get("server_id")
            if (tool.source != "mcp" or policy.get("classification_status") != "published"
                    or access not in {"read", "write"} or required_scope not in scopes or not server_id):
                continue
            classification = classifications[tool.id]
            if classification["status"] != "published" or classification["effective_access"] != access:
                continue
            snapshot = hash_secret(json.dumps([classification["fingerprint"], access,
                                                classification["reviewed_at"]], sort_keys=True))
            result[tool.id] = {"id": tool.id, "name": tool.name, "server_id": str(server_id),
                               "server_name": tool.metadata["server_name"].strip()
                               if isinstance(tool.metadata.get("server_name"), str) and tool.metadata["server_name"].strip() else None,
                               "access": access, "snapshot": snapshot}
        if len(result) > MAX_TOOLS:
            raise OAuthError("tool_catalog_limit", 409)
        return result

    def consent_context(self, interaction: str, browser: str, session: str | None) -> dict[str, Any]:
        csrf = self._ticket(interaction, browser)["csrf"]
        principal = self.session_principal(session)
        with self.store.transaction() as connection:
            row, request = self.interaction(connection, interaction, browser)
            client = connection.execute("SELECT name FROM gate_oauth_clients WHERE id=?",
                                        (request["client_id"],)).fetchone()
        catalog = self.catalog(principal, request["scopes"]) if principal and not row["completed"] else {}
        with self.store.transaction() as connection:
            row, request = self.interaction(connection, interaction, browser)
            if not row["completed"]:
                if principal is None:
                    connection.execute("DELETE FROM gate_oauth_interactions WHERE id_hash=? AND completed=0", (hash_secret(interaction),))
                else:
                    stored = connection.execute("SELECT user_id FROM gate_oauth_interactions WHERE id_hash=?", (hash_secret(interaction),)).fetchone()
                    if stored and stored["user_id"] != principal.id:
                        connection.execute("DELETE FROM gate_oauth_interactions WHERE id_hash=?", (hash_secret(interaction),))
                        stored = None
                    if not stored:
                        self._admit_authenticated(connection, principal.id, request["client_id"])
                        connection.execute("INSERT INTO gate_oauth_interactions "
                                           "(id_hash,browser_hash,csrf_hash,request_json,expires_at,user_id,client_id) VALUES(?,?,?,?,?,?,?)",
                                           (hash_secret(interaction), hash_secret(browser), hash_secret(csrf), json.dumps(request),
                                            row["expires_at"], principal.id, request["client_id"]))
                    connection.execute("UPDATE gate_oauth_interactions SET catalog_json=? WHERE id_hash=?",
                                       (json.dumps({"user_id": principal.id, "tools": catalog}), hash_secret(interaction)))
        return {"csrf": csrf, "completed": bool(row["completed"]), "expires_at": row["expires_at"],
                "phase": "completed" if row["completed"] else "authenticated" if principal else "preauth",
                "client": {"id": request["client_id"], "name": client["name"]},
                "resource": request["resource"], "scopes": request["scopes"],
                "user": {"id": principal.id, "username": principal.username,
                         "display_name": principal.display_name} if principal else None,
                "tools": list(catalog.values()), "max_grant_days": 30,
                "access_seconds": ACCESS_TTL, "refresh_days": 30}

    def release_interaction(self, interaction: str, browser: str, csrf: str) -> None:
        with self.store.transaction() as connection:
            self.interaction(connection, interaction, browser, csrf)
            connection.execute("DELETE FROM gate_oauth_interactions WHERE id_hash=? AND completed=0", (hash_secret(interaction),))

    def consent(self, interaction: str, browser: str, csrf: str, principal: AuthPrincipal | None,
                tool_ids: list[str], grant_days: int, rate: int, concurrency: int, *, deny: bool = False) -> str:
        if not deny and principal is None:
            raise OAuthError("login_required", 401)
        if not deny and (not tool_ids or len(tool_ids) > MAX_TOOLS or len(set(tool_ids)) != len(tool_ids)
                or not 1 <= grant_days <= 30 or not 1 <= rate <= 10000 or not 1 <= concurrency <= 100):
            raise OAuthError("invalid_consent")
        with self.store.transaction() as connection:
            _, request = self.interaction(connection, interaction, browser, csrf)
        current = self.catalog(principal, request["scopes"]) if principal and not deny else {}
        code, grant_id = secrets.token_urlsafe(32), uuid4().hex
        with self.store.transaction() as connection:
            row, request = self.interaction(connection, interaction, browser, csrf)
            if row["completed"]:
                raise OAuthError("authorization_completed", 409)
            if deny:
                self._complete(connection, interaction, row, request, principal.id if principal else None)
                return callback(request, request["issuer"], error="access_denied")
            assert principal is not None
            offered = json.loads(row["catalog_json"])
            if offered.get("user_id") != principal.id or any(
                    tool_id not in current or not tool_scope_matches(offered.get("tools", {}).get(tool_id, {}), current[tool_id])
                    for tool_id in tool_ids):
                raise OAuthError("tool_scope_changed", 409)
            tools = {tool_id: current[tool_id] for tool_id in tool_ids}
            granted_scopes = sorted({"tools.read" if value["access"] == "read" else "tools.invoke"
                                     for value in tools.values()})
            if len({item["server_id"] for item in tools.values()}) > 100:
                raise OAuthError("server_scope_limit")
            if connection.execute("SELECT COUNT(*) FROM gate_oauth_grants WHERE user_id=?", (principal.id,)).fetchone()[0] >= 1000:
                raise OAuthError("grant_limit", 409)
            now = int(time.time())
            connection.execute("INSERT INTO gate_oauth_grants VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               (grant_id, principal.id, request["client_id"], request["resource"],
                                json.dumps(granted_scopes), json.dumps(tools), now + grant_days * 86400,
                                rate, concurrency, None, 1, now))
            connection.execute("INSERT INTO gate_oauth_codes VALUES(?,?,?,?,?,?,?,NULL)",
                               (hash_secret(code), grant_id, request["client_id"], request["redirect_uri"],
                                request["resource"], request["code_challenge"], now + CODE_TTL))
            self._complete(connection, interaction, row, request, principal.id, grant_id)
        return callback(request, request["issuer"], code=code)

    def authenticate_client(self, connection: sqlite3.Connection, client_id: str, secret: str) -> Any:
        row = connection.execute("SELECT * FROM gate_oauth_clients WHERE id=?", (client_id,)).fetchone()
        expected = row["secret_hash"] if row else "0" * 64
        if not hmac.compare_digest(expected, hash_secret(secret)) or not secret or not row or not row["enabled"]:
            raise OAuthError("invalid_client", 401)
        return row

    def validate_client_credentials(self, client_id: str, secret: str) -> None:
        # The public protocol's low-cost admission read does not take SQLite's
        # writer lock. Token/revoke still authenticate again in their mutation
        # transaction, including after any admission wait or concurrent rotation.
        with self.store.database.session() as connection:
            self.ready_config(connection)
            self.authenticate_client(connection, client_id, secret)

    def _active_grant(self, connection: sqlite3.Connection, grant_id: str, client: Any,
                      resource: str, now: int) -> dict[str, Any]:
        self.ready_config(connection)
        row = connection.execute("SELECT g.*,u.status,u.must_change_password FROM gate_oauth_grants g "
                                 "JOIN users u ON u.id=g.user_id WHERE g.id=?", (grant_id,)).fetchone()
        if (not row or row["revoked_at"] is not None or row["expires_at"] <= now or row["status"] != "active"
                or row["must_change_password"] or row["client_id"] != client["id"] or row["resource"] != resource
                or resource != self.store.config(connection)["resource"]):
            raise OAuthError("invalid_grant")
        grant = self.store.grant(row)
        if not set(grant["scopes"]) & set(json.loads(client["scopes_json"])):
            raise OAuthError("invalid_grant")
        return grant

    def _sign(self, connection: sqlite3.Connection, grant: dict[str, Any], family: dict[str, Any],
              scopes: list[str], now: int) -> tuple[str, int]:
        row = connection.execute("SELECT * FROM gate_oauth_keys WHERE active=1").fetchone()
        if not row:
            raise OAuthError("signing_key_unavailable", 503)
        try:
            private = serialization.load_pem_private_key(
                self._fernet().decrypt(row["encrypted_private"].encode()), password=None)
            if not isinstance(private, rsa.RSAPrivateKey):
                raise OAuthError("signing_key_unavailable", 503)
            expires_at = min(now + ACCESS_TTL, grant["expires_at"], family["expires_at"])
            claims = {"iss": self.store.config(connection)["issuer"], "sub": grant["user_id"],
                      "aud": grant["resource"], "client_id": grant["client_id"], "gid": grant["id"],
                      "fid": family["id"], "scope": " ".join(scopes), "iat": now, "nbf": now,
                      "exp": expires_at, "jti": uuid4().hex, "token_use": "access"}
            return jwt.encode(claims, private, algorithm="RS256", headers={"kid": row["kid"], "typ": "at+jwt"}), expires_at - now
        except (InvalidToken, ValueError, TypeError) as exc:
            raise OAuthError("signing_key_unavailable", 503) from exc

    def token(self, fields: dict[str, str], client_id: str, secret: str) -> dict[str, Any]:
        refresh, error = secrets.token_urlsafe(48), None
        with self.store.transaction() as connection:
            # Lock admission may wait. Exchange deadlines use the time after
            # acquisition, never a stale timestamp from request arrival.
            now = int(time.time())
            config = self.ready_config(connection)
            client = self.authenticate_client(connection, client_id, secret)
            resource = fields.get("resource", "")
            if resource != config["resource"]:
                raise OAuthError("invalid_target")
            if fields.get("grant_type") == "authorization_code":
                row = connection.execute("SELECT * FROM gate_oauth_codes WHERE code_hash=?",
                                         (hash_secret(fields.get("code", "")),)).fetchone()
                verifier = fields.get("code_verifier", "")
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                if (not row
                        or row["client_id"] != client_id or row["redirect_uri"] != fields.get("redirect_uri")
                        or row["resource"] != resource or not PKCE_VERIFIER.fullmatch(verifier)
                        or not hmac.compare_digest(challenge, row["challenge"])):
                    raise OAuthError("invalid_grant")
                grant = self._active_grant(connection, row["grant_id"], client, resource, now)
                if row["consumed_at"] is not None:
                    connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL",
                                       (now, grant["id"]))
                    error = OAuthError("invalid_grant")
                else:
                    if row["expires_at"] <= now:
                        raise OAuthError("invalid_grant")
                    scopes = sorted(set(grant["scopes"]) & set(json.loads(client["scopes_json"])))
                    family = {"id": uuid4().hex, "expires_at": min(now + REFRESH_TTL, grant["expires_at"])}
                    connection.execute("UPDATE gate_oauth_codes SET consumed_at=? WHERE code_hash=? AND consumed_at IS NULL",
                                       (now, row["code_hash"]))
                    connection.execute("INSERT INTO gate_oauth_families VALUES(?,?,?,?,NULL)",
                                       (family["id"], grant["id"], json.dumps(scopes), family["expires_at"]))
            elif fields.get("grant_type") == "refresh_token":
                row = connection.execute("SELECT r.*,f.grant_id,f.scopes_json,f.expires_at,f.revoked_at "
                                         "FROM gate_oauth_refresh r JOIN gate_oauth_families f ON f.id=r.family_id "
                                         "WHERE r.token_hash=?", (hash_secret(fields.get("refresh_token", "")),)).fetchone()
                if not row:
                    raise OAuthError("invalid_grant")
                grant = self._active_grant(connection, row["grant_id"], client, resource, now)
                if row["consumed_at"] is not None:
                    # Commit this revocation before returning invalid_grant. Raising
                    # inside this transaction would accidentally roll it back.
                    connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE id=?", (now, row["family_id"]))
                    error = OAuthError("invalid_grant")
                elif row["revoked_at"] is not None or row["expires_at"] <= now:
                    raise OAuthError("invalid_grant")
                if not error:
                    family = {"id": row["family_id"], "expires_at": row["expires_at"]}
                    ceiling = set(json.loads(row["scopes_json"])) & set(grant["scopes"]) & set(json.loads(client["scopes_json"]))
                    scopes = scope_set(fields["scope"]) if "scope" in fields else sorted(ceiling)
                    if not set(scopes) <= ceiling or not scopes:
                        raise OAuthError("invalid_scope")
                    if connection.execute("SELECT COUNT(*) FROM gate_oauth_refresh WHERE family_id=?",
                                          (family["id"],)).fetchone()[0] >= 10000:
                        connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE id=?", (now, family["id"]))
                        error = OAuthError("invalid_grant")
                    else:
                        connection.execute("UPDATE gate_oauth_refresh SET consumed_at=? WHERE token_hash=?",
                                           (now, row["token_hash"]))
                        connection.execute("UPDATE gate_oauth_families SET scopes_json=? WHERE id=?",
                                           (json.dumps(scopes), family["id"]))
            else:
                raise OAuthError("unsupported_grant_type")
            if not error:
                access_token, expires_in = self._sign(connection, grant, family, scopes, now)
                connection.execute("INSERT INTO gate_oauth_refresh VALUES(?,?,NULL,?)",
                                   (hash_secret(refresh), family["id"], now))
        if error:
            raise error
        return {"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in,
                "refresh_token": refresh, "scope": " ".join(scopes), "resource": resource}

    def _claims(self, token: str) -> dict[str, Any]:
        config = self.ready_config()
        try:
            if not token or len(token) > 16384 or token.count(".") != 2:
                raise OAuthError("invalid_token", 401)
            header = jwt.get_unverified_header(token)
            if (header.get("alg") != "RS256" or header.get("typ") != "at+jwt"
                    or any(key in header for key in ("jku", "jwk", "x5u", "crit"))):
                raise OAuthError("invalid_token", 401)
            row = self.store.database.query_one("SELECT * FROM gate_oauth_keys WHERE kid=? AND (active=1 OR retire_at>?)",
                                               (header.get("kid"), int(time.time())))
            if not row:
                raise OAuthError("invalid_token", 401)
            public = jwt.algorithms.RSAAlgorithm.from_jwk(row["public_json"])
            if not isinstance(public, rsa.RSAPublicKey):
                raise OAuthError("invalid_token", 401)
            claims = jwt.decode(token, public, algorithms=["RS256"], audience=config["resource"], issuer=config["issuer"],
                                options={"require": ["iss", "sub", "aud", "exp", "iat", "nbf", "client_id", "gid", "fid", "scope", "jti"]})
            if (claims["aud"] != config["resource"] or claims.get("token_use") != "access"
                    or any(not isinstance(claims[key], str) or not 1 <= len(claims[key]) <= 256
                           for key in ("sub", "client_id", "gid", "fid", "jti"))
                    or any(not isinstance(claims[key], int) or isinstance(claims[key], bool) for key in ("exp", "iat", "nbf"))
                    or claims["exp"] - claims["iat"] > ACCESS_TTL):
                raise OAuthError("invalid_token", 401)
            if not isinstance(claims["scope"], str):
                raise OAuthError("invalid_token", 401)
            scope_set(claims["scope"])
            return claims
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError, sqlite3.Error) as exc:
            raise OAuthError("invalid_token", 401) from exc

    def verify(self, token: str) -> AuthPrincipal:
        claims = self._claims(token)
        with self.store.transaction() as connection:
            now = int(time.time())
            if claims["exp"] <= now:
                raise OAuthError("invalid_token", 401)
            client = connection.execute("SELECT * FROM gate_oauth_clients WHERE id=? AND enabled=1",
                                        (claims["client_id"],)).fetchone()
            if not client:
                raise OAuthError("invalid_token", 401)
            grant = self._active_grant(connection, claims["gid"], client, claims["aud"], now)
            family = connection.execute("SELECT * FROM gate_oauth_families WHERE id=? AND grant_id=?",
                                        (claims["fid"], grant["id"])).fetchone()
            if (claims["sub"] != grant["user_id"] or not family or family["revoked_at"] is not None
                    or family["expires_at"] <= now):
                raise OAuthError("invalid_token", 401)
            row = connection.execute("SELECT * FROM users WHERE id=?", (grant["user_id"],)).fetchone()
        principal = self.auth._build_principal(row, auth_type="session")
        if not self.access.has_control_permission(principal, "credentials.manage.self"):
            raise OAuthError("invalid_token", 401)
        scopes = sorted(set(scope_set(claims["scope"])) & set(grant["scopes"]) &
                        set(json.loads(client["scopes_json"])) & set(json.loads(family["scopes_json"])))
        current = self.catalog(principal, scopes)
        tools = {key: value for key, value in grant["tools"].items() if key in current and tool_scope_matches(value, current[key])}
        return replace(principal, auth_type="oauth", scopes=tuple(scopes), delegated_scopes=tuple(scopes),
                       external_grant_id=grant["id"], external_tool_ids=tuple(tools),
                       external_server_ids=tuple(sorted({value["server_id"] for value in tools.values()})),
                       external_access=tuple(sorted({value["access"] for value in tools.values()})),
                       external_expires_at=datetime.fromtimestamp(min(claims["exp"], grant["expires_at"]), timezone.utc).isoformat(),
                       external_rate_per_minute=grant["rate_per_minute"], external_concurrency=grant["concurrency"])

    def revoke_token(self, token: str, client_id: str, secret: str) -> None:
        # RFC 7009: unknown/already revoked tokens return success, without an oracle.
        with self.store.transaction() as connection:
            self.ready_config(connection)
            self.authenticate_client(connection, client_id, secret)
            try:
                claims = self._claims(token) if token.count(".") == 2 else None
            except OAuthError:
                claims = None
            family_id = claims["fid"] if claims and claims["client_id"] == client_id else None
            if not family_id:
                row = connection.execute("SELECT r.family_id FROM gate_oauth_refresh r "
                                         "JOIN gate_oauth_families f ON f.id=r.family_id "
                                         "JOIN gate_oauth_grants g ON g.id=f.grant_id WHERE r.token_hash=? AND g.client_id=?",
                                         (hash_secret(token), client_id)).fetchone()
                family_id = row["family_id"] if row else None
            if family_id:
                connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                                   (int(time.time()), family_id))

    def narrow_grant(self, user_id: str, grant_id: str, revision: int, tools: list[str],
                     expires_at: int, rate: int, concurrency: int, revoke: bool = False) -> dict[str, Any]:
        with self.store.transaction() as connection:
            row = connection.execute("SELECT * FROM gate_oauth_grants WHERE id=? AND user_id=?",
                                     (grant_id, user_id)).fetchone()
            if not row:
                raise OAuthError("grant_not_found", 404)
            grant = self.store.grant(row)
            if row["revision"] != revision:
                raise OAuthError("revision_conflict", 409)
            if not revoke and (row["revoked_at"] is not None or not tools or not set(tools) <= set(grant["tools"])
                    or not int(time.time()) < expires_at <= row["expires_at"]
                    or not 1 <= rate <= row["rate_per_minute"] or not 1 <= concurrency <= row["concurrency"]):
                raise OAuthError("grant_can_only_narrow")
            if revoke:
                connection.execute("UPDATE gate_oauth_grants SET revoked_at=COALESCE(revoked_at,?),revision=revision+1 WHERE id=?",
                                   (int(time.time()), grant_id))
                connection.execute("UPDATE gate_oauth_families SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL",
                                   (int(time.time()), grant_id))
            else:
                retained = {key: grant["tools"][key] for key in tools}
                scopes = sorted({"tools.read" if value["access"] == "read" else "tools.invoke"
                                 for value in retained.values()} & set(grant["scopes"]))
                connection.execute("UPDATE gate_oauth_grants SET tools_json=?,scopes_json=?,expires_at=?,rate_per_minute=?,concurrency=?,"
                                   "revision=revision+1 WHERE id=?", (json.dumps(retained), json.dumps(scopes),
                                                                  expires_at, rate, concurrency, grant_id))
        return next(grant for grant in self.store.grants(user_id) if grant["id"] == grant_id)

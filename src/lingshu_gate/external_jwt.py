"""RS256 resource-server verifier with administrator-pinned JWKS locations.

PyJWT performs cryptographic/registered-claim validation. Unverified issuer is
used only to select an already configured trust entry, never as a network URL.
"""
from __future__ import annotations

import http.client
import json
import queue
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from lingshu_gate.external_connection import ExternalConnectionConfig, _https_resource

MAX_JWKS_BYTES = 256 * 1024
JWKS_TIMEOUT_SECONDS = 5.0
JWKS_CACHE_SECONDS = 300.0
JWKS_REFRESH_INTERVAL = 30.0
MAX_TOKEN_BYTES = 16 * 1024
_JWKS_FETCH_SLOTS = threading.BoundedSemaphore(2)


class ExternalJwtError(PermissionError):
    """Safe authentication failure; never includes claims, tokens or remote bodies."""


@dataclass(frozen=True)
class VerifiedExternalIdentity:
    issuer: str
    subject: str
    client_id: str
    audiences: tuple[str, ...]
    scopes: tuple[str, ...]
    expires_at: datetime
    canonical_resource: str
    jwks_uri: str


def fetch_jwks(uri: str) -> dict[str, Any]:
    """Hard caller deadline, including slow DNS/headers; at most two workers.

    Socket timeouts alone do not bound byte-by-byte header trickles or DNS.
    Timed-out workers are daemonized and retain their capacity slot until exit,
    so a stuck resolver cannot create an unbounded thread/connection queue.
    """
    if not _https_resource(uri):
        raise ExternalJwtError("invalid trusted JWKS configuration")
    slots = _JWKS_FETCH_SLOTS
    if not slots.acquire(blocking=False):
        raise ExternalJwtError("trusted JWKS fetch capacity exhausted")
    result: queue.Queue[dict[str, Any] | Exception] = queue.Queue(maxsize=1)
    connections: list[http.client.HTTPSConnection] = []

    def run() -> None:
        try:
            result.put(_fetch_jwks_sync(uri, connections))
        except Exception as exc:
            result.put(exc)
        finally:
            slots.release()

    threading.Thread(target=run, daemon=True, name="gate-jwks-fetch").start()
    try:
        outcome = result.get(timeout=JWKS_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        for connection in connections:
            try:
                if connection.sock:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                connection.close()
            except OSError:
                pass
        raise ExternalJwtError("trusted JWKS timeout") from exc
    if isinstance(outcome, Exception):
        raise ExternalJwtError("trusted JWKS unavailable") from outcome
    return outcome


def _fetch_jwks_sync(uri: str, connections: list[http.client.HTTPSConnection]) -> dict[str, Any]:
    """HTTPS fetch without redirects, proxy inheritance or token headers."""
    if not _https_resource(uri):
        raise ExternalJwtError("invalid trusted JWKS configuration")
    parsed = urlsplit(uri)
    deadline = time.monotonic() + JWKS_TIMEOUT_SECONDS
    assert parsed.hostname is not None
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                             timeout=JWKS_TIMEOUT_SECONDS, context=ssl.create_default_context())
    connections.append(connection)
    try:
        connection.request("GET", parsed.path or "/", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ExternalJwtError("trusted JWKS unavailable")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > MAX_JWKS_BYTES):
            raise ExternalJwtError("trusted JWKS exceeds size limit")
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExternalJwtError("trusted JWKS timeout")
            # HTTPResponse can detach the socket from the connection on close.
            stream_socket = connection.sock or getattr(getattr(response.fp, "raw", None), "_sock", None)
            if stream_socket is not None:
                stream_socket.settimeout(remaining)
            chunk = response.read1(min(8192, MAX_JWKS_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_JWKS_BYTES:
                raise ExternalJwtError("trusted JWKS exceeds size limit")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ExternalJwtError("invalid trusted JWKS")
        return payload
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise ExternalJwtError("trusted JWKS unavailable") from exc
    finally:
        connection.close()


@dataclass
class _CachedKeys:
    keys: dict[str, RSAPublicKey]
    fetched_at: float
    attempted_at: float


class ExternalJwtVerifier:
    def __init__(self, config_provider: Callable[[], ExternalConnectionConfig], *,
                 jwks_fetcher: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._config_provider = config_provider
        self._fetcher = jwks_fetcher or fetch_jwks
        self._cache: dict[tuple[str, str], _CachedKeys] = {}
        self._lock = threading.Lock()
        self._issuer_locks: dict[tuple[str, str], threading.Lock] = {}

    def verify(self, token: str) -> VerifiedExternalIdentity:
        try:
            return self._verify(token)
        except ExternalJwtError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise ExternalJwtError("invalid external bearer") from exc

    def _verify(self, token: str) -> VerifiedExternalIdentity:
        config = self._config_provider()
        if not config.enabled or config.validation_errors():
            raise ExternalJwtError("external authentication is disabled or unconfigured")
        if not token or len(token) > MAX_TOKEN_BYTES or token.count(".") != 2:
            raise ExternalJwtError("invalid external bearer")
        header = jwt.get_unverified_header(token)
        if (header.get("alg") != "RS256" or header.get("typ", "JWT") not in {"JWT", "at+jwt"}
                or any(field in header for field in ("jku", "x5u", "jwk", "crit"))):
            raise ExternalJwtError("unsupported external bearer header")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            raise ExternalJwtError("invalid external bearer key id")
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified.get("iss")
        if not isinstance(issuer, str) or issuer not in config.trusted_issuers:
            raise ExternalJwtError("untrusted external issuer")
        uri = dict(config.issuer_jwks).get(issuer)
        if not uri:
            raise ExternalJwtError("unconfigured external issuer")
        key = self._key(issuer, uri, kid, config)
        audiences = [external for external, _ in config.resource_mappings]
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audiences, issuer=issuer,
                            options={"require": ["iss", "sub", "aud", "exp"], "verify_signature": True,
                                     "verify_exp": True, "verify_nbf": True, "verify_iat": True,
                                     "verify_aud": True, "verify_iss": True})
        if (claims.get("token_use") not in {None, "access"}
                or (header.get("typ") != "at+jwt" and claims.get("token_use") != "access")):
            raise ExternalJwtError("external bearer is not an access token")
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > 512:
            raise ExternalJwtError("invalid external subject")
        raw_audiences = claims["aud"]
        verified_audiences = (raw_audiences,) if isinstance(raw_audiences, str) else tuple(raw_audiences)
        if not verified_audiences or any(config.canonical_resource(aud) is None for aud in verified_audiences):
            raise ExternalJwtError("external audience mapping mismatch")
        client_id, authorized_party = claims.get("client_id"), claims.get("azp")
        if client_id is not None and authorized_party is not None and client_id != authorized_party:
            raise ExternalJwtError("external client binding mismatch")
        client_id = client_id if client_id is not None else authorized_party
        if not isinstance(client_id, str) or not client_id or client_id not in config.client_allowlist:
            raise ExternalJwtError("untrusted external client")
        scope = claims.get("scope")
        if not isinstance(scope, str) or len(scope) > 4096 or any(ord(char) < 32 for char in scope):
            raise ExternalJwtError("invalid external scope")
        # All scope interpretation belongs to Gate's common delegated policy.
        scopes = tuple(sorted(set(scope.split(" ")) - {""}))
        exp = claims["exp"]
        if not isinstance(exp, (int, float)) or isinstance(exp, bool):
            raise ExternalJwtError("invalid external expiry")
        return VerifiedExternalIdentity(issuer, subject, client_id, verified_audiences, scopes,
                                        datetime.fromtimestamp(exp, timezone.utc),
                                        config.canonical_resource(verified_audiences[0]) or "", uri)

    def _key(self, issuer: str, uri: str, kid: str, config: ExternalConnectionConfig) -> RSAPublicKey:
        pair = (issuer, uri)
        with self._lock:
            trusted = {(i, u) for i, u in config.issuer_jwks}
            self._cache = {pair: entry for pair, entry in self._cache.items() if pair in trusted}
            self._issuer_locks = {pair: lock for pair, lock in self._issuer_locks.items() if pair in trusted}
            issuer_lock = self._issuer_locks.setdefault(pair, threading.Lock())
        if not issuer_lock.acquire(timeout=JWKS_TIMEOUT_SECONDS):
            raise ExternalJwtError("external key refresh busy")
        try:
            now = time.monotonic()
            entry = self._cache.get(pair)
            fresh = entry is not None and now - entry.fetched_at < JWKS_CACHE_SECONDS
            if fresh and entry is not None and kid in entry.keys:
                return entry.keys[kid]
            if entry is not None and now - entry.attempted_at < JWKS_REFRESH_INTERVAL:
                raise ExternalJwtError("external key unavailable; retry later")
            # Negative requests and failures are rate bounded too; never accept
            # stale keys after a failed expiry refresh.
            self._cache[pair] = (_CachedKeys(entry.keys, entry.fetched_at, now) if fresh and entry is not None
                                 else _CachedKeys({}, float("-inf"), now))
            try:
                payload = self._fetcher(uri)
                keys = self._parse_keys(payload)
            except ExternalJwtError:
                raise
            except Exception as exc:
                raise ExternalJwtError("trusted JWKS unavailable") from exc
            entry = _CachedKeys(keys, now, now)
            self._cache[pair] = entry
            if kid not in keys:
                raise ExternalJwtError("unknown external key id")
            return keys[kid]
        finally:
            issuer_lock.release()

    @staticmethod
    def _parse_keys(payload: dict[str, Any]) -> dict[str, RSAPublicKey]:
        if len(json.dumps(payload).encode()) > MAX_JWKS_BYTES:
            raise ExternalJwtError("trusted JWKS exceeds size limit")
        items = payload.get("keys")
        if not isinstance(items, list) or not 1 <= len(items) <= 64:
            raise ExternalJwtError("invalid trusted JWKS")
        keys: dict[str, RSAPublicKey] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ExternalJwtError("invalid trusted JWKS")
            if item.get("kty") != "RSA" or item.get("alg", "RS256") != "RS256" or item.get("use", "sig") != "sig":
                continue
            if "key_ops" in item and item["key_ops"] != ["verify"]:
                continue
            kid = item.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256 or kid in keys:
                raise ExternalJwtError("ambiguous trusted JWKS key id")
            if any(field in item for field in ("d", "p", "q", "dp", "dq", "qi")):
                raise ExternalJwtError("trusted JWKS must contain public keys only")
            key = jwt.PyJWK.from_dict(item, algorithm="RS256").key
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ExternalJwtError("unsafe trusted JWKS key")
            keys[kid] = key
        if not keys:
            raise ExternalJwtError("trusted JWKS has no supported signing keys")
        return keys

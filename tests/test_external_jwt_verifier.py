"""JWT-01..09: real RSA signatures and production-fetch boundary tests.

All keys are ephemeral test-only data. No provider credentials or network are used.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from lingshu_gate.external_connection import ExternalConnectionConfig
from lingshu_gate.external_jwt import ExternalJwtError, ExternalJwtVerifier
from lingshu_gate import external_jwt


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def configuration(**overrides):
    return ExternalConnectionConfig(enabled=True, mode="direct", endpoint="https://gate.example.test/mcp",
        trusted_issuers=("https://issuer.example.test",),
        issuer_jwks=(("https://issuer.example.test", "https://issuer.example.test/jwks"),),
        client_allowlist=("synthetic-client",),
        resource_mappings=(("https://tunnel.example.test/mcp", "https://gate.example.test/mcp"),), **overrides)


def public_jwks(key, kid="synthetic-key"):
    return {"keys": [{**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())),
                       "kid": kid, "alg": "RS256", "use": "sig", "key_ops": ["verify"]}]}


def token(key, *, headers=None, **overrides):
    now = datetime.now(timezone.utc)
    claims = {"iss": "https://issuer.example.test", "sub": "synthetic-subject",
              "aud": "https://tunnel.example.test/mcp", "client_id": "synthetic-client",
              "scope": "tools.read tools.invoke", "exp": now + timedelta(minutes=5),
              "nbf": now - timedelta(seconds=1), **overrides}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic-key", "typ": "at+jwt", **(headers or {})})


def test_jwt01_valid_signature_and_exact_trust(signing_key):
    requested = []
    verifier = ExternalJwtVerifier(configuration, jwks_fetcher=lambda url: requested.append(url) or public_jwks(signing_key))
    identity = verifier.verify(token(signing_key))
    assert identity.issuer == "https://issuer.example.test"
    assert identity.subject == "synthetic-subject" and identity.client_id == "synthetic-client"
    assert identity.audiences == ("https://tunnel.example.test/mcp",)
    assert set(identity.scopes) == {"tools.read", "tools.invoke"}
    assert requested == ["https://issuer.example.test/jwks"]
    assert verifier.verify(token(signing_key, client_id=None, azp="synthetic-client")).client_id == "synthetic-client"


@pytest.mark.parametrize("override", [
    {"iss": "https://untrusted.example.test"}, {"aud": "https://other.example.test/mcp"},
    {"aud": ["https://tunnel.example.test/mcp", "https://untrusted.example.test/mcp"]},
    {"exp": 1}, {"exp": None}, {"nbf": 9999999999}, {"iat": 9999999999},
    {"sub": ""}, {"sub": 123}, {"client_id": "other"}, {"azp": "other"},
    {"client_id": None}, {"scope": ["tools.read"]}, {"scope": "tools.read\n*"},
    {"token_use": "id"},
])
def test_jwt02_registered_and_delegated_claims(signing_key, override):
    verifier = ExternalJwtVerifier(configuration, jwks_fetcher=lambda _: public_jwks(signing_key))
    with pytest.raises(ExternalJwtError):
        verifier.verify(token(signing_key, **override))


@pytest.mark.parametrize("header", [{"jku": "https://attacker.example.test/keys"}, {"x5u": "https://attacker.example.test/cert"},
                                    {"jwk": {}}, {"crit": []}, {"kid": ""}, {"typ": "id+jwt"}])
def test_jwt03_header_never_selects_network_trust(signing_key, header):
    requested = []
    verifier = ExternalJwtVerifier(configuration, jwks_fetcher=lambda url: requested.append(url) or public_jwks(signing_key))
    with pytest.raises(ExternalJwtError):
        verifier.verify(token(signing_key, headers=header))
    assert requested == []


def test_jwt04_algorithm_and_access_token_purpose(signing_key):
    verifier = ExternalJwtVerifier(configuration, jwks_fetcher=lambda _: public_jwks(signing_key))
    with pytest.raises(ExternalJwtError):
        verifier.verify(jwt.encode({"iss": "https://issuer.example.test"}, "synthetic-only-secret-32-bytes-minimum", algorithm="HS256",
                                   headers={"kid": "synthetic-key", "typ": "at+jwt"}))
    with pytest.raises(ExternalJwtError):
        verifier.verify(jwt.encode({}, key=None, algorithm="none"))
    with pytest.raises(ExternalJwtError):
        verifier.verify(token(signing_key, headers={"typ": "JWT"}))
    assert verifier.verify(token(signing_key, headers={"typ": "JWT"}, token_use="access"))
    different = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ExternalJwtError):
        verifier.verify(token(different))


def test_jwt05_disabled_oversize_ambiguous_and_unknown_key_refresh(signing_key, monkeypatch):
    requested = []
    payload = public_jwks(signing_key)
    clock = [1000.0]
    monkeypatch.setattr(external_jwt.time, "monotonic", lambda: clock[0])
    verifier = ExternalJwtVerifier(configuration, jwks_fetcher=lambda url: requested.append(url) or payload)
    assert verifier.verify(token(signing_key))
    for _ in range(20):
        with pytest.raises(ExternalJwtError):
            verifier.verify(token(signing_key, headers={"kid": "unknown"}))
    assert len(requested) == 1
    clock[0] += 31
    payload["keys"].append({**payload["keys"][0], "kid": "rotated"})
    assert verifier.verify(token(signing_key, headers={"kid": "rotated"}))
    assert len(requested) == 2
    with pytest.raises(ExternalJwtError):
        ExternalJwtVerifier(lambda: replace(configuration(), enabled=False), jwks_fetcher=lambda _: payload).verify(token(signing_key))
    with pytest.raises(ExternalJwtError):
        verifier.verify("a" * (external_jwt.MAX_TOKEN_BYTES + 1))
    payload["keys"].append(payload["keys"][0])
    with pytest.raises(ExternalJwtError):
        ExternalJwtVerifier(configuration, jwks_fetcher=lambda _: payload).verify(token(signing_key))


class FakeResponse:
    status = 200
    fp = None
    def __init__(self, body, length=None):
        self.body = body
        self.length = length
    def getheader(self, _):
        return self.length
    def read1(self, size):
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


def fake_connection(monkeypatch, response, *, entered=None, release=None, close_releases=True):
    calls = []
    class Connection:
        sock = None
        def __init__(self, host, port, **kwargs):
            calls.append((host, port, kwargs["timeout"]))
        def request(self, method, path, headers):
            calls.append((method, path, headers))
        def getresponse(self):
            if entered:
                entered.set()
            if release:
                release.wait(1)
            return response
        def close(self):
            if release and close_releases:
                release.set()
    monkeypatch.setattr(external_jwt.http.client, "HTTPSConnection", Connection)
    return calls


def test_jwt06_production_fetch_fixed_https_no_redirect_and_byte_limits(signing_key, monkeypatch):
    payload = public_jwks(signing_key)
    response = FakeResponse(json.dumps(payload).encode())
    calls = fake_connection(monkeypatch, response)
    assert external_jwt.fetch_jwks("https://issuer.example.test/jwks") == payload
    assert calls[0][:2] == ("issuer.example.test", 443)
    assert calls[1] == ("GET", "/jwks", {"Accept": "application/json"})
    response.status = 302
    with pytest.raises(ExternalJwtError):
        external_jwt.fetch_jwks("https://issuer.example.test/jwks")
    response.status = 200
    response.length = str(external_jwt.MAX_JWKS_BYTES + 1)
    with pytest.raises(ExternalJwtError):
        external_jwt.fetch_jwks("https://issuer.example.test/jwks")
    response.length = None
    response.body = b"a" * (external_jwt.MAX_JWKS_BYTES + 1)
    with pytest.raises(ExternalJwtError):
        external_jwt.fetch_jwks("https://issuer.example.test/jwks")
    for uri in ["http://127.0.0.1/keys", "https://user:pass@example.test/keys", "https://example.test/keys?token=synthetic"]:
        with pytest.raises(ExternalJwtError):
            external_jwt.fetch_jwks(uri)


def test_jwt07_production_fetch_total_deadline_includes_slow_headers(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    fake_connection(monkeypatch, FakeResponse(b'{}'), entered=entered, release=release)
    monkeypatch.setattr(external_jwt, "JWKS_TIMEOUT_SECONDS", 0.03)
    started = time.monotonic()
    with pytest.raises(ExternalJwtError, match="timeout"):
        external_jwt.fetch_jwks("https://issuer.example.test/jwks")
    assert time.monotonic() - started < 0.2
    assert entered.is_set() and release.is_set()


def test_jwt08_hung_fetches_have_bounded_capacity(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    fake_connection(monkeypatch, FakeResponse(b'{}'), entered=entered, release=release, close_releases=False)
    monkeypatch.setattr(external_jwt, "JWKS_TIMEOUT_SECONDS", 0.03)
    # Isolate this test's semaphore from an earlier worker's final cleanup.
    monkeypatch.setattr(external_jwt, "_JWKS_FETCH_SLOTS", threading.BoundedSemaphore(2))
    def request():
        with pytest.raises(ExternalJwtError):
            external_jwt.fetch_jwks("https://issuer.example.test/jwks")
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _: request(), range(2)))
        started = time.monotonic()
        with pytest.raises(ExternalJwtError, match="capacity"):
            external_jwt.fetch_jwks("https://issuer.example.test/jwks")
        assert time.monotonic() - started < 0.05
    finally:
        release.set()


def test_jwt09_configuration_requires_fixed_jwks_and_canonical_mapping():
    assert configuration().validation_errors() == ()
    assert replace(configuration(), issuer_jwks=()).validation_errors()
    assert replace(configuration(), issuer_jwks=(("https://issuer.example.test", "http://localhost/keys"),)).validation_errors()
    assert replace(configuration(), resource_mappings=(("https://tunnel.example.test/mcp", "https://other.example.test/mcp"),)).validation_errors()


def test_jwt10_failed_unknown_key_refresh_preserves_only_fresh_cached_keys(signing_key, monkeypatch):
    clock = [1000.0]
    requested = []

    def fetch(uri):
        requested.append(uri)
        if len(requested) > 1:
            raise ExternalJwtError("synthetic unavailable")
        return public_jwks(signing_key)

    monkeypatch.setattr(external_jwt.time, "monotonic", lambda: clock[0])
    verifier = ExternalJwtVerifier(configuration, jwks_fetcher=fetch)
    assert verifier.verify(token(signing_key))
    clock[0] += external_jwt.JWKS_REFRESH_INTERVAL + 1
    with pytest.raises(ExternalJwtError):
        verifier.verify(token(signing_key, headers={"kid": "unknown"}))
    assert verifier.verify(token(signing_key))
    assert requested == ["https://issuer.example.test/jwks"] * 2
    clock[0] += external_jwt.JWKS_CACHE_SECONDS + 1
    with pytest.raises(ExternalJwtError):
        verifier.verify(token(signing_key))
    assert len(requested) == 3

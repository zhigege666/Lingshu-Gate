"""Pinned TLS and proxy framing through synthetic sockets only."""
from __future__ import annotations

import io
import socket
import time
from unittest.mock import patch

import pytest

from lingshu_gate.adapters.native_executor.https import PinnedHTTPS
from lingshu_gate.registry import ToolExecutionError


class Socket:
    def __init__(self, response=b"", replies=b""):
        self.response = response
        self.replies = io.BytesIO(replies)
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def sendall(self, value):
        self.sent.append(value)

    def recv(self, size):
        return self.replies.read(size)

    def makefile(self, *args):
        return io.BytesIO(self.response)

    def settimeout(self, timeout):
        assert timeout > 0

    def close(self):
        self.closed = True

    def shutdown(self, *args):
        self.closed = True


class TLS:
    def __init__(self):
        self.names = []

    def wrap_socket(self, sock, *, server_hostname):
        self.names.append(server_hostname)
        return sock


def resolver(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def request(client, **kwargs):
    return client.request("https://git.example.invalid/project", rule={"host": "git.example.invalid", "port": 443, "private_cidrs": []}, material={"proxy": None}, deadline=time.monotonic() + 5, maximum=4096, **kwargs)


def test_tls_sni_and_every_connect_use_validated_numeric_ip():
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = Socket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with patch.object(client, "_connect", return_value=sock) as connect:
        assert request(client, credential="fixture-token") == (200, b"ok")
    assert connect.call_args.args[:2] == ("93.184.216.34", 443)
    assert client.context.names == ["git.example.invalid"]
    assert b"Authorization: Bearer fixture-token" in sock.sent[0]
    assert sock.closed


@pytest.mark.parametrize("response", [b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/\r\n\r\n", b"HTTP/1.1 200 OK\r\nX-Oversized: " + b"a" * 4096 + b"\r\n\r\n", b"HTTP/1.1 200 OK\r\nContent-Length: 4097\r\n\r\n" + b"a" * 4097, b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n"])
def test_redirect_header_body_and_encoding_limits_close_connection(response):
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = Socket(response)
    with patch.object(client, "_connect", return_value=sock), pytest.raises(ToolExecutionError):
        request(client)
    assert sock.closed


def test_any_forbidden_dns_address_rejects_before_connect():
    def mixed(host, port, **kwargs):
        return resolver(host, port) + [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]
    client = PinnedHTTPS(resolver=mixed)
    with patch.object(client, "_connect", side_effect=AssertionError("DNS policy rejected all connects")), pytest.raises(ToolExecutionError) as denied:
        request(client)
    assert denied.value.code == "network_dns_policy_rejected"


@pytest.mark.parametrize("scheme", ["http", "socks5", "socks5h"])
def test_proxy_upstream_uses_pinned_ip_never_remote_dns(scheme):
    client = PinnedHTTPS(proxy_hosts=({"host": "proxy.example.invalid", "port": 8080, "private_cidrs": []},), resolver=resolver)
    replies = b"HTTP/1.1 200 Connection established\r\n\r\n" if scheme == "http" else b"\x05\x00\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    sock = Socket(replies=replies)
    with patch.object(client, "_connect", return_value=sock):
        result = client._tunnel("93.184.216.35", 443, {"proxy": scheme + "://proxy.example.invalid:8080"}, 5, cancelled=lambda: False, deadline=time.monotonic() + 5)
    assert result is sock
    if scheme == "http":
        assert sock.sent[0].startswith(b"CONNECT 93.184.216.35:443 HTTP/1.1")
    else:
        assert sock.sent[-1][3] == 1  # IPv4 numeric, never SOCKS DNS type 3.
        assert socket.inet_aton("93.184.216.35") in sock.sent[-1]


def test_unreviewed_or_unsupported_proxy_does_not_fall_back():
    client = PinnedHTTPS(resolver=resolver)
    with patch.object(client, "_connect", side_effect=AssertionError("No direct fallback")):
        for proxy in ("http://proxy.example.invalid:8080", "https://proxy.example.invalid:8080"):
            with pytest.raises(ToolExecutionError):
                client._tunnel("93.184.216.35", 443, {"proxy": proxy}, 5, cancelled=lambda: False, deadline=time.monotonic() + 5)


def test_head_probe_does_not_return_a_body():
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = Socket(b"HTTP/1.1 200 OK\r\nContent-Length: 9999999\r\n\r\nprivate-body")
    with patch.object(client, "_connect", return_value=sock):
        assert request(client, method="HEAD") == (200, b"")


def test_unfinished_dns_is_unknown_and_cannot_claim_cancellation_or_spawn_more():
    import threading
    release = threading.Event()
    def slow(host, port, **kwargs):
        release.wait(1)
        return resolver(host, port)
    client = PinnedHTTPS(resolver=slow)
    try:
        with pytest.raises(InterruptedError, match="termination_unknown"):
            client.addresses("git.example.invalid", 443, {"host": "git.example.invalid", "port": 443}, deadline=time.monotonic() + 0.02, cancelled=lambda: True)
        assert client.dns_busy.is_set()
        with pytest.raises(ToolExecutionError) as busy:
            client.addresses("git.example.invalid", 443, {"host": "git.example.invalid", "port": 443})
        assert busy.value.code == "network_dns_resolver_busy"
    finally:
        release.set()


def test_basic_git_credential_is_only_inside_origin_tls_request():
    import base64
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = Socket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with patch.object(client, "_connect", return_value=sock):
        assert request(client, credential="fixture-user:fixture-token", auth_scheme="basic") == (200, b"ok")
    assert b"Authorization: Basic " + base64.b64encode(b"fixture-user:fixture-token") in sock.sent[0]
    assert b"fixture-token" not in sock.sent[0]

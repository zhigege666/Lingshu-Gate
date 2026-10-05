"""Pinned TLS and proxy framing through synthetic sockets only."""
from __future__ import annotations

import io
import socket
import time
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lingshu_gate.adapters.native_executor.https import PinnedHTTPS
from lingshu_gate.adapters.native_executor.git import HTTPSGitBackend, packet
from lingshu_gate.adapters.native_executor.pending import PendingDNS
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.ports.safe_network_executor import SafeExecutionCancelled


@pytest.mark.parametrize("version", [b"", packet(b"version 1\n")])
def test_smart_git_advertisement_resolves_exact_ref_with_optional_v1(version):
    commit = "a" * 40
    content = packet(b"# service=git-upload-pack\n") + b"0000" + version + packet(f"{commit} refs/heads/main\0side-band-64k shallow\n".encode()) + b"0000"
    transport = SimpleNamespace(request=lambda *args, **kwargs: (200, content))
    backend = HTTPSGitBackend(SimpleNamespace(), transport)
    request = {"source": {"repository_url": "https://git.example.invalid/project"}, "host_rule": {"host": "git.example.invalid", "port": 443, "private_cidrs": []}}
    assert backend._advertisement(request, {}, time.monotonic() + 5) == {"refs/heads/main": commit}


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

    def do_handshake(self):
        pass


class TLS:
    def __init__(self):
        self.names = []

    def wrap_socket(self, sock, *, server_hostname, do_handshake_on_connect):
        assert not do_handshake_on_connect
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


@pytest.mark.parametrize("reason", ["deadline", "cancel"])
@pytest.mark.parametrize("dns_stage", ["upstream", "proxy"])
def test_request_wrapper_preserves_live_dns_worker_after_deadline_or_cancel(reason, dns_stage):
    release, stopped = threading.Event(), threading.Event()
    calls = []
    def slow(host, port, **kwargs):
        calls.append((host, port))
        if dns_stage == "upstream" or host == "proxy.example.invalid":
            if reason == "cancel":
                stopped.set()
            assert release.wait(5)
        return resolver(host, port)
    client = PinnedHTTPS(resolver=slow, proxy_hosts=({"host": "proxy.example.invalid", "port": 8080, "private_cidrs": []},))
    material = {"proxy": None if dns_stage == "upstream" else "http://proxy.example.invalid:8080"}
    try:
        with patch.object(client, "_connect", side_effect=AssertionError("Unfinished DNS must never connect")) as connect:
            with pytest.raises(PendingDNS) as pending:
                client.request("https://git.example.invalid/project", rule={"host": "git.example.invalid", "port": 443}, material=material, deadline=time.monotonic() + 0.1, maximum=4096, credential="fixture-token", cancelled=stopped.is_set)
            assert pending.value.worker is client._dns_worker and pending.value.worker.is_alive()
            assert client.dns_pending()
            previous = list(calls)
            with pytest.raises(ToolExecutionError) as busy:
                request(client)
            assert busy.value.code == "network_dns_resolver_busy" and calls == previous
            connect.assert_not_called()
    finally:
        release.set()
        if client._dns_worker:
            client._dns_worker.join(1)
    assert not client.dns_pending()


def test_basic_git_credential_is_only_inside_origin_tls_request():
    import base64
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = Socket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with patch.object(client, "_connect", return_value=sock):
        assert request(client, credential="fixture-user:fixture-token", auth_scheme="basic") == (200, b"ok")
    assert b"Authorization: Basic " + base64.b64encode(b"fixture-user:fixture-token") in sock.sent[0]
    assert b"fixture-token" not in sock.sent[0]


@pytest.mark.parametrize("phase", ["connect", "handshake", "send"])
@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_whole_socket_lifecycle_is_supervised_and_next_request_can_run(phase, reason):
    stopped = threading.Event()
    class SlowSocket(Socket):
        def stall(self):
            limit = time.monotonic() + 1
            while not self.closed and time.monotonic() < limit:
                time.sleep(0.002)
            assert self.closed, "The budget must close even connecting/handshaking sockets"
            raise OSError("fixture interrupted socket")
        def connect(self, target):
            if phase == "connect":
                self.stall()
        def do_handshake(self):
            if phase == "handshake":
                self.stall()
        def sendall(self, data):
            if phase == "send":
                self.stall()
            super().sendall(data)
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = SlowSocket()
    timer = threading.Timer(0.03, stopped.set) if reason == "cancel" else None
    if timer:
        timer.start()
    started = time.monotonic()
    try:
        with patch("lingshu_gate.adapters.native_executor.https.socket.socket", return_value=sock), pytest.raises(SafeExecutionCancelled if reason == "cancel" else TimeoutError):
            client.request("https://git.example.invalid/project", rule={"host": "git.example.invalid", "port": 443}, material={"proxy": None}, deadline=started + (1 if reason == "cancel" else 0.05), maximum=4096, credential="fixture-token", cancelled=stopped.is_set)
    finally:
        if timer:
            timer.join()
    assert time.monotonic() - started < 0.3
    assert sock.sent == [] and sock.closed
    next_socket = Socket(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with patch.object(client, "_connect", return_value=next_socket):
        assert request(client) == (200, b"ok")


def test_tls_handshake_returning_after_cancel_never_sends_authentication():
    stopped = threading.Event()
    sock = Socket()
    def late():
        stopped.set()
    sock.do_handshake = late
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    with patch.object(client, "_connect", return_value=sock), pytest.raises(SafeExecutionCancelled):
        client.request("https://git.example.invalid/project", rule={"host": "git.example.invalid", "port": 443}, material={"proxy": None}, deadline=time.monotonic() + 1, maximum=4096, credential="fixture-token", cancelled=stopped.is_set)
    assert sock.sent == [] and sock.closed


def test_connect_tls_and_send_share_the_original_deadline_budget():
    budgets = []
    class SlowStages(Socket):
        def connect(self, target):
            time.sleep(0.03)
        def do_handshake(self):
            time.sleep(0.03)
        def settimeout(self, value):
            super().settimeout(value)
            budgets.append(value)
        def sendall(self, value):
            time.sleep(0.03)
            if self.closed:
                raise OSError("fixture deadline")
            super().sendall(value)
    client = PinnedHTTPS(resolver=resolver)
    client.context = TLS()
    sock = SlowStages()
    started = time.monotonic()
    with patch("lingshu_gate.adapters.native_executor.https.socket.socket", return_value=sock), pytest.raises(TimeoutError):
        client.request("https://git.example.invalid/project", rule={"host": "git.example.invalid", "port": 443}, material={"proxy": None}, deadline=started + 0.075, maximum=4096, credential="fixture-token")
    assert max(budgets) <= 0.075 and min(budgets) < 0.03
    assert time.monotonic() - started < 0.2 and sock.sent == []

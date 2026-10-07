"""Bounded HTTPS with validated DNS pinned at connect, including proxy upstream.

No project code, redirects, environment proxies, implicit retry or DNS performed
by a proxy. Credentials stay in this module, never container argv/env/files.
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import socket
import ssl
import struct
import time
import threading
from lingshu_gate.adapters.native_executor.pending import PendingDNS
from collections.abc import Callable
from typing import Any, NoReturn
from urllib.parse import urlsplit

from lingshu_gate.git_source import validate_resolved_addresses
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.ports.safe_network_executor import SafeExecutionCancelled

PROXY_SCHEMES = frozenset({"http", "socks5", "socks5h"})


def _deny(code: str) -> NoReturn:
    raise ToolExecutionError(code, "Trusted HTTPS request was rejected", next_action="Review the pinned endpoint and executor policy; no direct fallback or retry is permitted.")


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 8192 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        _deny("network_credential_format_invalid")
    return value


class SocketBudget:
    """One deadline/cancellation owner from TCP connect through response close."""
    def __init__(self, deadline: float, cancelled: Callable[[], bool]) -> None:
        self.deadline, self.cancelled = deadline, cancelled
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.sockets: list[Any] = []
        self.watcher = threading.Thread(target=self._watch, daemon=True, name="gate-trusted-https-deadline")
        self.watcher.start()

    def remaining(self) -> float:
        if self.cancelled():
            raise SafeExecutionCancelled("trusted_https_cancelled")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("trusted_https_timeout")
        return remaining

    def track(self, sock: Any) -> None:
        with self.lock:
            self.sockets.append(sock)
        try:
            self.remaining()
        except BaseException:
            self._close_sockets()
            raise

    def _close_sockets(self) -> None:
        with self.lock:
            sockets = list(self.sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _watch(self) -> None:
        while not self.finished.wait(0.02):
            if self.cancelled() or time.monotonic() >= self.deadline:
                self._close_sockets()
                return

    def close(self) -> None:
        self.finished.set()
        self._close_sockets()
        self.watcher.join(timeout=0.1)


class PinnedHTTPS:
    def __init__(self, *, proxy_hosts: tuple[dict[str, Any], ...] = (), resolver: Callable[..., Any] = socket.getaddrinfo) -> None:
        self.proxy_hosts = proxy_hosts
        self.resolver = resolver
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context = context
        self._dns_gate = threading.BoundedSemaphore(1)
        self.dns_busy = threading.Event()
        self._dns_worker: threading.Thread | None = None

    def dns_pending(self) -> bool:
        return self.dns_busy.is_set() or self._dns_worker is not None and self._dns_worker.is_alive()

    def addresses(self, host: str, port: int, rule: dict[str, Any], *, deadline: float | None = None, cancelled: Callable[[], bool] = lambda: False) -> list[str]:
        if host != rule["host"] or port != rule["port"]:
            _deny("network_target_not_allowed")
        if not self._dns_gate.acquire(blocking=False):
            _deny("network_dns_resolver_busy")
        self.dns_busy.set()
        ready = threading.Event()
        response: list[Any] = []
        def resolve() -> None:
            try:
                response.append(self.resolver(host, port, type=socket.SOCK_STREAM))
            except Exception:
                response.append(None)
            finally:
                self._dns_gate.release()
                self.dns_busy.clear()
                ready.set()
        worker = threading.Thread(target=resolve, daemon=True, name="gate-trusted-dns")
        self._dns_worker = worker
        worker.start()
        limit = min(deadline or time.monotonic() + 5, time.monotonic() + 5)
        while not ready.wait(0.02):
            if time.monotonic() >= limit:
                raise PendingDNS(worker)
        if cancelled():
            raise SafeExecutionCancelled("trusted_dns_closed_before_connect")
        try:
            if not response[0] or len(response[0]) > 64:
                raise ValueError
            addresses = list(dict.fromkeys(row[4][0] for row in response[0]))
            validate_resolved_addresses(rule, addresses)
            return addresses
        except (OSError, ValueError):
            _deny("network_dns_policy_rejected")
        raise AssertionError("unreachable")

    @staticmethod
    def _connect(address: str, port: int, timeout: float, *, budget: SocketBudget | None = None) -> socket.socket:
        # Numeric sockaddr prevents a second DNS resolution/rebinding.
        sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM)
        try:
            if budget is not None:
                budget.track(sock)
                timeout = budget.remaining()
            sock.settimeout(timeout)
            sock.connect((address, port))
            if budget is not None:
                budget.remaining()
            return sock
        except BaseException:
            sock.close()
            raise

    @staticmethod
    def _read_exact(sock: socket.socket, length: int, *, deadline: float, cancelled: Callable[[], bool]) -> bytes:
        data = bytearray()
        while len(data) < length:
            if cancelled():
                raise SafeExecutionCancelled("trusted_proxy_cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("trusted_proxy_timeout")
            sock.settimeout(min(remaining, 1.0))
            chunk = sock.recv(length - len(data))
            if not chunk:
                _deny("proxy_tunnel_failed")
            data.extend(chunk)
        return bytes(data)

    def _tunnel(self, address: str, port: int, material: dict[str, Any], timeout: float, *, cancelled: Callable[[], bool], deadline: float, budget: SocketBudget | None = None) -> socket.socket:
        proxy = urlsplit(_text(material["proxy"]))
        if proxy.scheme not in PROXY_SCHEMES or not proxy.hostname or not proxy.port or proxy.username or proxy.password or proxy.path not in {"", "/"} or proxy.query or proxy.fragment:
            _deny("proxy_scheme_unsupported")
        rule = next((item for item in self.proxy_hosts if item["host"] == proxy.hostname and item["port"] == proxy.port), None)
        if rule is None:
            _deny("proxy_host_not_reviewed")
        addresses = self.addresses(proxy.hostname, proxy.port, rule, deadline=deadline, cancelled=cancelled)
        sock = self._connect(addresses[0], proxy.port, budget.remaining() if budget else max(0.001, deadline - time.monotonic()), budget=budget)
        try:
            if budget:
                budget.track(sock)
                sock.settimeout(budget.remaining())
            def send(data: bytes) -> None:
                if budget:
                    sock.settimeout(budget.remaining())
                elif cancelled() or time.monotonic() >= deadline:
                    raise SafeExecutionCancelled("trusted_proxy_cancelled") if cancelled() else TimeoutError("trusted_proxy_timeout")
                sock.sendall(data)
            credential = material.get("proxy_credential")
            if proxy.scheme == "http":
                # HTTP CONNECT is made to the validated *numeric* upstream, so
                # even remotely resolving proxies cannot choose another target.
                target = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
                header = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
                if credential:
                    header += "Proxy-Authorization: Basic " + base64.b64encode(_text(credential).encode()).decode() + "\r\n"
                send((header + "\r\n").encode("ascii"))
                response = bytearray()
                while not response.endswith(b"\r\n\r\n"):
                    if len(response) >= 4096:
                        _deny("proxy_response_limit")
                    response.extend(self._read_exact(sock, 1, deadline=deadline, cancelled=cancelled))
                if response.split(b"\r\n", 1)[0].split(b" ")[1:2] != [b"200"]:
                    _deny("proxy_tunnel_failed")
            else:
                send(b"\x05\x01" + (b"\x02" if credential else b"\x00"))
                if self._read_exact(sock, 2, deadline=deadline, cancelled=cancelled) != (b"\x05\x02" if credential else b"\x05\x00"):
                    _deny("proxy_tunnel_failed")
                if credential:
                    parts = _text(credential).split(":", 1)
                    if len(parts) != 2 or any(not 0 < len(item.encode()) <= 255 for item in parts):
                        _deny("network_credential_format_invalid")
                    username, password = (item.encode() for item in parts)
                    send(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
                    if self._read_exact(sock, 2, deadline=deadline, cancelled=cancelled) != b"\x01\x00":
                        _deny("proxy_tunnel_failed")
                ip = ipaddress.ip_address(address)
                send(b"\x05\x01\x00" + (b"\x01" if ip.version == 4 else b"\x04") + ip.packed + struct.pack("!H", port))
                reply = self._read_exact(sock, 4, deadline=deadline, cancelled=cancelled)
                if reply[:3] != b"\x05\x00\x00" or reply[3] not in {1, 4}:
                    _deny("proxy_tunnel_failed")
                self._read_exact(sock, (4 if reply[3] == 1 else 16) + 2, deadline=deadline, cancelled=cancelled)
            return sock
        except BaseException:
            sock.close()
            raise

    def request(self, url: str, *, rule: dict[str, Any], material: dict[str, Any], deadline: float, maximum: int, method: str = "GET", body: bytes | None = None, credential: str | None = None, auth_scheme: str = "bearer", headers: dict[str, str] | None = None, cancelled: Callable[[], bool] = lambda: False) -> tuple[int, bytes]:
        budget = SocketBudget(deadline, cancelled)
        try:
            return self._request(url, rule=rule, material=material, deadline=deadline, maximum=maximum, method=method, body=body, credential=credential, auth_scheme=auth_scheme, headers=headers, cancelled=cancelled, socket_budget=budget)
        except PendingDNS:
            # A live resolver is not a stopped socket. Preserve its exact handle
            # even when the shared deadline expired or cancellation was asked.
            raise
        except (OSError, http.client.HTTPException):
            budget.remaining()  # Classify an interrupted connect/handshake/send.
            raise
        finally:
            budget.close()

    def _request(self, url: str, *, rule: dict[str, Any], material: dict[str, Any], deadline: float, maximum: int, method: str, body: bytes | None, credential: str | None, auth_scheme: str, headers: dict[str, str] | None, cancelled: Callable[[], bool], socket_budget: SocketBudget) -> tuple[int, bytes]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or "\\" in url or any(ord(ch) <= 32 for ch in url) or method not in {"GET", "HEAD", "POST"} or maximum > 50 * 1024 * 1024 or maximum < 1:
            _deny("network_target_not_allowed")
        remaining = socket_budget.remaining()
        port = parsed.port or 443
        addresses = self.addresses(parsed.hostname, port, rule, deadline=deadline, cancelled=cancelled)
        remaining = socket_budget.remaining()
        raw = self._tunnel(addresses[0], port, material, remaining, cancelled=cancelled, deadline=deadline, budget=socket_budget) if material.get("proxy") else self._connect(addresses[0], port, remaining, budget=socket_budget)
        with raw:
            socket_budget.track(raw)
            raw.settimeout(socket_budget.remaining())
            with self.context.wrap_socket(raw, server_hostname=parsed.hostname, do_handshake_on_connect=False) as sock:
                socket_budget.track(sock)
                sock.settimeout(socket_budget.remaining())
                sock.do_handshake()
                socket_budget.remaining()
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                host = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
                supplied = dict(headers or {})
                if any(name not in {"Content-Type", "Accept", "Git-Protocol"} for name in supplied):
                    _deny("network_header_rejected")
                supplied.update({"Host": host, "Connection": "close", "User-Agent": "Lingshu-Gate-TrustedFetch/1", "Accept-Encoding": "identity"})
                if credential:
                    value = _text(credential)
                    if auth_scheme == "basic":
                        if ":" not in value or not all(value.split(":", 1)):
                            _deny("network_credential_format_invalid")
                        supplied["Authorization"] = "Basic " + base64.b64encode(value.encode()).decode()
                    elif auth_scheme == "bearer":
                        supplied["Authorization"] = "Bearer " + value
                    else:
                        _deny("network_credential_format_invalid")
                if body is not None:
                    supplied["Content-Length"] = str(len(body))
                request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{name}: {_text(value)}\r\n" for name, value in supplied.items()) + "\r\n"
                sock.settimeout(socket_budget.remaining())
                sock.sendall(request.encode("ascii") + (body or b""))
                sock.settimeout(socket_budget.remaining())
                response = http.client.HTTPResponse(sock, method=method)
                original = response.fp
                class HeaderBudget:
                    total = 0
                    headers = True
                    def readline(self, size: int = -1) -> bytes:
                        limit = 4097 - self.total if self.headers else 8192
                        value = original.readline(min(size, limit) if size >= 0 else limit)
                        self.total += len(value) if self.headers else 0
                        if self.headers and self.total > 4096:
                            _deny("network_header_limit")
                        return value
                    def __getattr__(self, name: str) -> Any:
                        return getattr(original, name)
                budget = HeaderBudget()
                response.fp = budget  # type: ignore[assignment]
                try:
                    response.begin()
                    socket_budget.remaining()
                    budget.headers = False
                    if sum(len(name) + len(value) for name, value in response.getheaders()) > 4096:
                        _deny("network_header_limit")
                    if response.status not in {200, 204} or response.getheader("Content-Encoding", "identity") != "identity":
                        _deny("network_http_rejected")
                    if method == "HEAD":
                        return response.status, b""
                    content = bytearray()
                    while True:
                        remaining = socket_budget.remaining()
                        sock.settimeout(min(remaining, 1.0))
                        chunk = response.read1(min(64 * 1024, maximum + 1 - len(content)))
                        if not chunk:
                            break
                        content.extend(chunk)
                        if len(content) > maximum:
                            _deny("network_response_limit")
                    socket_budget.remaining()
                    return response.status, bytes(content)
                finally:
                    response.close()

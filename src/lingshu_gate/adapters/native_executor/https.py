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
from collections.abc import Callable
from typing import Any, NoReturn
from urllib.parse import urlsplit

from lingshu_gate.git_source import validate_resolved_addresses
from lingshu_gate.registry import ToolExecutionError

PROXY_SCHEMES = frozenset({"http", "socks5", "socks5h"})


def _deny(code: str) -> NoReturn:
    raise ToolExecutionError(code, "Trusted HTTPS request was rejected", next_action="Review the pinned endpoint and executor policy; no direct fallback or retry is permitted.")


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 8192 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        _deny("network_credential_format_invalid")
    return value


class PinnedHTTPS:
    def __init__(self, *, proxy_hosts: tuple[dict[str, Any], ...] = (), resolver: Callable[..., Any] = socket.getaddrinfo) -> None:
        self.proxy_hosts = proxy_hosts
        self.resolver = resolver
        self.context = ssl.create_default_context()
        self._dns_gate = threading.BoundedSemaphore(1)

    def addresses(self, host: str, port: int, rule: dict[str, Any], *, deadline: float | None = None, cancelled: Callable[[], bool] = lambda: False) -> list[str]:
        if host != rule["host"] or port != rule["port"]:
            _deny("network_target_not_allowed")
        if not self._dns_gate.acquire(blocking=False):
            _deny("network_dns_resolver_busy")
        ready = threading.Event()
        response: list[Any] = []
        def resolve() -> None:
            try:
                response.append(self.resolver(host, port, type=socket.SOCK_STREAM))
            except Exception:
                response.append(None)
            finally:
                self._dns_gate.release()
                ready.set()
        threading.Thread(target=resolve, daemon=True, name="gate-trusted-dns").start()
        limit = min(deadline or time.monotonic() + 5, time.monotonic() + 5)
        while not ready.wait(0.02):
            if cancelled():
                raise InterruptedError("trusted_https_cancelled")
            if time.monotonic() >= limit:
                raise TimeoutError("trusted_dns_timeout")
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
    def _connect(address: str, port: int, timeout: float) -> socket.socket:
        # Numeric sockaddr prevents a second DNS resolution/rebinding.
        sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((address, port))
            return sock
        except BaseException:
            sock.close()
            raise

    @staticmethod
    def _read_exact(sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                _deny("proxy_tunnel_failed")
            data.extend(chunk)
        return bytes(data)

    def _tunnel(self, address: str, port: int, material: dict[str, Any], timeout: float, *, cancelled: Callable[[], bool], deadline: float) -> socket.socket:
        proxy = urlsplit(_text(material["proxy"]))
        if proxy.scheme not in PROXY_SCHEMES or not proxy.hostname or not proxy.port or proxy.username or proxy.password or proxy.path not in {"", "/"} or proxy.query or proxy.fragment:
            _deny("proxy_scheme_unsupported")
        rule = next((item for item in self.proxy_hosts if item["host"] == proxy.hostname and item["port"] == proxy.port), None)
        if rule is None:
            _deny("proxy_host_not_reviewed")
        addresses = self.addresses(proxy.hostname, proxy.port, rule, deadline=deadline, cancelled=cancelled)
        sock = self._connect(addresses[0], proxy.port, timeout)
        try:
            credential = material.get("proxy_credential")
            if proxy.scheme == "http":
                # HTTP CONNECT is made to the validated *numeric* upstream, so
                # even remotely resolving proxies cannot choose another target.
                target = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
                header = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
                if credential:
                    header += "Proxy-Authorization: Basic " + base64.b64encode(_text(credential).encode()).decode() + "\r\n"
                sock.sendall((header + "\r\n").encode("ascii"))
                response = bytearray()
                while not response.endswith(b"\r\n\r\n"):
                    if len(response) >= 4096:
                        _deny("proxy_response_limit")
                    response.extend(self._read_exact(sock, 1))
                if response.split(b"\r\n", 1)[0].split(b" ")[1:2] != [b"200"]:
                    _deny("proxy_tunnel_failed")
            else:
                sock.sendall(b"\x05\x01" + (b"\x02" if credential else b"\x00"))
                if self._read_exact(sock, 2) != (b"\x05\x02" if credential else b"\x05\x00"):
                    _deny("proxy_tunnel_failed")
                if credential:
                    parts = _text(credential).split(":", 1)
                    if len(parts) != 2 or any(not 0 < len(item.encode()) <= 255 for item in parts):
                        _deny("network_credential_format_invalid")
                    username, password = (item.encode() for item in parts)
                    sock.sendall(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
                    if self._read_exact(sock, 2) != b"\x01\x00":
                        _deny("proxy_tunnel_failed")
                ip = ipaddress.ip_address(address)
                sock.sendall(b"\x05\x01\x00" + (b"\x01" if ip.version == 4 else b"\x04") + ip.packed + struct.pack("!H", port))
                reply = self._read_exact(sock, 4)
                if reply[:3] != b"\x05\x00\x00" or reply[3] not in {1, 4}:
                    _deny("proxy_tunnel_failed")
                self._read_exact(sock, (4 if reply[3] == 1 else 16) + 2)
            return sock
        except BaseException:
            sock.close()
            raise

    def request(self, url: str, *, rule: dict[str, Any], material: dict[str, Any], deadline: float, maximum: int, method: str = "GET", body: bytes | None = None, credential: str | None = None, headers: dict[str, str] | None = None, cancelled: Callable[[], bool] = lambda: False) -> tuple[int, bytes]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or "\\" in url or any(ord(ch) <= 32 for ch in url) or method not in {"GET", "HEAD", "POST"} or maximum > 50 * 1024 * 1024 or maximum < 1:
            _deny("network_target_not_allowed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("trusted_https_timeout")
        if cancelled():
            raise InterruptedError("trusted_https_cancelled")
        port = parsed.port or 443
        addresses = self.addresses(parsed.hostname, port, rule, deadline=deadline, cancelled=cancelled)
        if time.monotonic() >= deadline:
            raise TimeoutError("trusted_https_timeout")
        remaining = deadline - time.monotonic()
        raw = self._tunnel(addresses[0], port, material, remaining, cancelled=cancelled, deadline=deadline) if material.get("proxy") else self._connect(addresses[0], port, remaining)
        with raw:
            with self.context.wrap_socket(raw, server_hostname=parsed.hostname) as sock:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                host = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
                supplied = dict(headers or {})
                if any(name not in {"Content-Type", "Accept", "Git-Protocol"} for name in supplied):
                    _deny("network_header_rejected")
                supplied.update({"Host": host, "Connection": "close", "User-Agent": "Lingshu-Gate-TrustedFetch/1", "Accept-Encoding": "identity"})
                if credential:
                    supplied["Authorization"] = "Bearer " + _text(credential)
                if body is not None:
                    supplied["Content-Length"] = str(len(body))
                request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{name}: {_text(value)}\r\n" for name, value in supplied.items()) + "\r\n"
                sock.sendall(request.encode("ascii") + (body or b""))
                response = http.client.HTTPResponse(sock, method=method)
                original = response.fp
                class HeaderBudget:
                    total = 0
                    def readline(self, size: int = -1) -> bytes:
                        value = original.readline(min(size, 4097 - self.total) if size >= 0 else 4097 - self.total)
                        self.total += len(value)
                        if self.total > 4096:
                            _deny("network_header_limit")
                        return value
                    def __getattr__(self, name: str) -> Any:
                        return getattr(original, name)
                response.fp = HeaderBudget()  # type: ignore[assignment]
                try:
                    response.begin()
                    if sum(len(name) + len(value) for name, value in response.getheaders()) > 4096:
                        _deny("network_header_limit")
                    if response.status not in {200, 204} or response.getheader("Content-Encoding", "identity") != "identity":
                        _deny("network_http_rejected")
                    if method == "HEAD":
                        return response.status, b""
                    content = bytearray()
                    while True:
                        if cancelled():
                            raise InterruptedError("trusted_https_cancelled")
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("trusted_https_timeout")
                        sock.settimeout(min(remaining, 1.0))
                        chunk = response.read(min(64 * 1024, maximum + 1 - len(content)))
                        if not chunk:
                            break
                        content.extend(chunk)
                        if len(content) > maximum:
                            _deny("network_response_limit")
                    return response.status, bytes(content)
                finally:
                    response.close()

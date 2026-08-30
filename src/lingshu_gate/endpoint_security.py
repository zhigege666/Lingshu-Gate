"""Validation and disclosure controls for outbound HTTP MCP endpoints."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urlsplit

REDACTED_ENDPOINT = "[REDACTED]"
_HOST_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def validate_streamable_http_endpoint(endpoint: str) -> str:
    """Return a safe outbound endpoint or raise a value-only validation error.

    Remote clear-text HTTP is rejected. Plain HTTP remains available for
    canonical loopback IP literals and ``localhost`` so locally managed
    processes can expose an MCP endpoint without local TLS provisioning.
    """

    if not endpoint or endpoint != endpoint.strip():
        raise ValueError("streamable_http endpoint must be a non-empty absolute URL")
    if "\\" in endpoint or any(character.isspace() for character in endpoint) or _has_control_character(endpoint):
        raise ValueError("streamable_http endpoint contains an unsupported character")
    if _INVALID_PERCENT_ESCAPE.search(endpoint):
        raise ValueError("streamable_http endpoint contains an invalid percent escape")

    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise ValueError("streamable_http endpoint is not a valid absolute URL") from None

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("streamable_http endpoint scheme must be http or https")
    if not parsed.netloc or parsed.hostname is None:
        raise ValueError("streamable_http endpoint must include a valid host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("streamable_http endpoint must not include user information")
    if "?" in endpoint:
        raise ValueError("streamable_http endpoint must not include a query")
    if "#" in endpoint:
        raise ValueError("streamable_http endpoint must not include a fragment")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("streamable_http endpoint port must be between 1 and 65535")
    if _has_control_character(unquote(parsed.path)):
        raise ValueError("streamable_http endpoint path contains an unsupported character")

    host = parsed.hostname
    is_loopback = _validate_host_and_check_loopback(host)
    if scheme == "http" and not is_loopback:
        raise ValueError("streamable_http endpoint must use HTTPS unless its host is loopback")
    return endpoint


def redact_endpoint(endpoint: str | None) -> str | None:
    """Return the single representation permitted at logs and API boundaries."""

    return REDACTED_ENDPOINT if endpoint else None


def _validate_host_and_check_loopback(host: str) -> bool:
    if "%" in host:
        raise ValueError("streamable_http endpoint host must not include a zone identifier")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("streamable_http endpoint must include a valid host") from None
        if len(ascii_host) > 253:
            raise ValueError("streamable_http endpoint must include a valid host")
        labels = ascii_host.split(".")
        if any(not _HOST_LABEL_PATTERN.fullmatch(label) for label in labels):
            raise ValueError("streamable_http endpoint must include a valid host")
        return ascii_host.lower() == "localhost"
    return address.is_loopback


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)

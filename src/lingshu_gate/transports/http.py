"""Streamable HTTP framing and validation independent from protocol dispatch."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from lingshu_gate.protocol.request import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_META_KEY,
    build_request_params,
)
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION, UnsupportedProtocolVersion, require_current_protocol_version

HEADER_MISMATCH = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022
INVALID_ORIGIN = -32023


@dataclass(frozen=True)
class HttpProtocolContext:
    protocol_version: str
    client_capabilities: dict[str, Any]
    client_info: dict[str, Any] | None = None


class HttpProtocolValidationError(ValueError):
    def __init__(
        self,
        code: int,
        message: str,
        *,
        status_code: int = 400,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.data = data
        super().__init__(message)


def resolve_allowed_origins(configured: str, port: int) -> frozenset[tuple[str, str, int]]:
    """Return the explicit browser Origin allowlist for the MCP endpoint."""

    raw_origins = [item.strip() for item in configured.split(",") if item.strip()]
    if not raw_origins:
        raw_origins = [
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"http://[::1]:{port}",
        ]
    try:
        return frozenset(_normalize_origin(origin) for origin in raw_origins)
    except ValueError as exc:
        raise ValueError("LINGSHU_GATE_MCP_ALLOWED_ORIGINS contains an invalid origin") from exc


def validate_origin_header(
    headers: Mapping[str, str],
    allowed_origins: frozenset[tuple[str, str, int]],
) -> None:
    """Reject browser requests whose Origin is not explicitly trusted."""

    normalized_headers = {key.lower(): value for key, value in headers.items()}
    raw_origin = normalized_headers.get("origin")
    if raw_origin is None:
        return
    try:
        origin = _normalize_origin(raw_origin)
    except ValueError as exc:
        raise HttpProtocolValidationError(
            INVALID_ORIGIN,
            "Origin is not allowed",
            status_code=403,
        ) from exc
    if origin not in allowed_origins:
        raise HttpProtocolValidationError(
            INVALID_ORIGIN,
            "Origin is not allowed",
            status_code=403,
        )


def _normalize_origin(value: str) -> tuple[str, str, int]:
    if not value or value != value.strip() or value.casefold() == "null":
        raise ValueError("invalid origin")
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid origin port") from exc
    return (
        parsed.scheme.casefold(),
        parsed.hostname.casefold(),
        port or (443 if parsed.scheme.casefold() == "https" else 80),
    )


def validate_inbound_http_request(
    headers: Mapping[str, str],
    message: dict[str, Any],
) -> HttpProtocolContext:
    """Validate the required 2026-07-28 HTTP header and request metadata."""

    normalized_headers = {key.lower(): value for key, value in headers.items()}
    method = message.get("method")
    raw_params = message.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    raw_meta = params.get("_meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    header_version = normalized_headers.get("mcp-protocol-version")
    meta_version = meta.get(PROTOCOL_META_KEY)

    for version in (header_version, meta_version):
        if not isinstance(version, str):
            continue
        try:
            require_current_protocol_version(version)
        except UnsupportedProtocolVersion as exc:
            raise HttpProtocolValidationError(
                UNSUPPORTED_PROTOCOL_VERSION,
                "Unsupported protocol version",
                data={"supported": list(exc.supported), "requested": exc.requested},
            ) from exc

    if header_version is None:
        raise _header_error("MCP-Protocol-Version header is required")
    if meta_version is None:
        raise _header_error(f"params._meta.{PROTOCOL_META_KEY} is required")
    if header_version != meta_version:
        raise _header_error(
            "MCP-Protocol-Version header does not match request metadata"
        )
    require_current_protocol_version(header_version)

    header_method = normalized_headers.get("mcp-method")
    if not isinstance(method, str) or header_method != method:
        raise _header_error("Mcp-Method header does not match the JSON-RPC method")

    if method in {"tools/call", "resources/read", "prompts/get"}:
        source_key = "uri" if method == "resources/read" else "name"
        expected_name = params.get(source_key)
        raw_name = normalized_headers.get("mcp-name")
        if not isinstance(expected_name, str) or raw_name is None:
            raise _header_error(f"Mcp-Name header is required for {method}")
        try:
            decoded_name = decode_header_value(raw_name)
        except ValueError as exc:
            raise _header_error("Mcp-Name header is malformed") from exc
        if decoded_name != expected_name:
            raise _header_error("Mcp-Name header does not match request parameters")

    client_capabilities = meta.get(CLIENT_CAPABILITIES_META_KEY)
    if not isinstance(client_capabilities, dict):
        raise HttpProtocolValidationError(
            MISSING_REQUIRED_CLIENT_CAPABILITY,
            "Client capabilities are required for MCP 2026-07-28 requests",
            data={"requiredCapabilities": {}},
        )
    raw_client_info = meta.get(CLIENT_INFO_META_KEY)
    if raw_client_info is not None and not isinstance(raw_client_info, dict):
        raise _header_error("Client information metadata must be an object")
    client_info: dict[str, Any] | None = (
        raw_client_info if isinstance(raw_client_info, dict) else None
    )
    return HttpProtocolContext(
        header_version,
        client_capabilities,
        client_info,
    )


def build_protocol_request(
    method: str,
    params: dict[str, Any] | None,
    *,
    client_name: str,
    client_version: str,
    protocol_version: str = MCP_PROTOCOL_VERSION,
    client_capabilities: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Add current per-request metadata and mirrored HTTP routing headers."""

    require_current_protocol_version(protocol_version)

    request_params = build_request_params(
        params,
        client_name=client_name,
        client_version=client_version,
        protocol_version=protocol_version,
        client_capabilities=client_capabilities,
    )
    headers = {
        "MCP-Protocol-Version": protocol_version,
        "Mcp-Method": method,
    }
    if method in {"tools/call", "prompts/get"} and isinstance(
        request_params.get("name"), str
    ):
        headers["Mcp-Name"] = encode_header_value(request_params["name"])
    elif method == "resources/read" and isinstance(request_params.get("uri"), str):
        headers["Mcp-Name"] = encode_header_value(request_params["uri"])
    return request_params, headers


def encode_header_value(value: str) -> str:
    sentinel = value.startswith("=?base64?") and value.endswith("?=")
    safe_ascii = (
        not sentinel
        and value == value.strip(" \t")
        and all(
            character in "\t" or 0x20 <= ord(character) <= 0x7E for character in value
        )
    )
    if safe_ascii:
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"=?base64?{encoded}?="


def decode_header_value(value: str) -> str:
    if not (value.startswith("=?base64?") and value.endswith("?=")):
        if value != value.strip(" \t") or any(
            character not in "\t" and not 0x20 <= ord(character) <= 0x7E
            for character in value
        ):
            raise ValueError("unsafe header value")
        return value
    encoded = value[len("=?base64?") : -2]
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("invalid base64 header value") from exc


def _header_error(message: str) -> HttpProtocolValidationError:
    return HttpProtocolValidationError(HEADER_MISMATCH, f"Header mismatch: {message}")

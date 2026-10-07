"""按协议版本生成传输无关的请求参数。"""

from __future__ import annotations

from typing import Any

from lingshu_gate.protocol.version import (
    MCP_PROTOCOL_VERSION,
    resolve_downstream_protocol_version,
)

PROTOCOL_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"


def build_request_params(
    params: dict[str, Any] | None,
    *,
    client_name: str,
    client_version: str,
    protocol_version: str = MCP_PROTOCOL_VERSION,
    client_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp the required protocol, client identity, and capability metadata."""

    protocol_version = resolve_downstream_protocol_version(protocol_version, allow_legacy_stdio=True)
    request_params = dict(params or {})
    if protocol_version != MCP_PROTOCOL_VERSION:
        return request_params
    current_meta = request_params.get("_meta")
    meta = dict(current_meta) if isinstance(current_meta, dict) else {}
    meta.update(
        {
            PROTOCOL_META_KEY: protocol_version,
            CLIENT_INFO_META_KEY: {"name": client_name, "version": client_version},
            CLIENT_CAPABILITIES_META_KEY: dict(client_capabilities or {}),
        }
    )
    request_params["_meta"] = meta
    return request_params

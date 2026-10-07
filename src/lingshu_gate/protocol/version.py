"""按传输类型限定自动协商和显式选择的协议版本。"""

from __future__ import annotations

MCP_PROTOCOL_VERSION = "2026-07-28"

LEGACY_PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")
STDIO_LEGACY_PROTOCOL_VERSIONS = ("2024-11-05", *LEGACY_PROTOCOL_VERSIONS)
GATEWAY_HANDSHAKE_VERSIONS = LEGACY_PROTOCOL_VERSIONS
DOWNSTREAM_PROTOCOL_VERSIONS = (*LEGACY_PROTOCOL_VERSIONS, MCP_PROTOCOL_VERSION)


class UnsupportedProtocolVersion(ValueError):
    """当前协议路径收到不支持的版本时抛出。"""

    def __init__(self, requested: str, supported: tuple[str, ...] = (MCP_PROTOCOL_VERSION,)) -> None:
        self.requested = requested
        self.supported = supported
        super().__init__(
            f"unsupported MCP protocol version: {requested}; "
            f"supported: {', '.join(supported)}"
        )


def require_current_protocol_version(value: str | None) -> str:
    """Resolve an omitted version to the current protocol and reject every other value."""

    requested = value or MCP_PROTOCOL_VERSION
    if requested != MCP_PROTOCOL_VERSION:
        raise UnsupportedProtocolVersion(requested)
    return requested


def resolve_downstream_protocol_version(value: str | None, *, allow_legacy_stdio: bool = False) -> str:
    """自动协商优先当前协议，显式版本指定起始握手方式。"""

    requested = MCP_PROTOCOL_VERSION if value is None or value == "auto" else value
    supported = (
        (*STDIO_LEGACY_PROTOCOL_VERSIONS, MCP_PROTOCOL_VERSION)
        if allow_legacy_stdio else DOWNSTREAM_PROTOCOL_VERSIONS
    )
    if requested not in supported:
        raise UnsupportedProtocolVersion(requested, supported)
    return requested

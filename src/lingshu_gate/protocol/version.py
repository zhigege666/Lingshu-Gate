"""当前下游协议与入站网关的兼容握手版本。"""

from __future__ import annotations

MCP_PROTOCOL_VERSION = "2026-07-28"

# 仅供入站网关兼容 initialize 客户端；下游连接仍使用当前协议。
GATEWAY_HANDSHAKE_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")


class UnsupportedProtocolVersion(ValueError):
    """当前协议路径收到不支持的版本时抛出。"""

    def __init__(self, requested: str) -> None:
        self.requested = requested
        self.supported = (MCP_PROTOCOL_VERSION,)
        super().__init__(
            f"unsupported MCP protocol version: {requested}; "
            f"supported: {MCP_PROTOCOL_VERSION}"
        )


def require_current_protocol_version(value: str | None) -> str:
    """Resolve an omitted version to the current protocol and reject every other value."""

    requested = value or MCP_PROTOCOL_VERSION
    if requested != MCP_PROTOCOL_VERSION:
        raise UnsupportedProtocolVersion(requested)
    return requested

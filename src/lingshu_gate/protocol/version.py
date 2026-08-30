"""Single-version MCP protocol policy for Lingshu Gate."""

from __future__ import annotations

MCP_PROTOCOL_VERSION = "2026-07-28"


class UnsupportedProtocolVersion(ValueError):
    """Raised when a peer selects a protocol version the gateway does not serve."""

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

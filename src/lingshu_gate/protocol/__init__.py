"""Current MCP protocol semantics independent from wire transport."""

from lingshu_gate.protocol.capabilities import GatewayCapabilityPolicy
from lingshu_gate.protocol.version import (
    MCP_PROTOCOL_VERSION,
    UnsupportedProtocolVersion,
    require_current_protocol_version,
)

__all__ = [
    "GatewayCapabilityPolicy",
    "MCP_PROTOCOL_VERSION",
    "UnsupportedProtocolVersion",
    "require_current_protocol_version",
]

"""HTTP 与 stdio 共用的旧版初始化契约。"""

from __future__ import annotations

from typing import Any

from mcp.types import InitializeResult
from pydantic import ValidationError

from lingshu_gate.protocol.version import LEGACY_PROTOCOL_VERSIONS


def discovery_requires_initialize(code: int | None, message: str | None) -> bool:
    """仅在启动发现被协议层拒绝时尝试旧握手；认证、网络及业务错误不参与协商。"""

    if type(code) is not int:
        return False
    if code in {-32601, -32602, -32022}:
        return True
    # 部分实现把未知方法归入通用服务端错误，必须同时匹配被拒绝的发现方法。
    return code == -32000 and isinstance(message, str) and message.strip().lower() in {
        "unknown method: server/discover",
        "method not found: server/discover",
        "unsupported method: server/discover",
    }


def initialize_params(protocol_version: str, client_version: str) -> dict[str, Any]:
    return {
        "protocolVersion": protocol_version,
        "capabilities": {},
        "clientInfo": {"name": "lingshu-gate", "version": client_version},
    }


def parse_initialize_result(
    result: dict[str, Any], *, supported_versions: tuple[str, ...] = LEGACY_PROTOCOL_VERSIONS,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """只接受受支持的握手版本，校验失败时不回显下游原始数据。"""

    try:
        parsed = InitializeResult.model_validate(result, by_name=False)
    except ValidationError:
        raise ValueError("Invalid MCP initialize result") from None
    if parsed.protocol_version not in supported_versions:
        raise ValueError("MCP server negotiated an unsupported initialize protocol version")
    return (
        parsed.protocol_version,
        parsed.capabilities.model_dump(mode="json", by_alias=True, exclude_none=True),
        parsed.server_info.model_dump(mode="json", by_alias=True, exclude_none=True),
    )

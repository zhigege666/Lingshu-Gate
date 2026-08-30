"""Official MCP Python SDK type adapter.

Gate uses the SDK's wire models for validation and serialization. Its
authenticated gateway router deliberately owns dispatch so authorization and
per-principal tool projection are applied before every operation.
"""

from __future__ import annotations

from typing import Any

from mcp.types import (
    CallToolResult,
    DiscoverResult,
    ListToolsResult,
    ServerCapabilities,
    Tool,
)

from lingshu_gate.protocol.capabilities import GatewayCapabilityPolicy
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION

SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"


class OfficialSdkTypesAdapter:
    """Validate and serialize gateway payloads with official MCP v2 models."""

    @staticmethod
    def tool(payload: dict[str, Any]) -> dict[str, Any]:
        model = Tool.model_validate(payload)
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)

    @staticmethod
    def list_tools(
        tools: list[dict[str, Any]],
        *,
        server_name: str,
        server_version: str,
    ) -> dict[str, Any]:
        model = ListToolsResult(
            tools=[Tool.model_validate(tool) for tool in tools],
            _meta={
                SERVER_INFO_META_KEY: {"name": server_name, "version": server_version}
            },
            cache_scope="private",
            ttl_ms=0,
        )
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)

    @staticmethod
    def call_tool(
        result: dict[str, Any],
        *,
        server_name: str,
        server_version: str,
    ) -> dict[str, Any]:
        payload = dict(result)
        existing_meta = payload.get("_meta")
        payload["_meta"] = {
            **(existing_meta if isinstance(existing_meta, dict) else {}),
            SERVER_INFO_META_KEY: {"name": server_name, "version": server_version},
        }
        model = CallToolResult.model_validate(payload)
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)

    @staticmethod
    def discover(
        capability_policy: GatewayCapabilityPolicy,
        *,
        server_name: str,
        server_version: str,
        instructions: str,
        client_capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capabilities = ServerCapabilities.model_validate(
            capability_policy.advertised_for(client_capabilities or {})
        )
        model = DiscoverResult(
            supported_versions=[MCP_PROTOCOL_VERSION],
            capabilities=capabilities,
            instructions=instructions,
            ttl_ms=60_000,
            cache_scope="private",
            _meta={
                SERVER_INFO_META_KEY: {"name": server_name, "version": server_version}
            },
        )
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)

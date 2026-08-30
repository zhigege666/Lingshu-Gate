"""Stateless Streamable HTTP MCP gateway for Gate registered tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.models import ToolDefinition
from lingshu_gate.protocol.capabilities import GatewayCapabilityPolicy
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.protocol.sdk_adapter import OfficialSdkTypesAdapter
from lingshu_gate.protocol.tool_namespace import (
    ToolNamespace,
    ToolNamespaceCollisionError,
)
from lingshu_gate.registry import ToolNotFoundError, ToolRegistry
from lingshu_gate.transports.http import (
    HttpProtocolContext,
    HttpProtocolValidationError,
    resolve_allowed_origins,
    validate_inbound_http_request,
    validate_origin_header,
)
from lingshu_gate.transports.oauth import (
    McpOAuthDiscoveryBoundary,
    register_oauth_protected_resource_routes,
    with_mcp_auth_challenge,
)

JSONRPC_VERSION = "2.0"
SERVER_NAME = "lingshu_gate"
GATEWAY_INSTRUCTIONS = (
    "Tool discovery and invocation are filtered by published classifications, "
    "resource grants, and token scopes."
)


def register_mcp_gateway_route(
    app: FastAPI,
    settings: Settings,
    registry: ToolRegistry,
    access_store: AccessControlStore,
    require_viewer: Callable[[Request], AuthPrincipal],
    oauth_boundary: McpOAuthDiscoveryBoundary | None = None,
) -> None:
    """注册聚合 MCP 网关；发现与调用都复用统一访问策略。"""

    capability_policy = GatewayCapabilityPolicy()
    allowed_origins = resolve_allowed_origins(
        settings.mcp_allowed_origins,
        settings.port,
    )
    require_mcp_viewer = with_mcp_auth_challenge(require_viewer, oauth_boundary)
    if oauth_boundary is not None:
        register_oauth_protected_resource_routes(app, oauth_boundary)

    @app.post("/mcp", tags=["mcp-gateway"])
    async def mcp_gateway(
        request: Request,
        principal: AuthPrincipal = Depends(require_mcp_viewer),
    ) -> Response:
        if not settings.mcp_gateway_enabled:
            raise HTTPException(status_code=404, detail="MCP gateway is disabled")

        try:
            validate_origin_header(request.headers, allowed_origins)
        except HttpProtocolValidationError as exc:
            return _error_response(
                None,
                exc.code,
                str(exc),
                settings,
                status_code=exc.status_code,
                protocol_version=MCP_PROTOCOL_VERSION,
            )

        try:
            message = await request.json()
        except Exception:  # noqa: BLE001 - protocol boundary normalizes parse errors
            return _error_response(None, -32700, "Parse error")
        if not isinstance(message, dict):
            return _error_response(None, -32600, "Invalid Request")

        has_request_id = "id" in message
        request_id = message.get("id")
        method = message.get("method")
        valid_request_id = (
            isinstance(request_id, str)
            and bool(request_id)
            or isinstance(request_id, int)
            and not isinstance(request_id, bool)
        )
        if (
            message.get("jsonrpc") != JSONRPC_VERSION
            or not isinstance(method, str)
            or not method
            or has_request_id
            and not valid_request_id
        ):
            return _error_response(None, -32600, "Invalid Request")

        try:
            protocol_context = validate_inbound_http_request(request.headers, message)
        except HttpProtocolValidationError as exc:
            return _error_response(
                request_id,
                exc.code,
                str(exc),
                settings,
                data=exc.data,
                status_code=exc.status_code,
                protocol_version=MCP_PROTOCOL_VERSION,
            )

        if not has_request_id:
            return Response(status_code=202)
        if method == "server/discover":
            return _result_response(
                request_id,
                OfficialSdkTypesAdapter.discover(
                    capability_policy,
                    server_name=SERVER_NAME,
                    server_version=settings.version,
                    instructions=GATEWAY_INSTRUCTIONS,
                    client_capabilities=protocol_context.client_capabilities,
                ),
                settings,
                protocol_version=protocol_context.protocol_version,
            )
        if method == "tools/list":
            definitions = access_store.visible_tools(principal, registry.list_definitions())
            try:
                tools = [item[1] for item in _gateway_tools(registry, definitions)]
            except ToolNamespaceCollisionError as exc:
                return _namespace_collision_response(request_id, exc, settings, protocol_context)
            result = OfficialSdkTypesAdapter.list_tools(
                tools,
                server_name=SERVER_NAME,
                server_version=settings.version,
            )
            return _result_response(
                request_id,
                result,
                settings,
                protocol_version=protocol_context.protocol_version,
            )
        if method == "tools/call":
            return await _call_tool(
                request_id,
                message.get("params"),
                settings,
                registry,
                access_store,
                principal,
                protocol_context,
            )
        return _error_response(
            request_id,
            -32601,
            f"Method not found: {method}",
            settings,
            status_code=404,
            protocol_version=protocol_context.protocol_version,
        )


async def _call_tool(
    request_id: Any,
    params: Any,
    settings: Settings,
    registry: ToolRegistry,
    access_store: AccessControlStore,
    principal: AuthPrincipal,
    protocol_context: HttpProtocolContext,
) -> JSONResponse:
    if not isinstance(params, dict):
        return _error_response(
            request_id,
            -32602,
            "Invalid params",
            settings,
            protocol_version=protocol_context.protocol_version,
        )
    tool_name = params.get("name")
    if not isinstance(tool_name, str) or not tool_name:
        return _tool_error(
            request_id,
            "Tool name must be a non-empty string",
            settings,
            protocol_context=protocol_context,
        )
    arguments = params.get("arguments") if "arguments" in params else None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _error_response(
            request_id,
            -32602,
            "Tool arguments must be an object",
            settings,
            status_code=400,
            protocol_version=protocol_context.protocol_version,
        )

    try:
        namespace = ToolNamespace(registry.list_definitions())
    except ToolNamespaceCollisionError as exc:
        return _namespace_collision_response(request_id, exc, settings, protocol_context)
    definition = namespace.resolve(tool_name)
    if definition is None:
        return _error_response(
            request_id,
            -32602,
            f"Unknown tool: {tool_name}",
            settings,
            protocol_version=protocol_context.protocol_version,
        )

    try:
        invocation = await run_in_threadpool(
            access_store.invoke_tool,
            registry,
            principal,
            definition.id,
            arguments,
        )
    except AccessDeniedError as exc:
        return _tool_error(
            request_id,
            f"Access denied: {exc.reason}",
            settings,
            protocol_context=protocol_context,
        )
    except ToolNotFoundError:
        return _tool_error(
            request_id,
            f"Tool is no longer available: {tool_name}",
            settings,
            protocol_context=protocol_context,
        )
    if not invocation.ok:
        return _tool_error(
            request_id,
            invocation.error or "Tool invocation failed",
            settings,
            structured_content=invocation.output or None,
            protocol_context=protocol_context,
        )
    result = _normalize_tool_result(invocation.output)
    result = OfficialSdkTypesAdapter.call_tool(
        result,
        server_name=SERVER_NAME,
        server_version=settings.version,
    )
    return _result_response(
        request_id,
        result,
        settings,
        protocol_version=protocol_context.protocol_version,
    )


def _gateway_tools(
    registry: ToolRegistry,
    definitions: list[ToolDefinition] | None = None,
) -> list[tuple[str, dict[str, Any], ToolDefinition]]:
    """把当前 Registry 快照转换为稳定、唯一且符合 MCP 命名约束的工具列表。"""

    namespace = ToolNamespace(
        definitions if definitions is not None else registry.list_definitions()
    )
    tools: list[tuple[str, dict[str, Any], ToolDefinition]] = []
    for entry in namespace.entries:
        definition = entry.definition
        payload: dict[str, Any] = {
            "name": entry.wire_name,
            "title": definition.name,
            "description": definition.description,
            "inputSchema": definition.input_schema or {"type": "object", "properties": {}},
            "annotations": _tool_annotations(definition),
        }
        output_schema = definition.metadata.get("outputSchema") or definition.metadata.get("output_schema")
        if isinstance(output_schema, dict):
            payload["outputSchema"] = output_schema
        payload = OfficialSdkTypesAdapter.tool(payload)
        tools.append((entry.wire_name, payload, definition))
    return tools


def _tool_annotations(definition: ToolDefinition) -> dict[str, Any]:
    read_only = definition.permission.startswith("read")
    annotations: dict[str, Any] = {
        "readOnlyHint": read_only,
        "destructiveHint": not read_only,
        "idempotentHint": read_only,
        "openWorldHint": definition.source == "mcp",
    }
    source_annotations = definition.metadata.get("annotations")
    if isinstance(source_annotations, dict):
        annotations.update(source_annotations)
    return annotations


def _normalize_tool_result(output: dict[str, Any]) -> dict[str, Any]:
    """保留下游原生 CallToolResult；普通 Registry 输出转换为标准 MCP 结果。"""

    if isinstance(output.get("content"), list):
        result = dict(output)
        result.setdefault("isError", False)
        return result
    text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": output,
        "isError": False,
    }


def _tool_error(
    request_id: Any,
    message: str,
    settings: Settings,
    *,
    structured_content: dict[str, Any] | None = None,
    protocol_context: HttpProtocolContext | None = None,
) -> JSONResponse:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
    if structured_content:
        result["structuredContent"] = structured_content
    if protocol_context is not None:
        result = OfficialSdkTypesAdapter.call_tool(
            result,
            server_name=SERVER_NAME,
            server_version=settings.version,
        )
    return _result_response(
        request_id,
        result,
        settings,
        protocol_version=protocol_context.protocol_version if protocol_context else None,
    )


def _result_response(
    request_id: Any,
    result: dict[str, Any],
    settings: Settings,
    *,
    protocol_version: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result},
        headers={"MCP-Protocol-Version": protocol_version or MCP_PROTOCOL_VERSION},
    )


def _error_response(
    request_id: Any,
    code: int,
    message: str,
    settings: Settings | None = None,
    *,
    data: dict[str, Any] | None = None,
    status_code: int = 200,
    protocol_version: str | None = None,
) -> JSONResponse:
    headers = (
        {"MCP-Protocol-Version": protocol_version or MCP_PROTOCOL_VERSION}
        if settings
        else None
    )
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse(
        {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error},
        headers=headers,
        status_code=status_code,
    )


def _namespace_collision_response(
    request_id: Any,
    exc: ToolNamespaceCollisionError,
    settings: Settings,
    protocol_context: HttpProtocolContext,
) -> JSONResponse:
    return _error_response(
        request_id,
        -32603,
        "MCP tool namespace is ambiguous; tool discovery and calls are disabled",
        settings,
        # Do not disclose the colliding Registry ids: one of them may be hidden
        # from the current principal by access policy.
        data={"wireName": exc.wire_name},
        status_code=500,
        protocol_version=protocol_context.protocol_version,
    )

"""Stateless Streamable HTTP MCP gateway for Gate registered tools."""

from __future__ import annotations

from lingshu_gate.telemetry_http import request_correlation
from lingshu_gate.telemetry import exception_outcome, invocation_entry, protocol_outcome

import json
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import QueryParams
from pydantic import ValidationError

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.models import ToolDefinition, ToolInvokeResponse
from lingshu_gate.protocol.capabilities import GatewayCapabilityPolicy
from lingshu_gate.protocol.version import GATEWAY_HANDSHAKE_VERSIONS, MCP_PROTOCOL_VERSION
from lingshu_gate.protocol.sdk_adapter import OfficialSdkTypesAdapter
from lingshu_gate.protocol.tool_namespace import (
    ToolNamespace,
    ToolNamespaceCollisionError,
)
from lingshu_gate.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry
from lingshu_gate.tool_catalog import CATALOG_TOOL_NAMES, ToolCatalog, catalog_tools
from lingshu_gate.pinned_tools import project_pins
from lingshu_gate.result_budget import RESULT_TOOL, ResultCache, ResultRead, ResultTarget, result_read_tool
from lingshu_gate.transports.http import (
    HttpProtocolContext,
    HttpProtocolValidationError,
    resolve_allowed_origins,
    validate_gateway_http_request,
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
    oauth_boundary: McpOAuthDiscoveryBoundary | Callable[[], McpOAuthDiscoveryBoundary | None] | None = None,
    *,
    path: str = "/mcp",
    metadata_path: str | None = None,
    catalog: ToolCatalog | None = None,
    result_cache: ResultCache | None = None,
) -> None:
    """注册聚合 MCP 网关；发现与调用都复用统一访问策略。"""

    capability_policy = GatewayCapabilityPolicy()
    result_cache = result_cache or ResultCache(registry, access_store, catalog)
    allowed_origins = resolve_allowed_origins(
        settings.mcp_allowed_origins,
        settings.port,
    )
    require_mcp_viewer = with_mcp_auth_challenge(require_viewer, oauth_boundary)
    if oauth_boundary is not None:
        register_oauth_protected_resource_routes(app, oauth_boundary, include_root=path == "/mcp", metadata_path=metadata_path)

    @app.post(path, tags=["mcp-gateway"])
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
                exc.message,
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
            protocol_context = validate_gateway_http_request(request.headers, message)
        except HttpProtocolValidationError as exc:
            return _error_response(
                request_id,
                exc.code,
                exc.message,
                settings,
                data=exc.data,
                status_code=exc.status_code,
                protocol_version=MCP_PROTOCOL_VERSION,
            )

        if not has_request_id:
            return Response(status_code=202)
        query_params = QueryParams(request.scope.get("query_string", b""))
        requested_mode = query_params.get("tool_mode", request.headers.get("x-gate-tool-mode"))
        header_mode = request.headers.get("x-gate-tool-mode")
        from lingshu_gate.authorization_discovery import discovery_setting, principal_authorization

        authorization = principal_authorization(principal) if path == "/mcp" else None
        def saved_preferences(actor: AuthPrincipal) -> dict[str, Any]:
            key = principal_authorization(actor)
            if key is None or key != authorization:
                raise AccessDeniedError("authorization changed", required_access="invoke", granted_access="none")
            with access_store.database.session() as connection:
                return discovery_setting(connection, *key)

        def saved_mode(actor: AuthPrincipal) -> str:
            return str(saved_preferences(actor)["tool_discovery_mode"])

        # 每条业务授权决定工具呈现；旧客户端参数与请求头（含重复、冲突或未知值）均忽略。
        # Console 会话与管理资源沿用其既有请求级校验合同。
        mode = saved_mode(principal) if authorization else requested_mode or "direct"
        invalid_request_mode = not authorization and (
            len(query_params.getlist("tool_mode")) > 1 or len(request.headers.getlist("x-gate-tool-mode")) > 1
            or requested_mode is not None and requested_mode != mode
            or header_mode is not None and header_mode != mode)
        if (mode not in {"direct", "on_demand"} or invalid_request_mode
                or mode == "on_demand" and (path != "/mcp" or catalog is None)):
            return _error_response(request_id, -32602, "Unsupported or conflicting tool_mode", settings,
                status_code=400, protocol_version=protocol_context.protocol_version)
        def require_current_mode(request: Request) -> AuthPrincipal:
            current = require_mcp_viewer(request)
            if authorization and saved_mode(current) != mode:
                raise AccessDeniedError("discovery mode changed before dispatch", required_access="invoke", granted_access="none")
            return current

        preferences: dict[str, Any] = saved_preferences(principal) if authorization else {"tool_discovery_mode": mode, "pinned_tools": [], "result_budget": {"enabled": False}}
        budget_enabled = bool(authorization and preferences["result_budget"]["enabled"])
        call_params = message.get("params")
        if method == "tools/call" and isinstance(call_params, dict) and call_params.get("name") == RESULT_TOOL and path == "/mcp":
            try:
                if not budget_enabled:
                    raise result_cache.unavailable()
                query = ResultRead.model_validate(call_params.get("arguments", {}))
                result = await run_in_threadpool(_read_saved_result, result_cache, request, require_current_mode, query)
                result = OfficialSdkTypesAdapter.call_tool(result, server_name=SERVER_NAME,
                    server_version=settings.version, protocol_version=protocol_context.protocol_version)
                return _result_response(request_id, result, settings, protocol_version=protocol_context.protocol_version)
            except ValidationError:
                protocol_outcome("invalid")
                return _tool_error(request_id, "Invalid saved-result parameters", settings,
                    structured_content={"error": {"code": "result_parameters_invalid"}}, protocol_context=protocol_context)
            except ToolExecutionError as exc:
                protocol_outcome(exception_outcome(exc))
                return _tool_error(request_id, exc.message, settings,
                    structured_content={"error": {"code": exc.code}}, protocol_context=protocol_context)
            except AccessDeniedError:
                protocol_outcome("denied")
                return _tool_error(request_id, "The saved result is unavailable", settings,
                    structured_content={"error": {"code": "result_unavailable"}}, protocol_context=protocol_context)

        if mode == "on_demand" and method in {"tools/list", "tools/call"}:
            assert catalog is not None
            try:
                catalog.check_namespace()
                if method == "tools/list":
                    pins = await run_in_threadpool(project_pins, catalog, principal, preferences)
                    tools = [*catalog_tools(), *(pin.payload for pin in pins), *([result_read_tool()] if budget_enabled else [])]
                    result = OfficialSdkTypesAdapter.list_tools(tools, server_name=SERVER_NAME,
                        server_version=settings.version, protocol_version=protocol_context.protocol_version)
                    return _result_response(request_id, result, settings, protocol_version=protocol_context.protocol_version)
                params = message.get("params")
                if (not isinstance(params, dict) or not isinstance(params.get("name"), str)
                        or params["name"] not in CATALOG_TOOL_NAMES and not params["name"].startswith("gate_pinned_")
                        or not isinstance(params.get("arguments", {}), dict)):
                    return _error_response(request_id, -32602, "Select a catalog entry with object arguments", settings,
                        status_code=400, protocol_version=protocol_context.protocol_version)
                target = None
                business = params["name"] == "gate_tool_invoke" or params["name"] not in CATALOG_TOOL_NAMES
                if params["name"] in CATALOG_TOOL_NAMES:
                    if budget_enabled and business:
                        from lingshu_gate.tool_catalog import CatalogInvoke

                        selected = CatalogInvoke.model_validate(params.get("arguments", {}))
                        target = await run_in_threadpool(result_cache.capture, principal, selected.tool_ref,
                            instance_id=selected.instance_id, session_id=selected.session_id, revision=selected.schema_revision)
                    invocation = await run_in_threadpool(_call_catalog_authenticated, catalog, request,
                        require_current_mode, params["name"], params.get("arguments", {}))
                else:
                    invocation, target = await run_in_threadpool(_call_pin_authenticated, catalog, request,
                        require_current_mode, params["name"], params.get("arguments", {}), result_cache if budget_enabled else None)
            except ValidationError:
                protocol_outcome("invalid")
                return _tool_error(request_id, "Invalid catalog parameters", settings,
                    structured_content={"error": {"code": "catalog_parameters_invalid"}}, protocol_context=protocol_context)
            except ToolExecutionError as exc:
                protocol_outcome(exception_outcome(exc))
                return _tool_error(request_id, exc.message, settings, structured_content=exc.to_payload(),
                    protocol_context=protocol_context)
            except AccessDeniedError:
                protocol_outcome("denied")
                return _tool_error(request_id, "The selected tool is unavailable", settings,
                    structured_content={"error": {"code": "catalog_tool_unavailable"}}, protocol_context=protocol_context)
            if not invocation.ok:
                return _tool_error(request_id, invocation.error or "Tool invocation failed", settings,
                    structured_content=invocation.output or None, protocol_context=protocol_context)
            result = (_normalize_tool_result(invocation.output) if business else
                      {"content": [], "structuredContent": invocation.output, "isError": False})
            if budget_enabled and business:
                result = await run_in_threadpool(_budget_result, result_cache, result, request, require_current_mode, target)
            result = OfficialSdkTypesAdapter.call_tool(result, server_name=SERVER_NAME,
                server_version=settings.version, protocol_version=protocol_context.protocol_version)
            return _result_response(request_id, result, settings, protocol_version=protocol_context.protocol_version)
        if protocol_context.protocol_version in GATEWAY_HANDSHAKE_VERSIONS:
            if method == "initialize":
                return _result_response(
                    request_id,
                    OfficialSdkTypesAdapter.initialize(
                        capability_policy,
                        protocol_version=protocol_context.protocol_version,
                        server_name=SERVER_NAME,
                        server_version=settings.version,
                        instructions=GATEWAY_INSTRUCTIONS,
                        client_capabilities=protocol_context.client_capabilities,
                    ),
                    settings,
                    protocol_version=protocol_context.protocol_version,
                )
            if method == "ping":
                return _result_response(
                    request_id, {}, settings,
                    protocol_version=protocol_context.protocol_version,
                )
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
            # 工具发现也包含同步 SQLite 对账和权限读取，复用调用路径的线程池以免阻塞协议事件循环。
            try:
                # 发现与调用必须使用同一全局命名规则，隐藏的冲突也不能产生可列出却不可调用的工具。
                namespace = ToolNamespace(registry.list_definitions())
                definitions = await run_in_threadpool(
                    access_store.visible_tools, principal,
                    [entry.definition for entry in namespace.entries],
                )
                tools = [item[1] for item in _gateway_tools(registry, definitions, namespace=namespace)]
                if budget_enabled:
                    tools.append(result_read_tool())
            except ToolNamespaceCollisionError as exc:
                return _namespace_collision_response(request_id, exc, settings, protocol_context,
                    disclose_name=await run_in_threadpool(_can_disclose_collision, exc, registry, access_store, principal))
            result = OfficialSdkTypesAdapter.list_tools(
                tools,
                server_name=SERVER_NAME,
                server_version=settings.version,
                protocol_version=protocol_context.protocol_version,
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
                request,
                require_current_mode,
                result_cache if budget_enabled else None,
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
    request: Request,
    require_principal: Callable[[Request], AuthPrincipal],
    result_cache: ResultCache | None = None,
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
        protocol_outcome("invalid")
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
        return _namespace_collision_response(request_id, exc, settings, protocol_context,
                    disclose_name=await run_in_threadpool(_can_disclose_collision, exc, registry, access_store, principal))
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
        target = await run_in_threadpool(result_cache.capture, principal, definition.id) if result_cache else None
        invocation = await run_in_threadpool(
            _invoke_authenticated_tool,
            request,
            require_principal,
            access_store,
            registry,
            definition.id,
            arguments,
            target.revision if target else None,
        )
    except AccessDeniedError as exc:
        protocol_outcome("denied")
        return _tool_error(
            request_id,
            f"Access denied: {exc.reason}",
            settings,
            protocol_context=protocol_context,
        )
    except ToolNotFoundError:
        protocol_outcome("invalid")
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
    if result_cache:
        result = await run_in_threadpool(_budget_result, result_cache, result, request, require_principal, target)
    result = OfficialSdkTypesAdapter.call_tool(
        result,
        server_name=SERVER_NAME,
        server_version=settings.version,
        protocol_version=protocol_context.protocol_version,
    )
    return _result_response(
        request_id,
        result,
        settings,
        protocol_version=protocol_context.protocol_version,
    )


def _invoke_authenticated_tool(request: Request, require_principal: Callable[[Request], AuthPrincipal],
                               access_store: AccessControlStore, registry: ToolRegistry,
                               tool_id: str, arguments: dict[str, Any], expected_revision: str | None = None) -> ToolInvokeResponse:
    # Re-read the inbound credential in the dispatch thread after body parsing
    # and thread-pool admission. Never use a handshake/session-cached principal.
    principal = require_principal(request)

    def guard() -> None:
        from lingshu_gate.tool_catalog import _same_invocation_principal

        # 下游等待连接锁期间可能撤权或收紧配额，实际派发前重新读取入站凭据。
        current = require_principal(request)
        if (not _same_invocation_principal(current, principal)
                or not access_store.evaluate(current, registry.get_definition(tool_id))["allowed"]):
            raise AccessDeniedError("authorization changed before dispatch", required_access="invoke", granted_access="none")

    options: dict[str, Any] = {"dispatch_guard": guard, "correlation_id": request_correlation(request)}
    if expected_revision is not None:
        options["expected_definition_revision"] = expected_revision
    return access_store.invoke_tool(registry, principal, tool_id, arguments, **options)


def _read_saved_result(cache: ResultCache, request: Request, require_principal: Callable[[Request], AuthPrincipal],
                       query: ResultRead) -> dict[str, Any]:
    return cache.read(require_principal(request), request.headers.get("authorization", ""), query,
                      refresh_principal=lambda: require_principal(request))


def _budget_result(cache: ResultCache, result: dict[str, Any], request: Request,
                   require_principal: Callable[[Request], AuthPrincipal], target: ResultTarget | None) -> dict[str, Any]:
    try:
        return cache.apply(result, require_principal(request), request.headers.get("authorization", ""), target,
                           refresh_principal=lambda: require_principal(request))
    except (HTTPException, AccessDeniedError, ToolExecutionError):
        # The business call already completed. A changed preference/credential must
        # never create a cache entry or cause the original operation to be replayed.
        return result


def _call_pin_authenticated(catalog: ToolCatalog, request: Request,
                            require_principal: Callable[[Request], AuthPrincipal], name: str,
                            arguments: dict[str, Any], cache: ResultCache | None) -> tuple[ToolInvokeResponse, ResultTarget | None]:
    from lingshu_gate.authorization_discovery import discovery_setting, principal_authorization

    principal = require_principal(request)
    authorization = principal_authorization(principal)
    if not authorization:
        raise ToolExecutionError("catalog_tool_unavailable", "The selected tool is unavailable.")
    with catalog.database.session() as connection:
        setting = discovery_setting(connection, *authorization)
    pin = next((item for item in project_pins(catalog, principal, setting) if item.payload["name"] == name), None)
    if pin is None:
        raise ToolExecutionError("catalog_tool_unavailable", "The selected tool is unavailable.")
    selected = pin.invocation(arguments)

    def refresh() -> AuthPrincipal:
        current = require_principal(request)
        with catalog.database.session() as connection:
            latest = discovery_setting(connection, *authorization)
        if latest["discovery_revision"] != setting["discovery_revision"] or {"kind": pin.kind, "tool_ref": pin.tool_ref} not in latest["pinned_tools"]:
            raise ToolExecutionError("catalog_tool_unavailable", "The selected tool is unavailable.")
        return current

    target = cache.capture(principal, selected.tool_ref, instance_id=selected.instance_id,
                           session_id=selected.session_id, revision=selected.schema_revision) if cache else None
    with invocation_entry("pin"):
        return (catalog.invoke(principal, selected, refresh_principal=refresh,
                               correlation_id=request_correlation(request)), target)


def _call_catalog_authenticated(catalog: ToolCatalog, request: Request,
                                require_principal: Callable[[Request], AuthPrincipal],
                                name: str, arguments: dict[str, Any]) -> ToolInvokeResponse:
    with invocation_entry("catalog"):
        return catalog.call(name, arguments, require_principal(request),
            refresh_principal=lambda: require_principal(request),
            correlation_id=request_correlation(request))


def _gateway_tools(
    registry: ToolRegistry,
    definitions: list[ToolDefinition] | None = None,
    *,
    namespace: ToolNamespace | None = None,
) -> list[tuple[str, dict[str, Any], ToolDefinition]]:
    """把当前 Registry 快照转换为稳定、唯一且符合 MCP 命名约束的工具列表。"""

    namespace = namespace or ToolNamespace(registry.list_definitions())
    visible_ids = {definition.id for definition in definitions} if definitions is not None else None
    tools: list[tuple[str, dict[str, Any], ToolDefinition]] = []
    for entry in namespace.entries:
        definition = entry.definition
        if visible_ids is not None and definition.id not in visible_ids:
            continue
        payload: dict[str, Any] = {
            "name": entry.wire_name,
            "title": definition.name,
            "description": definition.description,
            "inputSchema": definition.input_schema or {"type": "object", "properties": {}},
            "annotations": _tool_annotations(definition),
        }
        output_schema = definition.metadata.get("outputSchema", definition.metadata.get("output_schema"))
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
    outcome: str = "error",
) -> JSONResponse:
    protocol_outcome(outcome)
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
            protocol_version=protocol_context.protocol_version,
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
    if result.get("isError") is True:
        protocol_outcome("error")
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
    protocol_outcome("invalid" if code in {-32700, -32600, -32601, -32602} else "error")
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


def _can_disclose_collision(
    exc: ToolNamespaceCollisionError, registry: ToolRegistry,
    access_store: AccessControlStore, principal: AuthPrincipal,
) -> bool:
    try:
        definitions = [registry.get_definition(tool_id) for tool_id in exc.tool_ids]
        visible = access_store.visible_tools(principal, definitions)
        return {definition.id for definition in visible} == set(exc.tool_ids)
    except ToolNotFoundError:
        return False


def _namespace_collision_response(
    request_id: Any,
    exc: ToolNamespaceCollisionError,
    settings: Settings,
    protocol_context: HttpProtocolContext,
    *,
    disclose_name: bool = True,
) -> JSONResponse:
    return _error_response(
        request_id,
        -32603,
        "MCP tool namespace is ambiguous; tool discovery and calls are disabled",
        settings,
        # Do not disclose the colliding Registry ids: one of them may be hidden
        # from the current principal by access policy.
        data={"wireName": exc.wire_name} if disclose_name else None,
        status_code=500,
        protocol_version=protocol_context.protocol_version,
    )

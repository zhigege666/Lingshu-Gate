"""Tests for the Gate MCP gateway and its system-debug tool."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from lingshu_gate import __version__
from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.models import McpServerListResponse, ToolDefinition
from lingshu_gate.protocol.tool_namespace import ToolNamespaceCollisionError
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolExecutionError, ToolRegistry
from lingshu_gate.system_debug import (
    SYSTEM_DEBUG_TOOL_ID,
    SystemDebugService,
    register_system_debug_tool,
)
from lingshu_gate.mcp_gateway import (
    _gateway_tools,
    register_mcp_gateway_route,
)
from lingshu_gate.transports.http import build_protocol_request


class FakeRuntime:
    def list_servers(self) -> McpServerListResponse:
        return McpServerListResponse(servers=[], load_errors=[])


class FakeObservabilityStore:
    def list_logs(self, **kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "level": kwargs.get("level") or "error",
                "server_id": kwargs.get("server_id") or "sample-service",
                "message": "request failed with Bearer abc.def password=visible",
                "payload": {"api_key": "secret-value", "nested": {"password": "hidden"}},
            }
        ]

    def list_events(self, **kwargs: object) -> list[dict[str, object]]:
        return [{"type": kwargs.get("event_type") or "gate.server.failed", "payload": {"token": "hidden"}}]


def allow_viewer(_: Request) -> AuthPrincipal:
    return AuthPrincipal(id="test", username="viewer", role="viewer")


def allow_operator(_: Request) -> AuthPrincipal:
    return AuthPrincipal(id="operator", username="operator", role="operator")


def deny_operator(_: Request) -> AuthPrincipal:
    raise HTTPException(status_code=403, detail="insufficient role")


class FakeAccessStore:
    def visible_tools(
        self,
        principal: AuthPrincipal,
        definitions: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if principal.role == "viewer":
            return [item for item in definitions if item.id == SYSTEM_DEBUG_TOOL_ID]
        return definitions

    def invoke_tool(
        self,
        registry: ToolRegistry,
        principal: AuthPrincipal,
        tool_id: str,
        arguments: dict[str, object],
    ):
        if principal.role == "viewer" and tool_id != SYSTEM_DEBUG_TOOL_ID:
            raise AccessDeniedError(
                "write access is required",
                required_access="write",
                granted_access="read",
            )
        return registry.invoke(tool_id, arguments)


class SystemDebugServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(system_debug_mcp_enabled=True)
        self.registry = ToolRegistry()
        self.service = SystemDebugService(
            self.settings,
            self.registry,
            FakeRuntime(),  # type: ignore[arg-type]
            FakeObservabilityStore(),  # type: ignore[arg-type]
        )

    def test_logs_are_redacted(self) -> None:
        result = self.service.invoke({"action": "logs", "server_id": "sample-service", "limit": 20})

        self.assertEqual(result["logs"][0]["payload"]["api_key"], "[REDACTED]")
        self.assertEqual(result["logs"][0]["payload"]["nested"]["password"], "[REDACTED]")
        self.assertEqual(
            result["logs"][0]["message"],
            "request failed with Bearer [REDACTED] password=[REDACTED]",
        )

    def test_invalid_limit_and_action_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit must be between"):
            self.service.invoke({"action": "logs", "limit": 201})
        with self.assertRaisesRegex(ValueError, "Unsupported action"):
            self.service.invoke({"action": "shell"})

    def test_setting_defaults_enabled_and_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(Settings.from_env().mcp_gateway_enabled)
            self.assertTrue(Settings.from_env().system_debug_mcp_enabled)
        with patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_MCP_GATEWAY_ENABLED": "false",
                "LINGSHU_GATE_SYSTEM_DEBUG_MCP_ENABLED": "false",
            },
            clear=True,
        ):
            self.assertFalse(Settings.from_env().mcp_gateway_enabled)
            self.assertFalse(Settings.from_env().system_debug_mcp_enabled)


class McpGatewayProtocolTest(unittest.TestCase):
    def _app(
        self,
        *,
        gateway_enabled: bool = True,
        debug_enabled: bool = True,
        operator_allowed: bool = True,
        business_error_tool: bool = False,
    ) -> FastAPI:
        settings = Settings(
            mcp_gateway_enabled=gateway_enabled,
            system_debug_mcp_enabled=debug_enabled,
        )
        registry = ToolRegistry()
        service = SystemDebugService(
            settings,
            registry,
            FakeRuntime(),  # type: ignore[arg-type]
            FakeObservabilityStore(),  # type: ignore[arg-type]
        )
        if debug_enabled:
            register_system_debug_tool(registry, service)
        registry.register(
            ToolDefinition(
                id="test.echo",
                name="Echo",
                description="Echo a message.",
                permission="read",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
                source="test",
            ),
            lambda arguments: {"message": arguments.get("message", "")},
        )
        registry.register(
            ToolDefinition(
                id="mcp.sample-service.search_parameters",
                name="搜索参数",
                description="Search parameters.",
                permission="mcp",
                input_schema={"type": "object", "properties": {}},
                source="mcp",
                metadata={
                    "annotations": {"readOnlyHint": True, "destructiveHint": False},
                },
            ),
            lambda _: {
                "content": [{"type": "text", "text": "matched"}],
                "structuredContent": {"count": 1},
                "isError": False,
            },
        )
        if business_error_tool:
            def reject(_: dict[str, object]) -> dict[str, object]:
                raise ToolExecutionError(
                    "demo_conflict",
                    "demo business conflict",
                    retryable=True,
                    next_action="retry later",
                    details={"resource_id": "demo"},
                )

            registry.register(
                ToolDefinition(
                    id="test.fail",
                    name="Fail",
                    description="Return a structured business error.",
                    permission="write",
                    input_schema={"type": "object"},
                    source="test",
                ),
                reject,
            )
        app = FastAPI()
        # 单元测试直接调用路由端点时不会经过 FastAPI 依赖注入，因此保存等价测试身份供 _post 显式传入。
        app.state.test_principal = (
            AuthPrincipal(id="operator", username="operator", role="operator")
            if operator_allowed
            else AuthPrincipal(id="test", username="viewer", role="viewer")
        )
        register_mcp_gateway_route(
            app,
            settings,
            registry,
            FakeAccessStore(),  # type: ignore[arg-type]
            allow_operator if operator_allowed else allow_viewer,
        )
        return app

    def _post(
        self,
        app: FastAPI,
        message: dict[str, object],
        headers: dict[str, str] | None = None,
    ):
        method = message.get("method")
        if isinstance(method, str) and message.get("jsonrpc") == "2.0":
            params = message.get("params")
            request_params, protocol_headers = build_protocol_request(
                method,
                params if isinstance(params, dict) else None,
                client_name="gate-gateway-test",
                client_version="1.0",
            )
            message = {**message, "params": request_params}
            headers = {**protocol_headers, **(headers or {})}
        body = json.dumps(message).encode("utf-8")
        sent = False

        async def receive() -> dict[str, object]:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request_headers = {"content-type": "application/json", **(headers or {})}
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [
                    (name.lower().encode("ascii"), value.encode("ascii"))
                    for name, value in request_headers.items()
                ],
            },
            receive,
        )
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/mcp")
        return asyncio.run(endpoint(request, app.state.test_principal))

    @staticmethod
    def _json(response) -> dict[str, object]:
        return json.loads(response.body.decode("utf-8"))

    def test_discover_and_tools_list(self) -> None:
        app = self._app()
        discovered = self._post(
            app,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {},
            },
        )
        tools = self._post(
            app,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

        self.assertEqual(discovered.status_code, 200)
        discovery = self._json(discovered)["result"]
        self.assertEqual(discovery["supportedVersions"], [MCP_PROTOCOL_VERSION])
        self.assertEqual(
            discovery["_meta"]["io.modelcontextprotocol/serverInfo"]["name"],
            "lingshu_gate",
        )
        self.assertEqual(
            [item["name"] for item in self._json(tools)["result"]["tools"]],
            [
                "gate_system_debug",
                "mcp__sample-service__search_parameters",
                "test__echo",
            ],
        )
        self.assertTrue(self._json(tools)["result"]["tools"][0]["annotations"]["readOnlyHint"])
        self.assertTrue(self._json(tools)["result"]["tools"][2]["annotations"]["readOnlyHint"])

    def test_fastapi_dependency_injection_reaches_gateway(self) -> None:
        params, headers = build_protocol_request(
            "server/discover",
            {},
            client_name="gate-gateway-test",
            client_version="1.0",
        )
        with TestClient(self._app()) as client:
            response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "server/discover",
                    "params": params,
                },
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["supportedVersions"], [MCP_PROTOCOL_VERSION])

    def test_tools_call_returns_structured_content(self) -> None:
        response = self._post(
            self._app(),
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "gate_system_debug", "arguments": {"action": "overview", "limit": 10}},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._json(response)["result"]["isError"])
        self.assertEqual(self._json(response)["result"]["structuredContent"]["service"]["version"], __version__)

    def test_registry_tool_call_is_routed_and_wrapped(self) -> None:
        response = self._post(
            self._app(),
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "test__echo", "arguments": {"message": "hello"}},
            },
        )

        result = self._json(response)["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"message": "hello"})

    def test_registry_business_error_is_returned_as_structured_tool_error(self) -> None:
        response = self._post(
            self._app(business_error_tool=True),
            {
                "jsonrpc": "2.0",
                "id": 51,
                "method": "tools/call",
                "params": {"name": "test__fail", "arguments": {}},
            },
        )

        result = self._json(response)["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["error"]["code"], "demo_conflict")
        self.assertTrue(result["structuredContent"]["error"]["retryable"])
        self.assertEqual(result["structuredContent"]["error"]["next_action"], "retry later")

    def test_downstream_mcp_result_is_preserved(self) -> None:
        response = self._post(
            self._app(),
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "mcp__sample-service__search_parameters",
                    "arguments": {},
                },
            },
        )

        result = self._json(response)["result"]
        self.assertEqual(result["content"][0]["text"], "matched")
        self.assertEqual(result["structuredContent"], {"count": 1})

    def test_viewer_cannot_call_non_debug_tool(self) -> None:
        response = self._post(
            self._app(operator_allowed=False),
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "test__echo", "arguments": {}},
            },
        )
        result = self._json(response)["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Access denied", result["content"][0]["text"])

    def test_viewer_can_still_call_system_debug(self) -> None:
        response = self._post(
            self._app(operator_allowed=False),
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "gate_system_debug", "arguments": {"action": "overview"}},
            },
        )
        self.assertFalse(self._json(response)["result"]["isError"])

    def test_disabled_endpoint_returns_not_found(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._post(
                self._app(gateway_enabled=False),
                {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_debug_tool_can_be_disabled_without_disabling_gateway(self) -> None:
        response = self._post(
            self._app(debug_enabled=False),
            {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}},
        )
        names = [item["name"] for item in self._json(response)["result"]["tools"]]
        self.assertNotIn("gate_system_debug", names)
        self.assertIn("test__echo", names)

    def test_gateway_tool_names_are_unique_and_bounded(self) -> None:
        registry = ToolRegistry()
        for tool_id in ("collision.a.b", "collision.a__b", "long." + "x" * 180):
            registry.register(
                ToolDefinition(
                    id=tool_id,
                    name=tool_id,
                    description="collision test",
                    permission="read",
                    input_schema={"type": "object"},
                ),
                lambda _: {},
            )

        with self.assertRaises(ToolNamespaceCollisionError):
            _gateway_tools(registry)

    def test_invalid_jsonrpc_request(self) -> None:
        response = self._post(self._app(), {"jsonrpc": "2.0", "id": 4})
        self.assertEqual(self._json(response)["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()

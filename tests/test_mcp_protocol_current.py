"""Current MCP 2026-07-28 protocol contract."""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.mcp_http_client import (
    McpHttpAuthenticationError,
    StreamableHttpMcpClient,
)
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import McpProtocolError, StdioMcpClient
from lingshu_gate.models import ToolDefinition
from lingshu_gate.protocol.capabilities import (
    GatewayCapabilityPolicy,
    intersect_capabilities,
)
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.transports.http import (
    build_protocol_request,
    decode_header_value,
    encode_header_value,
)
from lingshu_gate.transports.oauth import (
    McpOAuthDiscoveryBoundary,
    OAuthProtectedResourceMetadata,
    register_oauth_protected_resource_routes,
    with_mcp_auth_challenge,
)


class _AccessStore:
    def __init__(self) -> None:
        self.invocations: list[tuple[str, dict[str, object]]] = []

    def visible_tools(
        self,
        principal: AuthPrincipal,
        definitions: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        del principal
        return definitions

    def invoke_tool(
        self,
        registry: ToolRegistry,
        principal: AuthPrincipal,
        tool_id: str,
        arguments: dict[str, object],
    ):
        del principal
        self.invocations.append((tool_id, arguments))
        return registry.invoke(tool_id, arguments)


def _allow(_: Request) -> AuthPrincipal:
    return AuthPrincipal(id="test", username="test", role="admin")


def _deny_401(_: Request) -> AuthPrincipal:
    raise HTTPException(status_code=401, detail="authentication required")


def _deny_403(_: Request) -> AuthPrincipal:
    raise HTTPException(status_code=403, detail="forbidden")


class _HttpJsonResponse:
    def __init__(
        self,
        payload: dict[str, object] | None,
        status: int = 200,
    ) -> None:
        self.status = status
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        self._body = (
            json.dumps(payload).encode("utf-8") if payload is not None else b""
        )

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body)
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk


class GatewayCurrentProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()
        self.registry = ToolRegistry()
        self.registry.register(
            ToolDefinition(
                id="test.echo",
                name="Echo",
                description="Echo an input value.",
                permission="read",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
                source="test",
            ),
            lambda arguments: {"message": arguments.get("message", "")},
        )
        self.app = FastAPI()
        self.access_store = _AccessStore()
        register_mcp_gateway_route(
            self.app,
            self.settings,
            self.registry,
            self.access_store,  # type: ignore[arg-type]
            _allow,
        )

    def _post(
        self,
        message: dict[str, object],
        headers: dict[str, str] | None = None,
    ):
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
        endpoint = next(
            route.endpoint
            for route in self.app.routes
            if getattr(route, "path", None) == "/mcp"
        )
        return asyncio.run(endpoint(request, _allow(request)))

    @staticmethod
    def _json(response) -> dict[str, object]:
        return json.loads(response.body.decode("utf-8"))

    def _current_message(
        self,
        request_id: int,
        method: str,
        params: dict[str, object] | None = None,
        *,
        version: str = MCP_PROTOCOL_VERSION,
    ) -> tuple[dict[str, object], dict[str, str]]:
        current_params, headers = build_protocol_request(
            method,
            params,
            client_name="compat-test",
            client_version="1.0",
            protocol_version=version,
        )
        return (
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": current_params,
            },
            headers,
        )

    def test_discovery_list_and_call_are_stateless(self) -> None:
        discover_message, discover_headers = self._current_message(
            10, "server/discover", {}
        )
        list_message, list_headers = self._current_message(11, "tools/list", {})
        call_message, call_headers = self._current_message(
            12,
            "tools/call",
            {"name": "test__echo", "arguments": {"message": "current"}},
        )

        discovered = self._post(discover_message, discover_headers)
        listed = self._post(list_message, list_headers)
        called = self._post(call_message, call_headers)

        discovery = self._json(discovered)["result"]
        self.assertEqual(discovery["supportedVersions"], [MCP_PROTOCOL_VERSION])
        self.assertEqual(discovery["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(discovery["resultType"], "complete")
        self.assertEqual(self._json(listed)["result"]["resultType"], "complete")
        self.assertEqual(self._json(called)["result"]["resultType"], "complete")
        self.assertEqual(
            self._json(called)["result"]["structuredContent"],
            {"message": "current"},
        )

    def test_missing_and_null_tool_arguments_are_empty_objects(self) -> None:
        for request_id, params in (
            (13, {"name": "test__echo"}),
            (14, {"name": "test__echo", "arguments": None}),
        ):
            with self.subTest(params=params):
                message, headers = self._current_message(
                    request_id,
                    "tools/call",
                    params,
                )
                response = self._post(message, headers)
                self.assertEqual(
                    self._json(response)["result"]["structuredContent"],
                    {"message": ""},
                )

        self.assertEqual(
            self.access_store.invocations,
            [("test.echo", {}), ("test.echo", {})],
        )

    def test_non_object_tool_arguments_are_invalid_params_and_never_execute(
        self,
    ) -> None:
        invalid_arguments: tuple[object, ...] = ([], "", 0, False)
        for request_id, arguments in enumerate(invalid_arguments, start=15):
            with self.subTest(arguments=arguments):
                message, headers = self._current_message(
                    request_id,
                    "tools/call",
                    {"name": "test__echo", "arguments": arguments},
                )
                response = self._post(message, headers)
                payload = self._json(response)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(payload["error"]["code"], -32602)

        self.assertEqual(self.access_store.invocations, [])

    def test_array_tool_arguments_are_invalid_params_and_never_execute(
        self,
    ) -> None:
        message, headers = self._current_message(
            19,
            "tools/call",
            {"name": "test__echo", "arguments": []},
        )

        response = self._post(message, headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._json(response)["error"]["code"], -32602)
        self.assertEqual(self.access_store.invocations, [])

    def test_missing_headers_are_rejected(self) -> None:
        response = self._post(
            {"jsonrpc": "2.0", "id": 20, "method": "server/discover", "params": {}}
        )

        payload = self._json(response)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["code"], -32020)

    def test_browser_origin_must_be_explicitly_allowed(self) -> None:
        message, headers = self._current_message(23, "tools/list", {})

        allowed = self._post(
            message,
            {**headers, "Origin": "http://127.0.0.1:8000"},
        )
        rejected = self._post(
            message,
            {**headers, "Origin": "https://untrusted.example.test"},
        )
        malformed = self._post(message, {**headers, "Origin": "null"})

        self.assertEqual(allowed.status_code, 200)
        for response in (rejected, malformed):
            with self.subTest(response=response):
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self._json(response)["error"]["code"], -32023)

    def test_request_id_is_missing_or_a_non_empty_string_or_integer(self) -> None:
        base_message, headers = self._current_message(24, "tools/list", {})
        notification = dict(base_message)
        notification.pop("id")
        self.assertEqual(self._post(notification, headers).status_code, 202)

        string_id = {**base_message, "id": "request-24"}
        self.assertEqual(
            self._json(self._post(string_id, headers))["id"],
            "request-24",
        )

        for invalid_id in (None, "", True, False, 1.5, [], {}):
            with self.subTest(request_id=invalid_id):
                response = self._post({**base_message, "id": invalid_id}, headers)
                self.assertEqual(response.status_code, 200)
                payload = self._json(response)
                self.assertIsNone(payload["id"])
                self.assertEqual(payload["error"]["code"], -32600)

    def test_unknown_version_is_rejected_with_current_supported_version(self) -> None:
        params = {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2099-01-01",
                "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        }
        message = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/list",
            "params": params,
        }
        headers = {
            "MCP-Protocol-Version": "2099-01-01",
            "Mcp-Method": "tools/list",
        }
        response = self._post(message, headers)

        payload = self._json(response)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["code"], -32022)
        self.assertEqual(payload["error"]["data"]["requested"], "2099-01-01")
        self.assertEqual(payload["error"]["data"]["supported"], [MCP_PROTOCOL_VERSION])

    def test_mcp_name_header_mismatch_fails_before_dispatch(self) -> None:
        message, headers = self._current_message(
            22,
            "tools/call",
            {"name": "test__echo", "arguments": {}},
        )
        headers["Mcp-Name"] = "another_tool"
        response = self._post(message, headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._json(response)["error"]["code"], -32020)

    def test_non_ascii_mcp_name_uses_the_required_base64_sentinel(self) -> None:
        encoded = encode_header_value("搜索工具")

        self.assertTrue(encoded.startswith("=?base64?"))
        self.assertTrue(encoded.endswith("?="))
        self.assertEqual(decode_header_value(encoded), "搜索工具")

    def test_collision_disables_discovery_fail_closed(self) -> None:
        self.registry.register(
            ToolDefinition(
                id="test__echo",
                name="Collision",
                description="Collides after public name projection.",
                permission="read",
                input_schema={"type": "object"},
            ),
            lambda _: {},
        )
        message, headers = self._current_message(30, "tools/list", {})
        response = self._post(message, headers)

        payload = self._json(response)
        self.assertEqual(payload["error"]["code"], -32603)
        self.assertEqual(payload["error"]["data"]["wireName"], "test__echo")

    def test_capability_intersection_keeps_only_mutually_supported_values(self) -> None:
        result = intersect_capabilities(
            {"extensions": {"trace": {}, "admin": {}}, "feature": True},
            {"extensions": {"trace": {}, "other": {}}, "feature": False},
        )

        self.assertEqual(result, {"extensions": {"trace": {}}})

        policy = GatewayCapabilityPolicy(
            server_capabilities={
                "tools": {},
                "extensions": {"trace": {}, "admin": {}},
            }
        )
        self.assertEqual(
            policy.advertised_for({"extensions": {"trace": {}, "client-only": {}}}),
            {"tools": {}, "extensions": {"trace": {}}},
        )


class OAuthDiscoveryBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = McpOAuthDiscoveryBoundary(
            OAuthProtectedResourceMetadata(
                resource="https://gate.example.test/mcp",
                authorization_servers=("https://identity.example.test",),
            )
        )

    @staticmethod
    def _request() -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "scheme": "https",
                "server": ("untrusted-host.example", 443),
                "headers": [(b"host", b"untrusted-host.example")],
            }
        )

    def test_metadata_routes_are_registered_only_when_boundary_is_provided(
        self,
    ) -> None:
        app = FastAPI()
        register_oauth_protected_resource_routes(app, self.boundary)
        endpoints = {
            route.path: route.endpoint
            for route in app.routes
            if getattr(route, "path", "").startswith(
                "/.well-known/oauth-protected-resource"
            )
        }

        self.assertEqual(
            set(endpoints),
            {
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-protected-resource/mcp",
            },
        )
        document = asyncio.run(endpoints["/.well-known/oauth-protected-resource/mcp"]())
        self.assertEqual(document["resource"], "https://gate.example.test/mcp")
        self.assertEqual(
            document["authorization_servers"], ["https://identity.example.test"]
        )
        self.assertEqual(document["scopes_supported"], ["tools.read", "tools.invoke"])

    def test_401_has_trusted_discovery_challenge_and_403_does_not_change(self) -> None:
        unauthorized = with_mcp_auth_challenge(_deny_401, self.boundary)
        forbidden = with_mcp_auth_challenge(_deny_403, self.boundary)

        with self.assertRaises(HTTPException) as raised_401:
            unauthorized(self._request())
        self.assertEqual(raised_401.exception.status_code, 401)
        challenge = raised_401.exception.headers["WWW-Authenticate"]
        self.assertIn(
            "https://gate.example.test/.well-known/oauth-protected-resource/mcp",
            challenge,
        )
        self.assertNotIn("untrusted-host.example", challenge)

        with self.assertRaises(HTTPException) as raised_403:
            forbidden(self._request())
        self.assertEqual(raised_403.exception.status_code, 403)
        self.assertFalse(raised_403.exception.headers)

    def test_insecure_non_loopback_metadata_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS outside loopback"):
            OAuthProtectedResourceMetadata(
                resource="http://gate.example.test/mcp",
                authorization_servers=("https://identity.example.test",),
            )


class OutboundHttpSecurityTest(unittest.TestCase):
    def _client(
        self,
        data_dir: Path,
        *,
        protocol_version: str = MCP_PROTOCOL_VERSION,
        headers: dict[str, str] | None = None,
    ) -> StreamableHttpMcpClient:
        manifest = McpServerManifest.model_validate(
            {
                "id": "remote",
                "launch": {"type": "external"},
                "transport": {
                    "type": "streamable_http",
                    "endpoint": "https://mcp.example.test/mcp",
                    "protocol_version": protocol_version,
                    "headers": headers or {},
                },
            }
        )
        return StreamableHttpMcpClient(
            manifest,
            Settings(data_dir=data_dir, mcp_log_payloads=False),
        )

    def test_401_and_403_are_authentication_errors(self) -> None:
        for status in (401, 403):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                client = self._client(Path(directory))
                error = urllib.error.HTTPError(
                    client.endpoint,
                    status,
                    "auth rejected",
                    {},
                    io.BytesIO(b'{"error":"auth rejected"}'),
                )
                with (
                    patch.object(client._opener, "open", side_effect=error) as urlopen,
                    self.assertRaises(McpHttpAuthenticationError),
                ):
                    client.start()
                self.assertEqual(urlopen.call_count, 1)
                self.assertEqual(client.protocol_version, MCP_PROTOCOL_VERSION)

    def test_redirect_is_rejected_without_forwarding_or_retrying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(
                Path(directory),
                headers={"Authorization": "Bearer outbound-secret"},
            )
            client._resolve_headers()
            redirect = urllib.error.HTTPError(
                client.endpoint,
                302,
                "redirect",
                {"Location": "https://untrusted.example.test/mcp"},
                io.BytesIO(b""),
            )

            with (
                patch.object(client._opener, "open", side_effect=redirect) as opened,
                self.assertRaisesRegex(McpProtocolError, "redirects are not allowed"),
            ):
                client.request("tools/list", {})

            opened.assert_called_once()

    def test_json_rpc_auth_error_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            response = _HttpJsonResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": 401, "message": "token rejected"},
                }
            )

            with (
                patch.object(client._opener, "open", return_value=response) as urlopen,
                self.assertRaises(McpProtocolError),
            ):
                client.start()

            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(client.protocol_version, MCP_PROTOCOL_VERSION)

    def test_method_not_found_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            method_not_found = _HttpJsonResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
            with (
                patch.object(client._opener, "open", return_value=method_not_found) as urlopen,
                self.assertRaises(McpProtocolError),
            ):
                client.start()

            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(client.protocol_version, MCP_PROTOCOL_VERSION)

    def test_resolved_http_headers_are_redacted_by_key_and_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authorization = "Bearer outbound-secret"
            client_secret = "opaque-client-secret"
            client = self._client(
                Path(directory),
                protocol_version=MCP_PROTOCOL_VERSION,
                headers={
                    "Authorization": authorization,
                    "X-Client-Secret": client_secret,
                },
            )
            client._resolve_headers()

            redacted = client._redact(
                {
                    "Authorization": authorization,
                    "client_secret": client_secret,
                    "detail": f"upstream echoed {client_secret}",
                }
            )

            self.assertEqual(redacted["Authorization"], "[REDACTED]")
            self.assertEqual(redacted["client_secret"], "[REDACTED]")
            self.assertNotIn(client_secret, redacted["detail"])
            self.assertEqual(client._redact_text(authorization), "[REDACTED]")

    def test_http_error_does_not_echo_a_resolved_header_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client_secret = "opaque-client-secret"
            client = self._client(
                Path(directory),
                protocol_version=MCP_PROTOCOL_VERSION,
                headers={"X-Client-Secret": client_secret},
            )
            error = urllib.error.HTTPError(
                client.endpoint,
                500,
                "upstream failed",
                {},
                io.BytesIO(
                    json.dumps(
                        {"error": {"message": f"rejected {client_secret}"}}
                    ).encode("utf-8")
                ),
            )

            with (
                patch.object(client._opener, "open", side_effect=error),
                self.assertRaises(McpProtocolError) as raised,
            ):
                client.start()

            self.assertNotIn(client_secret, str(raised.exception))
            self.assertIn("[REDACTED]", str(raised.exception))

    def test_default_info_logs_do_not_include_arbitrary_protocol_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(Path(directory))
            stored_logs: list[tuple[str, str, str, dict[str, object]]] = []
            client.log_sink = lambda level, message, event, payload: stored_logs.append(
                (level, message, event, payload)
            )
            business_secret = "arbitrary-business-secret"

            def connect(_: int) -> None:
                client.server_info = {"name": business_secret}
                client.server_capabilities = {business_secret: {}}

            with (
                patch.object(client, "_start_current", side_effect=connect),
                patch(
                    "lingshu_gate.mcp_http_client.log_event"
                ) as emitted_logs,
            ):
                client.start()
                with patch.object(
                    client,
                    "request",
                    side_effect=[
                        {
                            "tools": [
                                {
                                    "name": "echo",
                                    "description": business_secret,
                                }
                            ]
                        },
                        {
                            "content": [{"type": "text", "text": business_secret}],
                            "isError": False,
                        },
                    ],
                ):
                    client.list_tools()
                    client.call_tool("echo", {"value": business_secret})
                client.stop()

            self.assertNotIn(business_secret, repr(emitted_logs.call_args_list))
            self.assertNotIn(business_secret, repr(stored_logs))

class StdioProtocolValidationTest(unittest.TestCase):
    @staticmethod
    def _manifest(protocol_version: str | None) -> McpServerManifest:
        transport: dict[str, object] = {"type": "stdio"}
        if protocol_version is not None:
            transport["protocol_version"] = protocol_version
        return McpServerManifest.model_validate(
            {
                "id": "stdio-test",
                "launch": {"type": "managed_process", "command": "stdio-server"},
                "transport": transport,
            }
        )

    def test_manifest_rejects_every_non_current_protocol_version(self) -> None:
        for protocol_version in ("auto", "2000-01-01", "2099-01-01"):
            with (
                self.subTest(protocol_version=protocol_version),
                self.assertRaisesRegex(ValueError, MCP_PROTOCOL_VERSION),
            ):
                self._manifest(protocol_version)

    def test_stdio_defaults_to_and_accepts_only_current_protocol(self) -> None:
        inherited = self._manifest(None)
        explicit = self._manifest(MCP_PROTOCOL_VERSION)

        self.assertIsNone(inherited.transport.protocol_version)
        self.assertEqual(explicit.transport.protocol_version, MCP_PROTOCOL_VERSION)
        with tempfile.TemporaryDirectory() as directory:
            client = StdioMcpClient(
                inherited,
                Settings(data_dir=Path(directory)),
            )
        self.assertEqual(client.protocol_version, MCP_PROTOCOL_VERSION)


if __name__ == "__main__":
    unittest.main()

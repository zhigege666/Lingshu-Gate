"""End-to-end regressions against the official MCP Python SDK v2."""

from __future__ import annotations

import asyncio
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import httpx2
import uvicorn
from fastapi import FastAPI, Request
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.models import ToolDefinition
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.mcp_gateway import register_mcp_gateway_route


class _AccessStore:
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
        return registry.invoke(tool_id, arguments)


def _allow(_: Request) -> AuthPrincipal:
    return AuthPrincipal(id="sdk-test", username="sdk-test", role="admin")


class OfficialSdkInteropEndToEndTest(unittest.TestCase):
    def test_official_client_discovers_lists_and_calls_gateway_over_asgi(self) -> None:
        app = FastAPI()
        registry = ToolRegistry()
        registry.register(
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
        register_mcp_gateway_route(
            app,
            Settings(),
            registry,
            _AccessStore(),  # type: ignore[arg-type]
            _allow,
        )

        async def scenario() -> None:
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="http://gateway.test",
            ) as http_client:
                async with streamable_http_client(
                    "http://gateway.test/mcp",
                    http_client=http_client,
                    terminate_on_close=False,
                ) as streams:
                    async with ClientSession(*streams) as session:
                        discovery = await session.discover()
                        tools = await session.list_tools()
                        result = await session.call_tool(
                            "test__echo",
                            {"message": "official-client"},
                        )

            self.assertEqual(
                discovery.supported_versions,
                [MCP_PROTOCOL_VERSION],
            )
            self.assertEqual([tool.name for tool in tools.tools], ["test__echo"])
            self.assertFalse(result.is_error)
            self.assertEqual(
                result.structured_content,
                {"message": "official-client"},
            )

        asyncio.run(scenario())

    def test_gateway_client_discovers_lists_and_calls_official_server(self) -> None:
        sdk_server = MCPServer("official-test", version="1.0")

        @sdk_server.tool()
        def echo(message: str) -> dict[str, str]:
            return {"message": message}

        app = sdk_server.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                lifespan="on",
                log_level="critical",
            )
        )
        thread = threading.Thread(
            target=lambda: server.run(sockets=[listener]),
            name="official-mcp-sdk-test",
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)

        try:
            self.assertTrue(server.started, "official SDK test server did not start")
            with tempfile.TemporaryDirectory() as directory:
                manifest = McpServerManifest.model_validate(
                    {
                        "id": "official-sdk",
                        "launch": {"type": "external"},
                        "transport": {
                            "type": "streamable_http",
                            "endpoint": f"http://127.0.0.1:{port}/mcp",
                            "protocol_version": MCP_PROTOCOL_VERSION,
                        },
                    }
                )
                client = StreamableHttpMcpClient(
                    manifest,
                    Settings(data_dir=Path(directory)),
                )
                client.start()
                tools = client.list_tools()
                result = client.call_tool("echo", {"message": "official-server"})
                client.stop()

            self.assertEqual(client.protocol_version, MCP_PROTOCOL_VERSION)
            self.assertEqual(client.server_info["name"], "official-test")
            self.assertEqual([tool["name"] for tool in tools], ["echo"])
            self.assertFalse(result["isError"])
            self.assertEqual(
                result["structuredContent"],
                {"message": "official-server"},
            )
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()

        self.assertFalse(thread.is_alive(), "official SDK test server did not stop")


if __name__ == "__main__":
    unittest.main()

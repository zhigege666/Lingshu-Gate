"""Explicitly started HTTP service for a frozen OpenAPI contract."""
from __future__ import annotations

import asyncio
import hmac
import json
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx2
from jsonschema import Draft202012Validator
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from lingshu_gate import __version__
from lingshu_gate.service_io import ServiceConfigError, bounded, canonical, secret_file, unique_pairs
from lingshu_gate.openapi_contract import OpenApiContract, Operation

MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def scalar(value: Any) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) not in {str, int, float}:
        raise ServiceConfigError("parameter_scalar_required")
    result = str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in result):
        raise ServiceConfigError("parameter_control_character")
    return result


def map_request(operation: Operation, arguments: dict[str, Any]) -> tuple[str, dict[str, str], bytes | None]:
    bounded(arguments)
    if len(canonical(arguments)) > MAX_REQUEST_BYTES or not Draft202012Validator(operation.input_schema).is_valid(arguments):
        raise ServiceConfigError("arguments_invalid")
    path, queries = operation.path, []
    headers = {"Accept": "application/json, text/plain", "Accept-Encoding": "identity"}
    for parameter in operation.parameters:
        kind, name = parameter["in"], parameter["name"]
        section = arguments.get(kind, {})
        if name not in section:
            continue
        value = section[name]
        if kind == "path":
            item = scalar(value)
            if any(c in item for c in ("/", "\\", "%")) or item in {".", ".."}:
                raise ServiceConfigError("path_parameter_unsafe")
            path = path.replace("{" + name + "}", quote(item, safe=""))
        elif kind == "header":
            headers[name] = scalar(value)
        else:
            key = quote(name, safe="")
            if isinstance(value, list):
                items = [scalar(item) for item in value]
                if not items:
                    queries.append(key + "=")
                elif parameter["explode"]:
                    queries.extend(key + "=" + quote(item, safe="") for item in items)
                else:
                    if any("," in item for item in items):
                        raise ServiceConfigError("query_comma_element_unsupported")
                    queries.append(key + "=" + ",".join(quote(item, safe="") for item in items))
            else:
                queries.append(key + "=" + quote(scalar(value), safe=""))
    if "{" in path or "}" in path:
        raise ServiceConfigError("path_parameter_mismatch")
    if any(unquote(part) in {".", ".."} for part in path.split("/")) or "//" in path:
        raise ServiceConfigError("path_parameter_unsafe")
    url = operation.base_url + path + ("?" + "&".join(queries) if queries else "")
    target, base = httpx2.URL(url), httpx2.URL(operation.base_url)
    expected_path = base.raw_path.split(b"?", 1)[0].rstrip(b"/") + quote(path, safe="/%:@-._~!$&'()*+,;=").encode("ascii")
    if ((target.scheme, target.host, target.port) != (base.scheme, base.host, base.port)
            or target.raw_path.split(b"?", 1)[0] != expected_path):
        raise ServiceConfigError("prepared_target_changed")
    body = canonical(arguments["body"]) if "body" in arguments else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    return str(target), headers, body


class OpenApiAdapter:
    def __init__(self, contract: OpenApiContract, *, ca_file: Path | None = None, transport: Any = None):
        self.contract = contract
        self.operations = {item.name: item for item in contract.operations}
        self.ssl_context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.transport = transport
        self.slots = asyncio.Semaphore(16)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            operation = self.operations.get(name)
            if operation is None:
                raise ServiceConfigError("operation_contract_unavailable")
            if self.slots.locked():
                raise ServiceConfigError("adapter_busy")
            async with self.slots:
                return await asyncio.wait_for(self._invoke(operation, arguments), timeout=30)
        except ServiceConfigError as error:
            return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text=json.dumps(error.detail()))])
        except (TimeoutError, httpx2.TimeoutException):
            return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text='{"code":"upstream_timeout_result_unknown"}')])
        except (httpx2.HTTPError, OSError, UnicodeError, ValueError, RecursionError):
            return types.CallToolResult(is_error=True, content=[types.TextContent(type="text", text='{"code":"upstream_response_unavailable_result_unknown"}')])

    async def _invoke(self, operation: Operation, arguments: dict[str, Any]) -> types.CallToolResult:
        url, headers, body = map_request(operation, arguments)
        if operation.authentication:
            authentication = operation.authentication
            value = secret_file(Path(self.contract.credential_files[authentication["scheme"]]))
            headers[authentication["header"]] = ("Bearer " if authentication["type"] == "bearer" else "") + value
        async with httpx2.AsyncClient(verify=self.ssl_context, follow_redirects=False, trust_env=False,
                                      timeout=20, transport=self.transport) as client:
            async with client.stream(operation.method, url, headers=headers, content=body) as response:
                if response.status_code >= 300 or response.status_code < 200:
                    raise ServiceConfigError("upstream_http_error_" + str(response.status_code))
                allowed = operation.responses.get(str(response.status_code), operation.responses.get("2XX"))
                if allowed is None:
                    raise ServiceConfigError("upstream_status_not_declared")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ServiceConfigError("upstream_encoding_unsupported")
                data = bytearray()
                async for chunk in response.aiter_bytes(65536):
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise ServiceConfigError("upstream_response_size_limit")
                if not allowed and not data:
                    return types.CallToolResult(content=[])
                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media not in allowed:
                    raise ServiceConfigError("upstream_media_not_declared")
                text = bytes(data).decode("utf-8")
                if media == "text/plain":
                    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
                payload = json.loads(text, object_pairs_hook=unique_pairs)
                bounded(payload, max_nodes=100000)
                structured = payload if isinstance(payload, dict) else {"value": payload}
                return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structured_content=structured)


class ServiceBoundary:
    def __init__(self, app, *, hosts: list[str], origins: list[str], token_file: Path | None):
        self.app, self.hosts, self.origins, self.token_file = app, frozenset(hosts), frozenset(origins), token_file

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, list[str]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.decode("latin1").lower(), []).append(value.decode("latin1"))
        host = headers.get("host", [])
        origin = headers.get("origin", [])
        if len(host) != 1 or host[0].lower() not in self.hosts or origin and (len(origin) != 1 or origin[0] not in self.origins):
            await JSONResponse({"code": "host_or_origin_rejected"}, status_code=403)(scope, receive, send)
            return
        if self.token_file:
            try:
                expected = "Bearer " + secret_file(self.token_file)
                supplied = headers.get("authorization", [])
                valid = len(supplied) == 1 and hmac.compare_digest(supplied[0], expected)
            except (ServiceConfigError, TypeError):
                valid = False
            if not valid:
                await JSONResponse({"code": "authentication_required"}, status_code=401,
                                   headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_openapi_app(contract: OpenApiContract, *, hosts: list[str], origins: list[str] | None = None,
                       token_file: Path | None = None, ca_file: Path | None = None, transport: Any = None):
    adapter = OpenApiAdapter(contract, ca_file=ca_file, transport=transport)

    async def list_tools(ctx, params):
        del ctx, params
        return types.ListToolsResult(tools=[types.Tool(name=item.name, description=item.description,
            input_schema=item.input_schema, annotations=types.ToolAnnotations(read_only_hint=item.method in {"GET", "HEAD"},
                destructive_hint=item.method not in {"GET", "HEAD"}, idempotent_hint=False, open_world_hint=True))
            for item in contract.operations])

    async def call_tool(ctx, params):
        del ctx
        return await adapter.invoke(params.name, params.arguments if params.arguments is not None else {})

    server: Server = Server("Lingshu Gate OpenAPI", version=__version__, on_list_tools=list_tools, on_call_tool=call_tool)
    app = server.streamable_http_app(json_response=True, stateless_http=True, max_request_body_size=MAX_REQUEST_BYTES,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins or []))
    app.add_middleware(ServiceBoundary, hosts=[host.lower() for host in hosts], origins=origins or [], token_file=token_file)
    return app

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest
from starlette.testclient import TestClient

from lingshu_gate.service_io import ServiceConfigError, parse_document
from lingshu_gate.openapi_adapter import OpenApiAdapter, create_openapi_app, map_request
from lingshu_gate.openapi_contract import compile_openapi
from lingshu_gate.transports.http import build_protocol_request


def spec():
    return {"openapi": "3.1.0", "paths": {"/items/{id}": {"parameters": [
        {"in": "path", "name": "id", "required": True, "schema": {"type": "string"}}], "get": {
        "operationId": "get_item", "parameters": [
            {"in": "query", "name": "tags", "schema": {"type": "array", "items": {"type": "string"}}},
            {"in": "header", "name": "X-Test", "schema": {"type": "boolean"}}],
        "responses": {"200": {"description": "Result", "content": {"application/json": {}}}}}}}}


def config():
    return {"schema_version": 1, "base_url": "http://127.0.0.1:18883/api", "operations": ["get_item"]}


def compiled(document=None, settings=None):
    return compile_openapi(document or spec(), settings or config())


def test_request_target_encoding_and_parameter_values():
    operation = compiled().operations[0]
    url, headers, body = map_request(operation, {"path": {"id": "a b"}, "query": {"tags": ["red", "blue"]}, "header": {"X-Test": True}})
    assert url == "http://127.0.0.1:18883/api/items/a%20b?tags=red&tags=blue"
    assert headers["X-Test"] == "true" and body is None
    document = spec()
    document["paths"]["/items/{id}"]["get"]["parameters"][0]["explode"] = False
    op = compiled(document).operations[0]
    assert map_request(op, {"path": {"id": "x"}, "query": {"tags": ["a b", "blue"]}})[0].endswith("tags=a%20b,blue")
    assert map_request(op, {"path": {"id": "x"}, "query": {"tags": []}})[0].endswith("tags=")
    with pytest.raises(ServiceConfigError, match="query_comma_element_unsupported"):
        map_request(op, {"path": {"id": "x"}, "query": {"tags": ["a,b"]}})


@pytest.mark.parametrize("value", ["../admin", "..", "%2e%2e", "x\\y", "/", "x\ny"])
def test_path_arguments_cannot_escape_single_segment(value):
    with pytest.raises(ServiceConfigError):
        map_request(compiled().operations[0], {"path": {"id": value}})


def test_nullable_body_is_distinct_from_absent_and_defaults_are_annotations():
    document = spec()
    document["openapi"] = "3.0.4"
    document["paths"]["/items/{id}"]["get"]["requestBody"] = {"content": {
        "application/json": {"schema": {"type": "string", "nullable": True, "default": "not injected"}}}}
    operation = compiled(document).operations[0]
    assert map_request(operation, {"path": {"id": "x"}})[2] is None
    assert map_request(operation, {"path": {"id": "x"}, "body": None})[2] == b"null"
    with pytest.raises(ServiceConfigError):
        map_request(operation, {"path": {"id": "x"}, "query": {"tags": None}})


@pytest.mark.parametrize("field,value", [("format", "date-time"), ("pattern", ".*"), ("readOnly", True),
    ("writeOnly", False), ("oneOf", [{"type": "string"}]), ("$ref", "https://invalid/schema")])
def test_unsupported_schema_does_not_degrade_to_arbitrary_arguments(field, value):
    document = spec()
    document["paths"]["/items/{id}"]["parameters"][0]["schema"] = {field: value}
    with pytest.raises(ServiceConfigError):
        compiled(document)


@pytest.mark.parametrize("data", [b'{"a":1,"a":2}', b'a: 1\na: 2', b'a: &x [*x]', b'a: !!python/object:bad {}'])
def test_duplicate_keys_and_yaml_aliases_are_rejected(data):
    with pytest.raises(ServiceConfigError):
        parse_document(data)


def test_local_reference_cycles_are_rejected():
    document = spec()
    document["components"] = {"schemas": {"Recursive": {"$ref": "#/components/schemas/Recursive"}}}
    document["paths"]["/items/{id}"]["parameters"][0]["schema"] = {"$ref": "#/components/schemas/Recursive"}
    with pytest.raises(ServiceConfigError, match="schema_reference_cycle"):
        compiled(document)


def test_security_override_and_credential_binding(tmp_path):
    document = spec()
    document["components"] = {"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}}
    document["security"] = [{"key": []}]
    settings = config()
    settings["credentials"] = {"key": {"type": "api_key", "reference": "test-api", "token_file": str(tmp_path / "secret")}}
    operation = compiled(document, settings).operations[0]
    assert operation.authentication["header"] == "X-Api-Key"
    document["paths"]["/items/{id}"]["get"]["security"] = []
    with pytest.raises(ServiceConfigError, match="unused_credentials_rejected"):
        compiled(document, settings)
    settings.pop("credentials")
    assert compiled(document, settings).operations[0].authentication is None


@pytest.mark.parametrize("change", ["method", "path", "origin", "credential"])
def test_changed_execution_mapping_invalidates_old_name_before_any_request(change, tmp_path):
    original = compiled()
    document, settings = spec(), config()
    if change == "method":
        document["paths"]["/items/{id}"]["delete"] = document["paths"]["/items/{id}"].pop("get")
    elif change == "path":
        document["paths"]["/other/{id}"] = document["paths"].pop("/items/{id}")
    elif change == "origin":
        settings["base_url"] = "http://127.0.0.1:18884/api"
    else:
        document["components"] = {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}
        document["security"] = [{"bearer": []}]
        settings["credentials"] = {"bearer": {"type": "bearer", "reference": "first", "token_file": str(tmp_path / "token")}}
    changed = compiled(document, settings)
    assert original.operations[0].name != changed.operations[0].name
    counter = []
    def sentinel(request):
        counter.append(request)
        return httpx2.Response(200, json={})
    result = asyncio.run(OpenApiAdapter(changed, transport=httpx2.MockTransport(sentinel)).invoke(original.operations[0].name, {"path": {"id": "x"}}))
    assert result.is_error and "operation_contract_unavailable" in result.content[0].text
    assert counter == []


def test_http_adapter_mcp_calls_and_redirects_never_replay():
    document = spec()
    document["paths"]["/items/{id}"]["get"]["parameters"][0]["explode"] = False
    contract = compiled(document)
    seen = []
    def upstream(request):
        seen.append(request)
        if request.url.path.endswith("redirect"):
            return httpx2.Response(307, headers={"Location": "https://elsewhere.invalid/sentinel"})
        return httpx2.Response(200, json={"wire_path": request.url.raw_path.decode()})
    app = create_openapi_app(contract, hosts=["127.0.0.1:18881"], transport=httpx2.MockTransport(upstream))
    with TestClient(app, base_url="http://127.0.0.1:18881") as client:
        def rpc(method, params=None):
            prepared, headers = build_protocol_request(method, params, client_name="adapter test", client_version="1")
            return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared}).json()
        tools = rpc("tools/list")["result"]["tools"]
        assert [t["name"] for t in tools] == [contract.operations[0].name]
        arguments = {"path": {"id": "a b"}, "query": {"tags": ["a b", "blue"]}}
        result = rpc("tools/call", {"name": tools[0]["name"], "arguments": arguments})["result"]
        assert result["structuredContent"]["wire_path"] == "/api/items/a%20b?tags=a%20b,blue"
        result = rpc("tools/call", {"name": tools[0]["name"], "arguments": {"path": {"id": "redirect"}}})["result"]
        assert result["isError"] and len(seen) == 2
        assert client.post("/mcp", headers={"Origin": "https://evil.invalid"}).status_code == 403


def test_legacy_numeric_exclusive_bound_normalizes_and_parameter_inheritance():
    document = spec()
    document["openapi"] = "3.0.4"
    document["paths"]["/items/{id}"]["get"]["parameters"].append({"in": "path", "name": "id", "required": True,
        "schema": {"type": "number", "minimum": 1, "exclusiveMinimum": True}})
    operation = compiled(document).operations[0]
    with pytest.raises(ServiceConfigError):
        map_request(operation, {"path": {"id": 1}})
    assert map_request(operation, {"path": {"id": 1.5}})[0].endswith("/items/1.5")


def test_invalid_argument_json_has_safe_error():
    result = asyncio.run(OpenApiAdapter(compiled()).invoke(compiled().operations[0].name, {"path": {"id": None}}))
    assert result.is_error and json.loads(result.content[0].text)["code"] == "arguments_invalid"


@pytest.mark.parametrize("template,value", [("/..{id}/sentinel", ""), ("/.{id}/sentinel", "."), ("/{id}./sentinel", ".")])
def test_complete_prepared_path_cannot_escape_base_path(template, value):
    document = spec()
    document["paths"][template] = document["paths"].pop("/items/{id}")
    with pytest.raises(ServiceConfigError):
        map_request(compiled(document).operations[0], {"path": {"id": value}})


def test_reference_expansion_cannot_create_unbounded_tool_metadata():
    document = {"openapi": "3.1.0", "components": {"schemas": {"shared": {
        "type": "string", "description": "d" * 8192, "default": "v" * 16384}}}, "paths": {}}
    for index in range(200):
        document["paths"][f"/items{index}/{{id}}"] = {"get": {"operationId": f"item{index}", "parameters": [
            {"in": "path", "name": "id", "required": True, "schema": {"$ref": "#/components/schemas/shared"}}],
            "responses": {"200": {"description": "result", "content": {"text/plain": {}}}}}}
    settings = {**config(), "operations": [f"item{i}" for i in range(200)]}
    with pytest.raises(ServiceConfigError, match="compiled_tools_size_limit"):
        compiled(document, settings)

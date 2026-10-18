"""Compile a deliberately finite OpenAPI subset into immutable MCP contracts."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from lingshu_gate.service_io import ServiceConfigError, bounded, canonical, digest, fixed_url

SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "items", "enum", "const", "minimum",
               "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems",
               "minProperties", "maxProperties", "description", "title", "default"}
TYPES = {"string", "integer", "number", "boolean", "array", "object", "null"}
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
RESERVED_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "host", "connection",
                    "content-length", "content-type", "accept", "accept-encoding", "transfer-encoding", "te",
                    "trailer", "upgrade", "proxy-connection", "keep-alive"}
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}")


def require(value: bool, code: str, location: str = "") -> None:
    if not value:
        raise ServiceConfigError(code, location)


class SchemaCompiler:
    def __init__(self, document: dict[str, Any]):
        self.document = document
        version = document.get("openapi", "")
        require(isinstance(version, str) and bool(re.fullmatch(r"3\.[01]\.[0-9]+", version)), "openapi_version_unsupported")
        self.legacy = version.startswith("3.0.")
        require(document.get("jsonSchemaDialect", "https://spec.openapis.org/oas/3.1/dialect/base") in {
            "https://spec.openapis.org/oas/3.1/dialect/base", "https://json-schema.org/draft/2020-12/schema"},
            "schema_dialect_unsupported")
        self.nodes = 0

    def schema(self, raw: Any, location: str, stack: tuple[str, ...] = ()) -> dict[str, Any]:
        self.nodes += 1
        require(self.nodes <= 10000 and len(stack) <= 32, "schema_complexity_limit", location)
        require(isinstance(raw, dict), "schema_object_required", location)
        if "$ref" in raw:
            ref = raw["$ref"]
            require(len(raw) == 1 and isinstance(ref, str) and ref.startswith("#/components/schemas/"), "schema_reference_unsupported", location)
            require(ref not in stack, "schema_reference_cycle", location)
            target: Any = self.document
            try:
                for key in ref[2:].split("/"):
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                raise ServiceConfigError("schema_reference_missing", location) from None
            return self.schema(target, location, (*stack, ref))
        value = copy.deepcopy(raw)
        if self.legacy:
            nullable = value.pop("nullable", False)
            require(type(nullable) is bool, "schema_nullable_invalid", location)
            if nullable:
                require(isinstance(value.get("type"), str) and value["type"] != "null", "schema_nullable_requires_type", location)
                value["type"] = [value["type"], "null"]
            for side in ("Minimum", "Maximum"):
                exclusive = "exclusive" + side
                if exclusive in value:
                    flag = value.pop(exclusive)
                    require(type(flag) is bool and type(value.get(side.lower())) in {int, float}, "schema_exclusive_bound_invalid", location)
                    if flag:
                        value[exclusive] = value.pop(side.lower())
        require(not set(value) - SCHEMA_KEYS, "schema_keyword_unsupported", location)
        for annotation in ("description", "title"):
            if annotation in value:
                require(isinstance(value[annotation], str) and len(value[annotation]) <= 8192, "schema_annotation_limit", location)
        kind = value.get("type")
        if kind is not None:
            kinds = kind if isinstance(kind, list) else [kind]
            require(1 <= len(kinds) <= 2 and all(isinstance(k, str) and k in TYPES for k in kinds)
                    and len(set(kinds)) == len(kinds) and (len(kinds) == 1 or "null" in kinds), "schema_type_unsupported", location)
        if "properties" in value:
            require(isinstance(value["properties"], dict) and len(value["properties"]) <= 256, "schema_properties_invalid", location)
            value["properties"] = {key: self.schema(item, location + "/properties/" + key, (*stack, "property:" + key))
                                   for key, item in value["properties"].items()}
        if "items" in value:
            value["items"] = self.schema(value["items"], location + "/items", (*stack, "items"))
        if "additionalProperties" in value and type(value["additionalProperties"]) is not bool:
            value["additionalProperties"] = self.schema(value["additionalProperties"], location + "/additionalProperties", (*stack, "additional"))
        if "enum" in value:
            require(isinstance(value["enum"], list) and 1 <= len(value["enum"]) <= 100, "schema_enum_limit", location)
        try:
            Draft202012Validator.check_schema(value)
        except (SchemaError, TypeError):
            raise ServiceConfigError("schema_invalid", location) from None
        return value


@dataclass(frozen=True)
class Operation:
    name: str
    operation_id: str
    description: str
    method: str
    base_url: str
    path: str
    parameters: tuple[dict[str, Any], ...]
    input_schema: dict[str, Any]
    responses: dict[str, list[str]]
    authentication: dict[str, str] | None
    contract_digest: str


@dataclass(frozen=True)
class OpenApiContract:
    operations: tuple[Operation, ...]
    source_digest: str
    credential_files: dict[str, str]

    def preview(self) -> dict[str, Any]:
        return {"schema_version": 1, "source_digest": self.source_digest, "operations": [
            {"name": item.name, "operation_id": item.operation_id, "method": item.method, "path": item.path,
             "contract_digest": item.contract_digest, "input_schema": item.input_schema,
             "required_credential": item.authentication, "review_required": True}
            for item in self.operations]}


def _parameters(compiler: SchemaCompiler, path_item: dict[str, Any], operation: dict[str, Any], path: str) -> tuple[dict[str, Any], ...]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for layer in (path_item.get("parameters", []), operation.get("parameters", [])):
        require(isinstance(layer, list) and len(layer) <= 128, "parameters_invalid", path)
        seen = set()
        for raw in layer:
            require(isinstance(raw, dict) and not set(raw) - {"name", "in", "description", "required", "deprecated",
                    "style", "explode", "schema", "example", "examples"}, "parameter_unsupported", path)
            kind, name = raw.get("in"), raw.get("name")
            require(kind in {"path", "query", "header"} and isinstance(name, str) and 1 <= len(name) <= 128,
                    "parameter_name_or_location_invalid", path)
            require(not any(ord(c) < 33 for c in name), "parameter_name_invalid", path)
            key = kind, name.casefold() if kind == "header" else name
            require(key not in seen, "parameter_duplicate", path)
            seen.add(key)
            required = raw.get("required", False)
            require(type(required) is bool, "parameter_required_invalid", path)
            schema = compiler.schema(raw.get("schema"), path + "/parameters/" + name)
            schema_type = schema.get("type")
            require(isinstance(schema_type, str) and schema_type in {"string", "integer", "number", "boolean", "array"},
                    "parameter_type_unsupported", path)
            explode = raw.get("explode", kind == "query")
            require(type(explode) is bool, "parameter_explode_invalid", path)
            if kind == "query":
                require(raw.get("style", "form") == "form", "query_style_unsupported", path)
                if schema_type == "array":
                    require(schema.get("items", {}).get("type") in {"string", "integer", "number", "boolean"}, "query_array_type_unsupported", path)
            else:
                require(schema_type != "array" and raw.get("style", "simple") == "simple" and not explode,
                        "parameter_serialization_unsupported", path)
                if kind == "path":
                    require(required, "path_parameter_must_be_required", path)
                else:
                    require(bool(HEADER_NAME.fullmatch(name)) and name.casefold() not in RESERVED_HEADERS,
                            "header_parameter_reserved", path)
            result[key] = {"in": kind, "name": name, "required": required, "explode": explode, "schema": schema}
    required_paths = re.findall(r"\{([^{}]+)\}", path)
    require(len(required_paths) == len(set(required_paths)) and set(required_paths) == {p["name"] for p in result.values() if p["in"] == "path"},
            "path_parameter_mismatch", path)
    return tuple(result[key] for key in sorted(result))


def _authentication(document: dict[str, Any], operation: dict[str, Any], credentials: dict[str, Any], path: str) -> dict[str, str] | None:
    security = operation.get("security", document.get("security", []))
    require(isinstance(security, list) and len(security) <= 1, "security_requirement_unsupported", path)
    if not security:
        return None
    require(isinstance(security[0], dict) and len(security[0]) == 1, "security_requirement_unsupported", path)
    name, scopes = next(iter(security[0].items()))
    require(scopes == [], "security_scopes_unsupported", path)
    scheme = document.get("components", {}).get("securitySchemes", {}).get(name)
    require(isinstance(scheme, dict), "security_scheme_missing", path)
    if scheme.get("type") == "http" and scheme.get("scheme", "").casefold() == "bearer":
        require(not set(scheme) - {"type", "scheme", "bearerFormat", "description"}, "security_scheme_unsupported", path)
        kind, header = "bearer", "Authorization"
    elif scheme.get("type") == "apiKey" and scheme.get("in") == "header":
        require(not set(scheme) - {"type", "in", "name", "description"}, "security_scheme_unsupported", path)
        kind, header = "api_key", scheme.get("name", "")
        require(isinstance(header, str) and bool(HEADER_NAME.fullmatch(header)) and header.casefold() not in RESERVED_HEADERS,
                "security_header_reserved", path)
    else:
        raise ServiceConfigError("security_scheme_unsupported", path)
    binding = credentials.get(name)
    require(isinstance(binding, dict) and set(binding) == {"type", "reference", "token_file"}, "credential_binding_required", path)
    assert isinstance(binding, dict)
    require(binding["type"] == kind and isinstance(binding["reference"], str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", binding["reference"]))
            and isinstance(binding["token_file"], str) and bool(binding["token_file"]), "credential_binding_invalid", path)
    return {"scheme": name, "type": kind, "reference": binding["reference"], "header": header}


def _compile_openapi(document: dict[str, Any], config: dict[str, Any]) -> OpenApiContract:
    bounded(document)
    bounded(config)
    require(len(canonical(document)) <= 2 * 1024 * 1024 and len(canonical(config)) <= 65536, "document_size_limit")
    require(not set(config) - {"schema_version", "base_url", "operations", "credentials", "allow_private_http"}
            and type(config.get("schema_version")) is int and config["schema_version"] == 1, "adapter_config_invalid")
    require(type(config.get("allow_private_http", False)) is bool, "adapter_config_invalid")
    base = fixed_url(config.get("base_url", ""), private_http=config.get("allow_private_http", False))
    selection, credentials = config.get("operations"), config.get("credentials", {})
    require(isinstance(selection, list) and 1 <= len(selection) <= 200 and all(isinstance(i, str) for i in selection)
            and len(set(selection)) == len(selection) and isinstance(credentials, dict), "operation_selection_invalid")
    assert isinstance(selection, list)
    assert isinstance(credentials, dict)
    compiler = SchemaCompiler(document)
    require(not document.get("webhooks"), "webhooks_unsupported")
    servers = document.get("servers", [])
    require(isinstance(servers, list) and all(isinstance(s, dict) and not s.get("variables") for s in servers), "server_variables_unsupported")
    paths = document.get("paths")
    require(isinstance(paths, dict) and len(paths) <= 1000, "paths_invalid")
    assert isinstance(paths, dict)
    seen, selected, used_credentials = set(), [], set()
    compiled_bytes = 0
    for path, path_item in paths.items():
        require(isinstance(path, str) and path.startswith("/") and "//" not in path and "\\" not in path and "%" not in path
                and "?" not in path and "#" not in path and not any(ord(c) < 33 for c in path)
                and not any(p in {".", ".."} for p in path.split("/")), "operation_path_invalid")
        require(isinstance(path_item, dict) and not set(path_item) - (METHODS | {"parameters", "summary", "description"}), "path_item_unsupported", path)
        literal_path = re.sub(r"\{[^{}]+\}", "parameter", path)
        require("{" not in literal_path and "}" not in literal_path, "path_template_invalid", path)
        for method, raw in path_item.items():
            if method not in METHODS:
                continue
            require(isinstance(raw, dict), "operation_invalid", path)
            operation_id = raw.get("operationId")
            require(isinstance(operation_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", operation_id)), "operation_id_invalid", path)
            require(operation_id not in seen, "operation_id_duplicate", path)
            seen.add(operation_id)
            if operation_id not in selection:
                continue
            require(not set(raw) - {"operationId", "summary", "description", "tags", "deprecated", "parameters", "requestBody", "responses", "security", "externalDocs"},
                    "operation_field_unsupported", path)
            parameters = _parameters(compiler, path_item, raw, path)
            input_schema: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
            required_sections = []
            for kind in ("path", "query", "header"):
                values = [p for p in parameters if p["in"] == kind]
                if not values:
                    continue
                section = {"type": "object", "properties": {p["name"]: p["schema"] for p in values}, "additionalProperties": False}
                required = [p["name"] for p in values if p["required"]]
                if required:
                    section["required"] = required
                    required_sections.append(kind)
                input_schema["properties"][kind] = section
            if "requestBody" in raw:
                body = raw["requestBody"]
                require(isinstance(body, dict) and not set(body) - {"description", "required", "content"}, "request_body_unsupported", path)
                content = body.get("content")
                require(isinstance(content, dict) and set(content) == {"application/json"}
                        and isinstance(content["application/json"], dict) and not set(content["application/json"]) - {"schema", "example", "examples"}, "request_media_unsupported", path)
                require(type(body.get("required", False)) is bool, "request_body_required_invalid", path)
                input_schema["properties"]["body"] = compiler.schema(content["application/json"].get("schema"), path + "/requestBody")
                if body.get("required"):
                    required_sections.append("body")
            if required_sections:
                input_schema["required"] = required_sections
            responses = raw.get("responses")
            require(isinstance(responses, dict), "responses_required", path)
            response_types = {}
            for status, response in responses.items():
                if not re.fullmatch(r"2[0-9]{2}|2XX", str(status)):
                    continue
                require(isinstance(response, dict) and not set(response) - {"description", "content", "headers"}, "response_unsupported", path)
                content = response.get("content", {})
                require(isinstance(content, dict) and set(content) <= {"application/json", "text/plain"}, "response_media_unsupported", path)
                response_types[str(status)] = sorted(content)
            require(bool(response_types), "success_response_required", path)
            authentication = _authentication(document, raw, credentials, path)
            if authentication:
                used_credentials.add(authentication["scheme"])
                require(not any(p["in"] == "header" and p["name"].casefold() == authentication["header"].casefold() for p in parameters), "credential_header_conflict", path)
            executable = {"schema_version": 1, "method": method.upper(), "base_url": base, "path": path,
                          "parameters": parameters, "input_schema": input_schema, "responses": responses,
                          "authentication": authentication}
            revision = digest(executable)
            name = operation_id[:57] + "__" + revision
            description = raw.get("description", raw.get("summary", operation_id))
            require(isinstance(description, str) and len(description) <= 8192, "operation_description_limit", path)
            tool_bytes = len(canonical({"name": name, "description": description, "inputSchema": input_schema}))
            compiled_bytes += tool_bytes
            require(tool_bytes <= 128 * 1024 and compiled_bytes <= 4 * 1024 * 1024, "compiled_tools_size_limit", path)
            selected.append(Operation(name, operation_id, description, method.upper(), base, path, parameters,
                                      input_schema, response_types, authentication, revision))
    require(set(selection) <= seen, "selected_operation_missing")
    require(set(credentials) == used_credentials, "unused_credentials_rejected")
    require(len({item.name for item in selected}) == len(selected), "tool_name_collision")
    return OpenApiContract(tuple(selected), digest(document), {name: credentials[name]["token_file"] for name in used_credentials})


def compile_openapi(document: dict[str, Any], config: dict[str, Any]) -> OpenApiContract:
    try:
        return _compile_openapi(document, config)
    except ServiceConfigError:
        raise
    except (TypeError, KeyError, AttributeError, ValueError, RecursionError):
        raise ServiceConfigError("openapi_document_invalid") from None

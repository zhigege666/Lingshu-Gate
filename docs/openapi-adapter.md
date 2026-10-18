# Expose selected OpenAPI operations as MCP tools

[简体中文](zh-CN/openapi-adapter.md) · [Documentation index](README.md)

The adapter compiles a local OpenAPI snapshot and an explicit operation allowlist into MCP tools. It runs separately from Gate, which connects to it as an external Streamable HTTP server and keeps its normal classification and authorization workflow.

## Validate a fixed contract

The [minimal schema](../examples/openapi/status.openapi.yaml) and [adapter configuration](../examples/openapi/adapter.json) select one operation against a placeholder HTTPS service. Replace the base URL with your actual service; the example does not start an HTTP API for you.

~~~bash
lingshu-gate openapi validate --schema examples/openapi/status.openapi.yaml --config examples/openapi/adapter.json
~~~

Validation reads local files only. The result shows each generated name, operation ID, method/path, input schema, required credential reference and contract digest; it does not execute the operation. A missing selected operation, unknown option, unsupported schema or unused credential binding is rejected.

Configuration fields are `schema_version: 1`, `base_url`, `operations`, optional `credentials` and optional `allow_private_http`. `operations` contains 1–200 unique operation IDs. The configured base URL is authoritative; server variables and remote schema retrieval are not supported. Remote APIs require HTTPS; loopback HTTP is allowed, and literal private-IP HTTP requires explicit opt-in.

## Bind credentials and serve

For an OpenAPI Bearer security scheme named `serviceAuth`:

~~~json
{
  "serviceAuth": {
    "type": "bearer",
    "reference": "status-service",
    "token_file": "/run/gate-adapter/status-token"
  }
}
~~~

Place this object under `credentials` and select only operations that use that scheme. A header API-key scheme uses `type: "api_key"`. Files must meet the same owner-only POSIX / verifiable Windows ACL boundary as the [connector](private-connector.md). This local secret is separate from the optional inbound MCP token and Gate's credential database.

Run the validated snapshot:

~~~bash
lingshu-gate openapi serve --schema examples/openapi/status.openapi.yaml --config examples/openapi/adapter.json --host 127.0.0.1 --port 18881
~~~

Use `uv run lingshu-gate` from source. Gate connects using [the adapter manifest](../examples/mcp.d/openapi.yaml). Save, apply, start, review and publish the new tools, then grant the caller access.

For non-loopback listening, add **`--tls-cert`, `--tls-key`, `--token-file` and exact `--allowed-host`**. `--allowed-host` and `--allowed-origin` may repeat. `--ca-file` supplies the upstream API CA; it does not replace the listener's certificate. Keep upstream and inbound tokens independent. Do not expose an unauthenticated listener remotely.

## Contract and supported subset

Tool names contain a bounded operation-ID prefix and a SHA-256 execution-contract digest. Base URL, method/path, parameter, response or credential-reference changes produce a new identity and require discovery/review. Rotating a token file's contents does not move authority to another reference. The adapter has no background schema refresh.

Selected-tool authorization snapshots do not transfer to the new tool identity. After review/publication, an existing continuous policy may include it only within previously confirmed service/access scopes, current account permissions and the same service lifecycle. A changed trust target requires reconfirmation.

Supported OpenAPI versions are **3.0.x and 3.1.x**, with this deliberately limited subset:

- Path, query and header parameters using supported explicit serialization, and `application/json` request bodies.
- Local, non-cyclic `#/components/schemas/…` references; primitive/object/array schemas and the supported type, property, required, enum/const, bounds, length and item/property count keywords.
- OpenAPI 3.0 nullable and exclusive bounds normalized into the compiled schema.
- Declared successful JSON, text/plain or empty responses. Response media/status are checked; this is not general response-schema validation.
- Bearer and header API-key authentication through fixed file bindings.

Remote/cyclic references, composition keywords outside the supported subset, arbitrary schema dialects, OAuth negotiation, cookies, form/multipart uploads, callbacks and webhooks are not supported. Unsupported input fails with a structured code instead of being silently ignored.

Input documents are bounded to **2 MiB**, adapter configuration to **64 KiB**, each generated tool to **128 KiB** and all tool definitions to **4 MiB**. Invocation uses a fixed destination, no redirects, no environment proxy, no Cookie reuse, at most **16 concurrent operations**, a **30-second timeout** and **8 MiB response limit**. Path/query values cannot replace the fixed origin or escape its base path. A failed or timed-out request is never automatically replayed; reconcile writes before retrying.

The upstream API's own authorization remains necessary. Gate annotations and generated tools do not themselves grant access. For a runnable local gateway demonstration without an upstream API, use [First call](first-call.md).

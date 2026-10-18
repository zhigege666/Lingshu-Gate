# Standard metrics and tracing

[简体中文](zh-CN/telemetry.md) · [Documentation index](README.md)

Gate can expose process-local Prometheus aggregates and export standard OTLP/HTTP protobuf traces to your existing observability service. Metrics and traces are independent and **disabled by default**. Neither requires a GitHub Traffic collector or a client plugin.

## Configure the Gate process

Set `LINGSHU_GATE_TELEMETRY` to a JSON object, then restart Gate. For metrics only:

~~~bash
export LINGSHU_GATE_TELEMETRY='{"metrics_enabled":true}'
~~~

For metrics and traces:

~~~bash
export LINGSHU_GATE_TELEMETRY='{"metrics_enabled":true,"traces_enabled":true,"otlp_endpoint":"https://telemetry.example/v1/traces","otlp_token_file":"/run/gate/otlp-token","otlp_ca_file":"/run/gate/telemetry-ca.pem","sample_ratio":1.0}'
~~~

| Field | Default | Contract |
|---|---|---|
| `metrics_enabled` | `false` | Boolean; aggregate metrics in this process |
| `traces_enabled` | `false` | Boolean; create the private SDK/export thread during application lifespan |
| `otlp_endpoint` | Empty | Required when tracing; complete endpoint path, remote HTTPS or explicit loopback HTTP |
| `otlp_token_file` | Unset | Absolute file containing the optional collector Bearer token |
| `otlp_ca_file` | Unset | Absolute PEM CA file; otherwise normal certificate verification |
| `sample_ratio` | `1.0` | Finite number from 0 to 1 |

Unknown fields, duplicate JSON keys and invalid values stop configuration loading with a fixed error. Endpoints cannot contain user credentials, query strings or fragments. Gate does not append `/v1/traces` or discover a collector. Enabling telemetry does not add or trigger business retries; the existing single read-only session-recovery retry remains unchanged.

POSIX token files must be regular files owned by the running user with no group/other permissions (`0400` or `0600`). Windows requires a verifiable restricted ACL. Token files are protected local plaintext; they are not automatically stored in Gate's encrypted credential database.

Compose templates explicitly pass the variable through. Put the same single-quoted JSON in the deployment's environment file. Mount token/CA files read-only at the exact container paths using an override, for example:

~~~yaml
services:
  core:
    volumes:
      - /srv/gate/otlp-token:/run/gate/otlp-token:ro
      - /srv/gate/telemetry-ca.pem:/run/gate/telemetry-ca.pem:ro
~~~

For the token, make its host owner match Core UID `10001` and its permissions `0400`. A default `0444` Docker secret does not satisfy this exporter token boundary. Do not mount a secret simply to enable metrics: metrics alone needs no exporter credential.

## Scrape and inspect status

| Endpoint | Response |
|---|---|
| `GET /v1/observability/metrics` | Prometheus text format 0.0.4, `Cache-Control: no-store` |
| `GET /v1/observability/telemetry` | Safe queue/export status JSON, `Cache-Control: no-store` |

Both require real Gate authentication and **both `operations.manage` and `observability.read.all`**, within the caller's token/delegated scopes. Disabled metrics return 404 before authentication; status returns 404 when both features are disabled. Disabling Gate authentication does not expose global telemetry.

Use a dedicated credential restricted to the two required scopes. It is **not a globally read-only credential**: `operations.manage` also permits existing operational writes. Keep the scraping endpoint inside the deployment's private control-plane boundary. External MCP OAuth credentials do not become valid REST credentials.

## Read the measurements

| Metric family | Meaning |
|---|---|
| `gate_http_total` / `gate_http_duration_seconds` | Completed HTTP requests; fixed route template, method and outcome |
| `gate_tool_total` / `gate_tool_duration_seconds` | Logical tool invocations entering Access; entry, transport and outcome |
| `gate_execution_total` / `gate_execution_duration_seconds` | Actual handler/downstream attempts; initial/retry, transport and outcome |
| `gate_telemetry_pending`, `gate_telemetry_inflight` | Accepted spans queued or being exported |
| `gate_telemetry_spans_total` | HTTP-accepted, failed or dropped span counts |
| `gate_telemetry_traces_ready`, `gate_telemetry_shutdown_timed_out` | Trace readiness and bounded shutdown status |

Duration families are histograms in seconds. Counters reset with the process. A rejected logical call can have no execution; a recovered read can have two execution attempts but one successful logical call. MCP protocol errors and `isError` responses remain errors even with HTTP 200. Do not add these three kinds of counts together.

Unknown routes use `unmatched` and unknown methods `other`. Tools, users, service IDs, credentials, arguments, results, URLs and correlation IDs are not metric labels. Standard spans use fixed phase names and a small attribute allowlist, with no automatic exception text, stack trace, request body, query, token or result recording. Gate's separate invocation-retention settings continue to govern audit payloads.

## Trace context and failure behavior

Gate accepts a single bounded W3C `traceparent` and injects the current traceparent into direct Streamable HTTP downstream calls. It does not forward `baggage` or `tracestate`. A single UUID or 32-hex `X-Correlation-ID` is shared with invocation audits and returned in the response; invalid or duplicate values are replaced. Header configuration cannot override Gate-owned context headers. A service hop may terminate propagation according to its own supported header contract.

One instance owns its SDK provider; Gate does not set a global OTel provider or use environment exporter endpoints, credentials, proxy, CA, resource or sampler settings. The standard SDK's `OTEL_SDK_DISABLED=true` still disables tracing and is reported as `sdk_environment_disabled`; this is not silently reported as ready.

The fixed queue bound is **1,024 pending plus inflight spans**, with batches of **64** and a **one-second** schedule. A full queue drops new observations and increments a counter. Network failures, bad collector responses and initialization failures do not reject, replay or alter business calls. Check the status endpoint's fixed failure code.

The exporter uses certificate verification, no redirects, no ambient proxy/netrc, no Cookie reuse and a two-second HTTP timeout configuration. That setting is not a strict DNS/wall-clock deadline. Gate waits at most one second for trace shutdown, then reports a timeout; shutdown is best effort and can lose queued observations.

`export_accepted_spans` means an HTTP 2xx response was accepted. It does not prove durable storage, and this implementation does not interpret an OTLP `partial_success` response body. Configure retention, dashboards and alerts in the external observability service.

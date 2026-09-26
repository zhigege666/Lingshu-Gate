# Operations

[简体中文](zh-CN/operations.md) · [Documentation index](README.md)

Operate Lingshu Gate from evidence: health probes for service state, server status for downstream state, structured events for transitions, logs for diagnostics, and invocation audits for access decisions.

## Probe semantics

| Endpoint | Answers | Should trigger |
|---|---|---|
| `/healthz` | Can the process and HTTP stack respond? | Process restart after a bounded failure threshold |
| `/startupz` | Did application initialization finish? | Keep traffic disabled while failing |
| `/readyz` | Can core storage and request paths serve? | Remove the instance from routing while failing |

Probe requests should use short timeouts and should not require a downstream server to be healthy. Monitor each downstream server separately.

Example:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/healthz
curl --fail --silent --show-error http://127.0.0.1:8000/startupz
curl --fail --silent --show-error http://127.0.0.1:8000/readyz
```

## Downstream status

Use `/v1/mcp/servers` for the list and `/v1/mcp/servers/{server_id}/detail` for one target. Distinguish:

- configured and enabled state;
- desired lifecycle state;
- observed process or connection state;
- health and last error;
- configuration digest;
- tool discovery count and last refresh result;
- restart history for a native managed process.

`desired_state=running` is an instruction, not proof of execution. A running process is not acceptance evidence until discovery succeeds.

The Console service workspace keeps the service directory beside the selected service. Overview, tools, logs, and configuration load independently. Tool visibility counts apply to the signed-in Console identity; they do not confirm the scopes or loaded tool catalog of a separate MCP client.

For bounded detail reads, use `/v1/mcp/servers/{server_id}/detail?section=overview`. Supported sections are `overview`, `tools`, `logs`, `events`, `configuration`, `recovery`, and `cache`. Log, event, and recovery reads accept `limit` from 1 to 200 (default 80); the Console requests 40. Overview reads runtime status only. Cache size is calculated only when the cache section or the complete diagnostic view is requested. Omit `section` to retain the complete legacy response. All sections require the same `operations.manage` permission. Missing section fields mean not requested, not zero or healthy.

## Tool catalog

The Tools page displays cards with search, a searchable MCP service selector, effective read/write filters, and pagination. Service options show the deployment ID as well as its name, so deployments with the same name remain distinct. Operators can select registered services with no visible tools; accounts without runtime management access see only services represented in their visible tool catalog. Built-in tools have a separate filter.

Each card opens full tool details or selects that exact registered tool in the invocation editor. Opening the editor does not execute it and resets arguments and results from the previous tool. Discovery and invocation retain the existing authorization checks.

`/v1/tools` and `/v1/tools/{tool_id}` include a request-local `metadata.gate_access` snapshot with `required_access` and `classification_status`. Read/write badges use this server-side decision rather than MCP annotations or manifest defaults. The snapshot does not mutate registry definitions, publish classifications, or grant access; invocation reevaluates policy at execution time.

## Logs and events

Authenticated operators can query:

- `/v1/logs` and `/v1/logs/stream`;
- `/v1/events` and `/v1/events/stream`.

Logs describe diagnostic records. Events describe state transitions and security-relevant operations. Filter at the server using the documented query parameters and bounded limits rather than downloading the entire store.

Keep `LINGSHU_GATE_LOG_PAYLOADS=false`. Normal records should contain identifiers, state, timing, counts, digests, and redacted metadata—not credentials, authorization headers, uploaded chunks, full tool arguments, or complete process output.

Before sharing a record, inspect nested fields and remove host paths, user data, and downstream content that the recipient does not need.

## Invoking tools from the Console

The invocation workspace selects an MCP service instance first, then a tool from the current identity's visible catalog. Built-in tools have their own group. Service names are supplemented by stable instance IDs; invocation still uses the original registered tool ID and the existing `/v1/invoke` authorization and audit path. No additional polling or privileged service lookup is introduced.

Arguments open in a schema-driven Form view with a JSON alternative. Both views edit the same payload. Field titles, descriptions, required markers, defaults, and examples come from the selected tool's input schema. Documentation is never added to the request. Invalid JSON blocks switching to Form without discarding the input. Unsupported structures remain editable in JSON; editing supported fields preserves undeclared keys and primitive types.

On first selection, declared defaults and examples are prefilled without executing the tool. **Restore defaults** uses defaults and constants only; **Fill example** also uses declared examples. Sensitive fields are excluded from automatic prefill. Missing required values must be supplied manually. Local JSON Schema validation checks supported dialects (draft-07, 2019-09, and 2020-12; 2020-12 when unspecified) before calling the existing API. Remote schema references are not fetched; unsupported or invalid schemas block the call with an error. Backend permissions, confirmations, and downstream validation remain authoritative.

Drafts and results are kept separately by service identity and registered tool ID while the invocation page remains mounted. They are not written to browser storage. Leaving the page or refreshing clears them. Late responses update the original tool's result even after a service switch. A changed schema does not overwrite edited arguments; the page warns and validates against the current definition when running.

## Invocation audit

`/v1/access/invocation-audits` records tool-access decisions. Use it to answer:

- who attempted the call and with which authentication type;
- which server and tool were targeted;
- whether the operation was classified read or write;
- which permission, grant, or token-scope decision allowed or denied it;
- when the decision occurred and how to correlate it with logs and events.

An audit is not a payload archive. Do not enable payload logging to compensate for missing business-level audit fields; add a bounded, redacted field instead.

## Diagnostics

| Endpoint or tool | Use |
|---|---|
| `GET /v1/diagnostics` | Read the current diagnostic snapshot |
| `POST /v1/diagnostics/run` | Run a fresh bounded diagnostic pass |
| `GET /v1/diagnostics/memory` | Inspect process memory summary |
| `GET /v1/runtime/environment` | Inspect platform and available runtime capabilities |
| `gate_system_debug` | Query a bounded read-only overview, server detail, logs, events, or diagnostics through MCP |

Diagnostics do not execute arbitrary shell commands. Treat returned host metadata as operationally sensitive and share only the minimum needed for investigation.

## Runtime cache

`GET /v1/runtime/cache` lists known cache entries and their bounded metadata. `DELETE /v1/runtime/cache/{cache_name}` clears one exact cache entry.

Cache deletion is an operator write:

1. list entries and resolve the exact name;
2. confirm the cache can be recreated;
3. clear only that entry;
4. observe the next request and related events;
5. do not clear persistent data or config directories as a cache workaround.

A cache miss may increase latency or repeat toolchain inspection; it must not bypass validation or authorization.

## Routine checks

### Each day

- verify readiness and disk space;
- inspect new error-level logs and denied invocation audits;
- check downstream targets whose observed state differs from desired state;
- review pending tool-classification changes;
- confirm backups completed without copying live SQLite state.

### Before a change window

- record Gate version and image digest or `BUILD-INFO.json`;
- capture current configuration and data backup hashes;
- inspect active uploads, builds, deployments, and uncertain idempotent operations;
- define success, rollback, and stop conditions;
- choose one read-only post-change tool call.

### After a change

- verify all three probes;
- sign in with a non-administrator account and confirm least privilege;
- inspect database/config load and downstream status;
- execute the selected read-only call;
- confirm audit and event records were written and contain no secrets.

## Incident triage

1. Preserve the current version, configuration digest, relevant IDs, timestamps, and redacted logs.
2. Determine whether impact is Gate-wide, one downstream server, one principal, or one delivery operation.
3. Revoke a specific token or grant when access is the issue; avoid disabling all authentication.
4. Stop a specific downstream process only after resolving the target and impact.
5. For uncertain delivery operations, query their existing IDs before retrying.
6. If credential exposure is possible, rotate the downstream credential and the affected Gate token; do not print the previous value while investigating.
7. Restore only from a verified backup that matches the intended Gate version.

Do not delete databases, volumes, uploads, or operation records as an initial troubleshooting step. Preservation is necessary for recovery and audit.

## Capacity notes

- SQLite is intended for one Gate process and moderate single-host operation.
- Long-running event streams consume connections; set proxy idle behavior intentionally.
- Uploads, build artifacts, logs, and audits grow under the data directory; monitor free space and define retention according to your environment.
- A downstream outage should be isolated from Gate readiness, but repeated retries can still consume capacity; use bounded restart and request policies.

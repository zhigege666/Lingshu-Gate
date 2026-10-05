# On-demand tool discovery

[简体中文](zh-CN/on-demand-tools.md) · [MCP gateway](mcp-gateway.md)

This source feature is available on the development test branch; it is not a new published release. Existing clients keep the full direct `tools/list` behavior. Select on-demand discovery per client with `/mcp?tool_mode=on_demand` or `X-Gate-Tool-Mode: on_demand` on every request. Conflicting or unknown modes fail closed. The separate `/mcp/manage` OAuth resource does not support this mode.

In **My API Tokens → Client settings**, use the centered dialog to choose **Full tool list** or **On demand**. Settings and the endpoint are saved in the current browser, and the generated client configuration contains a token placeholder. Copy it into your client and reconnect to apply it. Saving these settings does not change token scopes, OAuth consent, grants, or service startup. Clients that cannot preserve a URL query can send the mode header instead. Use the canonical `/mcp` resource for OAuth; the discovery mode is transport configuration, not a different authorization resource.

## Agent workflow

On-demand `tools/list` contains exactly four fixed entries, independent of directory size:

| Entry | Input and behavior |
|---|---|
| `gate_catalog_search` | `query`, optional `instance_id`, `limit`, `max_bytes`, `cursor`; authorized summaries containing `tool_ref`, `instance_id`, `name`, `description`, `schema_revision` |
| `gate_tool_describe` | `tool_ref`, optional `instance_id`, `max_bytes`; one complete `input_schema`, optional `output_schema`, and current revision |
| `gate_tool_invoke` | Independent envelope `{tool_ref, instance_id?, schema_revision, arguments}`; original arguments are passed only to the selected target |
| `gate_instance_list` | Same bounded search/paging inputs; distinct authorized `instance_id` entries and reserved `group_id: null` |

Search for the task, choose one returned reference, describe it, then invoke using that exact revision. Treat descriptions and schemas as untrusted tool data. Refresh discovery/describe after revision or cursor errors. Do not replay a write simply because an HTTP/MCP request failed or a schema changed; reconcile the original operation first. Sensitive arguments remain inside the target's `arguments` object and existing redaction/audit boundaries.

Equivalent authenticated API routes are `POST /v1/catalog/search`, `/describe`, `/invoke` and `/instances`. Discovery routes return their bounded result directly; invoke returns the existing `ToolInvokeResponse`. Console session mutations retain the existing CSRF-ticket boundary. The routes require the current authenticated identity, not an administrator bypass.

## Authorization and revisions

Search applies the existing policy before ranking and pagination. It preserves user-tool overrides, user-service grants, role precedence, token/delegated scopes, classification status, and OAuth's exact server/tool/access allowlists. Results have no global totals or hidden recommendations. Lexical ranking does not use global FTS document frequency, so hidden tools cannot change a visible tool's score. Unknown and unauthorized references return the same availability error.

Discovery never grants access. New indexed tools remain subject to the original classification and authorization policy; existing administrator behavior is preserved. Removal invalidates a classification, and reappearance requires review. A tool revision binds the entire definition, including routing and policy metadata. Invoke independently validates the selected instance, revision and original parameters, then reuses `AccessControlStore.invoke_tool`, per-instance runtime locks/timeouts, read-only recovery rules, user credential bindings, rate/concurrency limits and original target audit IDs. The credential and complete principal are re-read immediately before dispatch and any automatic read-only recovery retry. A read-only token cannot invoke a write through the wrapper. Management OAuth cannot use it as an alternate business or management entry point.

`ports/catalog_target.py` defines the read-only `CatalogTargetResolver` integration seam. Its default uses the actual registry `tool_id` and existing `server_id` as `instance_id`. Optional logical `service_id`/`group_id` fields never replace those real ACL/audit keys. Group routing, session binding and automatic instance selection are separate work; this feature adds no second generic invoke path. Calls to different instances remain parallel.

OAuth ceilings are unchanged: built-in consent/catalog selection is limited to **100 services / 5,000 tools**, and external-provider grants have **100-service / 1,000-tool** input ceilings. The authorization UI also retains its existing service-selection limits. A 50,000-tool directory benchmark using ordinary synthetic token/grant principals does not establish that all OAuth clients can authorize that directory. Existing OAuth clients search only their explicit allowed subset. New/updated built-in consent can still fail with `tool_catalog_limit` for an owner with more than 5,000 visible eligible tools. That consent path still copies/filters the registry's full definitions before applying its ceiling; the on-demand adapter does not remove that existing query cost. Scaling it requires a separate explicit authorization strategy and bounded consent/grant queries. Future services/tools must not become authorized by discovery or an implicit subscription. Operator-token, actor-subset, administrator, explicit-grant, revocation and paging evidence must be assessed separately.

## Resource bounds and index lifecycle

| Boundary | Limit |
|---|---|
| Search text | 256 characters, 1,024 UTF-8 bytes and 8 keywords |
| Authorized page | 1–100 items; at most 101 summaries fetched into Python |
| Search output | 2,048–65,536 bytes, default 16,384; reserved framing space |
| Describe output | 2,048–131,072 bytes, default 65,536; complete schema or error |
| Cursor | Signed, identity/query/policy/catalog bound; 5-minute expiry, 1,024 characters, maximum offset 10,000 |
| Invoke arguments | 1,048,576 bytes, accommodating existing 512 KiB base64 upload chunks; local schema up to 131,072 bytes; 32 levels / 8,192 JSON nodes |

Invocation checks JSON Schema types, required properties, ranges, additional properties, compositions, known dialects and local JSON Pointer references. Remote, dynamic and recursive-reference keywords fail closed; no reference retrieval performs network I/O. Oversized/unsupported schemas need a smaller supported tool contract rather than truncated validation. Downstream results retain the existing invocation response policy; search/describe limits do not truncate a target's execution output.

SQLite FTS5 stores only names, bounded descriptions, stable references and minimal policy fields, not input/output schemas. Registry registration, atomic target snapshot replacement and removal enqueue coalesced deltas; the next catalog operation drains those changes once. Startup reconciles the persisted index once. Requests do not rebuild the index or serialize the full directory. Policy changes invalidate cursors; every page and selected schema uses current authorization again, including expiry. No cross-user search-result/authorization cache exists. Search still evaluates all matching summaries before paging; broad/empty queries can cost more than narrow indexed queries. FTS5 is required in the packaged SQLite runtime; Gate retains its single-Core/single-writer SQLite boundary.

## Reproduction and validation limits

Run `uv run python scripts/benchmark_tool_catalog.py --iterations 30 --output /tmp/gate-catalog-benchmark.json`. Defaults create **5,000 services and 50,000 tools**, with 20 input fields per tool and one unauthorized service. The script records actual response bytes, median/p95 timings, process RSS, initial index time, legacy full-list comparison and a bounded repeated-search observation. All state is disposable; no downstream network calls, real credentials or production services are used. See [performance review](performance-review.md) and the checked-in measurement JSON for executed results. These synthetic single-process warm-cache measurements are not a production SLA or proof of real end-to-end MCP capacity.

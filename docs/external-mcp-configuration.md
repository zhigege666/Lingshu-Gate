# External MCP configuration

[简体中文](zh-CN/external-mcp-configuration.md) · [Project delivery](project-delivery.md)

This development addition registers an existing external Streamable HTTP MCP without uploading source, building a package, or starting a process on the remote server. It is separate from ordinary OAuth tool access. Publication and real-peer integration are pending independent review.

## Choose a source

| Source | Path |
|---|---|
| Trusted local project | Deterministic ZIP → upload → preflight/build → deploy/start |
| Explicit HTTPS Git repository | Git plan/import → owned upload → the same build/delivery workflow; a reviewed executor is still missing |
| Existing HTTP MCP endpoint | External configuration plan → confirmed apply → operation status |

The bundled Delivery Skill contains all three routes. Console configuration saves and this workflow use the existing `McpConfigurationService`; the new REST and MCP adapters share one `ExternalMcpConfigurationService`. Existing Console save-only behavior remains separate from explicit connection/discovery choices.

## Authority and input

Use an active Gate administrator's Console session, an explicitly scoped Gate API token, or a separately consented built-in management OAuth connection at `/mcp/manage`. `operations.manage` is required; apply, cancel and an optional remote probe also require `tools.invoke`. Current role permissions, token/family scopes, delegation ceilings, user status and session/token validity are checked again during execution and after lock waits. Management OAuth additionally binds the exact issuer/resource/client/grant/family, consented tool fingerprints and current exact target/create-update policy. Ordinary business OAuth and external-issuer OAuth remain denied. Operations are private to their actor and OAuth connection; an administrator role alone does not upgrade a bearer.

Only `launch.type=external` with `transport.type=streamable_http` is accepted. Unknown fields, commands, working directories, mounts, build metadata, roots, analysis and permission changes are rejected. Use only existing managed credential references in headers, for example `Bearer ${credential:example-binding}`; never provide secret values. New personal credential slots must be configured separately. Existing personal slot declarations can be preserved during update.

New manifests default to `enabled=true`, `auto_start=false`, `startup_policy=gate_start_v1` and a 120-second downstream timeout. Enabled means available for connection; it does not mean connected. Future Gate startup policy is separate from this apply's `connect` choice. HTTPS verification, denied redirects and current endpoint restrictions remain. Private HTTP requires the separately approved exact service/IP/port trust record; planning cannot create or expand trust.

## Plan and apply

| MCP tool | REST route | Purpose |
|---|---|---|
| `gate_mcp_config_plan` | `POST /v1/mcp/external-configs/plan` | Offline precheck and a five-minute plan; optional explicit probe |
| `gate_mcp_config_apply` | `POST /v1/mcp/external-configs/apply` | Confirm the exact plan and queue persistence/optional connection |
| `gate_mcp_config_status` | `GET /v1/mcp/external-configs/operations/{operation_id}` | Actor-owned operation progress and terminal result |
| `gate_mcp_config_status` | `GET /v1/mcp/external-configs/targets/{server_id}` | Redacted configuration and current Gate connection state |
| `gate_mcp_config_cancel` | `POST /v1/mcp/external-configs/operations/{operation_id}/cancel` | Explicit cancellation request; saved configuration remains |

Console session REST writes require the exact Console `Origin`, reject cross-site/`none` fetches, and consume a five-minute single-use CSRF ticket bound to the live Console session, action path and request digest. This shares the OAuth Console Origin/session binding helpers, without enabling OAuth or generating a signing key. Before each plan/apply/cancel POST, obtain `POST /v1/mcp/external-configs/csrf?action=plan|apply|cancel&request_digest=...` with that same Origin; cancel also requires its `operation_id`. The digest is SHA-256 of the UTF-8 JSON body with sorted keys, compact separators and unescaped Unicode. Send the returned `csrf` as `X-CSRF-Token`. Tickets are not cached, expire, and cannot be replayed or moved across sessions/actions/bodies. A transport retry obtains a fresh ticket and retains the original business arguments/idempotency key. Gate API bearer tokens retain their separate authentication/scope checks and do not use browser CSRF tickets. Management OAuth is accepted only through its MCP resource, not these REST routes; the application service enforces the management boundary for both adapters.

Console cookies cannot invoke these four management tools through `/v1/tools/{id}/invoke`, `/v1/invoke`, `/mcp` or any other generic registry entry; this applies to plan/status as well as apply/cancel. Use the dedicated routes above for Console sessions. Ordinary tools and scoped API tokens keep their existing generic entry points.

Credential revision checks run again after runtime/target lock waits and before catalog replacement. Connection/probe reads verify the approved revision against the same encrypted record before decryption. A changed binding returns `external_config_credential_changed`; saved configuration is retained if persistence already occurred. Review a new plan rather than consuming the rotated value under old approval.

1. For create, select an unused target ID. For update, read target status and retain `config_digest`, the SHA-256 of the raw saved file. Do not substitute the canonical digest returned by the older delivery status tool.
2. Call plan with explicit `mode=create|update`, a manifest, and `expected_config_digest` for update. Defaults are `connect=false`, `refresh_tools=false`, `probe=false`. `refresh_tools=true` requires `connect=true`; a requested connection requires an enabled manifest.
3. Offline validation changes no files or registry and contacts no peer. Only separately authorized `probe=true,probe_confirmed=true` initializes/discovers through a temporary session, then closes it; it does not register or grant tools.
4. Review mode, target, the caller-known endpoint, redacted manifest, digests, prior revision, expiry, timeout and exact actions. Update replaces any current Gate connection. Plan responses mask endpoints/headers; masked fields from target status can be preserved on update without reading secrets.
5. Apply with the exact plan ID/digest and action flags, `confirmed=true`, and a fresh idempotency key. The plan binds actor, Console session/API token/delegation or verified management OAuth connection and target-policy revision, normalized manifest, target, prior file digest, credential revisions, action choices and expiry. It is single-use; creation and update use CAS under the existing configuration mutation lock.
6. Poll operation status until `terminal=true`. Retry the same request with the same arguments/key after a transport interruption; never issue another create to repair connection failure. Changed inputs need a new reviewed plan/key.

Connection performs one strict initial discovery and classification reconciliation before registry replacement. When `connect=true,refresh_tools=true`, the refresh result reuses those exact records, snapshot and first new/changed/retired counts; it does not make a second `tools/list` call. It does not publish classifications or expand grants. A successful connection and initial discovery do not establish usable permissions.

## Completion and recovery

Read these fields together:

| Field | Meaning |
|---|---|
| `config_applied` / `config_digest` | Saved file and its revision; unknown after an interrupted completion |
| `connection_state` | This attempt's Gate connection, failure, cleanup or successor ownership |
| `discovery_state` | This operation's observed discovery; target status returns `not_observed` |
| `operation_id` / `terminal` | Durable operation identity and observed completion |
| `cleanup_state` / `requires_reconciliation` | Whether this attempt disconnected cleanly or needs an operator check |

Terminal states are `success`, `partial`, `failed`, `cancelled`, `timed_out`, and `interrupted`. Persistence success plus failed connection is a partial result, with the saved configuration retained. Read target status, then review an update using its current digest. Cancel uses a separate confirmed idempotent write and rechecks the target's terminal state under the queue lock and SQLite writer transaction; `cancel_requested` is not completed cancellation. Failure/cancellation closes only this attempt's Gate HTTP connection, never a successor connection or remote process. Ownership is checked even when no client exists. Interrupted runtime application retains unknown connection/discovery/cleanup and required reconciliation. It does not delete a configuration or grant history or claim that a remote process stopped.

The separate management resource is default-disabled and requires a fresh explicit resource/scope/target consent. See [administrator OAuth configuration](oauth-external-management-design.md). The owner can confirm exact target changes in Gate without changing JWT/family scope ceilings; old plans become stale, and cached-result/status/cancel reads recheck the current connection and actual target. Target changes cannot create credentials, HTTP trust or published classifications. Real-client scope requests and real-peer acceptance remain unverified.

The operation result and idempotency completion commit in one SQLite transaction. Restart, a lost worker or a failed completion transaction becomes `interrupted` with unknown state and required reconciliation. Nothing is replayed, reconnected or stopped automatically during recovery. Configuration files, HTTP state and SQLite still do not form a distributed transaction.

Operations use a 1–120 second monotonic budget for lock waits, HTTP initialization/discovery and refresh, with a separate five-second cleanup attempt. Control lock waits are limited to five seconds and each process queues at most four operations. Cancellation is cooperative; in-flight socket I/O uses its remaining deadline. OS DNS resolution and the existing SQLite busy timeout retain their lower-level limits, so this is not a hard process-kill guarantee. Terminal records follow the existing idempotency-journal retention.

`instance_id` currently equals `server_id`, and `config_revision` is the file digest. This is one configuration per target, not grouping or multi-instance routing. A content digest cannot distinguish deletion/recreation with identical bytes. Future generation/session routing requires its own design and tests. No Git executor or remote runtime has been installed by this feature.

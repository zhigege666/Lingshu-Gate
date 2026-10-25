# External MCP configuration

[简体中文](zh-CN/external-mcp-configuration.md) · [Project delivery](project-delivery.md)

This workflow manages an existing external Streamable HTTP MCP without uploading source, building a package, or starting a process on the remote server. Version 0.5.6 supports configuration deletion and exact private-HTTP permission changes through MCP, alongside separately scoped [shared credential management](shared-system-credentials.md). Deployment and real-peer acceptance are separate from source and synthetic-test completion.

## Choose a source

| Source | Path |
|---|---|
| Trusted local project | Deterministic ZIP → upload → preflight/build → deploy/start |
| Explicit HTTPS Git repository | Git plan/import → owned upload → the same build/delivery workflow; a reviewed executor is still missing |
| Existing HTTP MCP endpoint | HTTP management plan → confirmed apply → operation status |

The bundled Delivery Skill contains all three routes. Console configuration saves and this workflow use the existing `McpConfigurationService`; the new REST and MCP adapters share one `ExternalMcpConfigurationService`. Existing Console save-only behavior remains separate from explicit connection/discovery choices.

## Recommended HTTP management tools

| Tool | Purpose |
|---|---|
| `gate_http_mcp_test` | Test HTTP, authentication, MCP handshake and discovery with an ephemeral client; no save, permission grant or tool publication. |
| `gate_http_mcp_plan` | Offline review of `create`, `update`, `delete`, `revoke_trust` or `restore_trust`; never contacts the endpoint |
| `gate_http_mcp_apply` | Apply the exact reviewed plan with `confirmed=true` and an idempotency key |
| `gate_http_mcp_status` | Read the authorized target or actor-owned operation, including saved state and connection result |
| `gate_http_mcp_cancel` | Request cancellation; changes already persisted remain visible in the result |

Plan/apply/status/cancel share the existing operation engine, bounded queue and durable journal. The independent connection-test tool uses an ephemeral client and no durable operation record. They do not expand the schemas or fingerprints of the four legacy `gate_mcp_config_*` tools. An administrator API token retains its existing scope ceiling. A management OAuth connection must explicitly consent to the new tools and exact target actions; upgrading the server, refreshing a token or enlarging client scopes does not expand an old grant or refresh family.

Plan/status require `operations.manage`; apply/cancel also require `tools.invoke`, with a current active administrator. Create/update supply `manifest`; delete/revoke/restore supply `server_id` instead. All modes except create require the current raw-file `expected_config_digest`. `connect` and `refresh_tools` default to false; refresh requires connect. Delete/revoke cannot connect. The plan expires after five minutes and binds the target incarnation, configuration digest, trust revision, credential revisions, actor/connection and exact action choices. Apply uses the plan ID/digest and the same connection/refresh flags.

For a private HTTP create/update, the reviewed plan contains the exact service ID, canonical RFC1918 IPv4 address and port. One authorized apply saves the configuration and its connection permission. The Console uses the same policy when saving: the endpoint summary replaces the separate **Authorize this address** action. Static precheck does not write permission or contact the peer. HTTPS, canonical loopback behavior, denied redirects and normal TLS verification remain unchanged; there is no arbitrary-URL HTTP request tool.

Revocation is persistent. Ordinary update, reconnect and automatic startup cannot restore it. Use an explicit `restore_trust` plan, or the Console's restore action, after checking the exact current endpoint. Trust is tied to `server_binding`, not merely a reusable service ID. Only legacy permission records matching a currently saved service are adopted once; unmatched records require review. A pre-save permission is pending and cannot connect until the matching configuration is saved. Deleting a service removes its trust; recreating it requires a new authorized create and cannot inherit its predecessor's permission.

Delete previews affected tools, groups and personal downstream bindings. Apply uses the normal configuration/runtime cleanup path, removes the saved external configuration and its current catalog/group membership, and invalidates the old identity. Shared credentials and audit history remain. No operation uninstalls or stops the remote MCP process. Referenced shared credentials must be detached before their own explicit deletion.

Credential values are never embedded in an HTTP plan. First create or update a separately scoped credential, then use `${credential:example-binding}` in the manifest. Its HTTP scope must match the service, origin and incarnation. A pending scope may be consumed by the first matching save. See [shared system credentials](shared-system-credentials.md) for write-only values, revision checks and rotation results.

## Legacy authority and input

The following contract remains available for existing `gate_mcp_config_*` clients and their REST adapters. It supports create/update and preserves existing private-HTTP permission; use the new tools above for integrated permission, revoke/restore or physical deletion.

Use an active Gate administrator's Console session, an explicitly scoped Gate API token, or a separately consented built-in management OAuth connection at `/mcp/manage`. `operations.manage` is required; apply, cancel and an optional remote probe also require `tools.invoke`. Current role permissions, token/family scopes, delegation ceilings, user status and session/token validity are checked again during execution and after lock waits. Management OAuth additionally binds the exact issuer/resource/client/grant/family, consented tool fingerprints and current exact target/create-update policy. Ordinary business OAuth and external-issuer OAuth remain denied. Operations are private to their actor and OAuth connection; an administrator role alone does not upgrade a bearer.

Only `launch.type=external` with `transport.type=streamable_http` is accepted. Unknown fields, commands, working directories, mounts, build metadata, roots, analysis and permission changes are rejected. Use only existing managed credential references in headers, for example `Bearer ${credential:example-binding}`; never provide secret values. New personal credential slots must be configured separately. Existing personal slot declarations can be preserved during update.

New manifests default to `enabled=true`, `auto_start=true`, `startup_policy=gate_start_v1` and a 120-second downstream timeout. Explicit `auto_start=false` or `startup_policy=legacy_restore` remains unchanged. Enabled means available for connection; it does not mean connected. Future Gate startup policy is separate from this apply's `connect` choice. HTTPS verification, denied redirects and current endpoint restrictions remain. Private HTTP requires the separately approved exact service/IP/port trust record; planning cannot create or expand trust.

## Legacy plan and apply

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

The separate management resource is default-disabled and requires explicit resource/scope/tool/target consent. See [administrator OAuth configuration](oauth-external-management-design.md). The owner can confirm exact target changes in Gate without changing JWT/family scope ceilings; old plans become stale, and cached-result/status/cancel reads recheck the current connection and actual target. Target edits alone cannot add tools or scopes. Credential actions additionally require `credentials.manage.system` and their own consented tools. Discovery never publishes classifications or grants business access.

The operation result and idempotency completion commit in one SQLite transaction. Restart, a lost worker or a failed completion transaction becomes `interrupted` with unknown state and required reconciliation. Nothing is replayed, reconnected or stopped automatically during recovery. Configuration files, HTTP state and SQLite still do not form a distributed transaction.

Operations use a 1–120 second monotonic budget for lock waits, HTTP initialization/discovery and refresh, with a separate five-second cleanup attempt. Control lock waits are limited to five seconds and each process queues at most four operations. Cancellation is cooperative; in-flight socket I/O uses its remaining deadline. OS DNS resolution and the existing SQLite busy timeout retain their lower-level limits, so this is not a hard process-kill guarantee. Terminal records follow the existing idempotency-journal retention.

`instance_id` currently equals `server_id`, and `config_revision` is the file digest. This remains one configuration per target. HTTP permission and credential usage separately bind the lifecycle `server_binding`, so identical configuration bytes cannot revive an earlier incarnation's authority. This does not add multi-instance routing or a remote runtime. Configuration files, trust state, credentials and the operation journal are not a distributed transaction: inspect `config_applied`, `trust_applied`, `requires_reconciliation` and connection/discovery fields together after a partial or interrupted result.


## Independent connection test

`gate_http_mcp_test` does not enter the persisted operation journal above, create a plan or establish a long-lived connection. It requires explicit `confirmed=true`; management OAuth also requires the new tool and exact target action `test`. The Console exposes **Test connection** separately from static validation and saving. See the [connection-test guide](http-mcp-connection-testing.md) for inputs, result semantics, credential scopes and a Home integration example.

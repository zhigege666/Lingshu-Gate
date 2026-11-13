# Shared system credentials

[简体中文](zh-CN/shared-system-credentials.md) · [HTTP MCP management](external-mcp-configuration.md)

Shared credentials can be managed from the Console, the private credential REST API or five administrator MCP tools. They remain encrypted at rest. Reads, successful writes, validation errors, operation receipts, logs and optional invocation-content records do not return the saved plaintext. The manifest reference is `${credential:<id>}`. This workflow is separate from personal downstream bindings and business-account vaults.

## Tools and authority

| Tool | Required input | Result |
|---|---|---|
| `gate_credential_list` | None | Currently authorized masked metadata |
| `gate_credential_get` | `credential_id` | Masked metadata and current `updated_at` revision |
| `gate_credential_create` | `name`, `value`, `idempotency_key`; optional explicit `credential_id`, description and HTTP scopes | New encrypted record; existing IDs fail instead of overwriting |
| `gate_credential_update` | ID, `expected_revision`, idempotency key and changed fields | Revision-checked metadata, value rotation or scope change |
| `gate_credential_delete` | ID, `expected_revision`, idempotency key | Delete only after live dependency checks pass |

An active administrator needs `credentials.manage.system`; writes additionally need `tools.invoke`. API-token and delegation ceilings still apply, including an explicitly existing wildcard ceiling. Ordinary business OAuth cannot call these tools. Built-in management OAuth additionally requires `operations.manage`, an explicitly requested/consented `credentials.manage.system` scope, selected credential-tool fingerprints and exact credential target actions: `credential.read`, `credential.create`, `credential.update`, `credential.delete`. Service actions such as `create` or `delete` do not authorize a credential with the same ID. Old grants and refresh families gain nothing on upgrade.

Authority to manage a credential includes its complete `http_scopes` metadata and approval of those exact uses. It does not grant authority to configure, connect to or invoke the listed services; those operations still require their own service permissions. Connection and dependency details are filtered separately by current visibility.

Standalone Console credential management uses `/v1/credentials`; the configuration editor uses the combined save endpoint described below. Generic MCP/registry credential invocation rejects session authentication. The Console editor can create a credential inline or authorize an existing credential for the current service without leaving its HTTP configuration draft. It inserts only the reference afterward. The independent credentials page remains available for inspection, rotation and deletion.

## Use an existing credential in the Console

Select the authentication type and an existing credential in the service editor. Credentials needing another target remain selectable for credential administrators. The editor shows the credential, service ID and exact origin. **Authorize this use on save** stages only that target; the final configuration Save commits it while retaining the secret and other targets. New inline credentials are also staged and saved with the configuration. Cancelling before that final save writes neither a credential nor a grant. Existing connection bindings remain valid until the configuration is saved.

If another administrator changes the credential, the draft stays open. Reload its metadata, review the target, and explicitly authorize again. An unchanged retry keeps its operation key; a refresh does not silently grant new use. Accounts without management authority see that requirement beside the controls.

## Combined configuration save

`POST /v1/mcp/configs/with-credential` accepts the existing manifest/apply/start/trust fields, `existing_server_id` and its required `expected_config_digest` for updates, an `idempotency_key`, and one `credential_write`. A `create` draft contains `credential_id`, `name`, `value` and `target: {server_id, origin}`; an `authorize` draft contains the ID, target, `expected_revision` and `expected_http_scopes_revision`. The exact target must match a reference in the submitted HTTP configuration. Shared credential submissions follow the existing dedicated credential REST transport contract; personal `user_credential_values` retain their HTTPS requirement except on loopback. Remote deployments should use HTTPS. This Console/API-token route requires configuration management plus the existing live shared-credential administrator permissions and same-origin session checks; it does not extend management OAuth.

Preflight validates revisions, target and other references before credential writes. One HMAC-bound receipt covers credential creation/authorization and configuration application; successful replay does not create or start again. Files, runtime and SQLite are not one atomic transaction. Partial failures return `credential_saved`, `config_saved`, `runtime_state` and `requires_reconciliation`; inspect the actual stores and reopen with current revisions. Failed/pending receipts do not blindly repeat writes. Secrets never enter a manifest, receipt, audit event or validation response.

## Revision and retry contract

Read the current `updated_at` and send it as `expected_revision` on update/delete. Stale revisions fail; do not silently overwrite a newer value. Omitting `value`, or sending `null`, retains the existing secret. The mask `***` is never accepted as a replacement value. To rotate, provide the actual new value once with a fresh key.

All MCP writes require an idempotency key. Retrying exactly the same request, key and authenticated connection returns the original masked completion after current authority is checked. A reused key with different arguments conflicts. The journal uses a keyed fingerprint rather than storing the request's secret or an unkeyed guessable secret digest. A lost completion is reported as pending/interrupted and requires reconciliation; the server does not guess whether a secret write occurred and repeat it.

For one additional or renewed HTTP target, update with `authorize_http_target: {"server_id": "example-http", "origin": "https://mcp.example:443"}` and the current revision/key. This operation cannot include `server_binding` and is mutually exclusive with a full `http_scopes` replacement. Gate merges it with the latest scopes under the existing mutation locks. An already bound target keeps its current `server_binding` and receives `pending_rebind: true`; unrelated scopes are retained. The next matching configuration save consumes that approval and seals the current service identity. Cancelling the draft retains the old binding: connections that were already authorized can continue, and the new approval remains pending.

Masked metadata includes `http_scopes_revision`, a digest of the public target scopes. Target-authorization and full-list editors should send it as `expected_http_scopes_revision`; the Console does so automatically. This catches a pending-to-bound transition even though that transition preserves `updated_at`. Unchanged old scopes may be retained without reauthorizing a removed service. New or changed non-null bindings are still checked against the saved service identity. Older clients may omit the scope digest and retain the existing revision contract.

REST keeps the existing list/get/create/update/delete route shapes. Update requires `expected_revision` in the JSON body; delete takes `expected_revision` in its query parameters. An explicit `idempotency_key` is recommended and is used by the Console. Older REST requests omitting a key receive a new internal key for each request and therefore have no transport-retry guarantee. JSON parse/model errors omit rejected values, and credential responses use `Cache-Control: no-store`.

## Exact HTTP usage scopes

HTTP use requires an entry in `http_scopes`:

```json
{
  "server_id": "example-http",
  "origin": "http://10.10.0.23:4747",
  "server_binding": null
}
```

The origin contains only scheme, host and port; the MCP path stays in the server manifest. A bound scope uses the service's current `server_binding`. A null binding is pending, including when an existing service has not yet saved this use; it is consumed only by the next matching configuration save. It cannot authorize a connection by itself. Changing the endpoint (including its path), launch/transport type, or deleting/recreating a service changes its identity. The old bound scope does not automatically authorize that identity. Explicitly approve the next matching save; `pending_rebind` preserves an existing binding until that save and cannot authorize runtime requests by itself. Missing, mismatched or revoked usage is rejected before sending a credential.

Legacy credentials are migrated once, only to their currently saved, valid HTTP consumers and lifecycle identities. An orphaned credential gains no future-service wildcard. Git authentication, build environments and proxy consumers keep their existing credential semantics; the HTTP restriction does not redefine those consumers.

## Rotation, deletion and results

Existing HTTP clients resolve current authorized headers at dispatch instead of retaining the old value for their lifetime. A completed rotation makes subsequent dispatches use the current value; already dispatched requests are not recalled. A saved value does not prove that the downstream service accepts it. Results distinguish `value_saved`, affected connections, `refresh_on_next_dispatch` and `connection_verified=false`; connect or perform an authorized downstream check separately.

Deletion checks saved configurations, Git/build references, proxy revisions and network defaults. Referenced credentials return `credential_in_use`; remove their dependencies before retrying with the current revision and a new key. Shared credentials are retained when deleting an external MCP configuration. Dependency/connection detail is limited by the caller's current visibility, with hidden counts where appropriate.

The encrypted file and SQLite operation/audit state do not form a single transaction. On an interrupted result, read masked metadata and the relevant configuration before choosing a new write. Back up the encrypted store and its key together with Gate's database and configuration; plaintext recovery is not exposed through MCP or REST.

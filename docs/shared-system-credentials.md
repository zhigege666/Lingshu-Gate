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

Console sessions use the dedicated `/v1/credentials` routes; generic MCP/registry credential invocation rejects session authentication. The Console editor can create a credential inline while preserving its HTTP configuration draft, and inserts only the reference afterward. The independent credentials page remains available for inspection, rotation and deletion.

## Revision and retry contract

Read the current `updated_at` and send it as `expected_revision` on update/delete. Stale revisions fail; do not silently overwrite a newer value. Omitting `value`, or sending `null`, retains the existing secret. The mask `***` is never accepted as a replacement value. To rotate, provide the actual new value once with a fresh key.

All MCP writes require an idempotency key. Retrying exactly the same request, key and authenticated connection returns the original masked completion after current authority is checked. A reused key with different arguments conflicts. The journal uses a keyed fingerprint rather than storing the request's secret or an unkeyed guessable secret digest. A lost completion is reported as pending/interrupted and requires reconciliation; the server does not guess whether a secret write occurred and repeat it.

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

The origin contains only scheme, host and port; the MCP path stays in the server manifest. A bound scope uses the service's current `server_binding`. A null binding is pending, including when an existing service has not yet saved this use; it is consumed only by the next matching configuration save. It cannot authorize a connection by itself. Changing the origin or deleting/recreating a service does not carry over the old scope. Add or review the new exact scope explicitly. Missing, mismatched or revoked usage is rejected before sending a credential.

Legacy credentials are migrated once, only to their currently saved, valid HTTP consumers and lifecycle identities. An orphaned credential gains no future-service wildcard. Git authentication, build environments and proxy consumers keep their existing credential semantics; the HTTP restriction does not redefine those consumers.

## Rotation, deletion and results

Existing HTTP clients resolve current authorized headers at dispatch instead of retaining the old value for their lifetime. A completed rotation makes subsequent dispatches use the current value; already dispatched requests are not recalled. A saved value does not prove that the downstream service accepts it. Results distinguish `value_saved`, affected connections, `refresh_on_next_dispatch` and `connection_verified=false`; connect or perform an authorized downstream check separately.

Deletion checks saved configurations, Git/build references, proxy revisions and network defaults. Referenced credentials return `credential_in_use`; remove their dependencies before retrying with the current revision and a new key. Shared credentials are retained when deleting an external MCP configuration. Dependency/connection detail is limited by the caller's current visibility, with hidden counts where appropriate.

The encrypted file and SQLite operation/audit state do not form a single transaction. On an interrupted result, read masked metadata and the relevant configuration before choosing a new write. Back up the encrypted store and its key together with Gate's database and configuration; plaintext recovery is not exposed through MCP or REST.

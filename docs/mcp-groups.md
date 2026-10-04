# MCP groups

[简体中文](zh-CN/mcp-groups.md) · [Configuration](configuration.md)

This unreleased slice adds administrator-owned collections of existing MCP instances. An instance ID remains its existing `server_id`; configuration, tools, credentials, endpoints, authorization and runtime state stay with that instance. One instance may belong to several groups. Creating a group or adding a member grants no access. Existing ungrouped instances retain their behavior.

In **MCP services**, switch directly between Instances and Groups. Create or edit a group in the centered dialog, enter its name/description, choose Active or Archived, and explicitly select existing instances. Member search covers the complete metadata catalog; pagination and search retain selections from other pages. A group can contain up to 1,000 members; the store supports up to 1,000 groups. Group queries return instance metadata, not complete tool schemas. IDs remain stable when names change.

Archiving or deleting a group changes only group metadata and relationships. It does not stop, delete, reconnect or copy services, remove history, or change grants. Archived membership is retained; the Ungrouped view means no active group membership. Instance IDs and names remain visible even when an instance is missing or not loaded.

Known instance deletion invalidates its memberships before runtime/file removal; even a compensated deletion failure requires explicit member confirmation. Configuration reload marks disappeared instances missing. A missing membership does not automatically reactivate when an instance with the same ID returns. Retain/remove it, or uncheck and explicitly reselect the restored instance. Archiving can retain missing members. An unavailable file also appears unavailable in current detail queries; out-of-band file changes and SQLite metadata are not a single atomic store.

## Administrative API

All endpoints require an active current administrator, current `operations.manage` permission and an active Console session or appropriately scoped API token. Business OAuth and management OAuth cannot manage groups. The existing four management MCP tools and their resource/scope ceilings are unchanged; this slice registers no additional MCP tool.

| Method and path | Operation |
|---|---|
| `GET /v1/mcp/groups` | Search group names, descriptions or IDs; filter `status=active/archived/all`, `q`, `offset`, `limit` (maximum 100) |
| `GET /v1/mcp/groups/instances` | Search complete instance names/IDs with pagination; optional `group_id` or `ungrouped=true` |
| `GET /v1/mcp/groups/{id}` | Read saved metadata, revision and member IDs/availability |
| `POST /v1/mcp/groups/csrf` | Obtain a short-lived session/body/method/target-bound, single-use ticket using `action`, `request_digest`, and a group ID for update/delete |
| `POST /v1/mcp/groups` | Create explicitly confirmed metadata and memberships |
| `PUT /v1/mcp/groups/{id}` | Replace metadata/members with `expected_revision` CAS |
| `DELETE /v1/mcp/groups/{id}` | Delete metadata/relations with `expected_revision` and `confirmed=true` |

Create/update use `name`, `description`, `status`, distinct `members` IDs, optional explicit `reconfirm_members`, and `confirmed=true`. Unknown fields and unavailable new/reconfirmed members are rejected. Browser writes require a strict same Origin and an `X-CSRF-Token` ticket bound to the SHA-256 of canonical sorted-key JSON. API tokens retain their own scope ceiling. Updates and deletion recheck live authority inside the writer transaction; revision conflict or audit failure leaves the mutation unapplied. Audit records commit with metadata changes.

Console requests are bounded to 15 seconds each and writes are never automatically replayed. A timeout leaves completion unconfirmed: refresh saved state before retrying. Errors remain visible, edits remain intact on failure, and reload/dirty close require an explicit discard decision. Pending writes block duplicate submit and dismissal; late catalog/detail responses cannot replace a newer selection or closed editor.

## Support boundary

Logical tool compatibility review, schema revision directories, Agent routing envelopes, automatic future-instance authorization and session binding are **not implemented in this slice**. No same-name tool aggregation, endpoint routing or cross-instance retry/failover is added. Shared downstream clients and per-call user-credential clients retain their existing lifecycle; this feature makes no browser-session isolation claim. The Git transport and isolated worker readiness gap is unchanged.

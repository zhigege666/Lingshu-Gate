# Invocation content recording

[简体中文](zh-CN/invocation-recording.md)

Gate records invocation metadata by default. The persistent retention policy's `payload_mode` is `metadata_only` until an administrator with `retention.manage` explicitly changes it to `redacted`. This does not reconstruct earlier inputs or outputs. A record's `recording_mode` describes that invocation, not the current policy.

## Access and representation

`GET /v1/me/invocations/{audit_id}` requires current authentication, an active user and `console.view`, and selects the record by both its ID and the authenticated owner ID. Another user's ID returns 404, including for administrators using this personal endpoint. `GET /v1/access/invocation-audits/{audit_id}` separately requires `audit.payload.read`; `audit.read` alone does not grant content access. The new content permission belongs only to the default administrator role, and bearer-token scope restrictions still apply. Each request rechecks authorization; disabling a user or removing the content capability invalidates subsequent reads through existing sessions.

Responses contain safe `audit` metadata, `recording_mode`, and `input`/`output` envelopes. `status` is `recorded`, `not_recorded`, `not_invoked`, `truncated`, or `serialization_error`. A present `value` preserves JSON `null`, `false` and `0`. Output values contain `{ok, output, error}`. Errors are subject to the same redaction. The Console fetches authorized detail again before copying; a failed refresh clears displayed content. Already delivered data cannot be recalled.

## Recording boundary

Inputs are snapshotted before downstream credential injection and before dispatch can mutate the argument object. Denied calls and missing-credential calls store metadata only, with `not_invoked` content status. Each input and output envelope is independently limited to 32 KiB of JSON (at most 64 KiB combined), 12 nested levels and 1,000 visited value nodes. Truncation and serialization limits are explicit; unsupported objects are not converted with `repr` or arbitrary serialization hooks.

Sensitive field names, bearer strings, authorization headers and cookie lines are redacted. The runtime additionally redacts known shared and personal credential values from the already resolved client or the same personal credential resolution before persisting an output or error, including unlabelled echoes. No second credential lookup or full secret-store enumeration is performed. This audit handling does not change the caller's actual tool response. Values stay local to the invocation; the audit callback receives only the bounded redacted snapshot. Metadata-only mode does not capture content.

Redaction cannot reliably identify arbitrary business secrets in innocuously named fields. Keep metadata-only mode unless the intended tools and data are suitable for content recording; review organizational data handling before enabling it. The payload store is not a replacement for credential storage.

## Lifetime and deployment

Payloads and their audit metadata are inserted in one transaction. Payloads are deleted with their corresponding call record, under the call-record retention period; logs and events have separate retention periods. Old unrecorded data cannot be recovered by enabling recording later. See the retention controls for preview and explicit destructive-cleanup confirmation. Tests use isolated synthetic databases; installing this change does not authorize cleanup of existing user data.

SQLite remains a single-writer, single-Core deployment. In-memory invocation limits reset on Core restart and do not enforce a shared quota across multiple Core instances. Do not deploy multiple Core instances assuming a global quota or cleanup coordination guarantee.

## Evidence

`tests/test_invocation_payloads.py` covers scalar fidelity, byte/depth/node limits, cycles, real HTTP owner and capability boundaries, disabled users and revoked permissions in existing sessions, denied calls with zero dispatch, pre-dispatch snapshots, redacted errors, and known personal credential echoes. The downstream echo transport is synthetic; these tests do not verify real external OAuth provider or tunnel connectivity.

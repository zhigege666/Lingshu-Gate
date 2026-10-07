# Retention and cleanup

Runtime logs, events and invocation records have independent persisted policies. Each defaults to seven days. The management capability `retention.manage` belongs only to the built-in administrator by default. Whole-service log access or `operations.manage` alone does not grant retention management.

The HTTP policy names are `runtime_logs_retention_days`, `events_retention_days`, and `call_records_retention_days` (integers 1–3650). Internally these map to `logs_days`, `events_days`, and `invocation_audits_days`. The same CAS revision also protects `payload_mode`, initially `metadata_only`; see the [invocation recording guide](invocation-recording.md) for the optional `redacted` mode.

## Disabled by default

```dotenv
LINGSHU_GATE_RETENTION_WORKER_ENABLED=false
LINGSHU_GATE_RETENTION_INTERVAL_SECONDS=3600
```

These are deployment settings, not a browser toggle. With the worker disabled, immediate cleanup returns `409 retention_worker_disabled` and creates no job. Saving a policy never runs cleanup. Enabling the worker is an explicit deployment decision: after the configured interval it starts scheduled cleanup under the saved policy. Deletion is irreversible. No real environment was enabled for implementation verification; tests use only independent temporary databases and synthetic records.

## Review and execute separately

1. `GET /v1/retention/policy` returns the policy, revision and deployment `worker_enabled` status.
2. `POST /v1/retention/preview`, optionally with a complete proposed policy, counts eligible records without database writes. It returns fixed UTC cutoffs, proposed policy, current revision, shortened domains and a five-minute preview ID. Counts are estimates of the current snapshot, not a reservation of matching records.
3. `PUT /v1/retention/policy` uses `expected_revision`. Any shortening also requires the matching `preview_id` and `confirmed:true`; the server checks the proposed policy, revision and expiry. Canceling the confirmation sends no mutation. Concurrent edits return 409. Saving does not itself enqueue cleanup.
4. For immediate cleanup, obtain a **new preview of the saved policy**, then separately confirm `POST /v1/retention/jobs` with `preview_id`, `expected_revision` and `confirmed:true`. The server uses the preview's immutable cutoffs. It returns 202 and a queued job, not a claim that deletion succeeded.
5. `GET /v1/retention/jobs/{id}` reports `queued`, `running`, `retry`, `succeeded`, `failed` or `cancelled`, counts already deleted per table, and a safe error code. `POST /v1/retention/jobs/{id}/cancel` stops subsequent batches; rows already deleted cannot be restored.

Preview IDs live only in process memory; a process restart requires another preview. They are not authorization tokens: every endpoint rechecks retention management permission. Administrators with that capability share the management scope. A policy revision change cancels old jobs before another destructive batch.

## UTC, batching and recovery

Migration `0002_retention_and_invocation_payloads` adds persisted policy/jobs/lease tables, UTC expression indexes, and the optional payload table. Eligibility is strictly `julianday(created_at) < julianday(cutoff)`, so offset timestamps compare in UTC and records exactly at the boundary remain. Invalid legacy timestamps are not selected. Each transaction deletes at most 200 records from one domain (the internal batch bound is 1–1000). Deleting an invocation audit cascades to its associated `invocation_payloads` row through an enforced foreign key; runtime logs and events remain independent.

A SQLite lease fences concurrent workers and expires after 30 seconds for crash recovery. The lease and batch changes commit together. A failed batch rolls back, retries with a five-second delay and stops after three failures. Cancellation is checked between batches; shutdown waits for the current bounded transaction before stopping. These safeguards do not make multi-Core SQLite deployment supported: retain the existing single-writer, single-Core topology. Back up through the established deployment process before enabling irreversible retention.

`tests/test_retention.py` covers policy defaults/CAS, read-only previews, shortening confirmation, UTC/index/boundary behavior, bounded batches, lease takeover, retries, cancellation, payload cascade, real authenticated HTTP routes, disabled-worker refusal and isolated enabled-worker execution. UI confirmation and real deployment activation are separate acceptance layers.

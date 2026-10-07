import type { RetentionPolicy, RetentionSnapshot, RetentionPreview, RetentionJob } from "@/api/retention"

export const retentionFields = ["runtime_logs_retention_days", "events_retention_days", "call_records_retention_days"] as const
export const defaultRetentionDraft: RetentionPolicy = { runtime_logs_retention_days: 7, events_retention_days: 7, call_records_retention_days: 7, payload_mode: "metadata_only" }
export function policyDraft(value: RetentionPolicy): RetentionPolicy {
  return { runtime_logs_retention_days: value.runtime_logs_retention_days, events_retention_days: value.events_retention_days, call_records_retention_days: value.call_records_retention_days, payload_mode: value.payload_mode }
}
export function samePolicy(a: RetentionPolicy, b: RetentionPolicy) {
  return retentionFields.every(field => a[field] === b[field]) && a.payload_mode === b.payload_mode
}
export function shortensPolicy(before: RetentionPolicy, after: RetentionPolicy) {
  return retentionFields.some(field => after[field] < before[field])
}
export function assertPreview(preview: RetentionPreview, snapshot: RetentionSnapshot, draft: RetentionPolicy) {
  const tables = ["logs", "events", "invocation_audits"] as const
  if (tables.some(table => !Number.isInteger(preview.counts?.[table]) || preview.counts[table] < 0
    || !Number.isFinite(Date.parse(preview.cutoffs?.[table])) || Date.parse(preview.cutoffs[table]) > Date.now())) throw new Error("retention_preview_stale")
  if (preview.revision !== snapshot.revision || !samePolicy(preview.policy, draft) || !preview.preview_id || (!Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= Date.now())) throw new Error("retention_preview_stale")
}
export function assertSaved(saved: RetentionSnapshot, before: RetentionSnapshot, draft: RetentionPolicy) {
  assertSnapshot(saved)
  if (!Number.isInteger(saved.revision) || saved.revision <= before.revision || !samePolicy(saved, draft)) throw new Error("retention_save_unconfirmed")
}

export function validPolicy(policy: RetentionPolicy) {
  return retentionFields.every(field => Number.isInteger(policy[field]) && policy[field] >= 1 && policy[field] <= 3650)
    && ["metadata_only", "redacted"].includes(policy.payload_mode)
}

export function assertSnapshot(value: RetentionSnapshot) {
  if (!validPolicy(value) || !Number.isInteger(value.revision) || value.revision < 1 || typeof value.worker_enabled !== "boolean") throw new Error("retention_policy_unconfirmed")
}
export function assertJob(job: RetentionJob, revision?: number) {
  if (!job.id || !["queued", "running", "retry", "cancelled", "succeeded", "failed"].includes(job.state)
    || !Number.isInteger(job.policy_revision) || (revision !== undefined && job.policy_revision !== revision)) throw new Error("retention_job_unconfirmed")
}

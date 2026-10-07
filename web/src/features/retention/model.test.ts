import { describe, expect, it } from "vitest"
import { assertJob, assertPreview, assertSaved, assertSnapshot, defaultRetentionDraft, samePolicy, shortensPolicy, validPolicy } from "./model"
import type { RetentionJob, RetentionPreview, RetentionSnapshot } from "@/api/retention"
const snapshot: RetentionSnapshot = { ...defaultRetentionDraft, revision: 2, worker_enabled: false }
const preview: RetentionPreview = { preview_id: "synthetic-preview", revision: 2, policy: defaultRetentionDraft, counts: { logs: 1, events: 2, invocation_audits: 3 }, cutoffs: { logs: "2000-01-01T00:00:00Z", events: "2000-01-01T00:00:00Z", invocation_audits: "2000-01-01T00:00:00Z" }, expires_at: "2099-01-01T00:00:00Z", shortened: [] }
describe("retention policy confirmation", () => {
  it("defaults independently to seven days and metadata only", () => {
    expect(defaultRetentionDraft).toEqual({ runtime_logs_retention_days: 7, events_retention_days: 7, call_records_retention_days: 7, payload_mode: "metadata_only" })
    expect(validPolicy(defaultRetentionDraft)).toBe(true)
  })
  it("detects any shortened family without coupling independent days", () => {
    expect(shortensPolicy(snapshot, { ...snapshot, events_retention_days: 1 })).toBe(true)
    expect(shortensPolicy(snapshot, { ...snapshot, events_retention_days: 30 })).toBe(false)
    expect(samePolicy(snapshot, { ...snapshot, payload_mode: "redacted" })).toBe(false)
  })
  it.each([0, 3651, 1.5, NaN])("rejects invalid retention days %s", value => {
    expect(validPolicy({ ...snapshot, call_records_retention_days: value })).toBe(false)
  })
  it("requires a matching, unexpired preview before confirmation can apply", () => {
    expect(() => assertPreview(preview, snapshot, defaultRetentionDraft)).not.toThrow()
    for (const changed of [{ ...preview, counts: { ...preview.counts, logs: -1 } }, { ...preview, cutoffs: { ...preview.cutoffs, events: "invalid" } }, { ...preview, revision: 1 }, { ...preview, expires_at: "invalid" }, { ...preview, expires_at: "2000-01-01T00:00:00Z" }, { ...preview, policy: { ...defaultRetentionDraft, payload_mode: "redacted" as const } }]) {
      expect(() => assertPreview(changed, snapshot, defaultRetentionDraft)).toThrow()
    }
  })
  it("does not accept malformed or mismatched successful save responses", () => {
    expect(() => assertSnapshot({ ...snapshot, worker_enabled: undefined } as unknown as RetentionSnapshot)).toThrow()
    expect(() => assertSaved(snapshot, snapshot, defaultRetentionDraft)).toThrow()
    expect(() => assertSaved({ ...snapshot, revision: 3, events_retention_days: 30 }, snapshot, defaultRetentionDraft)).toThrow()
    expect(() => assertSaved({ ...snapshot, revision: 3 }, snapshot, defaultRetentionDraft)).not.toThrow()
  })
  it("recognizes backend state, including failed jobs, without accepting status aliases", () => {
    const job = { id: "synthetic-job", state: "failed", policy_revision: 2 } as RetentionJob
    expect(() => assertJob(job, 2)).not.toThrow()
    expect(() => assertJob({ ...job, state: undefined, status: "success" } as unknown as RetentionJob)).toThrow()
    expect(() => assertJob(job, 3)).toThrow()
  })
})

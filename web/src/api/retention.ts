import { request } from "@/api/http"

export type RetentionPolicy = { runtime_logs_retention_days: number; events_retention_days: number; call_records_retention_days: number; payload_mode: "metadata_only" | "redacted" }
export type RetentionSnapshot = RetentionPolicy & { revision: number; worker_enabled: boolean }
export type RetentionTable = "logs" | "events" | "invocation_audits"
export type RetentionPreview = { preview_id: string; revision: number; policy: RetentionPolicy; cutoffs: Record<RetentionTable, string>; counts: Record<RetentionTable, number>; expires_at: string; shortened: RetentionTable[] }
export type RetentionJob = { id: string; state: "queued" | "running" | "retry" | "cancelled" | "succeeded" | "failed"; policy_revision: number; cutoffs: Record<RetentionTable, string>; counts: Record<RetentionTable, number>; error_code: string | null; [key: string]: unknown }
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) })
export const retentionApi = {
  policy: () => request<RetentionSnapshot>("/v1/retention/policy"),
  save: (policy: RetentionPolicy, revision: number, previewId?: string) => request<RetentionSnapshot>("/v1/retention/policy", { method: "PUT", body: JSON.stringify({ ...policy, expected_revision: revision, ...(previewId ? { preview_id: previewId, confirmed: true } : {}) }) }),
  preview: (policy?: RetentionPolicy) => request<RetentionPreview>("/v1/retention/preview", post(policy ?? null)),
  cleanup: (preview: RetentionPreview) => request<RetentionJob>("/v1/retention/jobs", post({ preview_id: preview.preview_id, expected_revision: preview.revision, confirmed: true })),
  cancel: (id: string) => request<RetentionJob>(`/v1/retention/jobs/${encodeURIComponent(id)}/cancel`, post({})),
  job: (id: string) => request<RetentionJob>(`/v1/retention/jobs/${encodeURIComponent(id)}`),
}

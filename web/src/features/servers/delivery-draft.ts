import type { DeliveryDraft } from "@/api/builds"

/** PUT replaces the draft: retain context, never send response-only fields. */
export function deliveryDraftRequest(draft: DeliveryDraft, changes: Partial<DeliveryDraft> = {}) {
  const value = { ...draft, ...changes }
  return { expected_revision: draft.revision, manifest_patch: value.manifest_patch,
    server_id: value.server_id, build_id: value.build_id, deployment_id: value.deployment_id,
    overwrite: value.overwrite, start: value.start, project_root: value.project_root, runtime_override: value.runtime_override }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}
/** Runtime options override the generated artifact only where the user edited. */
export function manifestPatch(base: Record<string, unknown>, next: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const key of Object.keys(base)) {
    if (!(key in next)) result[key] = null
  }
  for (const [key, value] of Object.entries(next)) {
    if (JSON.stringify(base[key]) === JSON.stringify(value)) continue
    result[key] = record(base[key]) && record(value) ? manifestPatch(base[key], value) : value
  }
  return result
}
export function mergeManifestPatch(base: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const result = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete result[key]
    else result[key] = record(result[key]) && record(value) ? mergeManifestPatch(result[key], value) : value
  }
  return result
}

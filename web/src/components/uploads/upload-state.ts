export type UploadAction = "upload" | "draft" | "save" | "build" | "deploy" | "delete"

export type UploadActionResult = {
  uploadId: string
  action: UploadAction
  requestId: number
  data: unknown
  manifest: Record<string, unknown> | null
  analysis: Record<string, unknown> | null
}

export type UploadResults = Record<string, UploadActionResult>

/** Task results belong to an upload; list refreshes never replace this state. */
export function completeUploadAction(results: UploadResults, event: {
  uploadId: string
  action: UploadAction
  requestId: number
  data: unknown
  manifest?: Record<string, unknown>
}): UploadResults {
  const previous = results[event.uploadId]
  if (previous && previous.requestId > event.requestId) return results
  return { ...results, [event.uploadId]: {
    ...event,
    manifest: event.manifest || extractManifest(event.data) || previous?.manifest || null,
    analysis: extractAnalysis(event.data) || previous?.analysis || null,
  } }
}

export function resultForUpload(results: UploadResults, uploadId: string): UploadActionResult | null {
  return results[uploadId] || null
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null
}

export function extractManifest(value: unknown): Record<string, unknown> | null {
  const record = asRecord(value)
  return record ? asRecord(record.manifest) || asRecord(asRecord(record.draft)?.manifest) || asRecord(asRecord(record.build)?.manifest) : null
}

export function extractAnalysis(value: unknown): Record<string, unknown> | null {
  const record = asRecord(value)
  return record ? asRecord(record.analysis) || asRecord(asRecord(record.upload)?.analysis) || asRecord(asRecord(record.manifest)?.analysis) : null
}

/** One-time values are submitted separately and never retained with a result. */
export function prepareUploadManifest(text: string): { manifest: Record<string, unknown>; credentialValues: Record<string, string> } {
  const parsed = asRecord(JSON.parse(text))
  if (!parsed) throw new Error("Manifest must be a JSON object")
  const manifest = { ...parsed }
  const rawValues = manifest.user_credential_values
  delete manifest.user_credential_values
  const credentialValues: Record<string, string> = {}
  if (rawValues !== undefined) {
    const values = asRecord(rawValues)
    if (!values) throw new Error("user_credential_values must be an object of strings")
    for (const [key, value] of Object.entries(values)) {
      if (typeof value !== "string") throw new Error(`user_credential_values.${key} must be a string`)
      credentialValues[key] = value
    }
  }
  return { manifest, credentialValues }
}

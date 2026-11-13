export type StringMapRow = {
  id: number
  key: string
  value: string
  originalKey?: string
  originalValue?: string
}

export type StringMapIssue = { id: number; code: "missing_key" | "duplicate_key" | "masked_rename" }

/** Invalid edits stay in rows; they must never replace the last valid manifest. */
export function resolveStringMapRows(rows: StringMapRow[], ignoreKeyCase = false): {
  value: Record<string, string> | null; issues: StringMapIssue[]
} {
  const entries: Array<[string, string]> = []
  const keys = new Map<string, number>()
  const issues: StringMapIssue[] = []
  for (const row of rows) {
    if (!row.key && !row.value && row.originalKey === undefined) continue
    if (!row.key.trim() && row.key !== row.originalKey) {
      issues.push({ id: row.id, code: "missing_key" }); continue
    }
    const comparisonKey = ignoreKeyCase ? row.key.toLowerCase() : row.key
    const duplicate = keys.get(comparisonKey)
    if (duplicate !== undefined) {
      issues.push({ id: duplicate, code: "duplicate_key" }, { id: row.id, code: "duplicate_key" })
    }
    keys.set(comparisonKey, row.id)
    if (row.value === "***" && (row.originalValue !== "***" || row.key !== row.originalKey)) {
      issues.push({ id: row.id, code: "masked_rename" })
    }
    entries.push([row.key, row.value])
  }
  return { value: issues.length ? null : Object.fromEntries(entries), issues }
}

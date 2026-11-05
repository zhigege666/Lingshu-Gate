import type { ToolClassification } from "@/api/client"

export type ToolPolicyMode = "automatic" | "read" | "write" | "unknown"
export function effectiveToolPolicy(item: ToolClassification): "none" | "read" | "write" {
  if (item.required_access) return item.required_access
  // Older servers remain fail-closed; suggestions never authorize a tool.
  return item.status === "published" && item.effective_access !== "unknown" ? item.effective_access : "none"
}
export function toolPolicyMode(item: ToolClassification): ToolPolicyMode {
  if (item.policy_source === "default_write" || item.policy_source === "builtin_contract") return "automatic"
  const access = effectiveToolPolicy(item)
  return access === "none" ? "unknown" : access
}
/** Bound writes; retain successful responses and retry only unfinished items. */
export async function saveToolPolicyBatch(items: readonly ToolClassification[], access: ToolPolicyMode, note: string,
  save: (server: string, tool: string, payload: { access: ToolPolicyMode; destructive: boolean; idempotent: boolean; note: string; expected_fingerprint: string }) => Promise<ToolClassification>) {
  const saved: ToolClassification[] = []
  const failed: Array<{ item: ToolClassification; error: string }> = []
  for (let start = 0; start < items.length; start += 4) {
    const batch = items.slice(start, start + 4)
    const results = await Promise.allSettled(batch.map(item => save(item.server_id, item.tool_id, {
      access, destructive: item.destructive, idempotent: item.idempotent, note, expected_fingerprint: item.fingerprint,
    })))
    results.forEach((result, index) => {
      if (result.status === "fulfilled") saved.push(result.value)
      else failed.push({ item: batch[index], error: result.reason instanceof Error ? result.reason.message : String(result.reason) })
    })
  }
  return { saved, failed }
}

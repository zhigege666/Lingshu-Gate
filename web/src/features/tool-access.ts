import type { ToolDefinition } from "@/api/client"

export type ToolAccess = "read" | "write" | "unknown"

/** Display only: effective server decisions are distinct from declared permission. */
export function getToolAccessDisplay(tool: ToolDefinition): {
  access: ToolAccess; classificationStatus: string | null; pending: boolean
} {
  const raw = tool.metadata.gate_access
  const gate = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
  const status = typeof gate.classification_status === "string" ? gate.classification_status : null
  return {
    access: gate.required_access === "read" || gate.required_access === "write" ? gate.required_access : "unknown",
    classificationStatus: status,
    pending: status === "pending",
  }
}

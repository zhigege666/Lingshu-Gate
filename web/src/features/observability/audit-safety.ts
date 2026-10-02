import type { InvocationAudit } from "@/api/client"
export function auditSafety(item: Pick<InvocationAudit, "decision" | "outcome" | "required_access" | "granted_access">) {
  const rank: Record<string, number> = { none: 0, read: 1, write: 2 }
  const required = rank[item.required_access], granted = rank[item.granted_access]
  const insufficient = required !== undefined && granted !== undefined && granted < required
  if ((item.decision === "deny" && item.outcome !== "not_invoked") || (insufficient && (item.decision === "allow" || item.outcome !== "not_invoked"))) return "inconsistent"
  if (item.decision === "deny" && item.outcome === "not_invoked") return "blocked"
  return item.outcome
}

import type { McpServerPolicy, OAuthGrant } from "./oauth-api"

export type GrantFilter = "active" | "expired" | "revoked" | "all"
export function grantState(grant: OAuthGrant, now: number): string {
  if (grant.state === "revoked") return "revoked"
  if (grant.state === "expired" || grant.expires_at <= now) return "expired"
  return grant.state
}
export function filterGrants(grants: OAuthGrant[], filter: GrantFilter, query: string, now: number): OAuthGrant[] {
  const q = query.trim().toLocaleLowerCase()
  return grants.filter(grant => (filter === "all" || grantState(grant, now) === filter) && (!q ||
    `${grant.client_name} ${grant.client_id} ${grant.id} ${grant.tools.map(tool => `${tool.name} ${tool.id} ${tool.server_name || ""} ${tool.server_id}`).join(" ")}`.toLocaleLowerCase().includes(q)))
}
export function utcGrantTime(seconds?: number): string | null {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) return null
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.valueOf()) ? null : date.toISOString().slice(0, 16).replace("T", " ") + " UTC"
}
export function grantRemaining(seconds: number, now: number, zh: boolean): string {
  const remaining = seconds - now
  if (remaining <= 0) return zh ? "已到期" : "Expired"
  const [amount, unit] = remaining < 3600 ? [Math.ceil(remaining / 60), zh ? "分钟" : "min"]
    : remaining < 86400 ? [Math.ceil(remaining / 3600), zh ? "小时" : "h"] : [Math.ceil(remaining / 86400), zh ? "天" : "days"]
  return zh ? `剩余约 ${amount} ${unit}` : `About ${amount} ${unit} remaining`
}

/** 仅调整配额时保留原工具快照和服务绑定；是否仍可调用由后端当前授权判断。 */
export function isOAuthQuotaOnlyChange(grant: OAuthGrant | null, draft: { toolIds: string[]; policies: McpServerPolicy[]; expiresAt: number; rate: number | null; concurrency: number | null }): boolean {
  if (!grant || draft.rate === null || draft.concurrency === null || draft.expiresAt !== grant.expires_at || (draft.rate === grant.rate_per_minute && draft.concurrency === grant.concurrency)) return false
  const originalIds = new Set(grant.tools.map(tool => tool.id)), nextIds = new Set(draft.toolIds)
  if (originalIds.size !== nextIds.size || [...nextIds].some(id => !originalIds.has(id))) return false
  const previous = new Map((grant.server_policies || []).map(policy => [policy.server_id, policy]))
  if (draft.policies.some(policy => policy.server_binding !== undefined && policy.server_binding !== previous.get(policy.server_id)?.server_binding)) return false
  const intent = (policies: McpServerPolicy[]) => JSON.stringify(policies.map(policy => [policy.server_id, policy.mode, policy.access]).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))))
  return intent(draft.policies) === intent(grant.server_policies || [])
}

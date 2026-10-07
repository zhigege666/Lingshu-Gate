import type { OAuthGrant } from "./oauth-api"

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

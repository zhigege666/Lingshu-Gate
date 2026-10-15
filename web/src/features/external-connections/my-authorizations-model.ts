import type { PersonalToken } from "@/api/client"
import type { OAuthGrant } from "./oauth-api"
import type { Grant } from "./model"

export type Kind = "api" | "builtin" | "external"
export type AuthorizationRow = { key: string; kind: Kind; id: string; name: string; identifier: string; scope: string; rate: number | null; concurrency: number | null; status: string; expiry: string | null; purpose: "business" | "management"; source: PersonalToken | OAuthGrant | Grant }
export function authorizationRows(tokens: PersonalToken[], builtin: OAuthGrant[], external: Grant[], zh: boolean, now = Date.now()): AuthorizationRow[] {
  return [
    ...tokens.map(token => ({ key: `api:${token.id}`, kind: "api" as const, id: token.id, name: token.name, identifier: token.token_prefix, scope: token.authorization_mode !== "independent" ? zh ? "跟随账号资源权限" : "Follows account resource access" : `${new Set([...(token.server_policies || []).map(policy => policy.server_id)]).size} ${zh ? "持续授权 MCP" : "continuous MCPs"} · ${token.tool_ids?.length || 0} ${zh ? "指定工具" : "selected tools"}`, rate: token.rate_per_minute ?? null, concurrency: token.concurrency ?? null, status: token.revoked_at ? "revoked" : token.expires_at && Date.parse(token.expires_at) <= now ? "expired" : "active", expiry: token.expires_at || null, purpose: "business" as const, source: token })),
    ...builtin.map(grant => ({ key: `builtin:${grant.id}`, kind: "builtin" as const, id: grant.id, name: grant.client_name, identifier: `${grant.client_id} · …${grant.id.slice(-8)}`, scope: `${new Set([...grant.tools.map(tool => tool.server_id), ...(grant.server_policies || []).map(policy => policy.server_id)]).size} MCP · ${grant.server_policies?.length || 0} ${zh ? "持续授权" : "continuous"}`, rate: grant.rate_per_minute, concurrency: grant.concurrency, status: grant.state === "revoked" ? "revoked" : grant.expires_at * 1000 <= now ? "expired" : grant.state === "active" ? "active" : "disabled", expiry: new Date(grant.expires_at * 1000).toISOString(), purpose: grant.resource_kind || "business" as const, source: grant })),
    ...external.map(grant => ({ key: `external:${grant.id}`, kind: "external" as const, id: grant.id, name: grant.client_id, identifier: `…${grant.id.slice(-8)}`, scope: `${grant.server_allowlist.length} MCP · ${grant.tool_allowlist.length} ${zh ? "指定工具" : "selected tools"}`, rate: grant.rate_per_minute, concurrency: grant.concurrency, status: ["active", "enabled"].includes(grant.state) ? "active" : grant.state, expiry: grant.expires_at || null, purpose: "business" as const, source: grant })),
  ]
}

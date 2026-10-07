import type { ToolDefinition } from "@/api/client"
export type ConnectionDraft = { enabled: boolean; mode: "disabled" | "direct" | "secure_mcp_tunnel"; endpoint: string | null; canonical_resource_url: string | null; tunnel_reference: string | null; runtime_secret_reference: string | null; trusted_issuers: string[]; issuer_jwks: [string, string][]; client_allowlist: string[]; resource_mappings: [string, string][] }
export type ConnectionSnapshot = Partial<ConnectionDraft> & { revision: number; validation_errors?: string[]; connected?: boolean; oauth_verifier_ready?: boolean; provider_verified?: boolean }
export const emptyConnection: ConnectionDraft = { enabled: false, mode: "disabled", endpoint: null, canonical_resource_url: null, tunnel_reference: null, runtime_secret_reference: null, trusted_issuers: [], issuer_jwks: [], client_allowlist: [], resource_mappings: [] }
export type GrantDraft = { enabled: boolean; client_id: string; server_allowlist: string[]; tool_allowlist: string[]; access: ("read" | "write")[]; expires_at: string; rate_per_minute: number; concurrency: number }
export type Grant = GrantDraft & { id: string; revision: number; state: "enabled" | "active" | "disabled" | "expired" | "revoked"; scope_currently_authorized: boolean; activation_errors?: string[]; limits_enforced?: boolean }
export type GrantList = { grants: Grant[]; connection_ready: boolean; activation_errors: string[]; allowed_client_ids?: string[] }
export type BindingUser = { id: string; username: string; display_name: string; status: string }
export function bindingUserLabel(user: BindingUser | null | undefined, unavailable = "User unavailable") {
  return user ? (user.display_name ? `${user.display_name} (@${user.username})` : `@${user.username}`) : unavailable
}
export type SubjectLink = { id: string; issuer: string; subject: string; user_id: string; user?: BindingUser | null; enabled: boolean; revision: number }
export function httpsResource(value: string) {
  try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash } catch { return false }
}
export function connectionError(draft: ConnectionDraft): string | null {
  if (draft.endpoint && (draft.endpoint.length > 2048 || !httpsResource(draft.endpoint))) return "HTTPS URL: no credentials, query or fragment."
  if (draft.canonical_resource_url && !httpsResource(draft.canonical_resource_url)) return "Canonical resource must be an HTTPS URL without credentials, query or fragment."
  if (draft.tunnel_reference && !/^tunnel:[A-Za-z0-9_.-]{1,128}$/.test(draft.tunnel_reference)) return "Use tunnel:ID; never enter a key."
  if (draft.runtime_secret_reference && !/^credential:[A-Za-z0-9_.-]{1,128}$/.test(draft.runtime_secret_reference)) return "Use credential:ID; never enter a secret."
  if (draft.trusted_issuers.length > 20 || draft.resource_mappings.length > 20) return "At most 20 issuers and mappings are supported."
  if (draft.trusted_issuers.some(value => !httpsResource(value)) || draft.resource_mappings.some(pair => pair.some(value => !httpsResource(value)))) return "Issuer and audience mappings require HTTPS URLs without credentials, query or fragment."
  if (new Set(draft.resource_mappings.map(pair => pair[0])).size !== draft.resource_mappings.length) return "Each external audience must have exactly one canonical resource."
  if (draft.issuer_jwks.some(pair => pair.some(value => !httpsResource(value))) || new Set(draft.issuer_jwks.map(pair => pair[0])).size !== draft.issuer_jwks.length) return "Each issuer needs one fixed HTTPS JWKS URL."
  if (draft.client_allowlist.some(value => !/^[A-Za-z0-9_.:/-]{1,256}$/.test(value))) return "Client allowlist must contain exact client IDs, not secrets."
  return null
}
export function connectionReadiness(draft: ConnectionDraft): string[] {
  const errors: string[] = []
  if (draft.mode === "disabled") errors.push("transport_not_configured")
  if (draft.mode === "direct" && !draft.endpoint) errors.push("https_endpoint_required")
  if (draft.mode === "secure_mcp_tunnel" && (!draft.tunnel_reference || !draft.runtime_secret_reference)) errors.push("tunnel_references_required")
  if (!draft.trusted_issuers.length) errors.push("trusted_issuer_required")
  if (!draft.resource_mappings.length) errors.push("trusted_resource_mapping_required")
  if (!draft.client_allowlist.length || draft.client_allowlist.length > 100) errors.push("trusted_client_required")
  if (!draft.issuer_jwks.length || draft.trusted_issuers.some(issuer => !draft.issuer_jwks.some(pair => pair[0] === issuer && httpsResource(pair[1]))) || draft.issuer_jwks.some(pair => !draft.trusted_issuers.includes(pair[0]))) errors.push("trusted_jwks_mapping_required")
  const canonical = draft.canonical_resource_url || draft.endpoint
  if (!canonical || draft.resource_mappings.some(pair => pair[1] !== canonical)) errors.push("canonical_resource_required")
  if (connectionError(draft)) errors.push("invalid_configuration")
  return errors
}
export function eligibleTools(tools: ToolDefinition[], access: "read" | "write") {
  return tools.filter(tool => {
    const policy = tool.metadata.gate_access as { classification_status?: string; required_access?: string } | undefined
    return tool.source === "mcp" && typeof tool.metadata.server_id === "string" && policy?.classification_status === "published" && policy.required_access === access
  })
}
export function grantError(draft: GrantDraft, tools: ToolDefinition[], now = Date.now()): string | null {
  if (!/^[A-Za-z0-9_.:/-]{1,256}$/.test(draft.client_id)) return "Enter a client ID, not a secret."
  if (!Number.isFinite(Date.parse(draft.expires_at)) || Date.parse(draft.expires_at) <= now) return "Choose a future expiry."
  if (!Number.isInteger(draft.rate_per_minute) || draft.rate_per_minute < 1 || draft.rate_per_minute > 10000 || !Number.isInteger(draft.concurrency) || draft.concurrency < 1 || draft.concurrency > 100) return "Rate and concurrency must be whole numbers within the displayed bounds."
  if (!draft.access.length || draft.access.some(value => !["read", "write"].includes(value))) return "Choose an access level."
  const eligible = new Set(draft.access.flatMap(access => eligibleTools(tools, access).map(tool => tool.id)))
  if (!draft.tool_allowlist.length || draft.tool_allowlist.length > 1000 || draft.tool_allowlist.some(id => !eligible.has(id))) return "Select currently authorized published tools; unavailable selections must be removed."
  if (!draft.server_allowlist.length || draft.server_allowlist.length > 100) return "Select tools from at most 100 services."
  const selectedTools = tools.filter(tool => draft.tool_allowlist.includes(tool.id))
  const levels = new Set(selectedTools.map(tool => (tool.metadata.gate_access as { required_access: string }).required_access))
  if (draft.access.some(access => !levels.has(access))) return "Access must match the selected tools."
  const servers = new Set(selectedTools.map(tool => String(tool.metadata.server_id)))
  if (servers.size !== draft.server_allowlist.length || draft.server_allowlist.some(id => !servers.has(id))) return "Service scope must match the selected tools."
  return null
}
export function connectionDraft(snapshot: ConnectionSnapshot): ConnectionDraft {
  return { ...emptyConnection, enabled: snapshot.enabled ?? false, issuer_jwks: snapshot.issuer_jwks ?? [], client_allowlist: snapshot.client_allowlist ?? [], mode: snapshot.mode ?? "disabled", endpoint: snapshot.endpoint ?? null, canonical_resource_url: snapshot.canonical_resource_url ?? null, tunnel_reference: snapshot.tunnel_reference ?? null, runtime_secret_reference: snapshot.runtime_secret_reference ?? null, trusted_issuers: snapshot.trusted_issuers ?? [], resource_mappings: snapshot.resource_mappings ?? [] }
}

export function transportLabel(mode: ConnectionDraft["mode"], zh: boolean): string {
  const labels = {
    disabled: ["未选择传输方式", "No transport selected"],
    direct: ["公网 HTTPS 直连", "Direct HTTPS"],
    secure_mcp_tunnel: ["安全 MCP 隧道", "Secure MCP Tunnel"],
  }
  return labels[mode][zh ? 0 : 1]
}

/** Step completion is configuration-only, never proof of external connectivity. */
export function connectionGuideStepErrors(draft: ConnectionDraft, step: number): string[] {
  const errors = connectionReadiness(draft)
  if (step === 0) return errors.filter(reason => ["transport_not_configured", "https_endpoint_required", "tunnel_references_required", "invalid_configuration"].includes(reason))
  if (step === 1) return errors
  return []
}

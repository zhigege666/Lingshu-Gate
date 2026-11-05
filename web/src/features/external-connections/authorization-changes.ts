import type { McpServerPolicy } from "./oauth-api"
import type { ConnectionDraft, GrantDraft } from "./model"

/** Continuous access also covers future tools, so compare policies, not only today's IDs. */
export function expandsServerPolicies(before: readonly McpServerPolicy[], after: readonly McpServerPolicy[]): boolean {
  const previous = new Map(before.map(policy => [policy.server_id, policy]))
  return after.some(policy => {
    const saved = previous.get(policy.server_id)
    return !saved || saved.server_binding !== policy.server_binding || (saved.access === "read" && policy.access === "write")
  })
}

type TokenAccess = { mode: "account" | "independent"; scopes: readonly string[]; server_policies: readonly McpServerPolicy[] }

/** The preview remains authoritative for added or changed exact-tool snapshots. */
export function expandsTokenAccess(before: TokenAccess, after: TokenAccess, addedTools: readonly string[]): boolean {
  if (!before.scopes.includes("*") && after.scopes.some(scope => !before.scopes.includes(scope))) return true
  if (before.mode === "account") return false
  if (after.mode === "account") return true
  return addedTools.length > 0 || expandsServerPolicies(before.server_policies, after.server_policies)
}

/** Removing a management target/action never requires another review screen. */
export function expandsManagementTargets(before: Record<string, string[]>, after: Record<string, string[]>): boolean {
  return Object.entries(after).some(([id, actions]) => actions.some(action => !before[id]?.includes(action)))
}

export function expandsExternalTrust(before: ConnectionDraft, after: ConnectionDraft): boolean {
  if (!after.enabled) return false
  if (!before.enabled || before.mode !== after.mode) return true
  if ((before.canonical_resource_url || before.endpoint) !== (after.canonical_resource_url || after.endpoint)) return true
  if (after.mode === "direct" && before.endpoint !== after.endpoint) return true
  if (after.mode === "secure_mcp_tunnel" && (before.tunnel_reference !== after.tunnel_reference || before.runtime_secret_reference !== after.runtime_secret_reference)) return true
  return after.trusted_issuers.some(issuer => !before.trusted_issuers.includes(issuer))
    || after.client_allowlist.some(client => !before.client_allowlist.includes(client))
    || after.issuer_jwks.some(pair => !before.issuer_jwks.some(saved => saved[0] === pair[0] && saved[1] === pair[1]))
    || after.resource_mappings.some(pair => !before.resource_mappings.some(saved => saved[0] === pair[0] && saved[1] === pair[1]))
}

export function expandsExternalGrant(before: GrantDraft, after: GrantDraft): boolean {
  if (!after.enabled) return false
  return !before.enabled || before.client_id !== after.client_id
    || after.tool_allowlist.some(id => !before.tool_allowlist.includes(id))
    || after.access.some(access => !before.access.includes(access))
    || Date.parse(after.expires_at) > Date.parse(before.expires_at)
}

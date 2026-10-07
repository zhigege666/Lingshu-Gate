import type { OAuthClient, OAuthConfig } from "./oauth-api"

export type OAuthConfigDraft = Pick<OAuthConfig, "issuer" | "resource" | "enabled">
export type SigningKeyState = { phase: "loading" } | { phase: "error" } | { phase: "ready"; count: number }

// Suggestions only: the backend remains the authority for URL validation.
// Keep the exact issuer text, as persisted issuer/resource comparisons are exact.
export function suggestedMcpResource(issuer: string): string | null {
  if (issuer.length > 2048 || !/^https:\/\/[^/?#]+$/i.test(issuer) || /[^\x21-\x7e]|[\\"<>*]/.test(issuer)) return null
  try {
    const url = new URL(issuer)
    if (!url.hostname || url.username || url.password || url.port === "0") return null
    return `${issuer}/mcp`
  } catch { return null }
}

export function editOAuthIssuer(draft: OAuthConfigDraft, issuer: string, automaticResource: string | null) {
  const mayDerive = draft.resource === "" || (automaticResource !== null && draft.resource === automaticResource)
  const resource = mayDerive ? suggestedMcpResource(issuer) ?? "" : draft.resource
  return { draft: { ...draft, issuer, resource }, automaticResource: mayDerive ? resource || null : null }
}

export function signingKeyState(keys: unknown): SigningKeyState {
  if (!Array.isArray(keys) || keys.some(key => !key || typeof key !== "object" || typeof key.kid !== "string" || !key.kid || typeof key.active !== "boolean" || !(key.retire_at === null || Number.isFinite(key.retire_at)))) return { phase: "error" }
  // Retained verification keys cannot authorize new signing operations.
  return { phase: "ready", count: keys.filter(key => key.active === true && key.retire_at === null).length }
}

export function canEnableOAuth(keys: SigningKeyState): boolean {
  return keys.phase === "ready" && keys.count > 0
}

/** Saved prerequisites only; this does not claim external connectivity. */
export function showOAuthSetupSteps(config: Pick<OAuthConfig, "issuer" | "resource" | "enabled"> | null, keys: SigningKeyState, clientsReady: boolean, clients: Pick<OAuthClient, "enabled">[]): boolean {
  return !config?.enabled || !config.issuer || !config.resource || !canEnableOAuth(keys) || !clientsReady || !clients.some(client => client.enabled)
}

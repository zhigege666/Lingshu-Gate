import type { Credential } from "@/api/client"

/** Keys stay in this editor session and contain no credential data. */
export function credentialWriteKey(): string {
  return "credential-" + Array.from(crypto.getRandomValues(new Uint8Array(24)), byte => byte.toString(16).padStart(2, "0")).join("")
}

/** A scope stores an origin, never a path, URL credentials, query, or fragment. */
export function credentialHttpOrigin(endpoint: unknown): string | null {
  if (typeof endpoint !== "string" || /[\s\\?#]/.test(endpoint)) return null
  try {
    const url = new URL(endpoint)
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null
    return `${url.protocol}//${url.hostname}:${url.port || (url.protocol === "https:" ? 443 : 80)}`
  } catch { return null }
}

/** Display readiness only; the backend still verifies the current service identity. */
export function credentialMatchesHttpTarget(credential: Credential, serverId: string, endpoint: unknown,
  savedService = true, serverBinding?: string | null): boolean {
  const origin = credentialHttpOrigin(endpoint)
  return Boolean(origin && credential.http_scopes?.some(scope => scope.server_id === serverId
    && credentialHttpOrigin(scope.origin) === origin && (scope.server_binding == null || scope.pending_rebind === true
      || savedService && (serverBinding === undefined || scope.server_binding === serverBinding))))
}

/** Matches the HTTP service contract; credential IDs have their own 512-character limit. */
export function validHttpServiceId(serverId: string): boolean {
  return /^[A-Za-z0-9_.-]{1,128}$/.test(serverId)
}

/** The server merges this explicit target into its latest scopes under its lock. */
export function credentialHttpTarget(credential: Credential, serverId: string, endpoint: unknown): { server_id: string; origin: string } {
  const origin = credentialHttpOrigin(endpoint)
  if (!origin || !validHttpServiceId(serverId)) throw new Error("invalid_credential_target")
  const scopes = (credential.http_scopes || []).filter(scope => scope.server_id !== serverId || credentialHttpOrigin(scope.origin) !== origin)
  if (scopes.length >= 100) throw new Error("credential_target_limit")
  return { server_id: serverId, origin }
}

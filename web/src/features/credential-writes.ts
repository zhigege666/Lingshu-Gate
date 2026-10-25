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

import { isStringMap } from "./model"

export type HttpAuthKind = "none" | "bearer" | "api_key" | "basic" | "custom"
export type HttpAuthSelection = { kind: HttpAuthKind; credentialId: string; headerName: string }
const reference = /^\$\{credential:([A-Za-z0-9_.-]+)\}$/
const reserved = new Set(["host", "content-length", "transfer-encoding", "connection", "proxy-authorization", "content-type", "accept", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name", "traceparent", "tracestate", "baggage", "x-correlation-id"])

/** Infer only losslessly representable presets. Unknown values remain advanced. */
export function inferHttpAuth(value: unknown): HttpAuthSelection {
  const fallback: HttpAuthSelection = { kind: "custom", credentialId: "", headerName: "" }
  if (value === undefined) return { ...fallback, kind: "none" }
  if (!isStringMap(value)) return fallback
  const entries = Object.entries(value)
  if (new Set(entries.map(([key]) => key.toLowerCase())).size !== entries.length) return fallback
  const secrets = entries.filter(([key, item]) => /auth|token|key|secret|password|cookie/i.test(key) || /\$\{credential:/.test(item))
  if (secrets.length > 1) return fallback
  const auth = entries.find(([key]) => key.toLowerCase() === "authorization")
  if (auth) {
    const match = /^(Bearer|Basic) \$\{credential:([A-Za-z0-9_.-]+)\}$/.exec(auth[1])
    return match ? { kind: match[1] === "Basic" ? "basic" : "bearer", credentialId: match[2], headerName: auth[0] }
      : { ...fallback, headerName: auth[0] }
  }
  if (!secrets.length) return { ...fallback, kind: "none" }
  if (secrets.length === 1 && reference.test(secrets[0][1])) return {
    kind: "api_key", credentialId: reference.exec(secrets[0][1])![1], headerName: secrets[0][0],
  }
  return fallback
}

/** A preset changes only its owned header; unrelated/custom fields are retained. */
export function httpAuthHeaders(value: unknown, previous: HttpAuthSelection, next: HttpAuthSelection): Record<string, string> {
  if (value !== undefined && !isStringMap(value)) throw new Error("custom_headers_required")
  const headers = { ...(value || {}) as Record<string, string> }
  if (next.kind === "custom") return headers
  if (new Set(Object.keys(headers).map(key => key.toLowerCase())).size !== Object.keys(headers).length) throw new Error("duplicate_headers")
  if (previous.kind === "custom" && !previous.headerName && Object.keys(headers).length) throw new Error("custom_headers_required")
  if (next.kind !== "none" && !/^[A-Za-z0-9_.-]+$/.test(next.credentialId)) throw new Error("credential_required")
  const key = next.kind === "api_key" ? next.headerName : "Authorization"
  if (next.kind !== "none" && (!/^[A-Za-z0-9-]{1,128}$/.test(key) || reserved.has(key.toLowerCase()))) throw new Error("invalid_auth_header")
  const collision = Object.keys(headers).find(name => name.toLowerCase() === key.toLowerCase() && name.toLowerCase() !== previous.headerName.toLowerCase())
  if (collision && next.kind !== "none") throw new Error("header_conflict")
  if (previous.headerName) for (const name of Object.keys(headers)) {
    if (name.toLowerCase() === previous.headerName.toLowerCase()) delete headers[name]
  }
  if (next.kind !== "none") headers[key] = `${next.kind === "bearer" ? "Bearer " : next.kind === "basic" ? "Basic " : ""}\${credential:${next.credentialId}}`
  return headers
}

/** Raw secret inputs are used only for a separate encrypted credential write. */
export function prepareHttpSecret(format: "raw" | "bearer" | "basic", secret: string, username = ""): string {
  if (!secret || secret === "***" || /[\r\n]/.test(secret)) throw new Error("invalid_secret")
  if (format === "basic") {
    if (!username || /[:\r\n]/.test(username)) throw new Error("invalid_basic_username")
    const bytes = new TextEncoder().encode(`${username}:${secret}`)
    return btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(""))
  }
  if (format === "raw") {
    if (!secret.trim()) throw new Error("invalid_secret")
    return secret
  }
  const token = secret.trim().replace(/^Bearer\s+/i, "")
  if (!token || /\s/.test(token) || token === "***") throw new Error("invalid_secret")
  return token
}

/** Never guess ports or overwrite a supplied MCP path. This requires an explicit click. */
export function homeMcpEndpoint(endpoint: unknown): string | null {
  if (typeof endpoint !== "string" || /[\s\\]/.test(endpoint)) return null
  try {
    const url = new URL(endpoint)
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !["", "/"].includes(url.pathname)) return null
    url.pathname = "/mcp"
    return url.toString()
  } catch { return null }
}

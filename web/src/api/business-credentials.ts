import { queryString } from "./http"

export type BusinessCredentialScope = "personal" | "shared"
export type BusinessCredentialBinding = {
  id: string; credential_id: string; server_id: string; adapter: "agent_browser"
  tool_prefix: "agent_browser_" | ""; enabled: boolean; revision: number
  synced_version: number | null; sync_status: "pending" | "synced" | "failed" | "unknown" | "deleted"
  last_sync_at: string | null; last_error_code: string | null
}
export type BusinessCredential = {
  id: string; owner_id: string; name: string; environment: string; business_role: string
  login_url: string; scope: BusinessCredentialScope; enabled: boolean; allow_http: boolean
  version: number; username_masked: string; password_configured: boolean
  allowed_user_ids: string[]; allowed_role_ids: string[]
  selectors: { username?: string | null; password?: string | null; submit?: string | null }
  created_at: string; updated_at: string; bindings: BusinessCredentialBinding[]
}
export type BusinessCredentialWrite = {
  name: string; environment: string; business_role: string; login_url: string
  username: string | null; password: string | null; enabled: boolean; allow_http: boolean
  allowed_user_ids: string[]; allowed_role_ids: string[]; selectors: BusinessCredential["selectors"]
}
export type BusinessCredentialTargets = {
  servers: { server_id: string; name: string; compatible: boolean; reason?: string; managed?: boolean; safe_tools?: string[];
    tool_prefix?: "agent_browser_" | ""; compatible_prefixes?: ("agent_browser_" | "")[] }[]
  users: { id: string; label: string }[]; roles: { id: string; label: string }[]
}
export type BusinessBindingWrite = {
  server_id: string; adapter: "agent_browser"; tool_prefix: "agent_browser_" | ""; enabled: boolean
  expected_version: number; expected_revision?: number; confirm_managed_mode?: true
}
export type BusinessCredentialSession = { id: string; server_id: string; logical_session: string; status: "active" | "unknown" | "closed";
  credential_version: number; created_at: string; updated_at: string }

export class BusinessCredentialRequestError extends Error {
  constructor(public status: number, public code: string) { super(code) }
}

/** Never render a validation input, remote stdout/stderr, or an arbitrary error body. */
async function businessRequest<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) abort()
  signal?.addEventListener("abort", abort, { once: true })
  const timer = setTimeout(abort, init.method && init.method !== "GET" ? 150_000 : 20_000)
  try {
    const response = await fetch(path, { ...init, credentials: "include", cache: "no-store",
      headers: { "Content-Type": "application/json", ...init.headers }, signal: controller.signal })
    const text = await response.text()
    if (!response.ok) {
      let code = "business_credential_request_failed"
      try {
        const detail = JSON.parse(text)?.detail
        if (detail && typeof detail.code === "string" && /^[a-z_]{1,100}$/.test(detail.code)) code = detail.code
      } catch { /* An untrusted body is not user-facing diagnostic text. */ }
      throw new BusinessCredentialRequestError(response.status, code)
    }
    return (text ? JSON.parse(text) : {}) as T
  } catch (error) {
    if (error instanceof BusinessCredentialRequestError) throw error
    throw new BusinessCredentialRequestError(0, controller.signal.aborted ? "business_credential_request_timeout" : "business_credential_request_failed")
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", abort) }
}

const base = "/v1/business-credentials"
const credentialPath = (id: string) => `${base}/${encodeURIComponent(id)}`
const bindingPath = (id: string, bindingId: string) => `${credentialPath(id)}/bindings/${encodeURIComponent(bindingId)}`
export function canonicalBusinessCredentialBody(value: unknown): string {
  const ordered = (item: unknown): unknown => Array.isArray(item) ? item.map(ordered) : item && typeof item === "object"
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, entry]) => [key, ordered(entry)])) : item
  return JSON.stringify(ordered(value))
}
async function mutate<T>(path: string, method: "POST" | "PUT" | "DELETE", body: object = {}): Promise<T> {
  const bytes = new TextEncoder().encode(canonicalBusinessCredentialBody(body))
  const hex = (value: Uint8Array) => Array.from(value, byte => byte.toString(16).padStart(2, "0")).join("")
  // The ticket endpoint/logs see only an HMAC. Its random key travels solely
  // with the actual mutation, so the ticket cannot be used to guess a password.
  const nonce = crypto.getRandomValues(new Uint8Array(32))
  const key = await crypto.subtle.importKey("raw", nonce, { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
  const digest = hex(new Uint8Array(await crypto.subtle.sign("HMAC", key, bytes)))
  const ticket = await businessRequest<{ csrf: string }>(base + "/csrf" + queryString({ target: `${method}:${path}`, request_digest: digest }), { method: "POST" })
  return businessRequest<T>(path, { method, headers: { "X-CSRF-Token": ticket.csrf, "X-CSRF-Nonce": hex(nonce) }, body: JSON.stringify(body) })
}
export const businessCredentialsApi = {
  list: (scope: BusinessCredentialScope, signal?: AbortSignal) => businessRequest<{ credentials: BusinessCredential[] }>(base + queryString({ scope }), {}, signal),
  targets: (scope: BusinessCredentialScope, signal?: AbortSignal) => businessRequest<BusinessCredentialTargets>(base + "/targets" + queryString({ scope }), {}, signal),
  create: (body: BusinessCredentialWrite & { scope: BusinessCredentialScope }) => mutate<BusinessCredential>(base, "POST", body),
  update: (id: string, body: BusinessCredentialWrite & { expected_version: number }) => mutate<BusinessCredential>(credentialPath(id), "PUT", body),
  delete: (id: string, expected_version: number) => mutate<{ deleted: boolean }>(credentialPath(id) + queryString({ expected_version }), "DELETE"),
  createBinding: (id: string, body: BusinessBindingWrite) => mutate<BusinessCredentialBinding>(credentialPath(id) + "/bindings", "POST", body),
  updateBinding: (id: string, bindingId: string, body: BusinessBindingWrite) => mutate<BusinessCredentialBinding>(bindingPath(id, bindingId), "PUT", {
    expected_version: body.expected_version, expected_revision: body.expected_revision, enabled: body.enabled,
  }),
  deleteBinding: (id: string, bindingId: string, expected_revision: number) => mutate<{ deleted: boolean }>(bindingPath(id, bindingId) + queryString({ expected_revision }), "DELETE"),
  sync: (id: string, bindingId: string, expected_version: number, expected_revision: number) => mutate<BusinessCredentialBinding>(bindingPath(id, bindingId) + "/sync", "POST", { expected_version, expected_revision }),
  deleteRemote: (id: string, bindingId: string, expected_version: number, expected_revision: number) => mutate<BusinessCredentialBinding>(bindingPath(id, bindingId) + "/delete-remote", "POST", { expected_version, expected_revision }),
  sessions: (id: string, signal?: AbortSignal) => businessRequest<{ sessions: BusinessCredentialSession[] }>(credentialPath(id) + "/sessions", {}, signal),
  closeSession: (id: string, sessionId: string) => mutate<{ status: "closed"; website_logout_verified: false }>(credentialPath(id) + "/sessions/" + encodeURIComponent(sessionId) + "/close", "POST"),
}

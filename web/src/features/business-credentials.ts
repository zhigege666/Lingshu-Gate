import type { BusinessCredential, BusinessCredentialScope, BusinessCredentialWrite } from "@/api/business-credentials"

export type BusinessCredentialDraft = Omit<BusinessCredentialWrite, "username" | "password"> & { username: string; password: string }

export function emptyBusinessCredentialDraft(): BusinessCredentialDraft {
  return { name: "", environment: "", business_role: "", login_url: "", username: "", password: "", enabled: true,
    allow_http: false, allowed_user_ids: [], allowed_role_ids: [], selectors: {} }
}

export function businessCredentialDraft(record: BusinessCredential): BusinessCredentialDraft {
  return { name: record.name, environment: record.environment, business_role: record.business_role, login_url: record.login_url,
    username: "", password: "", enabled: record.enabled, allow_http: record.allow_http,
    allowed_user_ids: [...record.allowed_user_ids], allowed_role_ids: [...record.allowed_role_ids], selectors: { ...record.selectors } }
}

/** Empty edit inputs preserve encrypted values. A mask is never submitted as a value. */
export function businessCredentialWrite(draft: BusinessCredentialDraft, editing: boolean, scope: BusinessCredentialScope): BusinessCredentialWrite {
  return { ...draft, name: draft.name.trim(), environment: draft.environment.trim(), business_role: draft.business_role.trim(),
    login_url: draft.login_url.trim(), username: editing && draft.username === "" ? null : draft.username,
    password: editing && draft.password === "" ? null : draft.password,
    allowed_user_ids: scope === "shared" ? [...draft.allowed_user_ids] : [],
    allowed_role_ids: scope === "shared" ? [...draft.allowed_role_ids] : [],
    selectors: Object.fromEntries(Object.entries(draft.selectors).filter(([, value]) => Boolean(value?.trim())).map(([key, value]) => [key, value!.trim()])) }
}

export function secureBusinessCredentialTransport(location: { protocol: string; hostname: string }): boolean {
  return location.protocol === "https:" || ["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname)
}

export function validateBusinessCredentialDraft(draft: BusinessCredentialDraft, editing: boolean): Record<string, "required" | "url" | "http" | "mask"> {
  const errors: Record<string, "required" | "url" | "http" | "mask"> = {}
  for (const key of ["name", "login_url"] as const) if (!draft[key].trim()) errors[key] = "required"
  if (!editing && !draft.username.trim()) errors.username = "required"
  if (!editing && !draft.password.trim()) errors.password = "required"
  if (["***", "**********"].includes(draft.username)) errors.username = "mask"
  if (["***", "**********"].includes(draft.password)) errors.password = "mask"
  if (draft.login_url.trim()) {
    try {
      const url = new URL(draft.login_url)
      const safeFragment = !url.hash || url.hash.startsWith("#/") && !url.hash.includes("?") && !url.hash.includes("=")
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || !safeFragment) errors.login_url = "url"
      else if (url.protocol === "http:" && !draft.allow_http) errors.login_url = "http"
    } catch { errors.login_url = "url" }
  }
  return errors
}

export function filterBusinessCredentials(records: BusinessCredential[], query: string, status: string): BusinessCredential[] {
  const needle = query.trim().toLocaleLowerCase()
  return records.filter(record => (status === "all" || record.enabled === (status === "enabled"))
    && `${record.name} ${record.environment} ${record.business_role} ${record.login_url} ${record.id}`.toLocaleLowerCase().includes(needle))
}

export function businessCredentialPrompt(record: BusinessCredential): string {
  return JSON.stringify({ name: `gate:${record.id}`, session: "task-session" }, null, 2)
}

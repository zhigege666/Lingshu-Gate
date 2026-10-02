/** Preserve actionable structured errors without rendering request inputs or secret-bearing details. */
export function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) return detail.map(issue => {
    if (!issue || typeof issue !== "object") return fallback
    const path = Array.isArray(issue.loc) ? issue.loc.filter((part: unknown) => typeof part === "string" || typeof part === "number").join(".") : ""
    return `${path ? `${path}: ` : ""}${typeof issue.msg === "string" ? issue.msg : fallback}`
  }).join("; ") || fallback
  if (detail && typeof detail === "object") {
    const error = detail as Record<string, unknown>
    return [error.code, error.message, error.next_action].filter((value): value is string => typeof value === "string" && value.length > 0).join(" · ") || fallback
  }
  return fallback
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : {}
  if (!response.ok) {
    throw new Error(apiErrorMessage(body?.detail, `${response.status} ${response.statusText}`))
  }
  return body as T
}

export async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", credentials: "include", body })
  const text = await response.text()
  const payload = text ? JSON.parse(text) : {}
  if (!response.ok) throw new Error(apiErrorMessage(payload?.detail, `${response.status} ${response.statusText}`))
  return payload as T
}

export function queryString(filters: object): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === "") continue
    params.set(key, String(value))
  }
  const query = params.toString()
  return query ? `?${query}` : ""
}

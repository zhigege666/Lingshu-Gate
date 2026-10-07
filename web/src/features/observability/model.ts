import type { EventFilters, LogFilters, ObservabilityMcpScope } from "@/api/observability"

export type ObservabilitySelection = { logs: LogFilters; events: EventFilters; tab: "logs" | "events" }
export const scopePageSize = 40
export function cleanObservabilityFilters<T extends object>(filters: T): T {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== undefined && value !== "")) as T
}
export function exactScopeId(value: string): string | null {
  const id = value.trim()
  return /^[a-zA-Z0-9_.-]{1,256}$/.test(id) ? id : null
}
export function scopeOptionLabel(scope: ObservabilityMcpScope, historicalLabel: string): string {
  const identity = scope.name === scope.id ? scope.id : `${scope.name} · ${scope.id}`
  return scope.availability === "historical" ? `${identity} · ${historicalLabel}` : identity
}
export function readObservabilityHash(hash: string): ObservabilitySelection {
  const fallback: ObservabilitySelection = { logs: { limit: 80 }, events: { limit: 80 }, tab: "logs" }
  const [path, query = ""] = hash.split("?", 2)
  if (!/^#\/?logs(?:\/|$)/.test(path)) return fallback
  const params = new URLSearchParams(query)
  let serverId: string | undefined
  try { serverId = exactScopeId(decodeURIComponent(path.replace(/^#\/?logs\/?/, ""))) || undefined }
  catch { serverId = undefined }
  const logs: LogFilters = { limit: 80, server_id: serverId }
  const events: EventFilters = { limit: 80, server_id: serverId }
  for (const key of ["level", "tool_id", "event_type", "source", "keyword"] as const) {
    const value = params.get(`log_${key}`)
    if (value) logs[key] = value
  }
  for (const key of ["event_type", "source", "keyword"] as const) {
    const value = params.get(`event_${key}`)
    if (value) events[key] = value
  }
  for (const [prefix, filters] of [["log", logs], ["event", events]] as const) {
    const limit = Number(params.get(`${prefix}_limit`))
    if ([50, 80, 100, 200, 500].includes(limit)) filters.limit = limit
  }
  return { logs: cleanObservabilityFilters(logs), events: cleanObservabilityFilters(events), tab: params.get("tab") === "events" ? "events" : "logs" }
}
export function observabilityHash(selection: ObservabilitySelection): string {
  const params = new URLSearchParams({ tab: selection.tab })
  for (const [prefix, filters] of [["log", selection.logs], ["event", selection.events]] as const) {
    for (const [key, value] of Object.entries(cleanObservabilityFilters(filters))) {
      if (key !== "server_id" && key !== "subject_id") params.set(`${prefix}_${key}`, String(value))
    }
  }
  return `#/logs/${encodeURIComponent(selection.logs.server_id || "")}?${params}`
}
/** Ownership is independent from abort: a transport may ignore cancellation. */
export function createRequestOwner() {
  let revision = 0
  return { next: () => ++revision, owns: (id: number) => id === revision, invalidate: () => { revision += 1 } }
}

/** Changing the parent scope invalidates the child filter; reselecting is idempotent. */
export function changeLogScope(current: LogFilters, serverId: string): LogFilters {
  return { ...current, server_id: serverId || undefined,
    tool_id: (current.server_id || "") === serverId ? current.tool_id : undefined }
}

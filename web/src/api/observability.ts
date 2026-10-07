import { queryString, request } from "@/api/http"

export type HealthResponse = {
  status: string
  service: string
  version: string
  checks?: Record<string, { ok: boolean; detail: string; metadata: Record<string, unknown> }>
}

export type ObservabilityLog = {
  id: string
  level: string
  source: string
  server_id?: string | null
  tool_id?: string | null
  event_type?: string | null
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export type ObservabilityEvent = {
  id: string
  type: string
  source: string
  subject_type?: string | null
  subject_id?: string | null
  payload: Record<string, unknown>
  created_at: string
}

export type LogFilters = {
  level?: string
  server_id?: string
  tool_id?: string
  event_type?: string
  source?: string
  keyword?: string
  limit?: number
}

export type ObservabilityMcpScope = { id: string; name: string; availability: "current" | "historical" }
export type ObservabilityMcpScopes = { scopes: ObservabilityMcpScope[]; total: number; offset: number; limit: number; capabilities: { can_read_all: boolean; all_scope: "global" | "authorized_services" } }

export type EventFilters = {
  server_id?: string
  event_type?: string
  subject_id?: string
  source?: string
  keyword?: string
  limit?: number
}

export type DiagnosticsResponse = {
  ok: boolean
  checks: Array<{ name: string; ok: boolean; severity: string; detail: string; metadata: Record<string, unknown> }>
  summary: Record<string, unknown>
}

export const observabilityApi = {
  health: () => request<HealthResponse>("/healthz"),
  diagnostics: () => request<DiagnosticsResponse>("/v1/diagnostics"),
  runDiagnostics: () => request<DiagnosticsResponse>("/v1/diagnostics/run", { method: "POST" }),
  logs: (filters: LogFilters = {}, signal?: AbortSignal) => request<{ logs: ObservabilityLog[] }>(`/v1/logs${queryString(filters)}`, { signal }),
  events: (filters: EventFilters = {}, signal?: AbortSignal) => request<{ events: ObservabilityEvent[] }>(`/v1/events${queryString(filters)}`, { signal }),
  observabilityToolScopes: (filters: { server_id: string; q?: string; tool_id?: string; limit?: number; offset?: number }, signal?: AbortSignal) => request<Omit<ObservabilityMcpScopes, "capabilities">>(`/v1/observability/tool-scopes${queryString(filters)}`, { signal }),
  observabilityMcpScopes: (filters: { q?: string; server_id?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) => request<ObservabilityMcpScopes>(`/v1/observability/mcp-scopes${queryString(filters)}`, { signal }),
}

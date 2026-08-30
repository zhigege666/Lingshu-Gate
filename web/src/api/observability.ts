import { queryString, request } from "@/api/http"

export type HealthResponse = {
  status: string
  service: string
  version: string
  tool_count: number
  mcp_server_count: number
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

export type EventFilters = {
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
  logs: (filters: LogFilters = {}) => request<{ logs: ObservabilityLog[] }>(`/v1/logs${queryString(filters)}`),
  events: (filters: EventFilters = {}) => request<{ events: ObservabilityEvent[] }>(`/v1/events${queryString(filters)}`),
}

import { request } from "@/api/http"
import type { ObservabilityEvent, ObservabilityLog } from "@/api/observability"

export type McpServer = {
  id: string
  name?: string | null
  enabled: boolean
  launch_type: string
  transport_type: string
  status: string
  pid?: number | null
  tool_count: number
  last_error?: string | null
  manifest_path?: string | null
  restart_policy: Record<string, unknown>
  restart_count: number
  restart_attempts: number
  last_exit_code?: number | null
  last_started_at?: string | null
  last_exited_at?: string | null
  last_restart_at?: string | null
  next_restart_at?: string | null
  consecutive_health_failures: number
  last_health_check_at?: string | null
  last_health_ok_at?: string | null
  health_status: string
  desired_state?: "running" | "stopped"
  desired_state_source?: string
  desired_state_updated_at?: string | null
  desired_state_revision?: number
  effective_should_run?: boolean
  restore_blocked_reason?: string | null
  allowed_actions?: Array<"start" | "stop" | "restart">
}

export type RuntimeCachePathInfo = {
  path: string
  exists: boolean
  is_dir: boolean
  readable: boolean
  writable: boolean
  parent_writable: boolean
}

export type RuntimeCacheItem = RuntimeCachePathInfo & {
  name: string
  size_bytes: number
  file_count: number
  last_modified_at?: string | null
}

export type RuntimeCacheStatus = {
  root: RuntimeCachePathInfo
  total_size_bytes: number
  caches: RuntimeCacheItem[]
}

export type RuntimeCacheClearResponse = {
  cache: string
  removed: boolean
  before: RuntimeCacheItem
  after: RuntimeCacheItem
}

export type ManifestValidationCheck = {
  name: string
  severity: "error" | "warning" | "info" | "ok"
  message: string
  metadata: Record<string, unknown>
}

export type ManifestValidationResponse = {
  ok: boolean
  can_apply: boolean
  manifest_id?: string | null
  summary: { errors: number; warnings: number; info: number; ok: number }
  checks: ManifestValidationCheck[]
}

export type RestartHistoryItem = {
  id: string
  server_id: string
  event_type: string
  level: string
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export type RecoveryChartItem = {
  event_type: string
  label?: string | null
  count: number
}

export type RecoverySummary = {
  restart_policy_enabled?: boolean
  restart_on_exit?: boolean
  health_check_enabled?: boolean
  health_check_method?: string
  total_events?: number
  error_events?: number
  warning_events?: number
  info_events?: number
  scheduled_restarts?: number
  auto_restarts?: number
  exhausted_restarts?: number
  skipped_exit_code_restarts?: number
  health_failures?: number
  health_recoveries?: number
  attempts_remaining?: number
  active_restart_scheduled?: boolean
  latest_event_type?: string | null
  latest_event_label?: string | null
  latest_event_level?: string | null
  latest_event_at?: string | null
  manifest_auto_start?: boolean
}

export type McpServerDetail = {
  server: McpServer
  manifest: Record<string, unknown>
  runtime_cache: Record<string, unknown>
  timeline: Array<{ created_at?: string | null; level?: string | null; source: string; event_type: string; message?: string | null; payload: Record<string, unknown> }>
  recent_stdout: string[]
  recent_stderr: string[]
  logs: ObservabilityLog[]
  events: ObservabilityEvent[]
  tools: Array<Record<string, unknown>>
  failure_hints: Array<{ severity: string; code: string; message: string }>
  restart_history: RestartHistoryItem[]
  recovery_chart: RecoveryChartItem[]
  recovery_summary: RecoverySummary
}

export type McpServerListResponse = { servers: McpServer[]; load_errors: string[] }

export type ToolDefinition = {
  id: string
  name: string
  description: string
  permission: string
  input_schema: Record<string, unknown>
  source: string
  metadata: Record<string, unknown>
}

export type LaunchCapability = { available: boolean; reason: string }

export type RuntimeEnvironment = {
  platform: string
  python_version: string
  gate_deployment: "host" | "container" | string
  docker: {
    cli_available: boolean
    binary: string
    version: string
    daemon_reachable: boolean
    socket_present: boolean
    mode: "native" | "dood" | "unavailable" | string
  }
  toolchain: Record<string, boolean>
  launch_capabilities: Record<string, LaunchCapability>
}

export type McpConfig = {
  id: string
  path: string
  format: string
  manifest: Record<string, unknown>
}

export type McpConfigListResponse = { configs: McpConfig[]; errors: string[] }

export type ApplyResponse = {
  config?: McpConfig | null
  server?: McpServer | null
  servers?: McpServerListResponse | null
  message: string
}

export const serversRuntimeApi = {
  runtimeCache: () => request<RuntimeCacheStatus>("/v1/runtime/cache"),
  runtimeEnvironment: () => request<RuntimeEnvironment>("/v1/runtime/environment"),
  clearRuntimeCache: (cacheName: string) => request<RuntimeCacheClearResponse>(`/v1/runtime/cache/${encodeURIComponent(cacheName)}`, { method: "DELETE" }),
  servers: () => request<McpServerListResponse>("/v1/mcp/servers"),
  serverDetail: (serverId: string) => request<McpServerDetail>(`/v1/mcp/servers/${encodeURIComponent(serverId)}/detail`),
  serverTools: (serverId: string) => request<unknown[]>(`/v1/mcp/servers/${encodeURIComponent(serverId)}/tools`),
  serverAction: (serverId: string, action: "start" | "stop" | "restart") => request<McpServer>(`/v1/mcp/servers/${encodeURIComponent(serverId)}/${action}`, { method: "POST" }),
  tools: () => request<ToolDefinition[]>("/v1/tools"),
  invoke: (toolId: string, args: Record<string, unknown>) => request("/v1/invoke", { method: "POST", body: JSON.stringify({ tool_id: toolId, arguments: args }) }),
  configs: () => request<McpConfigListResponse>("/v1/mcp/configs"),
  validateConfig: (manifest: Record<string, unknown>, serverId?: string | null) => request<ManifestValidationResponse>(serverId ? `/v1/mcp/configs/${encodeURIComponent(serverId)}/validate` : "/v1/mcp/configs/validate", { method: "POST", body: JSON.stringify({ manifest, apply: false, start: false }) }),
  createConfig: (manifest: Record<string, unknown>, apply = false, start = false, userCredentialValues: Record<string, string> = {}) => request<ApplyResponse>("/v1/mcp/configs", { method: "POST", body: JSON.stringify({ manifest, apply, start, user_credential_values: userCredentialValues }) }),
  updateConfig: (serverId: string, manifest: Record<string, unknown>, apply = false, start = false, userCredentialValues: Record<string, string> = {}) => request<ApplyResponse>(`/v1/mcp/configs/${encodeURIComponent(serverId)}`, { method: "PUT", body: JSON.stringify({ manifest, apply, start, user_credential_values: userCredentialValues }) }),
  deleteConfig: (serverId: string) => request<ApplyResponse>(`/v1/mcp/configs/${encodeURIComponent(serverId)}`, { method: "DELETE" }),
  applyConfig: (serverId: string) => request<ApplyResponse>(`/v1/mcp/configs/${encodeURIComponent(serverId)}/apply`, { method: "POST" }),
  reloadConfigs: () => request<ApplyResponse>("/v1/mcp/configs/reload", { method: "POST" }),
}

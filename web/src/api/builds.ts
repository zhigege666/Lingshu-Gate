export type ProjectUpload = {
  id: string
  filename: string
  status: string
  detected_runtime: string
  root_dir: string
  analysis: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type BuildFailureHint = {
  code: string
  title: string
  suggestion: string
}

export type BuildPlanStep = {
  id: string
  phase: string
  command: string[]
  reason?: string
  depends_on?: string[]
}

export type BuildPlanManifest = {
  launch_type?: string
  transport?: string
  runtime?: string
  start_script?: boolean
  entrypoint_candidates?: string[]
  python_entrypoint?: string
  resolve_after_build?: boolean
}

export type BuildPlan = {
  ir_version: number
  runtime: string
  buildable: boolean
  project_root_dir?: string | null
  steps: BuildPlanStep[]
  artifact?: { strategy: string; ignore: string[] } | null
  manifest?: BuildPlanManifest | null
  warnings: string[]
  notes: string[]
}

export type BuildStepState = {
  index: number
  id: string
  phase: string
  command: string[]
  depends_on?: string[]
  status: "pending" | "running" | "success" | "failed" | "skipped" | "cancelled" | string
  returncode?: number | null
  duration_ms?: number | null
  started_at?: string | null
  finished_at?: string | null
}

export type BuildRecord = {
  id: string
  upload_id: string
  status: string
  runtime: string
  source_dir: string
  artifact_dir: string
  entrypoint?: string | null
  commands: unknown[]
  logs: Array<Record<string, unknown>>
  manifest: Record<string, unknown>
  plan?: BuildPlan | null
  steps?: BuildStepState[] | null
  error?: string | null
  failure_hint?: BuildFailureHint | null
  created_at: string
  updated_at: string
}

export type BuildLog = {
  id: string
  build_id: string
  sequence: number
  phase: string
  level: string
  message: string
  command: string[]
  returncode?: number | null
  stdout: string
  stderr: string
  duration_ms?: number | null
  started_at: string
  finished_at?: string | null
  created_at: string
}

export type BuildPreflightCheck = {
  id: string
  status: "ok" | "warning" | "error" | string
  message: string
  detail?: string
}

export type BuildPreflightRecommendation = {
  platform: string
  message: string
}

export type BuildPreflightTool = {
  command?: string
  available?: boolean
  path?: string
  version?: string
  error?: string
}

export type BuildPreflightMetadata = {
  has_package_json?: boolean
  has_pyproject?: boolean
  has_requirements?: boolean
  has_dockerfile?: boolean
  package_scripts?: string[]
  python_entrypoint?: string
  file_count?: number
}

export type BuildPreflightCacheInfo = {
  hit: boolean
  cache_key: string
  cached_at: string
  reused_tools?: boolean
  fingerprint?: {
    file_count?: number
    key_files?: string[]
    tools?: Record<string, boolean>
    runtime_override?: string | null
    project_root?: string
  }
}

export type BuildPreflightDiff = {
  has_previous: boolean
  unchanged?: boolean
  changed_files: { added: string[]; removed: string[]; modified: string[] }
  file_count_delta: number
  tool_changes: Array<{ name: string; from: boolean; to: boolean }>
  affected_checks: string[]
  check_changes?: Array<{ id: string; from_status?: string | null; to_status?: string | null; kind: string }>
  reused_tools?: boolean
}

export type BuildPreflightResult = {
  status: "ok" | "warning" | "error" | string
  runtime: string
  detected_runtime: string
  runtime_override?: string | null
  runtime_candidates: string[]
  project_root: string
  project_root_dir: string
  project_root_auto_descended?: string
  upload_root_dir: string
  platform: string
  checks: BuildPreflightCheck[]
  tools: Record<string, BuildPreflightTool>
  recommendations: BuildPreflightRecommendation[]
  metadata: BuildPreflightMetadata
  cache?: BuildPreflightCacheInfo
  diff?: BuildPreflightDiff
}

export type BuildApiDetail = {
  code: string
  message: string
  resource_type?: "project_upload" | "build" | "deployment"
  resource_id?: string
  dependencies?: Record<string, unknown>
  runtime?: string
  preflight?: BuildPreflightResult
}

export type BuildBlockedDetail = BuildApiDetail

export class BuildApiError extends Error {
  detail?: BuildApiDetail | string
  constructor(message: string, detail?: BuildApiDetail | string) {
    super(message)
    this.name = "BuildApiError"
    this.detail = detail
  }
}

export type DeploymentRecord = {
  id: string
  build_id: string
  server_id: string
  status: string
  manifest: Record<string, unknown>
  previous_manifest?: Record<string, unknown> | null
  config_path?: string | null
  started: boolean
  error?: string | null
  created_at: string
  updated_at: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : {}
  if (!response.ok) {
    const detail = (body as { detail?: unknown })?.detail
    if (detail && typeof detail === "object") {
      const structured = detail as BuildApiDetail
      throw new BuildApiError(structured.message || `${response.status} ${response.statusText}`, structured)
    }
    throw new BuildApiError((detail as string) || `${response.status} ${response.statusText}`, detail as string | undefined)
  }
  return body as T
}

export const buildApi = {
  uploads: () => request<{ uploads: ProjectUpload[] }>("/v1/projects/uploads"),
  deleteUpload: (uploadId: string) =>
    request<ProjectUpload>(`/v1/projects/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE" }),
  builds: () => request<{ builds: BuildRecord[] }>("/v1/builds"),
  buildLogs: (buildId: string, limit = 200) => request<{ logs: BuildLog[] }>(`/v1/builds/${encodeURIComponent(buildId)}/logs?limit=${encodeURIComponent(String(limit))}`),
  deployments: () => request<{ deployments: DeploymentRecord[] }>("/v1/deployments"),
  preflightBuild: (uploadId: string, options: { runtime_override?: string | null; project_root?: string | null; refresh?: boolean } = {}) =>
    request<BuildPreflightResult>("/v1/builds/preflight", { method: "POST", body: JSON.stringify({ upload_id: uploadId, runtime_override: options.runtime_override || null, project_root: options.project_root || null, refresh: options.refresh ?? false }) }),
  planBuild: (uploadId: string, options: { runtime_override?: string | null; project_root?: string | null; refresh?: boolean; run_install?: boolean; run_build?: boolean } = {}) =>
    request<{ preflight: BuildPreflightResult; plan: BuildPlan }>("/v1/builds/plan", { method: "POST", body: JSON.stringify({ upload_id: uploadId, runtime_override: options.runtime_override || null, project_root: options.project_root || null, run_install: options.run_install ?? true, run_build: options.run_build ?? true, refresh: options.refresh ?? false }) }),
  createBuild: (uploadId: string, options: { run_install?: boolean; run_build?: boolean; timeout_seconds?: number; runtime_override?: string | null; project_root?: string | null } = {}) =>
    request<BuildRecord>("/v1/builds", { method: "POST", body: JSON.stringify({ upload_id: uploadId, run_install: options.run_install ?? true, run_build: options.run_build ?? true, timeout_seconds: options.timeout_seconds ?? 300, runtime_override: options.runtime_override || null, project_root: options.project_root || null }) }),
  cancelBuild: (buildId: string) =>
    request<BuildRecord>(`/v1/builds/${encodeURIComponent(buildId)}/cancel`, { method: "POST", body: JSON.stringify({}) }),
  deleteBuild: (buildId: string) =>
    request<{ deleted: boolean; build: BuildRecord; deleted_log_count: number }>(`/v1/builds/${encodeURIComponent(buildId)}`, { method: "DELETE" }),
  deployBuild: (buildId: string, options: { server_id?: string; start?: boolean; overwrite?: boolean } = {}) =>
    request<DeploymentRecord>(`/v1/builds/${encodeURIComponent(buildId)}/deploy`, { method: "POST", body: JSON.stringify({ server_id: options.server_id || null, start: options.start ?? false, overwrite: options.overwrite ?? false }) }),
  rollback: (deploymentId: string, start = false) =>
    request<{ deployment: DeploymentRecord; server?: Record<string, unknown> | null; message: string }>(`/v1/deployments/${encodeURIComponent(deploymentId)}/rollback`, { method: "POST", body: JSON.stringify({ start }) }),
  deleteDeployment: (deploymentId: string) =>
    request<{ deleted: boolean; deployment: DeploymentRecord; runtime_unchanged: boolean; message: string }>(`/v1/deployments/${encodeURIComponent(deploymentId)}`, { method: "DELETE" }),
}

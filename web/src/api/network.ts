import { request } from "@/api/http"
import type { BuildPlan, PackageManagerOverride, ProjectUpload } from "@/api/builds"

export type NetworkSelection = { mode: "inherit" | "direct" | "profile"; profile_id?: string | null; version?: number | null }
export type NetworkProfile = { id: string; version: number; name: string; enabled: boolean; scheme: string; endpoint_masked: string; credential_ref: string | null; credential_configured: boolean }
export type NetworkDefaults = { git: NetworkSelection; install: NetworkSelection; npm_registry: string; python_index: string; npm_credential_ref: string | null; python_credential_ref: string | null; git_hosts: Array<{ host: string; port: number; private_cidrs: string[] }> }
export type NetworkSettings = { revision: number; defaults: NetworkDefaults; profiles?: NetworkProfile[]; executor: { available: boolean; code: string } }
export type GitSource = { repository_url: string; ref_type: "branch" | "tag" | "commit"; ref: string; project_root: string; credential_ref: string | null; git_network: NetworkSelection; install_network: NetworkSelection; runtime_template: "node" | "python" }
export type GitPlan = { status: "ready" | "blocked"; plan_id?: string; plan_digest?: string; plan?: { commit_sha: string; source: GitSource; network: Record<string, unknown>; limits: Record<string, number> }; error?: { code: string; message: string; next_action: string }; validation: { ok: boolean }; expires_at?: string }
export type GitImport = { status: string; import_id: string; upload_id: string | null; error_code: string | null; terminal: boolean; execution_state?: "active" | "completed" | "terminated" | "unknown"; execution_terminated?: boolean; requires_reconciliation?: boolean; next_action?: string | null; progress: Array<{ phase: string; status: string }> }
export type DeliveryBuildPlan = { status: string; upload_id: string; plan: BuildPlan; source_sha256: string; plan_fingerprint: string; validation: { ok: boolean; errors: string[] } }
const post = (value: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(value) })

export const networkApi = {
  settings: () => request<NetworkSettings>("/v1/system-settings/network"),
  options: () => request<NetworkSettings>("/v1/network/options"),
  saveDefaults: (defaults: NetworkDefaults, expected_revision: number) => request<NetworkSettings>("/v1/system-settings/network", { method: "PUT", body: JSON.stringify({ defaults, expected_revision }) }),
  saveProfile: (profile: { name: string; endpoint?: string | null; credential_ref: string | null; enabled: boolean; expected_version: number }, id?: string) => request<NetworkProfile>(id ? `/v1/system-settings/network/profiles/${encodeURIComponent(id)}` : "/v1/system-settings/network/profiles", { method: id ? "PUT" : "POST", body: JSON.stringify(profile) }),
  references: (id: string) => request<{ references: Array<{ version: number; resource_type: string; resource_id: string }> }>(`/v1/system-settings/network/profiles/${encodeURIComponent(id)}/references`),
  deleteProfile: (id: string, expected_version: number) => request(`/v1/system-settings/network/profiles/${encodeURIComponent(id)}/delete`, post({ expected_version })),
  test: (profile: NetworkProfile, target_id: "github" | "npm" | "python") => request<{ status: string; error_code?: string }>("/v1/network/test", post({ profile_id: profile.id, version: profile.version, target_id, confirmed: true })),
  plan: (source: GitSource) => request<GitPlan>("/v1/projects/git/plan", post(source)),
  acquire: (plan: GitPlan, idempotency_key: string) => request<GitImport>("/v1/projects/git/import", post({ plan_id: plan.plan_id, plan_digest: plan.plan_digest, idempotency_key, confirmed: true })),
  status: (id: string) => request<GitImport>(`/v1/projects/git/imports/${encodeURIComponent(id)}`),
  cancel: (id: string, idempotency_key: string) => request<GitImport>(`/v1/projects/git/imports/${encodeURIComponent(id)}/cancel`, post({ idempotency_key, confirmed: true })),
  upload: (id: string) => request<ProjectUpload>(`/v1/projects/uploads/${encodeURIComponent(id)}`),
  planBuild: (upload_id: string, options: { runtime_override?: string | null; project_root?: string | null; run_install?: boolean; run_build?: boolean; package_manager_override?: PackageManagerOverride | null }) => request<DeliveryBuildPlan>("/v1/projects/git/build-plan", post({ upload_id, ...options })),
  build: (plan: DeliveryBuildPlan, options: { runtime_override?: string | null; project_root?: string | null; run_install?: boolean; run_build?: boolean; package_manager_override?: PackageManagerOverride | null }, idempotency_key: string) => request<{ build_id: string; status: string }>("/v1/projects/git/build", post({ upload_id: plan.upload_id, source_sha256: plan.source_sha256, plan_fingerprint: plan.plan_fingerprint, timeout_seconds: 300, ...options, idempotency_key, confirmed: true })),
}

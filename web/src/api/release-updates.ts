import { request } from "@/api/http"

export type ReleaseUpdateSettings = {
  current_version: string
  revision: number
  proxy_profile: { id: string; version: number; name: string; enabled: boolean } | null
}
export type ReleaseUpdateResult = {
  current_version: string
  latest_version: string
  update_available: boolean
  release_name: string
  release_url: string
  published_at: string
  release_notes: string
  proxy: "direct" | "configured"
}
export const releaseUpdatesApi = {
  settings: () => request<ReleaseUpdateSettings>("/v1/system-settings/updates"),
  save: (expected_revision: number, proxy_profile_id: string | null, proxy_profile_version: number | null) =>
    request<Omit<ReleaseUpdateSettings, "current_version">>("/v1/system-settings/updates", {
      method: "PUT",
      body: JSON.stringify({ expected_revision, proxy_profile_id, proxy_profile_version }),
    }),
  check: () => request<ReleaseUpdateResult>("/v1/system-settings/updates/check", { method: "POST", body: "{}" }),
}
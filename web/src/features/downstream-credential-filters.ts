import type { UserDownstreamCredential } from "@/api/client"
export type DownstreamFilters = { query: string; server: string; status: string; required: string }
export function filterDownstreamCredentials(items: UserDownstreamCredential[], filters: DownstreamFilters) {
 const needle=filters.query.trim().toLowerCase()
 return items.filter(item => {
  if(filters.server && item.server_id !== filters.server) return false
  if(filters.status === "configured" && !item.configured) return false
  if(filters.status === "missing" && (!item.required || item.configured)) return false
  if(filters.status === "unconfigured" && item.configured) return false
  if(filters.required === "required" && !item.required) return false
  if(filters.required === "optional" && item.required) return false
  return !needle || `${item.server_id} ${item.server_name} ${item.id} ${item.name} ${item.description} ${item.injection.name}`.toLowerCase().includes(needle)
 })
}

export function downstreamEmptyState(total: number, loading: boolean, failed: boolean): "loadingData" | "notLoaded" | "noCurrentMatches" | "empty" {
  return loading ? "loadingData" : failed ? "notLoaded" : total > 0 ? "noCurrentMatches" : "empty"
}

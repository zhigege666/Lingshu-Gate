import { queryString, request } from "./http"

export type McpGroupSummary = { id: string; name: string; description: string; status: "active" | "archived"; revision: number; member_count: number; missing_count: number; created_at: string; updated_at: string }
export type McpGroup = Omit<McpGroupSummary, "member_count" | "missing_count"> & { members: { instance_id: string; status: "active" | "missing"; available?: boolean }[] }
export type McpGroupInstance = { instance_id: string; name: string; status: string; available: boolean; groups: { id: string; name: string; status: string }[] }
export type McpGroupDraft = { name: string; description: string; status: "active" | "archived"; members: string[]; reconfirm_members: string[]; confirmed: true; expected_revision?: number; request_key?: string }
export type GroupPage<T> = { total: number; offset: number; limit: number } & T

export const GROUP_REQUEST_TIMEOUT_MS = 15_000

async function groupRequest<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  signal?.addEventListener("abort", abort, { once: true })
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([request<T>(path, { ...init, signal: controller.signal }), new Promise<never>((_, reject) => {
      timer = setTimeout(() => { controller.abort(); reject(new Error("group_request_timeout")) }, GROUP_REQUEST_TIMEOUT_MS)
    })])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    signal?.removeEventListener("abort", abort)
  }
}

export function canonicalGroupBody(value: unknown): string {
  const ordered = (item: unknown): unknown => Array.isArray(item) ? item.map(ordered) : item && typeof item === "object"
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, entry]) => [key, ordered(entry)])) : item
  return JSON.stringify(ordered(value))
}

async function mutate<T>(action: "create" | "update" | "delete", groupId: string | undefined, body: object, signal?: AbortSignal) {
  const bytes = new TextEncoder().encode(canonicalGroupBody(body))
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), value => value.toString(16).padStart(2, "0")).join("")
  const ticket = await groupRequest<{ csrf: string }>("/v1/mcp/groups/csrf" + queryString({ action, group_id: groupId, request_digest: digest }), { method: "POST" }, signal)
  const path = "/v1/mcp/groups" + (groupId ? "/" + encodeURIComponent(groupId) : "")
  return groupRequest<T>(path, { method: action === "create" ? "POST" : action === "update" ? "PUT" : "DELETE",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": ticket.csrf }, body: JSON.stringify(body) }, signal)
}

export const mcpGroupsApi = {
  list: (filters: { q?: string; status?: string; offset?: number; limit?: number }, signal?: AbortSignal) => groupRequest<GroupPage<{ groups: McpGroupSummary[] }>>("/v1/mcp/groups" + queryString(filters), {}, signal),
  detail: (id: string, signal?: AbortSignal) => groupRequest<McpGroup>("/v1/mcp/groups/" + encodeURIComponent(id), {}, signal),
  createResult: (key: string, signal?: AbortSignal) => groupRequest<McpGroup>("/v1/mcp/groups/requests/" + encodeURIComponent(key), {}, signal),
  instances: (filters: { q?: string; group_id?: string; ungrouped?: boolean; offset?: number; limit?: number; refresh?: boolean }, signal?: AbortSignal) => groupRequest<GroupPage<{ instances: McpGroupInstance[] }>>("/v1/mcp/groups/instances" + queryString(filters), {}, signal),
  save: (id: string | undefined, body: McpGroupDraft, signal?: AbortSignal) => mutate<McpGroup>(id ? "update" : "create", id, body, signal),
  delete: (id: string, revision: number, signal?: AbortSignal) => mutate<{ deleted: boolean }>("delete", id, { expected_revision: revision, confirmed: true }, signal),
}

import type { McpServer, McpToolSync } from "@/api/client"
import type { ServerCopy } from "@/features/servers/copy"

export function hasToolSyncIssue(server: McpServer): boolean {
  return server.tool_sync?.state === "retrying" || server.tool_sync?.state === "auth_required"
}

export function canSyncServerTools(server: McpServer): boolean {
  if (!server.enabled || !server.tool_sync || server.tool_sync.state === "syncing" || server.tool_sync.state === "disabled" || server.desired_state === "stopped") return false
  return server.status === "running" || server.status === "failed" && server.launch_type === "external" && server.effective_should_run === true
}

/** Keep untouched service owners stable when another service changes in a poll. */
export function reconcileServerSnapshots(previous: McpServer[], current: McpServer[]): McpServer[] {
  const byId = new Map(previous.map(server => [server.id, server]))
  return current.map(server => {
    const before = byId.get(server.id)
    return before && JSON.stringify(before) === JSON.stringify(server) ? before : server
  })
}

/** Tool counts alone miss equal-size replacements and schema changes. */
export function toolCatalogChanged(previous: McpServer[], current: McpServer[]): boolean {
  if (previous.length !== current.length) return true
  const byId = new Map(previous.map(server => [server.id, server]))
  return current.some(server => {
    const before = byId.get(server.id)
    if (!before || before.tool_count !== server.tool_count) return true
    const beforeRevision = before.tool_sync?.last_changed_at === undefined ? before.tool_sync?.last_success_at : before.tool_sync.last_changed_at
    const revision = server.tool_sync?.last_changed_at === undefined ? server.tool_sync?.last_success_at : server.tool_sync.last_changed_at
    return beforeRevision !== revision
  })
}

export function toolSyncChanges(sync: McpToolSync, c: ServerCopy): string {
  if (!sync.added && !sync.updated && !sync.removed) return c.syncNoChanges
  return [[c.syncAdded, sync.added], [c.syncUpdated, sync.updated], [c.syncRemoved, sync.removed]]
    .filter(([, count]) => count !== 0).map(([label, count]) => `${label} ${count}`).join(" · ")
}

/** A successful HTTP request alone does not establish that upstream discovery succeeded. */
export function toolSyncResult(serverId: string, result: McpServer, c: ServerCopy): string {
  if (result.id !== serverId) throw new Error(`${c.syncIncomplete}: ${serverId}`)
  const sync = result.tool_sync
  if (sync?.state !== "ready") throw new Error(`${c.syncIncomplete}: ${serverId}${sync?.last_error ? ` · ${sync.last_error}` : ""}`)
  return `${c.syncComplete}: ${serverId} · ${toolSyncChanges(sync, c)}`
}

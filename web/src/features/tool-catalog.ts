import type { McpServer, ToolDefinition } from "@/api/client"
import { getToolAccessDisplay, type ToolAccess } from "@/features/tool-access"

export type { ToolAccess } from "@/features/tool-access"
export const ALL_TOOL_SERVICES = "all"
export const BUILTIN_TOOL_SERVICE = "builtin"

export function toolServerId(tool: ToolDefinition): string | null {
  const id = tool.metadata.server_id
  return tool.source === "mcp" && typeof id === "string" && id.trim() ? id.trim() : null
}

export function toolServiceKey(tool: ToolDefinition): string {
  const serverId = toolServerId(tool)
  return serverId ? `server:${serverId}` : `source:${tool.source}`
}

// Discovery supplies the effective access decision. MCP annotations and manifest
// defaults alone are not evidence of a reviewed read-only classification.
export function toolAccess(tool: ToolDefinition): ToolAccess {
  return getToolAccessDisplay(tool).access
}

export function toolServiceOptions(tools: ToolDefinition[], servers: Pick<McpServer, "id" | "name">[]) {
  const services = new Map<string, { value: string; id: string; name: string; count: number }>()
  for (const server of servers) {
    services.set(`server:${server.id}`, { value: `server:${server.id}`, id: server.id, name: server.name || server.id, count: 0 })
  }
  for (const tool of tools) {
    if (tool.source === "builtin") continue
    const value = toolServiceKey(tool)
    const id = toolServerId(tool) || tool.source
    const option = services.get(value) || { value, id, name: id, count: 0 }
    option.count += 1
    services.set(value, option)
  }
  return [...services.values()].sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
}

export function filterTools(tools: ToolDefinition[], servers: Pick<McpServer, "id" | "name">[], filters: {
  query: string
  service: string
  access: "all" | ToolAccess
}) {
  const needle = filters.query.trim().toLowerCase()
  const names = new Map(servers.map(server => [server.id, server.name || server.id]))
  return tools.filter(tool => {
    if (filters.service === BUILTIN_TOOL_SERVICE && tool.source !== "builtin") return false
    if (filters.service !== ALL_TOOL_SERVICES && filters.service !== BUILTIN_TOOL_SERVICE && toolServiceKey(tool) !== filters.service) return false
    if (filters.access !== "all" && toolAccess(tool) !== filters.access) return false
    const serverId = toolServerId(tool)
    return !needle || [tool.id, tool.name, tool.description, tool.permission, tool.source, serverId, serverId && names.get(serverId)]
      .filter(Boolean).join(" ").toLowerCase().includes(needle)
  })
}

export function paginateTools<T>(items: T[], page: number, pageSize: number) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const currentPage = Math.min(Math.max(1, page), pageCount)
  const start = (currentPage - 1) * pageSize
  return { items: items.slice(start, start + pageSize), page: currentPage, pageCount, start: items.length ? start + 1 : 0, end: Math.min(start + pageSize, items.length) }
}

import type { OAuthTool } from "./oauth-api"

export type ScopeSelectionMode = "read" | "all" | "custom"
export type OAuthMcpGroup = { id: string; name: string | null; tools: OAuthTool[]; selectedCount: number; readCount: number; writeCount: number }

/** Explicit choices use the full current eligible catalog, never a filtered page. */
export function selectCurrentTools(tools: OAuthTool[], mode: Exclude<ScopeSelectionMode, "custom">): string[] {
  return tools.filter(tool => tool.currently_authorized !== false && (mode === "all" || tool.access === "read")).map(tool => tool.id)
}

export function mcpSelectionGroups(tools: OAuthTool[], selected: string[]): OAuthMcpGroup[] {
  const ids = new Set(selected)
  const groups = new Map<string, OAuthMcpGroup>()
  for (const tool of tools) {
    if (tool.currently_authorized === false) continue
    let group = groups.get(tool.server_id)
    if (!group) {
      group = { id: tool.server_id, name: tool.server_name || null, tools: [], selectedCount: 0, readCount: 0, writeCount: 0 }
      groups.set(group.id, group)
    }
    if (!group.name && tool.server_name) group.name = tool.server_name
    group.tools.push(tool)
    if (ids.has(tool.id)) group.selectedCount++
    if (tool.access === "read") group.readCount++; else group.writeCount++
  }
  return [...groups.values()].sort((a, b) => a.id.localeCompare(b.id))
}

export function selectMcpTools(selected: string[], group: OAuthMcpGroup, checked: boolean, knownTools: OAuthTool[] = group.tools): string[] {
  if (checked) return [...new Set([...selected, ...group.tools.map(tool => tool.id)])]
  // Explicitly clearing a service also clears its retained unavailable draft.
  const groupIds = new Set(knownTools.filter(tool => tool.server_id === group.id).map(tool => tool.id))
  return selected.filter(id => !groupIds.has(id))
}

/** Retain unavailable draft entries so refresh cannot hide or discard a choice. */
export function scopeEditorTools(remembered: OAuthTool[], available: OAuthTool[] | null, selected: string[]): OAuthTool[] {
  if (available === null) return remembered
  const ids = new Set(available.map(tool => tool.id))
  const chosen = new Set(selected)
  return [...available, ...remembered.filter(tool => chosen.has(tool.id) && !ids.has(tool.id)).map(tool => ({ ...tool, currently_authorized: false }))]
}

import { describe, expect, it } from "vitest"
import type { OAuthTool } from "./oauth-api"
import { mcpSelectionGroups, scopeEditorTools, selectCurrentTools, selectMcpTools } from "./oauth-tool-selection"

const tools: OAuthTool[] = Array.from({ length: 5000 }, (_, index) => ({ id: `tool-${index}`, name: `Tool ${index}`, server_id: `mcp-${Math.floor(index / 50)}`, server_name: `MCP ${Math.floor(index / 50)}`, access: index % 2 ? "write" : "read", snapshot: "published" }))

describe("current OAuth catalog selection", () => {
  it("replaces selection across 5000 tools and 100 MCPs using only published access", () => {
    const mixed = { ...tools[1], name: "Read projects with create/update operations" }
    const available = [tools[0], mixed, ...tools.slice(2)]
    const read = selectCurrentTools(available, "read")
    expect(read).toHaveLength(2500)
    expect(read).toContain("tool-4998")
    expect(read).not.toContain(mixed.id)
    expect(selectCurrentTools(available, "all")).toEqual(tools.map(tool => tool.id))
  })
  it("selects and clears the whole MCP while retaining choices in other groups", () => {
    const groups = mcpSelectionGroups(tools, ["tool-0", "tool-4998"])
    expect(groups).toHaveLength(100)
    const last = groups.find(group => group.id === "mcp-99")!
    expect(last).toMatchObject({ selectedCount: 1, readCount: 25, writeCount: 25 })
    const selected = selectMcpTools(["tool-0", "tool-4998"], last, true)
    expect(selected).toHaveLength(51)
    expect(selected).toContain("tool-4999")
    expect(selectMcpTools(selected, last, false)).toEqual(["tool-0"])
  })
  it("retains unavailable draft details on refresh without selecting later services", () => {
    const later = { ...tools[1], id: "later-tool", server_id: "later-mcp" }
    const selected = [tools[0].id, tools[1].id]
    const refreshed = scopeEditorTools(tools.slice(0, 2), [tools[0], later], selected)
    expect(refreshed).toEqual([tools[0], later, { ...tools[1], currently_authorized: false }])
    expect(selected).toEqual(["tool-0", "tool-1"])
    expect(selectCurrentTools(refreshed, "all")).toEqual(["tool-0", "later-tool"])
    expect(mcpSelectionGroups(refreshed, selected).find(group => group.id === "mcp-0")?.selectedCount).toBe(1)
    const group = mcpSelectionGroups(refreshed, selected).find(group => group.id === "mcp-0")!
    expect(selectMcpTools(selected, group, false, refreshed)).toEqual([])
    expect(scopeEditorTools(tools.slice(0, 2), null, selected)).toEqual(tools.slice(0, 2))
  })
})

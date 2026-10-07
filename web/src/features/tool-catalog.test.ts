import { describe, expect, it } from "vitest"
import type { ToolDefinition } from "@/api/client"
import { filterTools, paginateTools, toolAccess, toolServerId, toolServiceOptions } from "@/features/tool-catalog"

function tool(id: string, serverId: string, access: string, overrides: Partial<ToolDefinition> = {}): ToolDefinition {
  return { id, name: "Read document", description: "Read a document by ID", source: "mcp", permission: "default:read", input_schema: {}, metadata: { server_id: serverId, gate_access: { required_access: access } }, ...overrides }
}
const tools = [
  tool("gate_build_preflight", "project-delivery", "read", { source: "builtin" }),
  tool("mcp.docs-prod.read_document", "docs-prod", "read"),
  tool("mcp.docs-test.read_document", "docs-test", "write"),
]
const servers = [{ id: "docs-prod", name: "Document service" }, { id: "docs-test", name: "Document service" }, { id: "stopped", name: "Stopped service" }]
const defaults = { query: "", service: "all", access: "all" as const }

describe("tool catalog", () => {
  it("distinguishes same-name deployments and keeps deployed services with no visible tools", () => {
    expect(toolServiceOptions(tools, servers)).toEqual([
      { value: "server:docs-prod", id: "docs-prod", name: "Document service", count: 1 },
      { value: "server:docs-test", id: "docs-test", name: "Document service", count: 1 },
      { value: "server:stopped", id: "stopped", name: "Stopped service", count: 0 },
    ])
    expect(filterTools(tools, servers, { ...defaults, service: "server:docs-test" }).map(item => item.id)).toEqual(["mcp.docs-test.read_document"])
  })

  it("offers only visible tool services when the user cannot read runtime management data", () => {
    expect(toolServiceOptions(tools, []).map(item => item.id)).toEqual(["docs-prod", "docs-test"])
    expect(toolServerId(tools[0])).toBeNull()
    expect(filterTools(tools, servers, { ...defaults, service: "builtin" })).toEqual([tools[0]])
  })

  it("combines case-insensitive search, exact service ID and effective access", () => {
    expect(filterTools(tools, servers, { query: "READ_DOCUMENT", service: "server:docs-test", access: "write" })).toEqual([tools[2]])
    expect(filterTools(tools, servers, { query: "document service", service: "all", access: "read" })).toEqual([tools[1]])
    expect(filterTools(tools, servers, { ...defaults, service: "server:stopped" })).toEqual([])
    expect(filterTools(tools, servers, { query: "document", service: "server:docs-test", access: "read" })).toEqual([])
  })

  it("does not mistake read-only annotations or manifest defaults for effective access", () => {
    expect(toolAccess(tools[2])).toBe("write")
    expect(toolAccess(tool("unreviewed", "demo", "", { metadata: { annotations: { readOnlyHint: true } } }))).toBe("unknown")
    expect(toolAccess(tool("malformed", "demo", "", { metadata: { gate_access: [] } }))).toBe("unknown")
  })

  it("clamps pagination after a catalog shrinks and returns accurate empty ranges", () => {
    const rows = Array.from({ length: 20 }, (_, index) => index)
    expect(paginateTools(rows, 2, 9)).toEqual({ items: rows.slice(9, 18), page: 2, pageCount: 3, start: 10, end: 18 })
    expect(paginateTools(rows.slice(0, 3), 3, 9)).toEqual({ items: [0, 1, 2], page: 1, pageCount: 1, start: 1, end: 3 })
    expect(paginateTools([], 3, 9)).toEqual({ items: [], page: 1, pageCount: 1, start: 0, end: 0 })
  })
})

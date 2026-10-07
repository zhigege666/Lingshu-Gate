import { describe, expect, it } from "vitest"
import { scopeDifference } from "./oauth-scope-difference"
import type { OAuthTool } from "./oauth-api"

const read: OAuthTool = { id: "read-tool", name: "Read", server_id: "service", access: "read", snapshot: "original" }
const write: OAuthTool = { id: "write-tool", name: "Write", server_id: "service", access: "write", snapshot: "original" }
describe("owner-confirmed live grant differences", () => {
  it("distinguishes pure reduction, addition and mixed changes", () => {
    expect(scopeDifference([read, write], [read.id], [read, write])).toEqual({ added: [], removed: [write] })
    expect(scopeDifference([read], [read.id, write.id], [read, write])).toEqual({ added: [write], removed: [] })
    expect(scopeDifference([read], [write.id], [read, write])).toEqual({ added: [write], removed: [read] })
  })
  it("requires fresh confirmation for changed access or policy, while display renames preserve scope", () => {
    expect(scopeDifference([read], [read.id], [{ ...read, name: "Renamed", server_name: "Renamed MCP" }])).toEqual({ added: [], removed: [] })
    const changed = { ...read, access: "write" as const, snapshot: "new-policy" }
    expect(scopeDifference([read], [read.id], [changed])).toEqual({ added: [changed], removed: [read] })
  })
})

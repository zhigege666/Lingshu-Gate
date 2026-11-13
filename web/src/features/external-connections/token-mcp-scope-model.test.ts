import { describe, expect, it } from "vitest"
import type { OAuthTool } from "./oauth-api"
import { changeTokenMcpChoice, completeTokenMcpPermissions, mergeTokenMcpTools, retainTokenTools, tokenMcpChoice, tokenMcpSignature, tokenMcpPermissionConflicts, type TokenMcpDraft } from "./token-mcp-scope-model"

const tools: OAuthTool[] = [
  { id: "a.read", name: "Read", server_id: "a", access: "read", snapshot: "1" },
  { id: "a.write", name: "Write", server_id: "a", access: "write", snapshot: "1" },
  { id: "b.read", name: "Read", server_id: "b", access: "read", snapshot: "1" },
]
const draft = (): TokenMcpDraft => ({ selected: ["a.read", "b.read", "unknown.saved"], policies: [{ server_id: "c", mode: "continuous", access: "read", server_binding: "c-original" }], modes: { a: "selected", b: "selected" } })

describe("token MCP draft boundaries", () => {
  it("replaces one MCP while preserving other MCPs and unavailable unknown selections", () => {
    expect(mergeTokenMcpTools("a", draft().selected, ["a.write", "b.read", "a.write"], tools)).toEqual(["b.read", "unknown.saved", "a.write"])
    expect(mergeTokenMcpTools("a", draft().selected, [], tools)).toEqual(["b.read", "unknown.saved"])
  })
  it("maps all four choices without disturbing another server's grants", () => {
    const selected = draft()
    expect(tokenMcpChoice("a", selected)).toBe("selected")
    for (const choice of ["none", "read", "write"] as const) {
      const next = changeTokenMcpChoice("a", choice, selected, tools, "a-current")
      expect(tokenMcpChoice("a", next)).toBe(choice)
      expect(next.selected).toEqual(["b.read", "unknown.saved"])
      expect(next.policies).toContainEqual(selected.policies[0])
      expect(next.modes.b).toBe("selected")
      if (choice !== "none") expect(next.policies).toContainEqual({ server_id: "a", mode: "continuous", access: choice, server_binding: "a-current" })
    }
  })
  it("keeps an old service binding when access changes; switching to selected removes only that policy", () => {
    const current = draft()
    const edited = changeTokenMcpChoice("c", "write", current, tools, "c-replaced")
    expect(edited.policies[0]).toMatchObject({ access: "write", server_binding: "c-original" })
    const selected = changeTokenMcpChoice("c", "selected", edited, tools, "c-replaced")
    expect(selected.policies).toEqual([])
    expect(selected.selected).toEqual(current.selected)
  })
  it("retains both saved and unsaved missing tools on refresh without granting new tools", () => {
    const future = { ...tools[0], id: "a.future" }
    const refreshed = retainTokenTools(tools, [future, tools[2]], [tools[0]], ["a.read", "a.write", "b.read"])
    expect(refreshed).toContainEqual({ ...tools[0], currently_authorized: false })
    expect(refreshed).toContainEqual({ ...tools[1], currently_authorized: false })
    expect(refreshed).toContainEqual(future)
    expect(mergeTokenMcpTools("a", ["a.read", "a.write", "b.read"], [], refreshed)).toEqual(["b.read"])
  })
  it("finds missing functional permissions by MCP without changing the draft", () => {
    const current = { ...draft(), selected: ["a.read", "a.write", "b.read"] }
    expect(tokenMcpPermissionConflicts(current, tools, ["tools.read"])).toEqual([{ server_id: "a", required: ["tools.invoke"] }])
    expect(tokenMcpPermissionConflicts(current, tools, ["tools.invoke"])).toEqual([{ server_id: "c", required: ["tools.read"] }, { server_id: "a", required: ["tools.read"] }, { server_id: "b", required: ["tools.read"] }])
    expect(tokenMcpPermissionConflicts(current, tools, ["*"])).toEqual([])
    expect(current.selected).toEqual(["a.read", "a.write", "b.read"])
  })
  it("does not mark reorder or an empty presentation-only selected mode as a saved grant change", () => {
    const current = draft()
    expect(tokenMcpSignature("a", current, tools)).toBe(tokenMcpSignature("a", { ...current, selected: [...current.selected].reverse() }, tools))
    const empty: TokenMcpDraft = { selected: [], policies: [], modes: {} }
    expect(tokenMcpSignature("a", empty, tools)).toBe(tokenMcpSignature("a", changeTokenMcpChoice("a", "selected", empty, tools), tools))
    expect(tokenMcpSignature("c", current, tools)).not.toBe(tokenMcpSignature("c", { ...current, policies: [{ ...current.policies[0], server_binding: "changed" }] }, tools))
  })
  it("adds only the permissions required by the selected MCP scope and permitted by its owner", () => {
    const current = { selected: ["a.write"], policies: [] }
    expect(completeTokenMcpPermissions(current, tools, ["audit.read"], ["tools.read", "tools.invoke", "operations.manage"])).toEqual(["audit.read", "tools.invoke"])
    expect(completeTokenMcpPermissions(current, tools, ["tools.read"], ["tools.read"])).toBeNull()
    expect(completeTokenMcpPermissions(current, tools, ["*"], [])).toEqual(["*"])
    expect(current.selected).toEqual(["a.write"])
  })
})

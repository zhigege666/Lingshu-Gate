import { describe, expect, it, vi } from "vitest"
import type { ToolClassification } from "@/api/client"
import { effectiveToolPolicy, saveToolPolicyBatch, toolPolicyMode } from "./tool-policy"
const tool = (id: string, extra: Partial<ToolClassification> = {}) => ({ id, server_id: "server", tool_id: id, tool_name: id, fingerprint: `schema-${id}`, status: "pending", effective_access: "unknown", suggested_access: "read", destructive: true, idempotent: false, ...extra } as ToolClassification)
describe("automatic tool access", () => {
  it("uses the current enforced policy without a publication step or upstream suggestion", () => {
    expect(effectiveToolPolicy(tool("a", { required_access: "write", policy_source: "default_write" }))).toBe("write")
    expect(toolPolicyMode(tool("a", { required_access: "write", policy_source: "default_write" }))).toBe("automatic")
    expect(effectiveToolPolicy(tool("b"))).toBe("none")
    expect(effectiveToolPolicy(tool("c", { required_access: "none", status: "published", effective_access: "read" }))).toBe("none")
  })
  it("retains successful writes, original safety flags and schema revision when one item conflicts", async () => {
    const items = [tool("a"), tool("b"), tool("c")]
    const save = vi.fn(async (_server, id, payload) => { if (id === "b") throw new Error("409 catalog changed"); return { ...items.find(item => item.id === id)!, required_access: payload.access } })
    const result = await saveToolPolicyBatch(items, "write", "", save)
    expect(result.saved.map(item => item.id)).toEqual(["a", "c"])
    expect(result.failed.map(item => item.item.id)).toEqual(["b"])
    expect(save).toHaveBeenCalledTimes(3)
    expect(save.mock.calls[0][2]).toEqual({ access: "write", note: "", destructive: true, idempotent: false, expected_fingerprint: "schema-a", expected_policy_revision: 1 })
  })
})

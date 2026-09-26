import { describe, expect, it } from "vitest"
import type { ToolDefinition } from "@/api/client"
import { getToolAccessDisplay } from "./tool-access"

const tool = (metadata: Record<string, unknown>, permission = "read") => ({ id: "tool", name: "tool", source: "mcp", permission, metadata, input_schema: {}, description: "" }) as ToolDefinition

describe("effective access presentation", () => {
  it("does not treat a declared permission or missing metadata as a reviewed classification", () => {
    expect(getToolAccessDisplay(tool({}))).toEqual({ access: "unknown", classificationStatus: null, pending: false })
  })
  it("uses the backend decision when declaration disagrees", () => {
    expect(getToolAccessDisplay(tool({ gate_access: { required_access: "write", classification_status: "published" } })).access).toBe("write")
  })
  it("shows pending only when the backend explicitly reports pending", () => {
    expect(getToolAccessDisplay(tool({ gate_access: { required_access: "unknown", classification_status: "pending" } })).pending).toBe(true)
    expect(getToolAccessDisplay(tool({ gate_access: { required_access: "unknown", classification_status: "missing" } })).pending).toBe(false)
  })
})

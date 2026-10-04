import { describe, expect, it } from "vitest"
import { builtinOriginName, grantOriginName } from "./tool-origin"

describe("registry-backed origin labels", () => {
  it("names the four built-in groups in both languages and retains their IDs", () => {
    expect(builtinOriginName("builtin", "builtin", "zh-CN")).toBe("Gate 基础能力")
    expect(builtinOriginName("builtin", "gate-control", "en-US")).toBe("Tool review management")
    expect(builtinOriginName("builtin", "gate-delivery", "zh-CN")).toBe("项目交付与服务管理")
    expect(builtinOriginName("builtin", "gate-tool-files", "en-US")).toBe("Tool file transfer")
  })
  it("does not infer origin from an ID, gate prefix, missing source or classification source", () => {
    expect(builtinOriginName("mcp", "gate-control", "zh-CN")).toBeNull()
    expect(builtinOriginName(undefined, "builtin", "en-US")).toBeNull()
    const resource = { server_id: "gate-control", tool_id: "synthetic", tool_name: "Synthetic", classification: "read" as const, classification_status: "published" as const, source: "builtin" }
    expect(grantOriginName([resource], resource.server_id, null, "zh-CN")).toBeNull()
    expect(grantOriginName([{ ...resource, registry_source: "builtin" }], resource.server_id, null, "zh-CN")).toBe("工具审核管理")
    expect(grantOriginName([{ ...resource, registry_source: "builtin" }, { ...resource, tool_id: "third-party", registry_source: "mcp" }], resource.server_id, null, "zh-CN")).toBeNull()
  })
})

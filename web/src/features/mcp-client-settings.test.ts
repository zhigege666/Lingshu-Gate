import { describe, expect, it } from "vitest"
import { clientConfiguration, clientEndpoint } from "./mcp-client-settings"

describe("MCP client discovery configuration", () => {
  const settings = { name: "gate", endpoint: "https://gate.example.test/mcp" }
  it("uses authorization settings without copying a client mode override", () => {
    expect(clientEndpoint(settings)).toBe(settings.endpoint)
    for (const mode of ["on_demand", "direct"]) {
      expect(clientEndpoint({ ...settings, endpoint: `${settings.endpoint}?tool_mode=${mode}` })).toBe(settings.endpoint)
    }
    expect(JSON.parse(clientConfiguration(settings)).mcpServers.gate.headers.Authorization).toBe("Bearer <YOUR_GATE_TOKEN>")
  })
  it("rejects embedded secrets, management resources and arbitrary query parameters", () => {
    for (const endpoint of ["https://name:password@gate.example.test/mcp", `${settings.endpoint}?token=secret`, `${settings.endpoint}/manage`, `${settings.endpoint}#secret`]) {
      expect(() => clientEndpoint({ ...settings, endpoint })).toThrow()
    }
  })
})

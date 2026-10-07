import { describe, expect, it } from "vitest"
import { clientConfiguration, clientEndpoint } from "./mcp-client-settings"

describe("MCP client discovery configuration", () => {
  const settings = { name: "gate", endpoint: "https://gate.example.test/mcp", mode: "direct" as const }
  it("preserves direct mode and explicitly selects on-demand mode per client", () => {
    expect(clientEndpoint(settings)).toBe(settings.endpoint)
    const selected = { ...settings, mode: "on_demand" as const }
    expect(clientEndpoint(selected)).toBe(`${settings.endpoint}?tool_mode=on_demand`)
    expect(clientEndpoint({ ...settings, endpoint: clientEndpoint(selected) })).toBe(settings.endpoint)
    expect(JSON.parse(clientConfiguration(selected)).mcpServers.gate.headers.Authorization).toBe("Bearer <YOUR_GATE_TOKEN>")
  })
  it("rejects embedded secrets, management resources and arbitrary query parameters", () => {
    for (const endpoint of ["https://name:password@gate.example.test/mcp", `${settings.endpoint}?token=secret`, `${settings.endpoint}/manage`, `${settings.endpoint}#secret`]) {
      expect(() => clientEndpoint({ ...settings, endpoint })).toThrow()
    }
  })
})

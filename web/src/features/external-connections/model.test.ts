import { describe, expect, it } from "vitest"
import type { ToolDefinition } from "@/api/client"
import { connectionDraft, connectionError, connectionReadiness, emptyConnection, eligibleTools, grantError, type GrantDraft } from "./model"
function tool(id: string, access: string, status = "published"): ToolDefinition {
  return { id: `mcp.${id}.tool`, name: id, source: "mcp", permission: "", description: "synthetic", input_schema: {}, metadata: { server_id: id, gate_access: { required_access: access, classification_status: status } } }
}
const tools = [tool("a", "read"), tool("b", "write"), tool("pending", "read", "pending")]
const grant: GrantDraft = { enabled: false, client_id: "synthetic-client", server_allowlist: ["a"], tool_allowlist: ["mcp.a.tool"], access: ["read"], expires_at: "2099-01-01T00:00:00Z", rate_per_minute: 30, concurrency: 1 }
describe("external trust and scope local validation", () => {
  it("rejects secrets in URLs and literal keys instead of safe references", () => {
    expect(connectionError({ ...emptyConnection, endpoint: "https://user:secret@example.invalid/mcp" })).not.toBeNull()
    expect(connectionError({ ...emptyConnection, runtime_secret_reference: "literal-secret" })).not.toBeNull()
    expect(connectionError({ ...emptyConnection, runtime_secret_reference: "credential:synthetic" })).toBeNull()
  })
  it("rejects ambiguous audiences rather than disabling audience checks", () => {
    expect(connectionError({ ...emptyConnection, resource_mappings: [["https://external.invalid", "https://gate.invalid/a"], ["https://external.invalid", "https://gate.invalid/b"]] })).not.toBeNull()
  })
  it("offers only published authorized MCP tools and rejects forged or stale choices", () => {
    expect(eligibleTools(tools, "read").map(item => item.id)).toEqual(["mcp.a.tool"])
    expect(grantError(grant, tools)).toBeNull()
    expect(grantError({ ...grant, tool_allowlist: ["mcp.hidden.tool"] }, tools)).not.toBeNull()
    expect(grantError(grant, [])).not.toBeNull()
    expect(grantError({ ...grant, access: ["read", "write"] }, tools)).not.toBeNull()
  })
  it("allows exact mixed read/write tool scopes but no extra service or expired scope", () => {
    expect(grantError({ ...grant, server_allowlist: ["a", "b"], tool_allowlist: ["mcp.a.tool", "mcp.b.tool"], access: ["read", "write"] }, tools)).toBeNull()
    expect(grantError({ ...grant, server_allowlist: ["a", "hidden"] }, tools)).not.toBeNull()
    expect(grantError({ ...grant, expires_at: "2000-01-01T00:00:00Z" }, tools)).not.toBeNull()
  })
  it("preserves enabled configuration and requires issuer, JWKS, client and canonical trust before enablement", () => {
    const ready = { ...emptyConnection, enabled: true, mode: "direct" as const, endpoint: "https://gate.invalid/mcp", trusted_issuers: ["https://issuer.invalid"], issuer_jwks: [["https://issuer.invalid", "https://issuer.invalid/jwks"]] as [string, string][], client_allowlist: ["test-client"], resource_mappings: [["https://tunnel.invalid/mcp", "https://gate.invalid/mcp"]] as [string, string][] }
    expect(connectionReadiness(ready)).toEqual([])
    expect(connectionDraft({ ...ready, revision: 4 }).enabled).toBe(true)
    expect(connectionReadiness({ ...ready, issuer_jwks: [] })).toContain("trusted_jwks_mapping_required")
    expect(connectionReadiness({ ...ready, client_allowlist: [] })).toContain("trusted_client_required")
    expect(connectionReadiness({ ...ready, canonical_resource_url: "https://other.invalid/mcp" })).toContain("canonical_resource_required")
    expect(connectionReadiness(emptyConnection)).not.toEqual([])
  })
  it("accepts enabled grants without discarding their state and validates actual limit bounds", () => {
    expect(grantError({ ...grant, enabled: true }, tools)).toBeNull()
    expect(grantError({ ...grant, rate_per_minute: 0 }, tools)).not.toBeNull()
    expect(grantError({ ...grant, concurrency: 1.5 }, tools)).not.toBeNull()
  })

})

import { bindingUserLabel } from "./model"

it("shows authoritative user labels without inventing names for missing users", () => {
  expect(bindingUserLabel({ id: "stable-id", username: "reader", display_name: "Read Team", status: "active" })).toBe("Read Team (@reader)")
  expect(bindingUserLabel({ id: "stable-id", username: "reader", display_name: "", status: "disabled" })).toBe("@reader")
  expect(bindingUserLabel(null)).toBe("User unavailable")
  expect(bindingUserLabel(undefined, "用户不可用")).toBe("用户不可用")
})

it('localizes both supported transports and the unconfigured state', async () => {
  const {transportLabel} = await import('./model')
  expect(transportLabel('direct', true)).toBe('公网 HTTPS 直连')
  expect(transportLabel('direct', false)).toBe('Direct HTTPS')
  expect(transportLabel('secure_mcp_tunnel', true)).toBe('安全 MCP 隧道')
  expect(transportLabel('secure_mcp_tunnel', false)).toBe('Secure MCP Tunnel')
  expect(transportLabel('disabled', true)).toBe('未选择传输方式')
  expect(transportLabel('disabled', false)).toBe('No transport selected')
})

it('does not advance an unconfigured guide but allows saving a partial disabled draft separately', async()=>{
 const {connectionGuideStepErrors}=await import('./model')
 expect(connectionGuideStepErrors(emptyConnection,0)).toContain('transport_not_configured')
 expect(connectionGuideStepErrors({...emptyConnection,mode:'direct',endpoint:'https://gate.example.com/mcp'},0)).toEqual([])
 expect(connectionGuideStepErrors({...emptyConnection,mode:'direct',endpoint:'https://gate.example.com/mcp'},1)).toContain('trusted_issuer_required')
 expect(connectionError({...emptyConnection,mode:'direct',endpoint:'https://gate.example.com/mcp'})).toBeNull()
})

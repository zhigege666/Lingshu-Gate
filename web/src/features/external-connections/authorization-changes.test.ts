import { describe, expect, it } from "vitest"
import { expandsExternalGrant, expandsExternalTrust, expandsManagementTargets, expandsServerPolicies, expandsTokenAccess } from "./authorization-changes"
import type { McpServerPolicy } from "./oauth-api"
import { emptyConnection, type GrantDraft } from "./model"

const read: McpServerPolicy = { server_id: "calendar", server_binding: "instance-1", mode: "continuous", access: "read" }
const write: McpServerPolicy = { ...read, access: "write" }

describe("authorization review follows actual access expansion", () => {
  it("saves policy removals, read-only narrowing and unchanged scopes directly", () => {
    expect(expandsServerPolicies([write], [read])).toBe(false)
    expect(expandsServerPolicies([read], [])).toBe(false)
    expect(expandsServerPolicies([read], [{ ...read }])).toBe(false)
  })
  it("reviews a new service, new write access and a rebound service even with no tool IDs", () => {
    expect(expandsServerPolicies([], [read])).toBe(true)
    expect(expandsServerPolicies([read], [write])).toBe(true)
    expect(expandsServerPolicies([read], [{ ...read, server_binding: "instance-2" }])).toBe(true)
  })
  it("preserves exact-tool grants until a user explicitly chooses continuous access", () => {
    const before = { mode: "independent" as const, scopes: ["tools.read"], server_policies: [] }
    expect(expandsTokenAccess(before, before, [])).toBe(false)
    expect(expandsTokenAccess(before, before, ["calendar.new"])).toBe(true)
    expect(expandsTokenAccess(before, { ...before, server_policies: [read] }, [])).toBe(true)
  })
  it("reviews account-following and functional-permission expansion", () => {
    const before = { mode: "independent" as const, scopes: ["tools.read"], server_policies: [read] }
    expect(expandsTokenAccess(before, { ...before, mode: "account" }, [])).toBe(true)
    expect(expandsTokenAccess(before, { ...before, scopes: ["tools.read", "tools.invoke"] }, [])).toBe(true)
    expect(expandsTokenAccess({ ...before, mode: "account" }, before, ["calendar.read"])).toBe(false)
    expect(expandsTokenAccess({ ...before, scopes: ["*"] }, before, [])).toBe(false)
  })
  it("reviews only new management target actions, independently of ordering", () => {
    const before = { calendar: ["test", "update"], email: ["test"] }
    expect(expandsManagementTargets(before, { calendar: ["update", "test"] })).toBe(false)
    expect(expandsManagementTargets(before, {})).toBe(false)
    expect(expandsManagementTargets(before, { calendar: ["delete"] })).toBe(true)
    expect(expandsManagementTargets(before, { drive: ["test"] })).toBe(true)
  })
  it("does not repeat the external-enable confirmation for ordinary or narrowing edits", () => {
    const before = { ...emptyConnection, enabled: true, trusted_issuers: ["https://issuer.test"], client_allowlist: ["one", "two"] }
    expect(expandsExternalTrust(before, { ...before, client_allowlist: ["one"] })).toBe(false)
    expect(expandsExternalTrust(before, { ...before, enabled: false })).toBe(false)
    expect(expandsExternalTrust(before, { ...before, trusted_issuers: [...before.trusted_issuers, "https://new.test"] })).toBe(true)
    expect(expandsExternalTrust(before, { ...before, issuer_jwks: [["https://issuer.test", "https://new-key.test/jwks"]] })).toBe(true)
  })
  it("keeps inactive transport drafts without asking to confirm an unchanged live connection", () => {
    const before = { ...emptyConnection, enabled: true, mode: "direct" as const, endpoint: "https://gate.test/mcp" }
    expect(expandsExternalTrust(before, { ...before, tunnel_reference: "tunnel:draft", runtime_secret_reference: "credential:draft" })).toBe(false)
    expect(expandsExternalTrust(before, { ...before, canonical_resource_url: before.endpoint })).toBe(false)
    expect(expandsExternalTrust(before, { ...before, endpoint: "https://other.test/mcp" })).toBe(true)
    const tunnel = { ...before, mode: "secure_mcp_tunnel" as const, canonical_resource_url: before.endpoint, tunnel_reference: "tunnel:active", runtime_secret_reference: "credential:active" }
    expect(expandsExternalTrust(tunnel, { ...tunnel, endpoint: "https://draft.test/mcp" })).toBe(false)
    expect(expandsExternalTrust(tunnel, { ...tunnel, runtime_secret_reference: "credential:replacement" })).toBe(true)
  })
  it("distinguishes external grant reductions from a new client, tool, or longer expiry", () => {
    const before: GrantDraft = { enabled: true, client_id: "one", server_allowlist: ["calendar"], tool_allowlist: ["read", "write"], access: ["read", "write"], expires_at: "2030-01-01T00:00:00Z", rate_per_minute: 6000, concurrency: 100 }
    expect(expandsExternalGrant(before, { ...before, tool_allowlist: ["read"], access: ["read"], rate_per_minute: 60 })).toBe(false)
    expect(expandsExternalGrant(before, { ...before, tool_allowlist: ["read", "write", "new"] })).toBe(true)
    expect(expandsExternalGrant(before, { ...before, client_id: "two" })).toBe(true)
    expect(expandsExternalGrant(before, { ...before, expires_at: "2031-01-01T00:00:00Z" })).toBe(true)
  })
})

import { describe, expect, it } from "vitest"
import { filterGrants, grantRemaining, grantState, isOAuthQuotaOnlyChange, utcGrantTime } from "./oauth-grants-model"
import type { OAuthGrant } from "./oauth-api"

const now = 2_000_000_000
const base: OAuthGrant = { id: "synthetic-grant", client_id: "synthetic-client", client_name: "Synthetic client", resource: "https://gate.example.test/mcp", scopes: ["tools.read"], tools: [{ id: "synthetic-tool", name: "Named read tool", server_id: "synthetic-mcp", server_name: "Named MCP", access: "read", snapshot: "synthetic" }], state: "active", expires_at: now + 600, rate_per_minute: 30, concurrency: 1, revision: 1, scope_currently_authorized: true, effective_tool_count: 1 }

describe("personal grant list", () => {
  it("keeps revoked state distinct from time expiry and fails closed on disabled/unknown state", () => {
    expect(grantState({ ...base, state: "revoked", expires_at: now - 1 }, now)).toBe("revoked")
    expect(grantState({ ...base, expires_at: now }, now)).toBe("expired")
    expect(grantState({ ...base, state: "expired" }, now)).toBe("expired")
    expect(filterGrants([{ ...base, state: "disabled" }, { ...base, state: "unknown" }], "active", "", now)).toEqual([])
  })
  it("filters the full loaded 1000-record dataset before pagination", () => {
    const grants = Array.from({ length: 1000 }, (_, index) => ({ ...base, id: `synthetic-${index}`, state: index >= 950 ? "active" : "revoked" }))
    const result = filterGrants(grants, "active", "", now)
    expect(result).toHaveLength(50)
    expect(result[0].id).toBe("synthetic-950")
    expect(filterGrants(grants, "revoked", "", now)).toHaveLength(950)
    expect(filterGrants(grants, "all", "", now)).toHaveLength(1000)
  })
  it.each(["Synthetic client", "synthetic-client", "Named read tool", "Named MCP", "synthetic-mcp", "synthetic-grant"])("searches names and identifiers across all loaded scope: %s", query => {
    expect(filterGrants([base], "active", query, now)).toEqual([base])
  })
  it("searches a 5000-tool, 100-MCP record beyond its first tool page", () => {
    const tools = Array.from({ length: 5000 }, (_, index) => ({ ...base.tools[0], id: `tool-${index}`, name: `Named tool ${index}`, server_id: `mcp-${Math.floor(index / 50)}`, server_name: `MCP ${Math.floor(index / 50)}` }))
    expect(filterGrants([{ ...base, tools }], "active", "Named tool 4999", now)).toHaveLength(1)
    expect(filterGrants([{ ...base, tools }], "active", "MCP 99", now)).toHaveLength(1)
    expect(new Set(tools.map(tool => tool.server_id)).size).toBe(100)
  })
  it("handles zero/one records and does not invent an authorization timestamp", () => {
    expect(filterGrants([], "active", "", now)).toEqual([])
    expect(filterGrants([base], "active", "", now)).toHaveLength(1)
    expect(utcGrantTime(base.created_at)).toBeNull()
    expect(utcGrantTime(0)).toBeNull()
    expect(utcGrantTime(Number.NaN)).toBeNull()
    expect(utcGrantTime(now)).toMatch(/ UTC$/)
  })
  it("gives explicit bounded remaining time without treating expired grants as active", () => {
    expect(grantRemaining(now, now, false)).toBe("Expired")
    expect(grantRemaining(now + 10, now, true)).toBe("剩余约 1 分钟")
    expect(grantRemaining(now + 3601, now, false)).toBe("About 2 h remaining")
    expect(grantRemaining(now + 86400, now, true)).toBe("剩余约 1 天")
  })
})

describe("OAuth 仅调整配额的范围保留", () => {
  const stale: OAuthGrant = { ...base, tools: [{ ...base.tools[0], currently_authorized: false }], scope_currently_authorized: false, server_policies: [{ server_id: "old-server", server_binding: "old-lifecycle", mode: "continuous", access: "read" }] }
  const original = () => ({ toolIds: stale.tools.map(tool => tool.id), policies: [...stale.server_policies!], expiresAt: stale.expires_at, rate: stale.rate_per_minute, concurrency: stale.concurrency })
  it("已失效的精确工具与服务绑定不变时允许调高或调低配额，保留原快照", () => {
    const before = JSON.stringify(stale)
    expect(isOAuthQuotaOnlyChange(stale, { ...original(), rate: 6000, concurrency: 100 })).toBe(true)
    expect(isOAuthQuotaOnlyChange(stale, { ...original(), rate: 1 })).toBe(true)
    expect(JSON.stringify(stale)).toBe(before)
    expect(stale.tools[0].currently_authorized).toBe(false)
    expect(stale.server_policies![0].server_binding).toBe("old-lifecycle")
  })
  it("改动工具、服务意图、身份绑定或到期时间不能通过仅配额路径", () => {
    const draft = { ...original(), rate: 6000 }
    expect(isOAuthQuotaOnlyChange(stale, { ...draft, toolIds: [] })).toBe(false)
    expect(isOAuthQuotaOnlyChange(stale, { ...draft, policies: [] })).toBe(false)
    expect(isOAuthQuotaOnlyChange(stale, { ...draft, policies: [{ ...draft.policies[0], access: "write" }] })).toBe(false)
    expect(isOAuthQuotaOnlyChange(stale, { ...draft, policies: [{ ...draft.policies[0], server_binding: "new-lifecycle" }] })).toBe(false)
    expect(isOAuthQuotaOnlyChange(stale, { ...draft, expiresAt: stale.expires_at - 60 })).toBe(false)
    expect(isOAuthQuotaOnlyChange(stale, original())).toBe(false)
    expect(isOAuthQuotaOnlyChange(stale, { ...draft, rate: null })).toBe(false)
  })
  it("采用后端兼容语义：省略未改变策略的绑定仍只保留原绑定", () => {
    expect(isOAuthQuotaOnlyChange(stale, { ...original(), rate: 6000, policies: [{ server_id: "old-server", mode: "continuous", access: "read" }] })).toBe(true)
  })
})

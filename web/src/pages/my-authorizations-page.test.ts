import { describe, expect, it } from "vitest"
import { authorizationRows } from "@/features/external-connections/my-authorizations-model"
import type { PersonalToken } from "@/api/client"
import type { OAuthGrant } from "@/features/external-connections/oauth-api"
import type { Grant } from "@/features/external-connections/model"

describe("我的授权来源聚合", () => {
  const token: PersonalToken = { id: "same", name: "Demo", token_prefix: "prefix", scopes: ["tools.read"], created_at: "2026-10-15T00:00:00Z" }
  const oauth: OAuthGrant = { id: "same", client_name: "Demo", client_id: "client", resource: "https://example.test/mcp", scopes: ["tools.read"], tools: [], state: "active", expires_at: 2000000000, rate_per_minute: 300, concurrency: 1, revision: 1, scope_currently_authorized: true, effective_tool_count: 0, server_policies: [{ server_id: "offline", mode: "continuous", access: "read" }] }
  const external: Grant = { id: "same", enabled: true, client_id: "Demo", server_allowlist: ["one"], tool_allowlist: ["one:a"], access: ["read"], expires_at: "2030-01-01T00:00:00Z", rate_per_minute: 6000, concurrency: 100, revision: 1, state: "enabled", scope_currently_authorized: true }
  it("相同名称和ID的不同来源不合并，配额展示真实值", () => {
    const rows = authorizationRows([token], [oauth], [external], true, Date.parse("2026-10-15T00:00:00Z"))
    expect(rows.map(row => row.key)).toEqual(["api:same", "builtin:same", "external:same"])
    expect(rows.map(row => [row.rate, row.concurrency])).toEqual([[null, null], [300, 1], [6000, 100]])
    expect(rows[0].scope).toBe("跟随账号资源权限")
    expect(rows[1].scope).toContain("1 MCP · 1 持续授权")
  })
  it("已撤销或到期API授权仍保留历史且不伪造quota", () => {
    const rows = authorizationRows([{ ...token, revoked_at: "2026-10-14T00:00:00Z" }, { ...token, id: "expired", expires_at: "2026-10-14T00:00:00Z" }], [], [], false, Date.parse("2026-10-15T00:00:00Z"))
    expect(rows.map(row => row.status)).toEqual(["revoked", "expired"])
    expect(rows.every(row => row.rate === null)).toBe(true)
  })
})

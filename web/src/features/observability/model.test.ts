import { describe, expect, it } from "vitest"
import { cleanObservabilityFilters, createRequestOwner, exactScopeId, observabilityHash, readObservabilityHash, scopeOptionLabel } from "./model"

describe("observability scope selection", () => {
  it("round-trips exact MCP identity, tab and independent draft filters through a deep link", () => {
    const selection = { logs: { server_id: "service-a", limit: 100, keyword: "timeout & restart", level: "error" }, events: { server_id: "service-a", limit: 50, source: "configs" }, tab: "events" as const }
    expect(readObservabilityHash(observabilityHash(selection))).toEqual(selection)
    expect(observabilityHash(selection)).toMatch(/^#\/logs\/service-a\?tab=events/)
  })
  it("retains an all-services route while rejecting malformed IDs and invalid limits", () => {
    expect(readObservabilityHash("#/logs/?tab=events")).toEqual({ logs: { limit: 80 }, events: { limit: 80 }, tab: "events" })
    expect(readObservabilityHash("#/logs/%E0%A4%A?log_limit=999999").logs).toEqual({ limit: 80 })
    expect(exactScopeId("  deleted-service.1  ")).toBe("deleted-service.1")
    expect(exactScopeId("../service")).toBeNull()
    expect(exactScopeId("*")).toBeNull()
  })
  it("labels current and historical options only from authorized API records", () => {
    expect(scopeOptionLabel({ id: "a", name: "Service A", availability: "current" }, "Historical")).toBe("Service A · a")
    expect(scopeOptionLabel({ id: "old", name: "old", availability: "historical" }, "Historical")).toBe("old · Historical")
  })
  it("omits empty filters without confusing all with a literal resource name", () => {
    expect(cleanObservabilityFilters({ server_id: "", level: undefined, limit: 80 })).toEqual({ limit: 80 })
    expect(readObservabilityHash("#/logs/all").logs.server_id).toBe("all")
    expect(cleanObservabilityFilters({ server_id: "__all__" })).toEqual({ server_id: "__all__" })
  })
  it("rejects late results independently of whether transport abort succeeded", async () => {
    const owner = createRequestOwner()
    let resolveOld!: (value: string) => void
    const old = new Promise<string>(resolve => { resolveOld = resolve })
    const first = owner.next()
    const published: string[] = []
    const waiting = old.then(value => { if (owner.owns(first)) published.push(value) })
    const second = owner.next()
    if (owner.owns(second)) published.push("current")
    resolveOld("old"); await waiting
    expect(published).toEqual(["current"])
    owner.invalidate()
    expect(owner.owns(second)).toBe(false)
  })
})

import { changeLogScope } from "./model"

describe("dependent log tool selection", () => {
  it("clears an inapplicable tool on MCP switch and clearing all, preserving unrelated filters", () => {
    const original = { server_id: "a", tool_id: "mcp.a.read", keyword: "error", limit: 80 }
    expect(changeLogScope(original, "b")).toEqual({ server_id: "b", tool_id: undefined, keyword: "error", limit: 80 })
    const cleared = changeLogScope(original, "")
    expect(cleared.tool_id).toBeUndefined()
    expect(cleared.server_id).toBeUndefined()
    expect(changeLogScope(cleared, "")).toEqual(cleared)
  })
  it("keeps exact historical tool deep links without requiring a live catalog", () => {
    const original = { server_id: "deleted", tool_id: "mcp.deleted.old", limit: 80 }
    expect(changeLogScope(original, "deleted")).toEqual(original)
    expect(readObservabilityHash(observabilityHash({ logs: original, events: { server_id: "deleted", limit: 80 }, tab: "logs" })).logs).toEqual(original)
  })
})

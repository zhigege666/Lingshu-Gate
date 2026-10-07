import { afterEach, describe, expect, it, vi } from "vitest"
import { observabilityApi } from "./observability"

afterEach(() => vi.unstubAllGlobals())
describe("observability scope API contract", () => {
  it("searches authorized scope options and propagates cancellation", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ scopes: [], total: 0 }) })
    vi.stubGlobal("fetch", fetcher)
    const controller = new AbortController()
    await observabilityApi.observabilityMcpScopes({ q: "Data MCP", offset: 40, limit: 40 }, controller.signal)
    expect(fetcher.mock.calls[0][0]).toBe("/v1/observability/mcp-scopes?q=Data+MCP&offset=40&limit=40")
    expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal)
  })
  it("uses the same server scope for logs and events without aliasing arbitrary subject IDs", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, text: async () => "{}" })
    vi.stubGlobal("fetch", fetcher)
    await observabilityApi.logs({ server_id: "historical-a" })
    await observabilityApi.events({ server_id: "historical-a" })
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(["/v1/logs?server_id=historical-a", "/v1/events?server_id=historical-a"])
  })
})

it("requests tools only within an explicit MCP log scope with cancellable search and exact lookup", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ scopes: [], total: 0 }) })
  vi.stubGlobal("fetch", fetcher)
  const controller = new AbortController()
  await observabilityApi.observabilityToolScopes({ server_id: "deleted-a", q: "Read records", offset: 40, limit: 40 }, controller.signal)
  expect(fetcher.mock.calls[0][0]).toBe("/v1/observability/tool-scopes?server_id=deleted-a&q=Read+records&offset=40&limit=40")
  expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal)
  await observabilityApi.observabilityToolScopes({ server_id: "deleted-a", tool_id: "mcp.deleted-a.old", limit: 1 })
  expect(fetcher.mock.calls[1][0]).toBe("/v1/observability/tool-scopes?server_id=deleted-a&tool_id=mcp.deleted-a.old&limit=1")
})

import { afterEach, describe, expect, it, vi } from "vitest"
import { canonicalGroupBody, GROUP_REQUEST_TIMEOUT_MS, mcpGroupsApi } from "./mcp-groups"

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers() })
describe("group metadata requests", () => {
  it("uses complete server-side search and pagination, without schema requests", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ instances: [], total: 1000, offset: 980, limit: 20 })))
    vi.stubGlobal("fetch", fetch)
    const page = await mcpGroupsApi.instances({ q: "中文 instance", offset: 980, limit: 20 })
    expect(page.total).toBe(1000)
    const url = new URL(fetch.mock.calls[0][0], "https://gate.example.test")
    expect(url.pathname).toBe("/v1/mcp/groups/instances")
    expect(url.searchParams.get("q")).toBe("中文 instance")
    expect(url.searchParams.get("offset")).toBe("980")
    expect(fetch).toHaveBeenCalledTimes(1)
  })
  it("binds a single-use ticket to the exact multilingual draft and revision", async () => {
    const body = { name: "中文组", description: "测试", status: "active" as const, members: ["a", "b"], reconfirm_members: [], confirmed: true as const, expected_revision: 7 }
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ csrf: "synthetic-ticket" }))).mockResolvedValueOnce(new Response(JSON.stringify({ id: "a".repeat(32), revision: 8 })))
    vi.stubGlobal("fetch", fetch)
    await mcpGroupsApi.save("a".repeat(32), body)
    expect(canonicalGroupBody(body)).toBe('{"confirmed":true,"description":"测试","expected_revision":7,"members":["a","b"],"name":"中文组","reconfirm_members":[],"status":"active"}')
    const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalGroupBody(body)))), byte => byte.toString(16).padStart(2, "0")).join("")
    expect(new URL(fetch.mock.calls[0][0], "https://gate.example.test").searchParams.get("request_digest")).toBe(digest)
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: "PUT", headers: { "X-CSRF-Token": "synthetic-ticket" }, body: JSON.stringify(body) })
  })
  it("bounds an unresponsive body and never replays a write", async () => {
    vi.spyOn(crypto.subtle, "digest").mockResolvedValue(new ArrayBuffer(32))
    vi.useFakeTimers()
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ csrf: "synthetic-ticket" })))
      .mockResolvedValueOnce({ ok: true, text: () => new Promise(() => {}) })
    vi.stubGlobal("fetch", fetch)
    const promise = mcpGroupsApi.delete("b".repeat(32), 3)
    const assertion = expect(promise).rejects.toThrow("group_request_timeout")
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(GROUP_REQUEST_TIMEOUT_MS + 1)
    await assertion
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls[1][1].signal.aborted).toBe(true)
  })
  it("retains an explicit create key and binds it to each fresh ticket on retry", async () => {
    const body = { name: "Synthetic retry", description: "", status: "active" as const, members: [], reconfirm_members: [], confirmed: true as const, request_key: "d".repeat(32) }
    const fetch = vi.fn().mockImplementation(async (path: string) => new Response(JSON.stringify(path.includes("/csrf") ? { csrf: "synthetic-ticket" } : { id: "c".repeat(32), revision: 1 })))
    vi.stubGlobal("fetch", fetch)
    await mcpGroupsApi.save(undefined, body)
    await mcpGroupsApi.save(undefined, body)
    expect(fetch).toHaveBeenCalledTimes(4)
    expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[3][1].body)
    expect(new URL(fetch.mock.calls[0][0], "https://gate.example.test").searchParams.get("request_digest"))
      .toBe(new URL(fetch.mock.calls[2][0], "https://gate.example.test").searchParams.get("request_digest"))
  })
  it("reconciles a creation by read only and explicitly refreshes metadata", async () => {
    const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ id: "c".repeat(32) })))
    vi.stubGlobal("fetch", fetch)
    await mcpGroupsApi.createResult("d".repeat(32))
    await mcpGroupsApi.instances({ refresh: true, limit: 1 })
    expect(fetch.mock.calls[0][0]).toBe("/v1/mcp/groups/requests/" + "d".repeat(32))
    expect(fetch.mock.calls.every(call => !call[1].method || call[1].method === "GET")).toBe(true)
    expect(new URL(fetch.mock.calls[1][0], "https://gate.example.test").searchParams.get("refresh")).toBe("true")
  })
})

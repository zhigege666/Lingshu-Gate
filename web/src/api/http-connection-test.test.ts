import { afterEach, describe, expect, it, vi } from "vitest"
import { testHttpConnection } from "./http-connection-test"

const manifest = { id: "synthetic-peer", launch: { type: "external" }, transport: { type: "streamable_http", endpoint: "https://mcp.example.test/mcp" } }

describe("HTTP connection test requests", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it("binds one CSRF ticket to exactly the tested draft without WebCrypto or config writes", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response('{"csrf":"synthetic-ticket"}')).mockResolvedValueOnce(new Response('{"ok":true,"tool_count":0}'))
    vi.stubGlobal("fetch", fetcher)
    vi.stubGlobal("crypto", {})
    expect(await testHttpConnection(manifest)).toMatchObject({ ok: true, tool_count: 0 })
    expect(fetcher).toHaveBeenCalledTimes(2)
    const [ticket, test] = fetcher.mock.calls
    expect(ticket[0]).toBe("/v1/mcp/external-configs/test/csrf")
    expect(test[0]).toBe("/v1/mcp/external-configs/test")
    expect(ticket[1].body).toBe(test[1].body)
    expect(JSON.parse(test[1].body)).toEqual({ manifest, confirmed: true, timeout_seconds: 15 })
    expect(test[1]).toMatchObject({ method: "POST", cache: "no-store", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": "synthetic-ticket" } })
  })

  it("includes the original saved digest, not an implicit fresh snapshot", async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"csrf":"synthetic-ticket","ok":true}')))
    vi.stubGlobal("fetch", fetcher)
    await testHttpConnection(manifest, "synthetic-peer", "a".repeat(64))
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({ existing_server_id: "synthetic-peer", expected_config_digest: "a".repeat(64) })
  })

  it("does not call the target adapter after a denied ticket, or automatically retry failures", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"detail":{"code":"cross_origin_denied"}}', { status: 403 }))
    vi.stubGlobal("fetch", fetcher)
    await expect(testHttpConnection(manifest)).rejects.toThrow("cross_origin_denied")
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it("ends waiting on the client deadline without issuing a retry", async () => {
    vi.useFakeTimers()
    const fetcher = vi.fn().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true })
    }))
    vi.stubGlobal("fetch", fetcher)
    const waiting = testHttpConnection(manifest)
    const assertion = expect(waiting).rejects.toMatchObject({ name: "AbortError" })
    await vi.advanceTimersByTimeAsync(35_000)
    await assertion
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

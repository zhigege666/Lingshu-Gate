import { afterEach, describe, expect, it, vi } from "vitest"
import { fetchGateVersion, GATE_VERSION_TIMEOUT_MS } from "./gate-version"
import { gateVersionText } from "@/features/gate-version"

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe("public running Gate version", () => {
  it("uses the actual backend version with no credentials or cache", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ version: "9.8.7-rc.2", ignored: "never displayed" })))
    vi.stubGlobal("fetch", fetcher)
    expect(await fetchGateVersion()).toBe("9.8.7-rc.2")
    expect(fetcher).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledWith("/healthz", expect.objectContaining({ method: "GET", credentials: "omit", cache: "no-store" }))
  })

  it.each([null, {}, { version: 4 }, { version: "" }, { version: "/private/build/path" }, { version: "<script>secret</script>" },
    { version: "1.2" }, { version: "01.2.3" }, { version: "1.2.3-rc.01" }, { version: `1.2.3-${"a".repeat(91)}` }])("rejects unavailable or unsafe metadata %#", async data => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))))
    await expect(fetchGateVersion()).rejects.toThrow("Gate version is unavailable")
  })

  it.each([401, 503])("does not expose HTTP %s response details or retry", async status => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "private diagnostic", version: "9.8.7" }), { status }))
    vi.stubGlobal("fetch", fetcher)
    await expect(fetchGateVersion()).rejects.toThrow("Gate version is unavailable")
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it("handles non-JSON public responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>proxy failure</html>")))
    await expect(fetchGateVersion()).rejects.toThrow()
  })

  it.each(["headers", "body"])("bounds stalled %s and aborts without retry", async phase => {
    vi.useFakeTimers()
    const never = new Promise(() => {})
    const fetcher = vi.fn().mockReturnValue(phase === "headers" ? never : Promise.resolve({ ok: true, json: () => never }))
    vi.stubGlobal("fetch", fetcher)
    const pending = fetchGateVersion()
    const assertion = expect(pending).rejects.toThrow("Gate version is unavailable")
    await vi.advanceTimersByTimeAsync(GATE_VERSION_TIMEOUT_MS)
    await assertion
    expect(fetcher).toHaveBeenCalledOnce()
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it("cancels an owned pending read on unmount", async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const fetcher = vi.fn().mockReturnValue(new Promise(() => {}))
    vi.stubGlobal("fetch", fetcher)
    const pending = fetchGateVersion(controller.signal)
    const assertion = expect(pending).rejects.toThrow("Gate version is unavailable")
    controller.abort()
    await assertion
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it("does not start a cancelled read", async () => {
    const controller = new AbortController()
    controller.abort()
    const fetcher = vi.fn()
    vi.stubGlobal("fetch", fetcher)
    await expect(fetchGateVersion(controller.signal)).rejects.toThrow("Gate version is unavailable")
    expect(fetcher).not.toHaveBeenCalled()
  })

  it.each(["zh-CN", "en-US"] as const)("uses honest localized loading/failure labels in %s", locale => {
    expect(gateVersionText({ status: "ready", version: "9.8.7-rc.2" }, locale)).toBe("v9.8.7-rc.2")
    expect(gateVersionText({ status: "loading" }, locale)).toBe(locale === "zh-CN" ? "正在读取版本…" : "Reading version…")
    expect(gateVersionText({ status: "unavailable" }, locale)).toBe(locale === "zh-CN" ? "版本不可用" : "Version unavailable")
  })
})

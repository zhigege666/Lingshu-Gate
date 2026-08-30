import { afterEach, describe, expect, it, vi } from "vitest"
import { queryString } from "@/api/http"
import { serversRuntimeApi } from "@/api/servers-runtime"
import { buildApi } from "@/api/builds"

describe("feature API construction", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("omits unset filters and preserves explicit values", () => {
    expect(queryString({ level: "warning", source: "", limit: 0, missing: undefined }))
      .toBe("?level=warning&limit=0")
  })

  it("encodes server ids and uses the requested lifecycle method", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"id":"a/b"}', {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await serversRuntimeApi.serverAction("a/b", "restart")

    expect(fetchMock).toHaveBeenCalledWith("/v1/mcp/servers/a%2Fb/restart", expect.objectContaining({
      method: "POST",
      credentials: "include",
    }))
  })

  it("defaults config, deploy, and rollback side effects to false", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{"message":"ok"}', {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)

    await serversRuntimeApi.createConfig({ id: "safe-defaults" })
    await serversRuntimeApi.updateConfig("safe-defaults", { id: "safe-defaults" })
    await buildApi.deployBuild("build-safe-defaults")
    await buildApi.rollback("deployment-safe-defaults")

    const requestBodies = fetchMock.mock.calls.map((call) => JSON.parse(String(call[1]?.body)))
    expect(requestBodies[0]).toMatchObject({ apply: false, start: false })
    expect(requestBodies[1]).toMatchObject({ apply: false, start: false })
    expect(requestBodies[2]).toMatchObject({ start: false, overwrite: false })
    expect(requestBodies[3]).toEqual({ start: false })
  })
})

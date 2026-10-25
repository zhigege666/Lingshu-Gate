import { afterEach, describe, expect, it, vi } from "vitest"
import { queryString } from "@/api/http"
import { serversRuntimeApi } from "@/api/servers-runtime"
import { buildApi } from "@/api/builds"
import { identityAccessApi } from "@/api/identity-access"

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

  it("invokes the exact registered tool with arguments only and retains session credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    const args = { query: "sample", limit: 0, includeArchived: false, nested: { keep: null } }

    await serversRuntimeApi.invoke("mcp.docs-test.search", args)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith("/v1/invoke", expect.objectContaining({
      method: "POST", credentials: "include",
      body: JSON.stringify({ tool_id: "mcp.docs-test.search", arguments: args }),
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

  it("requests one bounded detail section and forwards cancellation", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{"server":{"id":"a/b"}}', {
      status: 200, headers: { "Content-Type": "application/json" },
    }))
    vi.stubGlobal("fetch", fetchMock)
    const controller = new AbortController()

    await serversRuntimeApi.serverDetail("a/b", { section: "logs", limit: 40, signal: controller.signal })

    expect(fetchMock).toHaveBeenCalledWith("/v1/mcp/servers/a%2Fb/detail?section=logs&limit=40", expect.objectContaining({
      signal: controller.signal, credentials: "include",
    }))
    await serversRuntimeApi.serverDetail("a/b")
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/mcp/servers/a%2Fb/detail")
  })

  it("keeps HTTP permission intent in the checked save request and revokes with an exact revision", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    const trust = { http_trust_action: "restore" as const, expected_http_trust_revision: 7 }
    await serversRuntimeApi.validateConfig({ id: "test-service" }, "test-service", trust)
    await serversRuntimeApi.updateConfig("test-service", { id: "test-service" }, false, false, {}, "a".repeat(64), trust)
    await serversRuntimeApi.replaceMcpHttpTrust("test-service", [], 8)
    const bodies = fetchMock.mock.calls.map(call => JSON.parse(String(call[1].body)))
    expect(bodies[0]).toMatchObject({ ...trust, apply: false, start: false })
    expect(bodies[1]).toMatchObject({ ...trust, expected_config_digest: "a".repeat(64), apply: false, start: false })
    expect(bodies[1].manifest).toEqual({ id: "test-service" })
    expect(bodies[2]).toEqual({ origins: [], expected_revision: 8, confirmed: true })
  })

  it("uses a credential snapshot revision and idempotency key for deletion", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    await identityAccessApi.deleteCredential("test/key", "2026-10-23T09:00:00+00:00", "test-delete-01")
    expect(fetchMock.mock.calls[0][0]).toBe("/v1/credentials/test%2Fkey?expected_revision=2026-10-23T09%3A00%3A00%2B00%3A00&idempotency_key=test-delete-01")
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "DELETE" })
  })
})

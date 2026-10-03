import { afterEach, describe, expect, it, vi } from "vitest"
import { oauthError, oauthRequest, OAuthRequestError, toolFilter, type OAuthTool } from "./oauth-api"

const tools: OAuthTool[] = Array.from({ length: 5000 }, (_, index) => ({ id: `mcp.service-${Math.floor(index / 50)}.tool-${index}`, name: `Tool ${index}`, server_id: `service-${Math.floor(index / 50)}`, server_name: `Synthetic catalog ${Math.floor(index / 50)}`, access: index % 2 ? "write" : "read", snapshot: `snapshot-${index}` }))
afterEach(() => vi.unstubAllGlobals())

describe("OAuth scope and request boundaries", () => {
  it("searches thousands of tools across 100 MCPs without expanding selection", () => {
    expect(new Set(tools.map(tool => tool.server_id)).size).toBe(100)
    expect(toolFilter(tools, "", "service-99", "read")).toHaveLength(25)
    expect(toolFilter(tools, "tool-4999", "", "").map(tool => tool.id)).toEqual(["mcp.service-99.tool-4999"])
    expect(toolFilter(tools, "tool-4999", "", "read")).toEqual([])
    expect(tools).toHaveLength(5000)
  })
  it("localizes recoverable and terminal errors without echoing an untrusted body", () => {
    expect(oauthError(new OAuthRequestError("login_required", 401), true)).toContain("重新登录")
    expect(oauthError(new OAuthRequestError("authorization_completed", 409), false)).toContain("already processed")
    expect(oauthError(new Error("password=private client_secret=private"), false)).not.toContain("private")
    expect(oauthError(new OAuthRequestError("client_secret=private", 502), true)).not.toContain("private")
  })
  it("finds actual MCP display names and tolerates missing legacy names", () => {
    expect(toolFilter(tools, "Synthetic catalog 99", "", "")).toHaveLength(50)
    expect(toolFilter(tools, "service-99", "", "read")).toHaveLength(25)
    expect(toolFilter([{ ...tools[0], server_name: null }], "service-0", "", "")).toHaveLength(1)
    expect(toolFilter([{ ...tools[0], server_name: null }], "invented service", "", "")).toEqual([])
  })
  it("never retries a failed write or retains a secret in browser storage", async () => {
    vi.stubGlobal("window", { setTimeout, clearTimeout })
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "revision_conflict" }), { status: 409 }))
    vi.stubGlobal("fetch", fetch)
    await expect(oauthRequest("/v1/auth/oauth/clients/example", { rotate_secret: true }, "PATCH")).rejects.toMatchObject({ code: "revision_conflict", status: 409 })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "PATCH", cache: "no-store", credentials: "same-origin" })
  })
  it("returns a one-time secret only to the current caller", async () => {
    vi.stubGlobal("window", { setTimeout, clearTimeout })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ client: { id: "synthetic" }, client_secret: "synthetic-once" }), { status: 201 })))
    const result = await oauthRequest<{ client_secret: string }>("/v1/auth/oauth/clients", { name: "Synthetic" })
    expect(result.client_secret).toBe("synthetic-once")
  })
})

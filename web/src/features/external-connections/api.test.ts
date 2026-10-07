import { afterEach, describe, expect, it, vi } from "vitest"
import { activationReason, externalError, externalRequest } from "./api"
afterEach(() => vi.unstubAllGlobals())
describe("external control API feedback", () => {
  it("keeps actionable activation errors instead of object stringification and never retries a write", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { activation_errors: ["subject_link_required", "client_not_allowed"] } }), { status: 409 }))
    vi.stubGlobal("fetch", fetch)
    await expect(externalRequest("/v1/auth/external-grants", { method: "POST", body: "{}" })).rejects.toThrow("subject_link_required, client_not_allowed")
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(externalError(new Error("subject_link_required, client_not_allowed"), true)).toContain("身份绑定")
    expect(activationReason("subject_link_required", false)).toContain("identity binding")
  })
  it("retains the actual enabled response without converting it into a draft", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ enabled: true, state: "enabled", connected: false }))))
    expect(await externalRequest("/v1/auth/external-grants/example")).toEqual({ enabled: true, state: "enabled", connected: false })
  })
})

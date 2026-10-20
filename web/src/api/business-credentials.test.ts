import { afterEach, describe, expect, it, vi } from "vitest"
import { businessCredentialsApi, BusinessCredentialRequestError, canonicalBusinessCredentialBody } from "./business-credentials"
import { businessCredentialWrite, emptyBusinessCredentialDraft } from "@/features/business-credentials"

describe("business credential API boundary", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it("binds a CSRF ticket to the method, encoded path, revision query, and canonical body with a separate random HMAC nonce", async () => {
    const fetcher = vi.fn().mockImplementation(async (path: string) => new Response(path.includes("/csrf?") ? '{"csrf":"one-use-ticket"}' : '{"deleted":true}', { status: 200 }))
    vi.stubGlobal("fetch", fetcher)
    await businessCredentialsApi.deleteBinding("account/a", "binding/b", 7)
    expect(fetcher).toHaveBeenCalledTimes(2)
    const url = new URL(fetcher.mock.calls[0][0], "https://gate.example.test")
    expect(url.pathname).toBe("/v1/business-credentials/csrf")
    expect(url.searchParams.get("target")).toBe("DELETE:/v1/business-credentials/account%2Fa/bindings/binding%2Fb?expected_revision=7")
    const nonce = fetcher.mock.calls[1][1].headers["X-CSRF-Nonce"] as string
    expect(nonce).toMatch(/^[a-f0-9]{64}$/)
    expect(fetcher.mock.calls[0][0]).not.toContain(nonce)
    expect(fetcher.mock.calls[0][1].headers["X-CSRF-Nonce"]).toBeUndefined()
    const key = await crypto.subtle.importKey("raw", Uint8Array.from(nonce.match(/../g)!, value => parseInt(value, 16)), { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
    const bytes = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("{}"))
    expect(url.searchParams.get("request_digest")).toBe(Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, "0")).join(""))
    expect(fetcher.mock.calls[1]).toEqual(["/v1/business-credentials/account%2Fa/bindings/binding%2Fb?expected_revision=7", expect.objectContaining({ method: "DELETE", credentials: "include", cache: "no-store", body: "{}", headers: expect.objectContaining({ "X-CSRF-Token": "one-use-ticket" }) })])
  })

  it("keeps secrets out of ticket URLs and sends no update scope or mask", async () => {
    const fetcher = vi.fn().mockImplementation(async (path: string) => new Response(path.includes("/csrf?") ? '{"csrf":"ticket"}' : '{}', { status: 200 }))
    vi.stubGlobal("fetch", fetcher)
    const draft = { ...emptyBusinessCredentialDraft(), name: "test", password: "private-value" }
    await businessCredentialsApi.update("credential", { ...businessCredentialWrite(draft, true, "personal"), expected_version: 3 })
    expect(fetcher.mock.calls[0][0]).not.toContain("private-value")
    const body = JSON.parse(fetcher.mock.calls[1][1].body)
    expect(body.password).toBe("private-value")
    expect(body.username).toBeNull()
    expect(body.scope).toBeUndefined()
    expect(body.expected_version).toBe(3)
  })

  it("forwards scope and cancellation on reads", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"servers":[],"users":[],"roles":[]}', { status: 200 }))
    vi.stubGlobal("fetch", fetcher)
    const controller = new AbortController()
    await businessCredentialsApi.targets("personal", controller.signal)
    expect(fetcher).toHaveBeenCalledWith("/v1/business-credentials/targets?scope=personal", expect.objectContaining({ credentials: "include", cache: "no-store", signal: expect.any(AbortSignal) }))
  })

  it("renders only a bounded machine code from failures, never secret-bearing validation input or remote text", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"detail":{"code":"business_credential_invalid","message":"private-value","input":{"password":"private-value"}}}', { status: 422 }))
    vi.stubGlobal("fetch", fetcher)
    let failure: unknown
    try { await businessCredentialsApi.list("personal") } catch (error) { failure = error }
    expect(failure).toBeInstanceOf(BusinessCredentialRequestError)
    expect(String(failure)).toContain("business_credential_invalid")
    expect(String(failure)).not.toContain("private-value")
  })

  it("does not retry ambiguous writes automatically", async () => {
    const fetcher = vi.fn().mockImplementation(async (path: string) => {
      if (path.includes("/csrf?")) return new Response('{"csrf":"ticket"}', { status: 200 })
      throw new Error("remote-password-may-be-saved")
    })
    vi.stubGlobal("fetch", fetcher)
    await expect(businessCredentialsApi.sync("account", "binding", 2, 1)).rejects.toMatchObject({ code: "business_credential_request_failed" })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it("canonicalizes object keys while preserving array order, null, and false", () => {
    expect(canonicalBusinessCredentialBody({ z: null, a: { d: false, c: [2, 1] } })).toBe('{"a":{"c":[2,1],"d":false},"z":null}')
  })
})

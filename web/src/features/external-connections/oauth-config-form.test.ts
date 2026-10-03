import { describe, expect, it } from "vitest"
import { canEnableOAuth, editOAuthIssuer, signingKeyState, suggestedMcpResource } from "./oauth-config-form"

describe("OAuth URL suggestions", () => {
  it("derives only empty or previously automatic resource values on issuer edits", () => {
    const initial = { issuer: "", resource: "", enabled: false }
    const first = editOAuthIssuer(initial, "https://gate.example.test", null)
    expect(first.draft.resource).toBe("https://gate.example.test/mcp")
    const next = editOAuthIssuer(first.draft, "https://next.example.test:8443", first.automaticResource)
    expect(next.draft.resource).toBe("https://next.example.test:8443/mcp")
    expect(next.draft.enabled).toBe(false)
    expect(initial.resource).toBe("")
  })
  it("preserves loaded and manual resource values, including a manual automatic-looking value", () => {
    const saved = { issuer: "https://gate.example.test", resource: "https://gate.example.test/mcp", enabled: false }
    expect(editOAuthIssuer(saved, "https://next.example.test", null).draft.resource).toBe(saved.resource)
    expect(editOAuthIssuer({ ...saved, resource: "https://mcp.example.test/mcp" }, "", null).draft.resource).toBe("https://mcp.example.test/mcp")
  })
  it("clears only an owned suggestion when issuer is cleared or gains a forbidden trailing slash", () => {
    const auto = editOAuthIssuer({ issuer: "", resource: "", enabled: false }, "https://gate.example.test", null)
    expect(editOAuthIssuer(auto.draft, "", auto.automaticResource).draft.resource).toBe("")
    const invalid = editOAuthIssuer(auto.draft, "https://gate.example.test/", auto.automaticResource)
    expect(invalid.draft.resource).toBe("")
    expect(editOAuthIssuer(invalid.draft, "https://gate.example.test", invalid.automaticResource).draft.resource).toBe(auto.draft.resource)
  })
  it.each(["", "http://gate.example.test", "https://gate.example.test/", "https://gate.example.test/path", "https://gate.example.test?x=1", "https://gate.example.test#fragment", "https://user:password@gate.example.test", "https://gate.example.test:0", "https://gate.example.test:65536", "https://gate.example.test\\evil", " https://gate.example.test", "https://gate.example.test\n", "https://*.example.test", "https://" + "a".repeat(2048)])("does not fabricate a resource for %s", issuer => {
    expect(suggestedMcpResource(issuer)).toBeNull()
  })
  it("retains the issuer's exact text used by backend comparisons", () => {
    expect(suggestedMcpResource("https://Gate.Example.test:443")).toBe("https://Gate.Example.test:443/mcp")
  })
})

describe("OAuth signing prerequisites", () => {
  it("never counts retained, inactive or inconsistent keys as signing-ready", () => {
    expect(signingKeyState([{ kid: "retained", active: false, retire_at: 1000 }, { kid: "inconsistent", active: true, retire_at: 1000 }])).toEqual({ phase: "ready", count: 0 })
    expect(signingKeyState([{ kid: "current", active: true, retire_at: null }])).toEqual({ phase: "ready", count: 1 })
  })
  it.each([undefined, null, {}, [{ active: true }], [{ kid: "", active: true, retire_at: null }], [{ kid: "x", active: "true", retire_at: null }], [{ kid: "x", active: true, retire_at: "1000" }]])("fails closed on malformed metadata %j", keys => {
    expect(signingKeyState(keys)).toEqual({ phase: "error" })
  })
  it("requires a successfully read positive key count", () => {
    expect(canEnableOAuth({ phase: "loading" })).toBe(false)
    expect(canEnableOAuth({ phase: "error" })).toBe(false)
    expect(canEnableOAuth({ phase: "ready", count: 0 })).toBe(false)
    expect(canEnableOAuth({ phase: "ready", count: 1 })).toBe(true)
  })
})

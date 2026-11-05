import { describe, expect, it } from "vitest"
import { credentialHttpOrigin, credentialHttpTarget, credentialMatchesHttpTarget, credentialWriteKey, validHttpServiceId } from "./credential-writes"
import type { Credential } from "@/api/client"

describe("shared credential request boundaries", () => {
  it("binds HTTP credentials to scheme, host and effective port without the MCP path", () => {
    expect(credentialHttpOrigin("https://service.example/mcp")).toBe("https://service.example:443")
    expect(credentialHttpOrigin("http://10.23.45.67:4747/mcp")).toBe("http://10.23.45.67:4747")
    expect(credentialHttpOrigin("http://[::1]/mcp")).toBe("http://[::1]:80")
  })
  it.each(["http://user:secret@service.example/mcp", "https://service.example/mcp?secret=sample", "https://service.example/mcp#fragment", "file:///tmp/socket", "***", "https://service.example/with space"])("does not bind credential-bearing or invalid targets: %s", endpoint => {
    expect(credentialHttpOrigin(endpoint)).toBeNull()
  })
  it("creates independent opaque keys without depending on secure-context randomUUID", () => {
    const key = credentialWriteKey()
    expect(key).toMatch(/^credential-[a-f0-9]{48}$/)
    expect(credentialWriteKey()).not.toBe(key)
  })
})

const credential: Credential = { id: "synthetic", name: "Synthetic", description: "Keep metadata", value_masked: "***", created_at: "v1", updated_at: "v1",
  http_scopes: [{ server_id: "one", origin: "https://one.example:443", server_binding: "generation-one" },
    { server_id: "two", origin: "https://two.example:443", server_binding: "generation-two" }] }

describe("explicit HTTP target authorization", () => {
  it("adds the exact target while preserving existing service identities and input metadata", () => {
    const target = credentialHttpTarget(credential, "three", "https://three.example/mcp")
    expect(target).toEqual({ server_id: "three", origin: "https://three.example:443" })
    expect(credential.http_scopes).toHaveLength(2)
    expect(credential.description).toBe("Keep metadata")
  })
  it("reapproves only the selected target when a service is recreated", () => {
    expect(credentialMatchesHttpTarget(credential, "one", "https://one.example/mcp", false)).toBe(false)
    expect(credentialMatchesHttpTarget(credential, "one", "https://one.example/mcp", true, "new-generation")).toBe(false)
    expect(credentialMatchesHttpTarget(credential, "one", "https://one.example/mcp", true, "generation-one")).toBe(true)
    const target = credentialHttpTarget(credential, "one", "https://one.example/new-path")
    expect(target).toEqual({ server_id: "one", origin: "https://one.example:443" })
    expect(credentialMatchesHttpTarget({ ...credential, http_scopes: [target] }, "one", "https://one.example/mcp", false)).toBe(true)
  })
  it("does not silently expand to a different origin or an invalid target", () => {
    expect(credentialMatchesHttpTarget(credential, "one", "https://different.example/mcp")).toBe(false)
    expect(() => credentialHttpTarget(credential, "one", "https://user:secret@one.example/mcp")).toThrow("invalid_credential_target")
  })
  it("recognizes an explicit pending rebind without discarding the current connection identity", () => {
    const authorized = { ...credential, http_scopes: [{ ...credential.http_scopes![0], pending_rebind: true }] }
    expect(credentialMatchesHttpTarget(authorized, "one", "https://one.example/new-path", false)).toBe(true)
    expect(authorized.http_scopes[0].server_binding).toBe("generation-one")
    expect(credentialMatchesHttpTarget(authorized, "one", "https://different.example/mcp", false)).toBe(false)
    expect(credentialMatchesHttpTarget(authorized, "two", "https://one.example/mcp", false)).toBe(false)
  })
  it("accepts the same service ID characters as the HTTP backend, with its declared length boundary", () => {
    for (const id of ["_service", ".service", "-service", "a".repeat(128)]) expect(validHttpServiceId(id)).toBe(true)
    expect(validHttpServiceId("a".repeat(129))).toBe(false)
    expect(validHttpServiceId("service name")).toBe(false)
  })
})

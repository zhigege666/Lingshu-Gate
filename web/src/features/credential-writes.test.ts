import { describe, expect, it } from "vitest"
import { credentialHttpOrigin, credentialWriteKey } from "./credential-writes"

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

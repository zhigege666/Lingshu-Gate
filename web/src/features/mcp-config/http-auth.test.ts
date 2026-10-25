import { describe, expect, it } from "vitest"
import { homeMcpEndpoint, httpAuthHeaders, inferHttpAuth, prepareHttpSecret } from "./http-auth"

const bearer = { Authorization: "Bearer ${credential:example-token}" }

describe("HTTP authentication preset conversion foundation", () => {
  it("recognizes reference-based formats without inferring an unknown secret", () => {
    expect(inferHttpAuth(undefined).kind).toBe("none")
    expect(inferHttpAuth(bearer)).toEqual({ kind: "bearer", credentialId: "example-token", headerName: "Authorization" })
    expect(inferHttpAuth({ authorization: "Basic ${credential:example-basic}" }).kind).toBe("basic")
    expect(inferHttpAuth({ "X-API-Key": "${credential:example-api}" }).kind).toBe("api_key")
    expect(inferHttpAuth({ Authorization: "***" }).kind).toBe("custom")
    expect(inferHttpAuth({ Authorization: "Bearer synthetic-literal" }).kind).toBe("custom")
    expect(inferHttpAuth({ ...bearer, authorization: bearer.Authorization }).kind).toBe("custom")
    expect(inferHttpAuth([]).kind).toBe("custom")
  })

  it("converts only the selected authentication header, retaining all unrelated fields", () => {
    const original = { ...bearer, "X-Tenant": "synthetic-tenant", "X-Empty": "" }
    const result = httpAuthHeaders(original, inferHttpAuth(original), { kind: "api_key", credentialId: "example-api", headerName: "X-API-Key" })
    expect(result).toEqual({ "X-API-Key": "${credential:example-api}", "X-Tenant": "synthetic-tenant", "X-Empty": "" })
    expect(original).toHaveProperty("Authorization")
    expect(httpAuthHeaders(result, inferHttpAuth(result), { kind: "none", credentialId: "", headerName: "" }))
      .toEqual({ "X-Tenant": "synthetic-tenant", "X-Empty": "" })
  })

  it("does not overwrite a header conflict or silently discard unsupported custom configuration", () => {
    const original = { ...bearer, "x-api-key": "keep-this-reference" }
    expect(() => httpAuthHeaders(original, inferHttpAuth(original), { kind: "api_key", credentialId: "example-api", headerName: "X-API-Key" })).toThrow("custom_headers_required")
    const custom = { "X-One": "${credential:one}", "X-Two": "${credential:two}" }
    expect(() => httpAuthHeaders(custom, inferHttpAuth(custom), { kind: "none", credentialId: "", headerName: "" })).toThrow("custom_headers_required")
    expect(httpAuthHeaders(custom, inferHttpAuth(custom), { kind: "custom", credentialId: "", headerName: "" })).toEqual(custom)
  })

  it.each(["Host", "Content-Type", "Mcp-Session-Id", "Proxy-Authorization", "X Key", "X\r\nBad"])("rejects reserved or malformed header %s", headerName => {
    expect(() => httpAuthHeaders({}, inferHttpAuth({}), { kind: "api_key", credentialId: "example-api", headerName })).toThrow("invalid_auth_header")
  })

  it("normalizes one pasted Bearer prefix and encodes Basic separately from the manifest", () => {
    expect(prepareHttpSecret("bearer", "  Bearer synthetic-test  ")).toBe("synthetic-test")
    expect(prepareHttpSecret("basic", "synthetic-pass", "example-user")).toBe(btoa("example-user:synthetic-pass"))
    expect(() => prepareHttpSecret("bearer", "Bearer Bearer example")).toThrow("invalid_secret")
    expect(() => prepareHttpSecret("bearer", "example\r\nvalue")).toThrow("invalid_secret")
    expect(() => prepareHttpSecret("raw", "***")).toThrow("invalid_secret")
    expect(() => prepareHttpSecret("basic", "example", "a:b")).toThrow("invalid_basic_username")
  })

  it("appends the Home path only to a root URL and never guesses an existing path or port", () => {
    expect(homeMcpEndpoint("https://home.example.test:8443/")).toBe("https://home.example.test:8443/mcp")
    for (const url of ["https://home.example.test/other", "https://home.example.test/mcp", "https://a:b@home.example.test", "https://home.example.test/?secret=x", "not a URL"]) expect(homeMcpEndpoint(url)).toBeNull()
  })
})


describe("authentication preset safety", () => {
  it("treats multiple simultaneous authentication headers as custom, including Authorization", () => {
    const value = { Authorization: "Bearer ${credential:one}", "X-API-Key": "${credential:two}", "X-Tenant": "keep" }
    expect(inferHttpAuth(value).kind).toBe("custom")
    expect(() => httpAuthHeaders(value, inferHttpAuth(value), { kind: "none", credentialId: "", headerName: "" })).toThrow("custom_headers_required")
    expect(value.Authorization).toBe("Bearer ${credential:one}")
  })
  it("preserves literal API key spaces while rejecting line breaks and keeps Basic Unicode separate", () => {
    expect(prepareHttpSecret("raw", "synthetic scoped key")).toBe("synthetic scoped key")
    const encoded = prepareHttpSecret("basic", "密码 example", "用户")
    expect(new TextDecoder().decode(Uint8Array.from(atob(encoded), character => character.charCodeAt(0)))).toBe("用户:密码 example")
    expect(() => prepareHttpSecret("raw", "   ")).toThrow()
  })
  it("does not normalize unsafe Home inputs or overwrite an existing subpath", () => {
    for (const value of [" https://example.test", "https://example.test/\\other", "https://example.test/proxy/mcp", "https://example.test?x=1"]) expect(homeMcpEndpoint(value)).toBeNull()
  })
  it("keeps unknown and masked values until an explicit replacement, never treats a mask as a credential", () => {
    const value = { Authorization: "***", "X-Tenant": "same" }
    expect(httpAuthHeaders(value, inferHttpAuth(value), { kind: "bearer", credentialId: "new-reference", headerName: "Authorization" }))
      .toEqual({ Authorization: "Bearer ${credential:new-reference}", "X-Tenant": "same" })
    expect(value.Authorization).toBe("***")
  })
})

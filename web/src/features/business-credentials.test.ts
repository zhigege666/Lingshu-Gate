import { describe, expect, it } from "vitest"
import type { BusinessCredential } from "@/api/business-credentials"
import { businessCredentialDraft, businessCredentialPrompt, businessCredentialWrite, emptyBusinessCredentialDraft,
  secureBusinessCredentialTransport, validateBusinessCredentialDraft } from "./business-credentials"

const record: BusinessCredential = {
  id: "example-account", owner_id: "user-a", name: "Test doctor", environment: "Test", business_role: "Doctor",
  login_url: "https://app.example.test/login", scope: "personal", enabled: true, allow_http: false,
  version: 2, username_masked: "***", password_configured: true, allowed_user_ids: [], allowed_role_ids: [],
  selectors: {}, created_at: "", updated_at: "", bindings: [],
}

describe("business credential editing boundaries", () => {
  it("never populates password or username inputs from returned metadata and preserves blanks on edit", () => {
    const draft = businessCredentialDraft(record)
    expect(draft.username).toBe("")
    expect(draft.password).toBe("")
    expect(businessCredentialWrite(draft, true, "personal")).toMatchObject({ username: null, password: null })
    expect(JSON.stringify(draft)).not.toContain("***")
  })

  it("requires initial secrets but allows exact replacement whitespace without silently trimming passwords", () => {
    const draft = { ...businessCredentialDraft(record), password: "  replacement-value  ", username: "sample" }
    expect(validateBusinessCredentialDraft(draft, false)).toEqual({})
    expect(businessCredentialWrite(draft, false, "personal").password).toBe("  replacement-value  ")
    expect(validateBusinessCredentialDraft({ ...draft, password: "" }, false).password).toBe("required")
    expect(validateBusinessCredentialDraft({ ...draft, password: "***" }, true).password).toBe("mask")
  })

  it("requires explicit HTTP opt-in and rejects secret-bearing or ambiguous login URLs", () => {
    const draft = { ...businessCredentialDraft(record), login_url: "http://app.example.test/login" }
    expect(validateBusinessCredentialDraft(draft, true).login_url).toBe("http")
    expect(validateBusinessCredentialDraft({ ...draft, allow_http: true }, true)).toEqual({})
    expect(validateBusinessCredentialDraft({ ...draft, login_url: "https://app.example.test/#/login" }, true)).toEqual({})
    for (const login_url of ["file:///etc/passwd", "https://user:pass@app.example.test/login", "https://app.example.test/login?token=value", "https://app.example.test/#token"]) {
      expect(validateBusinessCredentialDraft({ ...draft, login_url }, true).login_url).toBe("url")
    }
  })

  it("limits secret submission to HTTPS or actual loopback names", () => {
    for (const hostname of ["localhost", "127.0.0.1", "::1", "[::1]"]) expect(secureBusinessCredentialTransport({ protocol: "http:", hostname })).toBe(true)
    expect(secureBusinessCredentialTransport({ protocol: "https:", hostname: "gate.example.test" })).toBe(true)
    expect(secureBusinessCredentialTransport({ protocol: "http:", hostname: "localhost.example.test" })).toBe(false)
    expect(secureBusinessCredentialTransport({ protocol: "http:", hostname: "192.168.1.10" })).toBe(false)
  })

  it("copies only the credential reference and logical session, without native vault/profile or account fields", () => {
    expect(JSON.parse(businessCredentialPrompt(record))).toEqual({ name: "gate:example-account", session: "task-session" })
    expect(businessCredentialPrompt(record)).not.toContain(record.login_url)
    expect(businessCredentialPrompt(record)).not.toContain("password")
  })

  it("does not retain shared grants when writing a personal credential", () => {
    const draft = { ...emptyBusinessCredentialDraft(), allowed_user_ids: ["user-b"], allowed_role_ids: ["role-admin"] }
    expect(businessCredentialWrite(draft, true, "personal")).toMatchObject({ allowed_user_ids: [], allowed_role_ids: [] })
    expect(businessCredentialWrite(draft, true, "shared")).toMatchObject({ allowed_user_ids: ["user-b"], allowed_role_ids: ["role-admin"] })
  })
})

import { describe, expect, it } from "vitest"
import { credentialDraftTarget, currentCredentialDraft, type ConfigurationCredentialDraft } from "./credential-draft"

const endpoint = "https://example.test/mcp"
const draft: ConfigurationCredentialDraft = { targetKey: credentialDraftTarget("service", endpoint),
  write: { kind: "create", credential_id: "key", name: "Synthetic", value: "synthetic-secret", target: { server_id: "service", origin: "https://example.test:443" } } }

describe("staged configuration credential", () => {
  it("is valid only for its exact draft target and retained reference", () => {
    const headers = { Authorization: "Bearer ${credential:key}" }
    expect(currentCredentialDraft(draft, "service", endpoint, headers)).toBe(true)
    expect(currentCredentialDraft(draft, "other", endpoint, headers)).toBe(false)
    expect(currentCredentialDraft(draft, "service", endpoint + "/changed", headers)).toBe(false)
    expect(currentCredentialDraft(draft, "service", endpoint, { Authorization: "Bearer ${credential:another}" })).toBe(false)
    expect(currentCredentialDraft(null, "service", endpoint, headers)).toBe(false)
    expect(JSON.stringify(headers)).not.toContain(draft.write.kind === "create" ? draft.write.value : "")
  })
})

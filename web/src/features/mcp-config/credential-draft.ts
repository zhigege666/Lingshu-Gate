import type { ConfigurationCredentialWrite } from "@/api/client"

export type ConfigurationCredentialDraft = { write: ConfigurationCredentialWrite; targetKey: string }

export function credentialDraftTarget(serverId: string, endpoint: unknown) { return JSON.stringify([serverId, endpoint]) }

/** A staged grant never follows an edited target or a removed reference silently. */
export function currentCredentialDraft(draft: ConfigurationCredentialDraft | null, serverId: string, endpoint: unknown, headers: unknown): boolean {
  if (!draft || draft.targetKey !== credentialDraftTarget(serverId, endpoint) || !headers || typeof headers !== "object" || Array.isArray(headers)) return false
  const reference = `\${credential:${draft.write.credential_id}}`
  return Object.values(headers).some(value => typeof value === "string" && value.includes(reference))
}

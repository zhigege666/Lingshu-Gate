import { BusinessCredentialRequestError, type BusinessCredential, type BusinessCredentialBinding } from "@/api/business-credentials"

type SyncResult = { serverId: string; status: "synced" | "failed" | "unknown"; error?: unknown }

/** A saved credential stays saved even when an individual bound node fails to synchronize. */
export async function saveBusinessCredentialWithSync(
  save: () => Promise<BusinessCredential>,
  sync: (id: string, bindingId: string, version: number, revision: number) => Promise<BusinessCredentialBinding>,
  synchronize: boolean,
): Promise<{ credential: BusinessCredential; results: SyncResult[] }> {
  const credential = await save()
  const results: SyncResult[] = []
  if (synchronize && credential.enabled) {
    for (const binding of credential.bindings.filter(item => item.enabled)) {
      try {
        const result = await sync(credential.id, binding.id, credential.version, binding.revision)
        results.push({ serverId: binding.server_id, status: result.sync_status === "synced" && result.synced_version === credential.version ? "synced" : result.sync_status === "failed" ? "failed" : "unknown" })
      } catch (error) {
        results.push({ serverId: binding.server_id, status: error instanceof BusinessCredentialRequestError && error.status > 0 && error.status < 500 ? "failed" : "unknown", error })
      }
    }
  }
  return { credential, results }
}

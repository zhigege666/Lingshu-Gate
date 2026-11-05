import { describe, expect, it, vi } from "vitest"
import { BusinessCredentialRequestError, type BusinessCredential, type BusinessCredentialBinding } from "@/api/business-credentials"
import { saveBusinessCredentialWithSync } from "./business-credentials-panel-model"

const binding = (id: string, enabled = true): BusinessCredentialBinding => ({ id, server_id: id, credential_id: "credential", enabled, adapter: "agent_browser", tool_prefix: "", revision: 3, synced_version: 6, sync_status: "pending", last_sync_at: null, last_error_code: null })
const record = { id: "credential", enabled: true, version: 7, bindings: [binding("one"), binding("disabled", false), binding("two")] } as BusinessCredential

describe("save and synchronize already authorized credential nodes", () => {
  it("uses the returned credential version and each binding revision, skipping disabled nodes", async () => {
    const save = vi.fn().mockResolvedValue(record)
    const sync = vi.fn(async (_: string, id: string) => ({ ...binding(id), sync_status: "synced" as const, synced_version: 7 }))
    const result = await saveBusinessCredentialWithSync(save, sync, true)
    expect(save).toHaveBeenCalledTimes(1)
    expect(sync.mock.calls).toEqual([["credential", "one", 7, 3], ["credential", "two", 7, 3]])
    expect(result.results.map(item => item.status)).toEqual(["synced", "synced"])
  })
  it("does not repeat an accepted save or sync after a timeout and reports partial outcomes", async () => {
    const save = vi.fn().mockResolvedValue(record)
    const sync = vi.fn().mockRejectedValueOnce(new BusinessCredentialRequestError(0, "business_credential_request_timeout")).mockResolvedValueOnce({ ...binding("two"), sync_status: "synced", synced_version: 7 })
    const result = await saveBusinessCredentialWithSync(save, sync, true)
    expect(result.credential).toBe(record)
    expect(save).toHaveBeenCalledTimes(1)
    expect(sync).toHaveBeenCalledTimes(2)
    expect(result.results.map(item => [item.serverId, item.status])).toEqual([["one", "unknown"], ["two", "synced"]])
  })
  it("keeps save-only and disabled credentials local to Gate", async () => {
    const sync = vi.fn()
    expect((await saveBusinessCredentialWithSync(async () => record, sync, false)).results).toEqual([])
    expect((await saveBusinessCredentialWithSync(async () => ({ ...record, enabled: false }), sync, true)).results).toEqual([])
    expect(sync).not.toHaveBeenCalled()
  })
  it("never sends a password to a node when the save is rejected", async () => {
    const sync = vi.fn()
    await expect(saveBusinessCredentialWithSync(async () => { throw new BusinessCredentialRequestError(409, "credential_revision_conflict") }, sync, true)).rejects.toMatchObject({ status: 409 })
    expect(sync).not.toHaveBeenCalled()
  })
})

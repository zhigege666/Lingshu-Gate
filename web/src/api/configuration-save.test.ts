import { afterEach, describe, expect, it, vi } from "vitest"
import { ConfigurationCredentialSaveError, serversRuntimeApi, type ConfigSaveOptions } from "./servers-runtime"

const manifest = { id: "synthetic", transport: { type: "streamable_http", endpoint: "https://example.test/mcp", headers: { Authorization: "Bearer ${credential:synthetic}" } } }
const options: ConfigSaveOptions = { credential_operation_key: "synthetic-operation", credential_write: { kind: "create", credential_id: "synthetic", name: "Synthetic",
  value: "synthetic-secret", target: { server_id: "synthetic", origin: "https://example.test:443" } } }
afterEach(() => vi.unstubAllGlobals())

describe("configuration save boundary", () => {
  it("submits the credential and configuration through one final request, with secrets outside the manifest", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ config: { id: "synthetic" }, message: "created" })))
    vi.stubGlobal("fetch", fetch)
    await serversRuntimeApi.createConfig(manifest, false, false, {}, options)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toBe("/v1/mcp/configs/with-credential")
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.manifest).toEqual(manifest)
    expect(JSON.stringify(body.manifest)).not.toContain("synthetic-secret")
    expect(body.credential_write.value).toBe("synthetic-secret")
    expect(body.idempotency_key).toBe("synthetic-operation:00")
    expect(body.existing_server_id).toBeNull()
  })
  it("keeps the same operation key for a retry and binds activation and the current config revision", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ config: { id: "synthetic" }, message: "updated" }))))
    vi.stubGlobal("fetch", fetch)
    for (let attempt = 0; attempt < 2; attempt++) await serversRuntimeApi.updateConfig("synthetic", manifest, true, true, {}, "a".repeat(64), options)
    const bodies = fetch.mock.calls.map(call => JSON.parse(call[1].body))
    expect(bodies[0]).toEqual(bodies[1])
    expect(bodies[0]).toMatchObject({ existing_server_id: "synthetic", expected_config_digest: "a".repeat(64), idempotency_key: "synthetic-operation:11", apply: true, start: true })
  })
  it("preserves structured partial-save facts so the editor can stop and reconcile", async () => {
    const detail = { code: "mcp_config_credential_partial", message: "Review saved state", credential_saved: true, config_saved: false, requires_reconciliation: true }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 409 })))
    const failure = await serversRuntimeApi.createConfig(manifest, false, false, {}, options).catch(error => error)
    expect(failure).toBeInstanceOf(ConfigurationCredentialSaveError)
    expect(failure.requiresReconciliation).toBe(true)
    expect(failure.detail).toEqual(detail)
  })
})

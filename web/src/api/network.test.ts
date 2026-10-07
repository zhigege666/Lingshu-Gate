import { afterEach, describe, expect, it, vi } from "vitest"
import { networkApi, type DeliveryBuildPlan, type GitPlan } from "./network"

describe("controlled Git network API", () => {
  afterEach(() => vi.unstubAllGlobals())
  it("binds the confirmed immutable plan and idempotency key, not a moving ref", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{"status":"queued"}'))
    vi.stubGlobal("fetch", fetch)
    const plan: GitPlan = { status: "ready", plan_id: "plan-id", plan_digest: "a".repeat(64), validation: { ok: true } }
    await networkApi.acquire(plan, "key-0001")
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body).toEqual({ plan_id: "plan-id", plan_digest: "a".repeat(64), idempotency_key: "key-0001", confirmed: true })
    expect(body).not.toHaveProperty("repository_url")
  })
  it("uses server-owned test target IDs and never adds arbitrary URLs or methods", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{"status":"failed"}'))
    vi.stubGlobal("fetch", fetch)
    await networkApi.test({ id: "named", version: 3, name: "Example", scheme: "https", enabled: true, credential_configured: true, credential_ref: null, endpoint_masked: "***" }, "npm")
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ profile_id: "named", version: 3, target_id: "npm", confirmed: true })
  })
  it("binds a saved tool override to the same reviewed build digest", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{"status":"queued","build_id":"build"}'))
    vi.stubGlobal("fetch", fetch)
    const plan = { upload_id: "upload", source_sha256: "a".repeat(64), plan_fingerprint: "b".repeat(64) } as DeliveryBuildPlan
    const selection = { name: "pnpm", version: "9.15.4", lockfile: "pnpm-lock.yaml" } as const
    await networkApi.build(plan, { package_manager_override: selection }, "same-reviewed-key")
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ confirmed: true, idempotency_key: "same-reviewed-key", source_sha256: plan.source_sha256, plan_fingerprint: plan.plan_fingerprint, package_manager_override: selection })
  })
})

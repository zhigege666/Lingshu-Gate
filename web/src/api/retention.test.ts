import { afterEach, describe, expect, it, vi } from "vitest"
import { retentionApi } from "./retention"
import { defaultRetentionDraft } from "@/features/retention/model"
afterEach(() => vi.unstubAllGlobals())
describe("retention API wire contract", () => {
  it("previews current policy with null rather than resetting to request defaults", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"))
    vi.stubGlobal("fetch", fetcher)
    await retentionApi.preview()
    expect(fetcher.mock.calls[0][1].body).toBe("null")
  })
  it("binds shortening writes to revision and explicitly confirmed preview", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"))
    vi.stubGlobal("fetch", fetcher)
    await retentionApi.save(defaultRetentionDraft, 4, "preview-synthetic")
    expect(fetcher.mock.calls[0][0]).toBe("/v1/retention/policy")
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ ...defaultRetentionDraft, expected_revision: 4, preview_id: "preview-synthetic", confirmed: true })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it("cancels only the selected job with no polling or cleanup request", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}"))
    vi.stubGlobal("fetch", fetcher)
    await retentionApi.cancel("synthetic/job")
    expect(fetcher.mock.calls[0][0]).toBe("/v1/retention/jobs/synthetic%2Fjob/cancel")
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

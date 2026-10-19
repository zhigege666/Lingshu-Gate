import { describe, expect, it, vi } from "vitest"
import type { ToolClassification } from "@/api/client"
import { publishedSelectionIds, publishClassificationBatches } from "./tool-classifications-page"

function classification(id: string, serverId = "service-a"): ToolClassification {
  return {
    id, server_id: serverId, tool_id: `tool-${id}`, tool_name: `Tool ${id}`,
    fingerprint: `fingerprint-${id}`, suggested_access: "read", effective_access: "read",
    status: "pending", confidence: 1, source: "manual", destructive: false,
    idempotent: true, open_world: false, evidence: {},
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  }
}

const published = (item: ToolClassification): ToolClassification => ({ ...item, status: "published" })

describe("classification publication recovery", () => {
  it("keeps confirmed work and stops after a later service fails without counting unrelated records", async () => {
    const selected = [classification("a"), classification("b"), classification("c", "service-b"), classification("d", "service-c")]
    const publish = vi.fn()
      .mockResolvedValueOnce({ classifications: [published(selected[0]), published(selected[1]), published(classification("unselected"))] })
      .mockRejectedValueOnce(new Error("Publication rejected for service-b"))

    const result = await publishClassificationBatches(selected, publish)

    expect(publish.mock.calls).toEqual([
      [{ server_id: "service-a", tool_ids: ["tool-a", "tool-b"] }],
      [{ server_id: "service-b", tool_ids: ["tool-c"] }],
    ])
    expect(result.published.map(item => item.id)).toEqual(["a", "b"])
    expect(result.error).toBe("Publication rejected for service-b")
    expect(selected.filter(item => !publishedSelectionIds(selected, result.published).has(item.id)).map(item => item.id)).toEqual(["c", "d"])
    expect(selected.every(item => item.status === "pending")).toBe(true)
  })

  it("caps service batches at 500 and does not double-count service-wide response records", async () => {
    const selected = Array.from({ length: 501 }, (_, index) => classification(String(index)))
    const completed = new Set<string>()
    const publish = vi.fn(async (payload: { server_id: string; tool_ids: string[] }) => {
      payload.tool_ids.forEach(id => completed.add(id))
      return { classifications: selected.map(item => completed.has(item.tool_id) ? published(item) : item) }
    })

    const result = await publishClassificationBatches(selected, publish)

    expect(publish.mock.calls.map(([payload]) => payload.tool_ids.length)).toEqual([500, 1])
    expect(result.error).toBeNull()
    expect(result.published).toHaveLength(501)
    expect(new Set(result.published.map(item => item.id)).size).toBe(501)
  })

  it("retains changed decisions and stops further writes when a response does not confirm the selected snapshot", async () => {
    const selected = [classification("a"), classification("b"), classification("c", "service-b")]
    const publish = vi.fn().mockResolvedValue({ classifications: [
      published(selected[0]),
      { ...published(selected[1]), fingerprint: "definition-changed" },
    ] })

    const result = await publishClassificationBatches(selected, publish)

    expect(publish).toHaveBeenCalledTimes(1)
    expect(result.published.map(item => item.id)).toEqual(["a"])
    expect(publishedSelectionIds(selected, result.published)).toEqual(new Set(["a"]))
  })

  it("reconciles an uncertain write against refreshed state without treating changed access or identity as completion", () => {
    const selected = [classification("a"), classification("b"), classification("c"), classification("d"), classification("e"), classification("f")]
    const refreshed = [
      published(selected[0]),
      { ...published(selected[1]), effective_access: "write" as const },
      { ...published(selected[2]), tool_id: "another-tool" },
      { ...published(selected[3]), server_id: "another-service" },
      selected[4],
      // f was removed; neither a missing record nor a pending record is success.
    ]

    expect(publishedSelectionIds(selected, refreshed)).toEqual(new Set(["a"]))
  })
})

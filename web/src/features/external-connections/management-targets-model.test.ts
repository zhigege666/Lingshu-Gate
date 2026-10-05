import { describe, expect, it } from "vitest"
import { managementTargetRows, managementTargets } from "./management-targets-model"

describe("explicit management target drafts", () => {
  it("retains the entire target policy across pages and changes only the edited target", () => {
    const saved = Object.fromEntries(Array.from({ length: 1000 }, (_, index) => [`synthetic-${index}`, ["create"]]))
    const rows = managementTargetRows(saved)
    const chosen = rows.findIndex(row => row.id === "synthetic-999")
    rows[chosen] = { ...rows[chosen], actions: ["update", "create"] }
    const result = managementTargets(rows)
    expect(Object.keys(result)).toHaveLength(1000)
    expect(result["synthetic-999"]).toEqual(["create", "update"])
    expect(result["synthetic-0"]).toEqual(["create"])
    expect(saved["synthetic-999"]).toEqual(["create"])
  })
  it("requires exact unique IDs and explicit supported actions instead of inferring rights", () => {
    for (const rows of [[], [{ id: "", actions: ["create"] }], [{ id: "synthetic-*", actions: ["create"] }],
      [{ id: "synthetic", actions: [] }], [{ id: "synthetic", actions: ["delete"] }],
      [{ id: "synthetic", actions: ["create", "create"] }],
      [{ id: "synthetic", actions: ["create"] }, { id: "synthetic", actions: ["update"] }]]) {
      expect(() => managementTargets(rows)).toThrow("invalid_management_targets")
    }
    expect(managementTargets([], true)).toEqual({})
  })
  it("keeps valid object-like IDs as data and enforces the 1000-target ceiling", () => {
    expect(managementTargets([{ id: "constructor", actions: ["update"] }]).constructor).toEqual(["update"])
    expect(() => managementTargets(Array.from({ length: 1001 }, (_, index) => ({ id: `synthetic-${index}`, actions: ["create"] })))).toThrow("invalid_management_targets")
    expect(Object.prototype).not.toHaveProperty("synthetic-999")
  })
})

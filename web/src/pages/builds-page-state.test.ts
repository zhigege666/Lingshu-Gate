import { describe, expect, it } from "vitest"
import { rollbackResultError, rollbackStartFor } from "./builds-page-state"

describe("rollback target and outcome", () => {
  it("never starts another deployment using the previously checked option", () => {
    const option = { deploymentId: "deployment-a", start: true }
    expect(rollbackStartFor(option, "deployment-a")).toBe(true)
    expect(rollbackStartFor(option, "deployment-b")).toBe(false)
  })
  it("uses the explicitly selected older deployment even when its build has a newer deployment", () => {
    const latest = { id: "deployment-new", build_id: "same-build" }
    const selected = { id: "deployment-old", build_id: "same-build" }
    const checked = { deploymentId: selected.id, start: true }
    expect(rollbackStartFor(checked, selected.id)).toBe(true)
    expect(rollbackStartFor(checked, latest.id)).toBe(false)
  })
  it("requires the confirmed target and the requested runtime state", () => {
    expect(rollbackResultError({ id: "a", status: "running" }, "a", true)).toBeNull()
    expect(rollbackResultError({ id: "a", status: "loaded" }, "a", false)).toBeNull()
    expect(rollbackResultError({ id: "b", status: "running" }, "a", true)).not.toBeNull()
    expect(rollbackResultError({ id: "a", status: "loaded" }, "a", true)).not.toBeNull()
    expect(rollbackResultError(undefined, "a", false)).not.toBeNull()
    expect(rollbackResultError({ id: "a", status: "failed", last_error: "synthetic failure" }, "a", false)).toBe("synthetic failure")
  })
})

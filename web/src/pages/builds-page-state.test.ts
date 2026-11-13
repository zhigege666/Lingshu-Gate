import { describe, expect, it } from "vitest"
import { requiresDeploymentConfirmation, rollbackResultError, rollbackStartFor } from "./builds-page-state"

describe("deployment confirmation follows actual impact", () => {
  const first = { server_id: "new-service", interrupts_existing_service: false, expected_previous_config_digest: null }
  it("deploys a new service directly to the visible target", () => {
    expect(requiresDeploymentConfirmation(first, "new-service", false)).toBe(false)
  })
  it("still confirms overwrite, interruption, existing configuration and target changes", () => {
    expect(requiresDeploymentConfirmation(first, "new-service", true)).toBe(true)
    expect(requiresDeploymentConfirmation({ ...first, interrupts_existing_service: true }, "new-service", false)).toBe(true)
    expect(requiresDeploymentConfirmation({ ...first, expected_previous_config_digest: "existing" }, "new-service", false)).toBe(true)
    expect(requiresDeploymentConfirmation(first, "another-service", false)).toBe(true)
    expect(requiresDeploymentConfirmation(first, "", false)).toBe(true)
  })
})

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

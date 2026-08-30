import { describe, expect, it } from "vitest"
import {
  DEFAULT_DEPLOYMENT_SIDE_EFFECTS,
  formatDeploymentSummary,
  resolveDeploymentTarget,
} from "@/features/deployment-options"

describe("deployment options", () => {
  it("defaults every optional deployment side effect to off", () => {
    expect(DEFAULT_DEPLOYMENT_SIDE_EFFECTS).toEqual({ start: false, overwrite: false })
  })

  it("prefers an explicit target and includes every choice in the summary", () => {
    const target = resolveDeploymentTarget(" explicit-target ", "manifest-target", "unresolved")
    expect(formatDeploymentSummary(target, { start: false, overwrite: true }, {
      target: "Target",
      overwrite: "Overwrite",
      start: "Start",
      yes: "Yes",
      no: "No",
      unresolved: "Unresolved",
    })).toBe("Target: explicit-target\nOverwrite: Yes\nStart: No")
  })
})

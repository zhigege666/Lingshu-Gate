import { expect, it } from "vitest"
import type { BuildRecord } from "@/api/builds"
import { confirmedBuildAttempt } from "./build-attempt"

it("retains an uncertain confirmed write key on a manual same-plan retry", () => {
  const pending = { fingerprint: "plan", key: "same-key", buildId: null }
  expect(confirmedBuildAttempt(pending, "plan", [], () => "new-key")).toBe(pending)
  expect(() => confirmedBuildAttempt(pending, "changed", [], () => "new-key")).toThrow(/Reconcile/)
})
it("permits a fresh confirmed write only after its known resource is terminal", () => {
  const pending = { fingerprint: "plan", key: "same-key", buildId: "existing" }
  const builds = [{ id: "existing", status: "failed" }] as BuildRecord[]
  expect(confirmedBuildAttempt(pending, "plan", builds, () => "new-key")).toEqual({ fingerprint: "plan", key: "new-key", buildId: null })
  expect(confirmedBuildAttempt(pending, "plan", [{ ...builds[0], status: "running" }], () => "new-key")).toBe(pending)
})

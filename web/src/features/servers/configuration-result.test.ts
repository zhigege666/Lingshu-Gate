import { describe, expect, it } from "vitest"
import type { ApplyResponse } from "@/api/client"
import { configurationResultError } from "./configuration-result"

const result = (status?: string): ApplyResponse => ({ message: "ok", config: { id: "safe", path: "safe.json", format: "json", manifest: {} }, ...(status ? { server: { id: "safe", status } as NonNullable<ApplyResponse["server"]> } : {}) })
describe("configuration save outcome", () => {
  it("does not report HTTP 200 failed or unknown activation as successful", () => {
    for (const status of ["failed", "starting", "stopped", undefined]) expect(configurationResultError(result(status), "safe", true)).toBeTruthy()
  })
  it("requires the intended running instance for activation", () => {
    expect(configurationResultError(result("running"), "safe", true)).toBeNull()
    expect(configurationResultError(result("running"), "other", true)).toBeTruthy()
  })
  it("allows disk-only save without claiming runtime activation", () => {
    expect(configurationResultError(result(), "safe", false)).toBeNull()
  })
})

it("localizes unknown save and activation guidance", () => {
  expect(configurationResultError(result(), "safe", true, true)).toContain("勿盲目重试")
  expect(configurationResultError(result(), "missing", false, true)).toContain("保存结果尚未确认")
})

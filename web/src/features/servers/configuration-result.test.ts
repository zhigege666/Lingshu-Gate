import { describe, expect, it } from "vitest"
import type { ApplyResponse, McpServer } from "@/api/client"
import { configurationApplyResultError, configurationResultError } from "./configuration-result"

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

describe("apply without starting outcome", () => {
  const idle = (status: string, launch_type = "external", enabled = true): ApplyResponse => ({
    ...result(status), server: { ...result(status).server!, launch_type, enabled, desired_state: "stopped", effective_should_run: false, pid: null },
  })
  it("accepts the actual backend idle states while keeping enabled and disabled distinct", () => {
    for (const [status, launch] of [["external", "external"], ["loaded", "managed_process"], ["loaded", "managed_container"], ["stopped", "external"]]) {
      for (const enabled of [true, false]) expect(configurationApplyResultError(idle(status, launch, enabled), "safe")).toBeNull()
    }
  })
  it("does not turn failed, active, missing or mismatched runtime evidence into success", () => {
    for (const status of ["failed", "starting", "running", "unsupported", "unknown"]) expect(configurationApplyResultError(idle(status), "safe")).toBeTruthy()
    const patches: Partial<McpServer>[] = [{ id: "other" }, { desired_state: "running" }, { desired_state: undefined }, { effective_should_run: true }, { effective_should_run: undefined }, { pid: 123 }, { launch_type: "managed_process" }]
    for (const patch of patches) {
      const response = idle("external")
      response.server = { ...response.server!, ...patch }
      expect(configurationApplyResultError(response, "safe")).toBeTruthy()
    }
    expect(configurationApplyResultError({ ...idle("external"), config: null }, "safe")).toBeTruthy()
    expect(configurationApplyResultError(result(), "safe")).toBeTruthy()
    expect(configurationApplyResultError(idle("loaded", "external"), "safe")).toBeTruthy()
  })
  it("keeps actual errors and localized recovery guidance", () => {
    const response = idle("external")
    response.server!.last_error = "Synthetic connection failure"
    expect(configurationApplyResultError(response, "safe", true)).toBe("Synthetic connection failure")
    response.server!.enabled = false
    response.server!.last_error = "Server is disabled"
    expect(configurationApplyResultError(response, "safe", true)).toBeNull()
    expect(configurationApplyResultError(result(), "safe", true)).toBe("配置应用状态未知，请查看服务状态。")
  })
})

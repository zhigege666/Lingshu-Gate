import { describe, expect, it } from "vitest"
import type { McpServer, McpToolSync } from "@/api/client"
import { hasServerIssue, isPlannedDisabled } from "@/pages/servers-page"

const server = (changes: Partial<McpServer> = {}): McpServer => ({
  id: "disabled-service", enabled: false, launch_type: "external", transport_type: "streamable_http", status: "external",
  tool_count: 0, restart_policy: {}, restart_count: 0, restart_attempts: 0, consecutive_health_failures: 0, health_status: "unknown",
  last_error: "Server is disabled", restore_blocked_reason: "Server is disabled", ...changes,
})

describe("intentional disabled server presentation", () => {
  it("does not turn the backend's two matching disabled reasons into a failure", () => {
    expect(isPlannedDisabled(server())).toBe(true)
    expect(hasServerIssue(server())).toBe(false)
    expect(isPlannedDisabled(server({ last_error: null }))).toBe(true)
    expect(isPlannedDisabled(server({ restore_blocked_reason: null }))).toBe(true)
  })
  it("keeps real errors and blocked reasons visible", () => {
    expect(hasServerIssue(server({ last_error: "Connection refused" }))).toBe(true)
    expect(hasServerIssue(server({ restore_blocked_reason: "Secure Core cannot execute managed workloads" }))).toBe(true)
  })
  it("does not hide an enabled, active, or failed server behind a stale disabled reason", () => {
    expect(isPlannedDisabled(server({ enabled: true }))).toBe(false)
    for (const status of ["running", "starting", "failed", "unsupported"]) {
      expect(isPlannedDisabled(server({ status }))).toBe(false)
      expect(hasServerIssue(server({ status }))).toBe(true)
    }
  })
  it("includes upstream sync failures in Issues even when the runtime is running", () => {
    const sync: McpToolSync = { state: "retrying", last_attempt_at: null, last_success_at: null, next_sync_at: null, last_error: null, error_code: null, added: 0, updated: 0, removed: 0 }
    const running = server({ enabled: true, status: "running", last_error: null, restore_blocked_reason: null, tool_sync: sync })
    expect(hasServerIssue(running)).toBe(true)
    expect(hasServerIssue({ ...running, tool_sync: { ...sync, state: "auth_required" } })).toBe(true)
    expect(hasServerIssue({ ...running, tool_sync: { ...sync, state: "ready" } })).toBe(false)
    expect(hasServerIssue({ ...running, tool_sync: undefined })).toBe(false)
  })
})

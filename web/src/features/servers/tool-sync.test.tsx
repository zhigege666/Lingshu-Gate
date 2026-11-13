import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { McpServer, McpToolSync } from "@/api/client"
import { serverCopy } from "@/features/servers/copy"
import { canSyncServerTools, hasToolSyncIssue, reconcileServerSnapshots, toolCatalogChanged, toolSyncResult } from "@/features/servers/tool-sync-model"
import { ToolSyncSummary } from "@/features/servers/tool-sync"

const ready: McpToolSync = {
  state: "ready", last_attempt_at: "2026-11-13T01:00:00Z", last_success_at: "2026-11-13T01:00:00Z",
  next_sync_at: null, last_error: null, error_code: null, added: 1, updated: 2, removed: 1,
}
const server = (tool_sync?: McpToolSync): McpServer => ({
  id: "remote-http", enabled: true, launch_type: "external", transport_type: "streamable_http", status: "running",
  tool_count: 5, restart_policy: {}, restart_count: 0, restart_attempts: 0, consecutive_health_failures: 0,
  health_status: "unknown", tool_sync,
})

describe("upstream tool synchronization feedback", () => {
  it("keeps the selected service owner stable when only a different service changes", () => {
    const selected = server(ready)
    const another = { ...server(ready), id: "another-service" }
    const changed = { ...another, tool_sync: { ...ready, state: "retrying" as const } }
    const next = reconcileServerSnapshots([selected, another], [structuredClone(selected), changed])
    expect(next[0]).toBe(selected)
    expect(next[1]).toBe(changed)
    expect(reconcileServerSnapshots([selected], [])[0]).toBeUndefined()
  })

  it("permits explicit recovery of intended-running external services without starting stopped or disabled services", () => {
    const recovering = { ...server({ ...ready, state: "auth_required" }), status: "failed", effective_should_run: true }
    expect(canSyncServerTools(server(ready))).toBe(true)
    expect(canSyncServerTools(recovering)).toBe(true)
    expect(canSyncServerTools({ ...recovering, launch_type: "managed_process" })).toBe(false)
    expect(canSyncServerTools({ ...recovering, effective_should_run: false })).toBe(false)
    expect(canSyncServerTools({ ...recovering, desired_state: "stopped" })).toBe(false)
    expect(canSyncServerTools({ ...recovering, status: "stopped" })).toBe(false)
    expect(canSyncServerTools({ ...recovering, enabled: false })).toBe(false)
    expect(canSyncServerTools(server({ ...ready, state: "syncing" }))).toBe(false)
    expect(canSyncServerTools(server({ ...ready, state: "disabled" }))).toBe(false)
    expect(canSyncServerTools(server())).toBe(false)
  })

  it("reloads the catalog for schema or equal-size changes, but not unchanged successful polls", () => {
    const before = server({ ...ready, last_changed_at: "2026-11-13T01:00:00Z" })
    const unchanged = server({ ...ready, last_changed_at: "2026-11-13T01:00:00Z", last_success_at: "2026-11-13T01:01:00Z" })
    const changed = server({ ...ready, last_changed_at: "2026-11-13T01:01:00Z" })
    expect(toolCatalogChanged([before], [unchanged])).toBe(false)
    expect(toolCatalogChanged([before], [changed])).toBe(true)
    expect(toolCatalogChanged([before], [])).toBe(true)
    expect(toolCatalogChanged([server(ready)], [server({ ...ready, last_success_at: "2026-11-13T01:01:00Z" })])).toBe(true)
    expect(toolCatalogChanged([server(ready)], [server({ ...ready, state: "retrying" })])).toBe(false)
  })

  it("reports all changes only for the requested server's completed sync", () => {
    expect(toolSyncResult("remote-http", server(ready), serverCopy("zh-CN"))).toBe("同步完成: remote-http · 新增 1 · 更新 2 · 移除 1")
    expect(toolSyncResult("remote-http", server({ ...ready, added: 0, updated: 0, removed: 0 }), serverCopy("en-US"))).toBe("Sync complete: remote-http · No tool changes")
    expect(() => toolSyncResult("another-server", server(ready), serverCopy("en-US"))).toThrow("Sync incomplete: another-server")
  })

  it("does not convert a 200 response with a failed, pending, or absent sync into success", () => {
    for (const state of ["idle", "syncing", "retrying", "auth_required", "disabled"] as const) {
      expect(() => toolSyncResult("remote-http", server({ ...ready, state, last_error: "upstream unavailable" }), serverCopy("en-US"))).toThrow("upstream unavailable")
    }
    expect(() => toolSyncResult("remote-http", server(), serverCopy("en-US"))).toThrow("Sync incomplete")
    expect(hasToolSyncIssue(server())).toBe(false)
  })

  it("keeps the last successful snapshot visible while recovery is scheduled", () => {
    const sync: McpToolSync = { ...ready, state: "retrying", last_attempt_at: "2026-11-13T01:05:00Z", next_sync_at: "2026-11-13T01:06:00Z" }
    const html = renderToStaticMarkup(<ToolSyncSummary sync={sync} c={serverCopy("en-US")} />)
    expect(html).toContain("Recovering")
    expect(html).toContain("2026-11-13 09:00:00")
    expect(html).toContain("Next retry")
    expect(html).toContain("2026-11-13 09:06:00")
    expect(html).not.toContain("09:05:00")
  })

  it("does not claim a successful initial sync or automatic retry for credential failures", () => {
    const sync: McpToolSync = { ...ready, state: "auth_required", last_success_at: null, next_sync_at: "2026-11-13T01:06:00Z" }
    const html = renderToStaticMarkup(<ToolSyncSummary sync={sync} c={serverCopy("zh-CN")} />)
    expect(html).toContain("凭据错误")
    expect(html).toContain("尚未成功同步")
    expect(html).not.toContain("下次重试")
    expect(hasToolSyncIssue(server(sync))).toBe(true)
  })
})

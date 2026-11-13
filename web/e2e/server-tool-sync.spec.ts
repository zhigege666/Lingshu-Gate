import { expect, test, type Page, type Request } from "@playwright/test"
import { login, expectInViewportAndUnobscured } from "./helpers"
import type { McpServer, ToolDefinition } from "../src/api/servers-runtime"

// Synthetic upstream states exercise console behavior; backend discovery and
// authorization are covered by the runtime/API tests rather than these mocks.
async function fixture(page: Page) {
  const state = {
    server: {
      id: "synthetic-auto-sync", name: "Remote HTTP MCP", enabled: true, launch_type: "external", transport_type: "streamable_http", status: "running",
      tool_count: 1, restart_policy: {}, restart_count: 0, restart_attempts: 0, consecutive_health_failures: 0, health_status: "unknown", allowed_actions: ["stop", "restart"],
      tool_sync: { state: "ready", last_attempt_at: "2026-11-13T01:00:00Z", last_success_at: "2026-11-13T01:00:00Z", last_changed_at: "2026-11-13T01:00:00Z", next_sync_at: null, last_error: null, error_code: null, added: 1, updated: 0, removed: 0 },
    } as McpServer,
    names: ["initial_tool"], reads: { servers: 0, tools: 0, details: 0 }, writes: [] as string[], failSync: false,
    holdNextList: null as ((request: Request) => Promise<void>) | null,
  }
  const tools = (): ToolDefinition[] => state.names.map(name => ({ id: `mcp.${state.server.id}.${name}`, name, description: "Synthetic tool", source: "mcp", permission: "tools.invoke", input_schema: { type: "object" }, metadata: { server_id: state.server.id } }))
  await page.route("**/v1/**", async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === "POST") state.writes.push(path)
    if (path === "/v1/mcp/servers") {
      state.reads.servers++
      const snapshot = { servers: [structuredClone(state.server)], load_errors: [] }
      const hold = state.holdNextList
      state.holdNextList = null
      if (hold) await hold(route.request())
      if (!route.request().failure()) await route.fulfill({ json: snapshot })
    }
    else if (path === "/v1/tools") { state.reads.tools++; await route.fulfill({ json: tools() }) }
    else if (path === `/v1/mcp/servers/${state.server.id}/detail`) { state.reads.details++; await route.fulfill({ json: { server: state.server, tools: tools(), manifest: { id: state.server.id } } }) }
    else if (path === "/v1/access/tool-classifications") await route.fulfill({ json: { classifications: [] } })
    else if (path === `/v1/mcp/servers/${state.server.id}/tools/refresh`) {
      if (state.failSync) state.server = { ...state.server, status: "failed", effective_should_run: true, tool_sync: { ...state.server.tool_sync!, state: "auth_required", last_error: "Upstream credentials expired", error_code: "http_auth_required", next_sync_at: null } }
      else {
        state.names = ["initial_tool", "new_remote_tool"]
        state.server = { ...state.server, status: "running", tool_count: 2, tool_sync: { ...state.server.tool_sync!, state: "ready", last_error: null, error_code: null, last_success_at: "2026-11-13T01:02:00Z", last_changed_at: "2026-11-13T01:02:00Z", added: 1 } }
      }
      await route.fulfill({ json: state.server })
    } else await route.continue()
  })
  return state
}

test("manual sync uses the upstream action and reports failures without publication", async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1920, height: 1080 })
  const state = await fixture(page)
  await page.goto("/#/servers/synthetic-auto-sync")
  await page.getByRole("tab", { name: "Tools 1", exact: true }).click()
  const sync = page.getByRole("button", { name: "Sync now", exact: true })
  await expect(sync).toBeEnabled()
  await sync.click()
  await expect(page.getByRole("status").filter({ hasText: "Sync complete: synthetic-auto-sync" })).toBeVisible()
  await expect(page.getByRole("tab", { name: "Tools 2", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "new_remote_tool", exact: true })).toBeVisible()
  expect(state.writes).toEqual(["/v1/mcp/servers/synthetic-auto-sync/tools/refresh"])

  state.failSync = true
  await sync.click()
  await expect(page.getByRole("alert").filter({ hasText: "Sync incomplete" })).toBeVisible()
  await expect(page.locator(".service-tool-sync")).toContainText("Credentials required")
  await expect(page.locator(".service-tool-sync")).toContainText("2026-11-13 09:02:00")
  await expect(page.getByRole("button", { name: "Edit configuration", exact: true })).toBeVisible()
  await expect(page.getByRole("status").filter({ hasText: "Sync complete:" })).toHaveCount(0)
  expect(state.writes).toHaveLength(2)
  expect(state.writes.some(path => path.includes("tool-classifications"))).toBe(false)
  await expect(sync).toBeEnabled()
  state.failSync = false
  await sync.click()
  await expect(page.locator(".service-tool-sync")).toContainText("Synced")
  expect(state.writes).toHaveLength(3)
})

test("live service snapshots refresh only changed catalogs and stop while hidden or away", async ({ page }) => {
  await login(page)
  await page.clock.install()
  const state = await fixture(page)
  await page.goto("/#/servers/synthetic-auto-sync")
  await expect(page.locator(".service-tool-sync")).toContainText("Synced")
  await expect(page.getByRole("button", { name: "initial_tool", exact: true })).toBeVisible()
  const initial = { ...state.reads }
  await page.clock.fastForward(15_000)
  await expect.poll(() => state.reads.servers).toBe(initial.servers + 1)
  expect(state.reads.tools).toBe(initial.tools)
  expect(state.reads.details).toBe(initial.details)

  state.names = ["replacement_tool"]
  state.server = { ...state.server, tool_sync: { ...state.server.tool_sync!, last_success_at: "2026-11-13T01:02:00Z", last_changed_at: "2026-11-13T01:02:00Z", added: 1, removed: 1 } }
  await page.clock.fastForward(15_000)
  await expect(page.getByRole("button", { name: "replacement_tool", exact: true })).toBeVisible()
  expect(state.reads.tools).toBe(initial.tools + 1)

  await page.evaluate(() => Object.defineProperty(document, "hidden", { configurable: true, value: true }))
  const beforeHidden = state.reads.servers
  await page.clock.fastForward(30_000)
  expect(state.reads.servers).toBe(beforeHidden)
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: false }); document.dispatchEvent(new Event("visibilitychange")) })
  await expect.poll(() => state.reads.servers).toBe(beforeHidden + 1)
  await page.locator('[data-console-nav="desktop"] a[href="#/tools"]').click()
  await expect(page.getByRole("textbox", { name: "Search tool name, ID or description" })).toBeVisible()
  const afterLeaving = state.reads.servers
  await page.clock.fastForward(30_000)
  expect(state.reads.servers).toBe(afterLeaving)
})

test("manual synchronization cancels an older live snapshot before publishing its result", async ({ page }) => {
  await login(page)
  await page.clock.install()
  const state = await fixture(page)
  await page.goto("/#/servers/synthetic-auto-sync")
  await page.getByRole("tab", { name: "Tools 1", exact: true }).click()
  await expect(page.getByRole("button", { name: "initial_tool", exact: true })).toBeVisible()
  let release = () => {}
  const blocked = new Promise<void>(resolve => { release = resolve })
  let pending: Request | null = null
  state.holdNextList = request => { pending = request; return blocked }
  try {
    await page.clock.fastForward(15_000)
    await expect.poll(() => pending !== null).toBe(true)
    await page.getByRole("button", { name: "Sync now", exact: true }).click()
    await expect(page.getByRole("button", { name: "new_remote_tool", exact: true })).toBeVisible()
    await expect.poll(() => pending?.failure()?.errorText).toBeTruthy()
  } finally { release() }
  await expect(page.getByRole("tab", { name: "Tools 2", exact: true })).toBeVisible()
})

for (const [width, height, locale, theme] of [
  [2560, 1440, "zh-CN", "light"], [1920, 1080, "en-US", "light"], [1600, 900, "en-US", "dark"], [2560, 1080, "zh-CN", "dark"],
] as const) {
  test(`tool recovery remains readable ${width}x${height} ${locale} ${theme}`, async ({ page }, info) => {
    await login(page)
    await page.addInitScript(({ locale, theme }) => { localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme) }, { locale, theme })
    await page.setViewportSize({ width, height })
    const state = await fixture(page)
    state.server = { ...state.server, tool_sync: { ...state.server.tool_sync!, state: "retrying", next_sync_at: "2026-11-13T01:05:00Z", last_error: "Upstream connection interrupted. Automatic recovery is scheduled.", error_code: "http_unavailable" } }
    await page.goto("/#/servers/synthetic-auto-sync")
    await page.getByRole("tab", { name: locale === "zh-CN" ? "工具 1" : "Tools 1", exact: true }).click()
    await expectInViewportAndUnobscured(page.getByRole("button", { name: locale === "zh-CN" ? "立即同步" : "Sync now", exact: true }))
    await expect(page.locator(".service-tool-sync")).toContainText(locale === "zh-CN" ? "下次重试" : "Next retry")
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    expect(await page.locator(".service-tool-sync").evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: info.outputPath(`tool-sync-${width}x${height}-${theme}.png`), animations: "disabled" })
  })
}

import { expect, test, type APIRequestContext, type Page } from "@playwright/test"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { expectInViewportAndUnobscured } from "./helpers"
import type { OAuthGrant } from "../src/features/external-connections/oauth-api"

test.skip(process.env.GATE_E2E_OAUTH_CATALOG_SCALE !== "1", "Requires the isolated 5,000-service / 50,000-tool fixture")
test.setTimeout(60_000)
const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
let ownerCookies: Awaited<ReturnType<APIRequestContext["storageState"]>>["cookies"] = []
test.beforeAll(async ({ playwright }) => {
  const owner = await playwright.request.newContext({ baseURL: "http://127.0.0.1:18763" })
  try {
    expect((await owner.post("/v1/auth/login", { data: { username: "synthetic-oauth-owner", password: "Synthetic-oauth-owner-123!" } })).status()).toBe(200)
    ownerCookies = (await owner.storageState()).cookies
  } finally { await owner.dispose() }
})

async function open(page: Page, locale: "en-US" | "zh-CN") {
  await page.context().addCookies(ownerCookies)
  await page.addInitScript(value => localStorage.setItem("lingshu-gate-console-locale", value), locale)
  await page.goto("/console/#/myConnections")
  await page.getByRole("tab", { name: locale === "zh-CN" ? "Gate 内置 OAuth" : "Gate built-in OAuth", exact: true }).click()
  const response = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
  await page.getByRole("button", { name: locale === "zh-CN" ? "调整授权范围" : "Adjust scope", exact: true }).click()
  expect((await response).status()).toBe(200)
  return page.getByRole("dialog", { name: locale === "zh-CN" ? "调整授权范围" : "Adjust authorization scope", exact: true })
}

async function captureRecovery(page: Page, locale: string, state: string) {
  const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: join(directory, `${state}-${locale}-1600x900.png`), animations: "disabled" })
  writeFileSync(join(directory, `${state}-${locale}-1600x900.json`), JSON.stringify({ source_sha: process.env.GATE_UI_SOURCE_SHA || null, fixture_services: 5000, fixture_tools: 50000, catalog_apis_mocked: false, locale, state, viewport: page.viewportSize() }, null, 2) + "\n")
}

test("OAuth entry avoids full definitions and the tool route still loads on navigation", async ({ page }) => {
  let fullReads = 0
  // Only the unrelated legacy tool page is mocked with one small definition;
  // OAuth catalog/session/selection requests use the actual large fixture.
  await page.route("**/v1/tools", route => {
    fullReads++
    return route.fulfill({ json: [{ id: "mcp.oauth-scale-0000.navigation", name: "Navigation read tool",
      source: "mcp", permission: "read", description: "Synthetic navigation fixture", input_schema: { type: "object" },
      metadata: { server_id: "oauth-scale-0000" } }] })
  })
  const editor = await open(page, "en-US")
  expect(fullReads).toBe(0)
  await editor.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.getByRole("link", { name: "Tool catalog", exact: true }).click()
  await expect(page.getByText("Navigation read tool", { exact: true }).first()).toBeVisible()
  expect(fullReads).toBe(1)
})

for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) {
  test(`real paged OAuth catalog fits ${locale} ${size.width}x${size.height}`, async ({ page }, testInfo) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize(size)
    let legacyReads = 0, fullToolReads = 0
    page.on("request", request => {
      const path = new URL(request.url()).pathname
      if (path.endsWith("/scope-options")) legacyReads++
      if (path === "/v1/tools") fullToolReads++
    })
    const editor = await open(page, locale)
    await editor.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(15)
    await editor.evaluate(async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)) })
    for (const control of [
      editor.getByRole("radio", { name: zh ? "仅选全部当前只读" : "All current read-only tools", exact: true }),
      editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }),
      editor.getByRole("button", { name: zh ? "下一页" : "Next page", exact: true }),
      editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true }),
    ]) await expectInViewportAndUnobscured(control)
    const metrics = await editor.evaluate(element => {
      const body = element.querySelector(".oauth-grant-scope-body")!
      const table = element.querySelector(".ant-table-body")!.getBoundingClientRect()
      const rows = Array.from(element.querySelectorAll("tr[data-row-key]")).filter(row => { const r = row.getBoundingClientRect(); return r.top >= table.top - 1 && r.bottom <= table.bottom + 1 }).length
      const labels = Array.from(element.querySelectorAll(".oauth-grant-limits label")).map(label => {
        const range = document.createRange(); range.selectNode(label.firstChild!)
        const text = range.getBoundingClientRect(), input = label.querySelector("input")!.getBoundingClientRect()
        return range.getClientRects().length === 1 && Math.abs((text.top + text.bottom - input.top - input.bottom) / 2) < 3
      })
      return { rows, labels, bodyOverflow: body.scrollHeight - body.clientHeight, pageOverflow: document.documentElement.scrollWidth - innerWidth }
    })
    expect(metrics.rows).toBeGreaterThanOrEqual(8)
    expect(metrics.labels.every(Boolean)).toBe(true)
    expect(metrics.bodyOverflow).toBeLessThanOrEqual(1)
    expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
    expect(legacyReads).toBe(0)
    expect(fullToolReads).toBe(0)
    const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
    if (directory) {
      mkdirSync(directory, { recursive: true })
      const basename = `paged-${locale}-${size.width}x${size.height}`
      await page.screenshot({ path: join(directory, `${basename}.png`), animations: "disabled" })
      writeFileSync(join(directory, `${basename}.json`), JSON.stringify({ source_sha: process.env.GATE_UI_SOURCE_SHA || null, fixture_services: 5000, fixture_tools: 50000, catalog_apis_mocked: false, locale, ...size, ...metrics }, null, 2) + "\n")
    }
    await testInfo.attach("layout", { body: JSON.stringify(metrics), contentType: "application/json" })
  })
}

for (const locale of ["en-US", "zh-CN"] as const) {
  test(`real paging group selection limits refresh and save recovery ${locale}`, async ({ page, playwright }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    const editor = await open(page, locale)
    const before = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    const group = zh ? "oauth-scale-0002" : "oauth-scale-0001"
    const expected = before.tools.length + 10
    await editor.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    const readFilter = editor.getByRole("radio", { name: zh ? "只读" : "Read", exact: true })
    await expect(readFilter).toBeEnabled()
    await readFilter.locator("..").click()
    await expect(readFilter).toBeChecked()
    const chosen = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
    const groupCheckbox = editor.getByRole("checkbox", { name: zh ? `选择 MCP ${group} 的全部当前可授权工具` : `Select all current available tools in MCP ${group}`, exact: true })
    await groupCheckbox.click()
    const groupResponse = await chosen
    expect(groupResponse.status()).toBe(200)
    const groupResult = await groupResponse.json()
    await expect(groupCheckbox).toBeChecked()
    expect(groupResult.tool_ids).toHaveLength(expected)
    expect(groupResult.tools.some((tool: { access: string }) => tool.access === "write")).toBe(true)
    await editor.getByRole("button", { name: zh ? "下一页" : "Next page", exact: true }).click()
    await expect(editor.locator(".oauth-paged-navigation")).toContainText(zh ? "第 2 页" : "Page 2")
    for (const name of [zh ? "选中全部当前工具" : "All current tools", zh ? "仅选全部当前只读" : "All current read-only tools"]) {
      const rejected = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
      await editor.getByRole("radio", { name, exact: true }).click()
      expect((await rejected).status()).toBe(409)
      await expect(editor.getByRole("alert")).toContainText(zh ? "草稿已保留" : "draft is retained")
      await expect(editor.locator(".oauth-selection")).toContainText(`${expected} /`)
      await expect(editor.getByRole("radio", { name: zh ? "自定义" : "Custom", exact: true })).toBeChecked()
    }
    const admin = await playwright.request.newContext({ baseURL: "http://127.0.0.1:18763" })
    try {
      expect((await admin.post("/v1/auth/login", { data: { username: "admin", password: "Synthetic-admin-123!" } })).status()).toBe(200)
      expect((await admin.post("/v1/access/tool-classifications/publish", { data: { server_id: "oauth-scale-4998" } })).status()).toBe(200)
      const refreshed = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
      await editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }).click()
      const next = await (await refreshed).json()
      expect(next.tool_ids).toEqual(groupResult.tool_ids)
      expect(next.tool_ids.some((id: string) => id.includes("oauth-scale-4998"))).toBe(false)
      await expect(editor.getByRole("radio", { name: zh ? "自定义" : "Custom", exact: true })).toBeChecked()
      const toolId = `mcp.${group}.tool-0`
      expect((await admin.put(`/v1/access/tool-classifications/${group}/${toolId}`, { data: { access: "read", destructive: false, idempotent: true } })).status()).toBe(200)
      const withdrawn = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
      await editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }).click()
      expect((await (await withdrawn).json()).unavailable_ids).toEqual([toolId])
      await expect(editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })).toBeDisabled()
      await editor.getByRole("button", { name: zh ? "查看不可授权原因" : "Why unavailable", exact: true }).click()
      const reasons = page.getByRole("dialog", { name: zh ? "不可授权原因" : "Unavailable scope reasons", exact: true })
      await expect(reasons).toContainText(zh ? "分类尚未发布" : "Classification is unpublished")
      await reasons.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).filter({ hasNot: page.locator("svg") }).click()
      await editor.getByRole("button", { name: zh ? "移除不可授权选择" : "Remove unavailable selections", exact: true }).click()
      await expect(editor.locator(".oauth-selection")).toContainText(`${expected - 1} /`)
    } finally { await admin.dispose() }
    const writePattern = "**/v1/auth/oauth/grants/*/scope"
    await page.route(writePattern, route => route.abort("failed"))
    const review = editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })
    await review.click()
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    await expect(editor.getByRole("alert")).toContainText(zh ? "结果未知" : "result is unknown")
    await expect(editor.locator(".oauth-selection")).toContainText(String(expected - 1))
    await expect(review).toBeDisabled()
    await page.unroute(writePattern)
    const recovered = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
    await editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }).click()
    expect((await recovered).status()).toBe(200)
    await expect(editor.locator(".oauth-selection")).toContainText(`${expected - 1} /`)
    await review.click()
    const saved = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope") && response.request().method() === "POST")
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    expect((await saved).status()).toBe(200)
    await expect(editor).toHaveCount(0)
    const after = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    expect(after.tools).toHaveLength(expected - 1)
    expect(after.scopes).toEqual(before.scopes)
    expect(after.revision).toBe(before.revision + 1)
  })
}

for (const locale of ["en-US", "zh-CN"] as const) {
  test(`remote MCP selector searches bounded groups and keeps draft across pages ${locale}`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    const editor = await open(page, locale)
    const before = editor.locator(".oauth-selection [role=status]")
    const selection = (await before.innerText()).split(" /")[0]
    const filter = editor.getByRole("combobox", { name: zh ? "按 MCP 筛选" : "Filter by MCP", exact: true })
    const initialGroups = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname.endsWith("/scope-catalog") && url.searchParams.get("view") === "groups" && url.searchParams.get("query") === "" })
    await filter.click()
    const initial = await initialGroups
    expect(initial.status()).toBe(200)
    expect((await initial.json()).items.length).toBeLessThanOrEqual(15)
    await editor.getByRole("button", { name: zh ? "加载更多 MCP" : "Load more MCPs", exact: true }).click()
    const group = "oauth-scale-0010"
    const searched = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname.endsWith("/scope-catalog") && url.searchParams.get("view") === "groups" && url.searchParams.get("query") === group })
    await filter.fill(group)
    expect((await searched).status()).toBe(200)
    const pageRead = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname.endsWith("/scope-catalog") && url.searchParams.get("view") === "tools" && url.searchParams.get("server_id") === group })
    await editor.locator(".ant-select-item-option-content").getByText(group, { exact: true }).click()
    expect((await pageRead).status()).toBe(200)
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(10)
    await expect(before).toContainText(selection)
    await editor.getByRole("button", { name: zh ? "重置筛选" : "Reset filters", exact: true }).click()
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(50)
    await expect(before).toContainText(selection)
  })
  test(`committed scope save with a lost response refreshes actual state ${locale}`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    const editor = await open(page, locale)
    const before: OAuthGrant = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    const group = zh ? "oauth-scale-0011" : "oauth-scale-0010"
    await editor.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    const selection = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
    await editor.getByRole("checkbox", { name: zh ? `选择 MCP ${group} 的全部当前可授权工具` : `Select all current available tools in MCP ${group}`, exact: true }).click()
    const draft = (await (await selection).json()).tool_ids as string[]
    const limit = editor.getByRole("spinbutton", { name: zh ? "每分钟调用上限" : "Calls per minute", exact: true })
    await limit.fill(String(before.rate_per_minute - 1))
    let writes = 0, previews = 0, savedReads = 0
    const tickets: string[] = [], revisions: number[] = []
    let submitted: Record<string, unknown> = {}
    page.on("request", request => { if (new URL(request.url()).pathname === "/v1/auth/oauth/grants") savedReads++ })
    page.on("response", async response => {
      if (new URL(response.url()).pathname.endsWith("/scope-preview") && response.ok()) {
        previews++
        tickets.push((await response.json()).confirmation)
        revisions.push(response.request().postDataJSON().expected_revision)
      }
    })
    const scopePath = `/v1/auth/oauth/grants/${before.id}/scope`
    await page.route(`**${scopePath}`, async route => {
      writes++
      if (writes > 1) return route.continue()
      submitted = route.request().postDataJSON()
      // Forward the real HTTP write and receive its committed 200 response,
      // then drop only the browser response. This is not a pre-send abort.
      const committed = await route.fetch({ maxRedirects: 0, maxRetries: 0 })
      expect(committed.status()).toBe(200)
      expect((await committed.json()).revision).toBe(before.revision + 1)
      await route.abort("failed")
    })
    const review = editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })
    await review.click()
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    await expect(editor.getByRole("alert")).toContainText(zh ? "结果未知" : "result is unknown")
    const saved: OAuthGrant = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    expect(saved.revision).toBe(before.revision + 1)
    expect(saved.tools.map(tool => tool.id).sort()).toEqual([...draft].sort())
    expect(saved.rate_per_minute).toBe(before.rate_per_minute - 1)
    expect(saved.scopes).toEqual(before.scopes)
    // Replaying the consumed confirmation is rejected without another commit.
    const replay = await page.request.post(scopePath, { data: submitted, headers: { Origin: "http://127.0.0.1:18763" } })
    expect(replay.status()).toBe(409)
    expect((await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0].revision).toBe(saved.revision)
    await expect(review).toBeDisabled()
    expect(writes).toBe(1)
    expect(previews).toBe(1)
    expect(savedReads).toBe(0)
    await captureRecovery(page, locale, "save-unknown")
    const pendingRate = saved.rate_per_minute - (zh ? 1 : 0)
    if (zh) {
      await limit.fill(String(pendingRate))
      await expect(review).toBeDisabled()
    } else {
      // A failed authoritative read must not clear uncertainty or unlock save.
      const readPattern = "**/v1/auth/oauth/grants"
      await page.route(readPattern, route => route.abort("failed"))
      await editor.getByRole("button", { name: "Refresh available scope", exact: true }).click()
      await expect(editor.getByRole("alert")).toContainText("Connection failed")
      await expect(review).toBeDisabled()
      await expect(editor.locator(".oauth-selection")).toContainText(String(draft.length))
      await page.unroute(readPattern)
    }
    await editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }).click()
    await expect(editor.locator(".oauth-scope-refresh-status")).toContainText(zh ? `保存版本 ${saved.revision}` : `Saved grant revision ${saved.revision}`)
    await expect(editor.locator(".oauth-selection")).toContainText(`${draft.length} /`)
    await expect(limit).toHaveValue(String(pendingRate))
    await expect(editor.getByRole("alert")).toHaveCount(0)
    if (zh) await expect(review).toBeEnabled()
    else await expect(review).toBeDisabled()
    expect(writes).toBe(1)
    expect(previews).toBe(1)
    expect(savedReads).toBe(zh ? 1 : 2)
    await captureRecovery(page, locale, "save-reconciled")
    // A later explicit edit requires a fresh preview/ticket at the actual revision.
    await limit.fill(String(saved.rate_per_minute - 1))
    await review.click()
    const updated = page.waitForResponse(response => new URL(response.url()).pathname === scopePath && response.request().method() === "POST")
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    expect((await updated).status()).toBe(200)
    await expect(editor).toHaveCount(0)
    expect(writes).toBe(2)
    expect(previews).toBe(2)
    expect(revisions).toEqual([before.revision, saved.revision])
    expect(tickets[0] !== tickets[1]).toBe(true)
    const after: OAuthGrant = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    expect(after.revision).toBe(before.revision + 2)
    expect(after.tools.map(tool => tool.id).sort()).toEqual([...draft].sort())
    expect(after.scopes).toEqual(before.scopes)
    expect(after.rate_per_minute).toBe(saved.rate_per_minute - 1)
  })
}

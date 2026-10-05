import { expect, test, type APIRequestContext, type Page } from "@playwright/test"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { expectInViewportAndUnobscured } from "./helpers"

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
  await editor.getByRole("button", { name: "Close", exact: true }).filter({ hasNot: page.locator("svg") }).click()
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
      editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true }),
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
    expect(metrics.rows).toBeGreaterThanOrEqual(6)
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
      writeFileSync(join(directory, `${basename}.json`), JSON.stringify({ fixture_services: 5000, fixture_tools: 50000, locale, ...size, ...metrics }, null, 2) + "\n")
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
      await expect(editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true })).toBeDisabled()
      await editor.getByRole("button", { name: zh ? "查看不可授权原因" : "Why unavailable", exact: true }).click()
      const reasons = page.getByRole("dialog", { name: zh ? "不可授权原因" : "Unavailable scope reasons", exact: true })
      await expect(reasons).toContainText(zh ? "分类尚未发布" : "Classification is unpublished")
      await reasons.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).filter({ hasNot: page.locator("svg") }).click()
      await editor.getByRole("button", { name: zh ? "移除不可授权选择" : "Remove unavailable selections", exact: true }).click()
      await expect(editor.locator(".oauth-selection")).toContainText(`${expected - 1} /`)
    } finally { await admin.dispose() }
    const writePattern = "**/v1/auth/oauth/grants/*/scope"
    await page.route(writePattern, route => route.abort("failed"))
    const review = editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true })
    await review.click()
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    await expect(editor.getByRole("alert")).toContainText(zh ? "连接失败" : "Connection failed")
    await expect(editor.locator(".oauth-selection")).toContainText(`${expected - 1} /`)
    await page.unroute(writePattern)
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

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
  await page.getByRole("radiogroup", { name: locale === "zh-CN" ? "授权方式" : "Authorization type", exact: true }).getByRole("radio", { name: "Gate OAuth", exact: true }).check()
  const row = page.locator('.my-authorizations-page .ant-table-tbody > tr[data-row-key^="builtin:"]')
    .filter({ has: page.getByRole("button", { name: "Synthetic scale OAuth client", exact: true }) })
  await expect(row).toHaveCount(1)
  const response = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
  await row.getByRole("button", { name: locale === "zh-CN" ? "调整授权" : "Adjust", exact: true }).click()
  expect((await response).status()).toBe(200)
  const editor = page.getByRole("dialog", { name: locale === "zh-CN" ? "调整授权范围" : "Adjust authorization scope", exact: true })
  await expect(editor.locator(".authorization-mcp-editor tr[data-row-key]")).toHaveCount(10)
  return editor
}

async function captureRecovery(page: Page, locale: string, state: string) {
  const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: join(directory, `${state}-${locale}-1600x900.png`), animations: "disabled" })
  writeFileSync(join(directory, `${state}-${locale}-1600x900.json`), JSON.stringify({ source_sha: process.env.GATE_UI_SOURCE_SHA || null, fixture_services: 5000, fixture_tools: 50000, catalog_apis_mocked: false, locale, state, viewport: page.viewportSize() }, null, 2) + "\n")
}

async function chooseMcp(editor: import("@playwright/test").Locator, server: string, zh: boolean) {
  await editor.getByRole("textbox", { name: zh ? "搜索 MCP" : "Search MCP", exact: true }).fill(server)
  const row = editor.locator(`.authorization-mcp-editor tr[data-row-key="${server}"]`)
  await expect(row).toBeVisible()
  const mode = row.getByRole("radio", { name: zh ? "指定工具" : "Selected tools", exact: true })
  if (await mode.isChecked()) await row.getByRole("button", { name: `${server} ${zh ? "选择工具" : "choose tools"}`, exact: true }).click()
  else await mode.check()
  const picker = editor.locator(".oauth-paged-tools")
  await expect(picker.locator("tr[data-row-key]")).toHaveCount(10)
  return picker
}

test("OAuth entry reads one service page and avoids full definitions", async ({ page }) => {
  let fullReads = 0
  const groupReads: URL[] = []
  page.on("request", request => { const url = new URL(request.url()); if (url.pathname.endsWith("/scope-catalog") && url.searchParams.get("view") === "groups") groupReads.push(url) })
  await page.route("**/v1/tools", route => {
    fullReads++
    return route.fulfill({ json: [{ id: "mcp.oauth-scale-0000.navigation", name: "Navigation read tool", source: "mcp", permission: "read", description: "Synthetic navigation fixture", input_schema: { type: "object" }, metadata: { server_id: "oauth-scale-0000", gate_access: { required_access: "read", policy_source: "local_override", classification_status: "configured" } } }] })
  })
  const editor = await open(page, "en-US")
  expect(fullReads).toBe(0)
  expect(groupReads).toHaveLength(1)
  expect(groupReads[0].searchParams.get("limit")).toBe("10")
  await editor.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.getByRole("link", { name: "Tool catalog", exact: true }).click()
  await expect(page.getByText("Navigation read tool", { exact: true }).first()).toBeVisible()
  expect(fullReads).toBe(1)
})

for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) {
  test(`real paged OAuth service editor fits ${locale} ${size.width}x${size.height}`, async ({ page }, testInfo) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize(size)
    let fullReads = 0
    page.on("request", request => { const path = new URL(request.url()).pathname; if (path === "/v1/tools" || path.endsWith("/scope-options")) fullReads++ })
    const editor = await open(page, locale)
    const body = editor.locator(".oauth-grant-edit-body")
    const save = editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })
    const cancel = editor.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true })
    await editor.evaluate(async element => { await Promise.allSettled(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished)) })
    const footer = await cancel.boundingBox()
    for (const control of [editor.getByRole("textbox", { name: zh ? "搜索 MCP" : "Search MCP", exact: true }), editor.getByRole("navigation", { name: zh ? "MCP 分页" : "MCP pages", exact: true }).getByRole("button", { name: zh ? "下一页" : "Next page", exact: true }), cancel]) {
      await control.scrollIntoViewIfNeeded()
      await expectInViewportAndUnobscured(control)
      await expectInViewportAndUnobscured(save)
    }
    expect(await cancel.boundingBox()).toEqual(footer)
    expect(await body.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    await expect(editor.locator(".authorization-mcp-editor tr[data-row-key]")).toHaveCount(10)
    expect(fullReads).toBe(0)
    const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
    if (directory) {
      mkdirSync(directory, { recursive: true })
      await page.screenshot({ path: join(directory, `paged-services-${locale}-${size.width}x${size.height}.png`), animations: "disabled" })
    }
    await testInfo.attach("layout", { body: JSON.stringify({ ...size, serviceRows: 10, fullReads, oneMainScroll: true }), contentType: "application/json" })
  })
}

for (const locale of ["en-US", "zh-CN"] as const) {
  test(`real explicit MCP selection survives policy changes and unknown saves ${locale}`, async ({ page, playwright }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    const editor = await open(page, locale)
    const before = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    const group = zh ? "oauth-scale-0002" : "oauth-scale-0001"
    const picker = await chooseMcp(editor, group, zh)
    const expected = before.tools.length + 10
    await picker.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    const chosen = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
    await picker.getByRole("checkbox", { name: zh ? `选择 MCP ${group} 的全部当前可授权工具` : `Select all current available tools in MCP ${group}`, exact: true }).check()
    const groupResult = await (await chosen).json()
    expect(groupResult.tool_ids).toHaveLength(expected)
    const admin = await playwright.request.newContext({ baseURL: "http://127.0.0.1:18763" })
    const refresh = editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true })
    try {
      expect((await admin.post("/v1/auth/login", { data: { username: "admin", password: "Synthetic-admin-123!" } })).status()).toBe(200)
      // Re-enable one locally disabled tool directly. No review or publish step.
      expect((await admin.put("/v1/access/tool-classifications/oauth-scale-4998/mcp.oauth-scale-4998.tool-0", { data: { access: "read", destructive: false, idempotent: true } })).status()).toBe(200)
      const refreshed = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
      await refresh.click()
      const next = await (await refreshed).json()
      expect(next.tool_ids).toEqual(groupResult.tool_ids)
      expect(next.tool_ids.some((id: string) => id.includes("oauth-scale-4998"))).toBe(false)
      const toolId = `mcp.${group}.tool-0`
      expect((await admin.put(`/v1/access/tool-classifications/${group}/${toolId}`, { data: { access: "unknown", destructive: false, idempotent: false } })).status()).toBe(200)
      const withdrawn = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
      await refresh.click()
      expect((await (await withdrawn).json()).unavailable_ids).toEqual([toolId])
      await expect(editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })).toBeDisabled()
      // Disabled resources are filtered from candidate details; the retained
      // selection is still visible as unavailable without exposing other tools.
      await expect(editor.locator(".oauth-unavailable-selection")).toBeVisible()
      await editor.getByRole("button", { name: zh ? "移除不可授权选择" : "Remove unavailable selections", exact: true }).click()
      await expect(editor.locator(".oauth-selection")).toContainText(`${expected - 1} /`)
    } finally { await admin.dispose() }
    const writePattern = "**/v1/auth/oauth/grants/*/scope"
    await page.route(writePattern, route => route.abort("failed"))
    const save = editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })
    await save.click()
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    await expect(editor.getByRole("alert")).toContainText(zh ? "结果未知" : "result is unknown")
    await expect(save).toBeDisabled()
    await page.unroute(writePattern)
    const recovered = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
    await refresh.click()
    expect((await recovered).status()).toBe(200)
    await expect(editor.locator(".oauth-selection")).toContainText(`${expected - 1} /`)
    await save.click()
    const saved = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope") && response.request().method() === "POST")
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    expect((await saved).status()).toBe(200)
    await expect(editor).toHaveCount(0)
    const after = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    expect(after.tools).toHaveLength(expected - 1)
    expect(after.scopes).toEqual(before.scopes)
    expect(after.revision).toBe(before.revision + 1)
  })

  test(`remote MCP pages search and retry without changing the saved scope ${locale}`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    let writes = 0, fullReads = 0
    page.on("request", request => { const path = new URL(request.url()).pathname; if (path.endsWith("/scope-preview") || path.endsWith("/scope")) writes++; if (path === "/v1/tools" || path.endsWith("/scope-options")) fullReads++ })
    const editor = await open(page, locale)
    const selection = await editor.locator(".oauth-selection [role=status]").innerText()
    const search = editor.getByRole("textbox", { name: zh ? "搜索 MCP" : "Search MCP", exact: true })
    const searched = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname.endsWith("/scope-catalog") && url.searchParams.get("view") === "groups" && url.searchParams.get("query") === "oauth-scale-4999" })
    await search.fill("oauth-scale-4999")
    expect((await (await searched).json()).items).toHaveLength(1)
    await expect(editor.locator('.authorization-mcp-editor tr[data-row-key="oauth-scale-4999"]').getByRole("radio", { name: zh ? "不授权" : "None", exact: true })).toBeChecked()
    await search.fill("")
    await expect(editor.locator(".authorization-mcp-editor tr[data-row-key]")).toHaveCount(10)
    let injected = false, failedCursor = ""
    const routePattern = "**/v1/auth/oauth/grants/*/scope-catalog?**"
    await page.route(routePattern, route => {
      const url = new URL(route.request().url())
      if (!injected && url.searchParams.get("view") === "groups" && url.searchParams.has("cursor")) { injected = true; failedCursor = url.searchParams.get("cursor")!; return route.fulfill({ status: 503, json: { error: "scope_catalog_unavailable" } }) }
      return route.continue()
    })
    const next = editor.getByRole("navigation", { name: zh ? "MCP 分页" : "MCP pages", exact: true }).getByRole("button", { name: zh ? "下一页" : "Next page", exact: true })
    await next.focus(); await page.keyboard.press("Enter")
    const retry = editor.getByRole("button", { name: zh ? "重试读取 MCP" : "Retry MCP page", exact: true })
    await expect(retry).toBeEnabled()
    const retried = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname.endsWith("/scope-catalog") && url.searchParams.get("cursor") === failedCursor && response.status() === 200 })
    await retry.focus(); await page.keyboard.press("Space")
    expect((await (await retried).json()).items).toHaveLength(10)
    await expect(retry).toHaveCount(0)
    await expect(editor.getByRole("navigation", { name: zh ? "MCP 分页" : "MCP pages", exact: true })).toContainText(zh ? "第 2 页" : "Page 2")
    await expect(editor.locator(".oauth-selection [role=status]")).toHaveText(selection)
    expect(writes).toBe(0); expect(fullReads).toBe(0)
    await captureRecovery(page, locale, "service-page-recovered")
    await page.unroute(routePattern)
  })
  test(`committed scope save with a lost response refreshes actual state ${locale}`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    const editor = await open(page, locale)
    const before: OAuthGrant = (await (await page.request.get("/v1/auth/oauth/grants")).json()).grants[0]
    const group = zh ? "oauth-scale-0011" : "oauth-scale-0010"
    const picker = await chooseMcp(editor, group, zh)
    await picker.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    const selection = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/scope-selection"))
    await picker.getByRole("checkbox", { name: zh ? `选择 MCP ${group} 的全部当前可授权工具` : `Select all current available tools in MCP ${group}`, exact: true }).click()
    const draft = (await (await selection).json()).tool_ids as string[]
    await expandCallLimits(editor)
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
    const updated = page.waitForResponse(response => new URL(response.url()).pathname === scopePath && response.request().method() === "POST")
    await review.click()
    await expect(page.getByRole("alertdialog")).toHaveCount(0)
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

async function expandCallLimits(editor: import("@playwright/test").Locator) {
  const header = editor.locator(".authorization-quota-settings [aria-expanded]").first()
  if (await header.getAttribute("aria-expanded") === "false") await header.click()
}

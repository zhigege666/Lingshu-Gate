import { expect, test, type Page } from "@playwright/test"
import { mkdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import type { OAuthGrant } from "../src/features/external-connections/oauth-api"
import { expectInViewportAndUnobscured } from "./helpers"

// Built Console UI, owner-scoped synthetic responses only; no real credentials.
const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static/console")
const now = Math.floor(Date.now() / 1000)
const tools = Array.from({ length: 5000 }, (_, index) => ({ id: `synthetic-tool-${index}`, name: `Named tool ${index}`, server_id: `synthetic-mcp-${Math.floor(index / 50)}`, server_name: `Named MCP ${Math.floor(index / 50)}`, access: index % 2 ? "write" as const : "read" as const, snapshot: "synthetic", currently_authorized: true }))
function grant(index: number, state = "active", large = false): OAuthGrant {
  return { id: `synthetic-grant-${String(index).padStart(8, "0")}`, client_id: "lgc_synthetic_personal", client_name: "Synthetic research client", resource: "https://gate.example.test/mcp", scopes: ["tools.read", "tools.invoke"], tools: large ? tools : tools.slice(0, 112), created_at: now - index * 60, state, expires_at: state === "expired" ? now - 60 : now + 86400, rate_per_minute: 300, concurrency: 5, revision: 1, scope_currently_authorized: true, effective_tool_count: large ? 5000 : 112 }
}
type Locale = "en-US" | "zh-CN"
async function setup(page: Page, locale: Locale, records: OAuthGrant[], theme = "light") {
  const model = { records, writes: [] as { path: string; body: Record<string, unknown> }[], failure: false }
  await page.addInitScript(({ locale, theme }) => {
    localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme)
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => undefined } })
  }, { locale, theme })
  await page.route("**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(assets, "index.html"), "utf8") }))
  await page.route("**/console/assets/**", route => { const name = path.basename(new URL(route.request().url()).pathname); return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(assets, "assets", name)) }) })
  await page.route("**/healthz", route => route.fulfill({ json: { version: "0.4.1" } }))
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-owner", username: "synthetic-owner", display_name: "Synthetic owner", status: "active", role: "custom", roles: ["custom"], permissions: ["console.view", "credentials.manage.self"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/grants") return route.fulfill(model.failure ? { status: 503, json: { error: "request_failed" } } : { json: { grants: model.records } })
    if (pathname.startsWith("/v1/auth/oauth/grants/")) {
      const body = route.request().postDataJSON(), id = pathname.split("/")[5]
      model.writes.push({ path: pathname, body })
      const existing = model.records.find(grant => grant.id === id)!
      const next = pathname.endsWith("/revoke") ? { ...existing, state: "revoked", revision: existing.revision + 1 } : { ...existing, rate_per_minute: Number(body.rate_per_minute), concurrency: Number(body.concurrency), expires_at: Number(body.expires_at), tools: existing.tools.filter(tool => (body.tool_ids as string[]).includes(tool.id)), revision: existing.revision + 1 }
      model.records = model.records.map(grant => grant.id === id ? next : grant)
      return route.fulfill({ json: next })
    }
    return route.fulfill({ status: 404, json: { error: "unmocked_synthetic_request" } })
  })
  await page.goto("/console/#/myConnections")
  // The current navigation uses the built-in OAuth tab in My connections.
  await page.getByRole("tab", { name: locale === "zh-CN" ? "Gate 内置 OAuth" : "Gate built-in OAuth", exact: true }).click()
  await expect(page.getByRole("heading", { name: locale === "zh-CN" ? "我的 OAuth 授权" : "My OAuth grants", exact: true })).toBeVisible()
  await expect(page.locator(".oauth-grants-toolbar")).toBeVisible()
  return model
}
function stateTab(page: Page, name: string) { return page.locator(".oauth-grants-toolbar").getByRole("radio", { name, exact: true }).locator("..") }
function rows(page: Page) { return page.locator(".ant-table-tbody tr[data-row-key]") }
async function capture(page: Page, name: string) { const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR; if (directory) { mkdirSync(directory, { recursive: true }); await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" }) } }

const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) for (const theme of ["light", "dark"]) {
  const suffix = `${locale}-${theme}-${size.width}x${size.height}`
  test(`personal OAuth grants statuses and read-only details ${suffix}`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize(size)
    const model = await setup(page, locale, [grant(1), grant(2, "revoked"), grant(3, "expired"), grant(4, "disabled")], theme)
    await expect(rows(page)).toHaveCount(1)
    await expect(page.getByRole("radio", { name: zh ? "有效" : "Active", exact: true })).toBeChecked()
    await expect(rows(page).first()).toContainText("UTC")
    await expect(rows(page).first()).toContainText(zh ? "含写入" : "Includes write")
    await capture(page, `grants-active-${suffix}`)
    await stateTab(page, zh ? "全部" : "All").click()
    await expect(rows(page)).toHaveCount(4)
    const revoked = page.locator(`[data-row-key="${grant(2).id}"]`)
    await expect(revoked.getByRole("button", { name: zh ? "缩小范围" : "Reduce scope", exact: true })).toHaveCount(0)
    await expect(revoked.getByRole("button", { name: zh ? "撤销" : "Revoke", exact: true })).toHaveCount(0)
    await capture(page, `grants-all-${suffix}`)
    const trigger = revoked.getByRole("button", { name: zh ? "112 个工具" : "112 tools", exact: true })
    await trigger.click()
    const details = page.getByRole("dialog", { name: zh ? "授权详情" : "Grant details", exact: true })
    await expect(details.getByLabel("Grant ID", { exact: true })).toHaveValue(grant(2).id)
    await expect(details.getByRole("textbox", { name: zh ? "搜索当前范围内的工具" : "Search tools in the current scope", exact: true })).toBeEnabled()
    await expect(details.getByRole("checkbox")).toHaveCount(0)
    await expect(details.getByRole("button", { name: zh ? "保存缩小后的授权" : "Save reduced grant", exact: true })).toHaveCount(0)
    // Measure before any pagination click; Playwright clicking alone scrolls a clipped pager into view.
    const body = details.locator(".oauth-grant-details-body")
    const viewport = details.locator(".ant-table-body")
    const pager = details.locator(".ant-pagination")
    const next = pager.locator(".ant-pagination-next")
    const footerClose = details.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).filter({ hasNot: page.locator("svg") })
    await expectInViewportAndUnobscured(next)
    await expectInViewportAndUnobscured(footerClose)
    expect(await body.evaluate(element => ({ top: element.scrollTop, overflow: element.scrollHeight - element.clientHeight }))).toEqual({ top: 0, overflow: 0 })
    const pagerPosition = await pager.boundingBox()
    await viewport.evaluate(element => { element.scrollTop = element.scrollHeight })
    expect(await viewport.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
    expect(await body.evaluate(element => element.scrollTop)).toBe(0)
    expect(await pager.boundingBox()).toEqual(pagerPosition)
    await expectInViewportAndUnobscured(next)
    await next.click()
    await expect(details.getByText("51–100 / 112", { exact: true })).toBeVisible()
    expect(await details.locator(".ant-table-tbody tr[data-row-key]").count()).toBe(50)
    expect(await body.evaluate(element => element.scrollTop)).toBe(0)
    await pager.getByTitle("1", { exact: true }).click()
    await expect(details.getByText("1–50 / 112", { exact: true })).toBeVisible()
    await capture(page, `grants-readonly-${suffix}`)
    await page.keyboard.press("Escape")
    await expect(details).toHaveCount(0)
    await expect(trigger).toBeFocused()
    expect(model.writes).toHaveLength(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}

for (const locale of ["en-US", "zh-CN"] as const) {
  const zh = locale === "zh-CN"
  for (const outcome of ["success", "failure"] as const) test(`OAuth old clipboard ${outcome} does not change new grant details ${locale}`, async ({ page }) => {
    await setup(page, locale, [grant(1), grant(2)])
    await page.evaluate(outcome => {
      let finish!: () => void
      const pending = new Promise<void>((resolve, reject) => { finish = outcome === "success" ? resolve : () => reject(new Error("synthetic clipboard failure")) })
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => pending } })
      ;(window as unknown as { finishSyntheticCopy: () => void }).finishSyntheticCopy = finish
    }, outcome)
    await page.locator(`[data-row-key="${grant(1).id}"]`).getByRole("button", { name: zh ? "详情" : "Details", exact: true }).click()
    const details = page.getByRole("dialog", { name: zh ? "授权详情" : "Grant details", exact: true })
    await details.getByRole("button", { name: zh ? "复制授权 ID" : "Copy grant ID", exact: true }).click()
    await page.keyboard.press("Escape")
    await expect(details).toHaveCount(0)
    await page.locator(`[data-row-key="${grant(2).id}"]`).getByRole("button", { name: zh ? "详情" : "Details", exact: true }).click()
    await expect(details.getByLabel("Grant ID", { exact: true })).toHaveValue(grant(2).id)
    await page.evaluate(() => (window as unknown as { finishSyntheticCopy: () => void }).finishSyntheticCopy())
    await expect(details.locator("p[role=status]")).toHaveCount(0)
  })
  test(`OAuth 1000 records filter before pagination and 5000 tools remain searchable ${locale} @large-data`, async ({ page }) => {
    const records = Array.from({ length: 1000 }, (_, index) => grant(index, index < 950 ? "revoked" : "active", index === 999))
    await setup(page, locale, records)
    await expect(page.getByText("1–15 / 50", { exact: true })).toBeVisible()
    await page.locator(".ant-pagination-next").click()
    await expect(page.getByText("16–30 / 50", { exact: true })).toBeVisible()
    await stateTab(page, zh ? "已撤销" : "Revoked").click()
    await expect(page.getByText("1–15 / 950", { exact: true })).toBeVisible()
    await stateTab(page, zh ? "全部" : "All").click()
    await expect(page.getByText("1–15 / 1000", { exact: true })).toBeVisible()
    const search = page.getByRole("textbox", { name: zh ? "搜索我的授权" : "Search my grants", exact: true })
    await search.fill("Named tool 4999")
    await expect(rows(page)).toHaveCount(1)
    await rows(page).getByRole("button", { name: zh ? "5000 个工具" : "5000 tools", exact: true }).click()
    const details = page.getByRole("dialog", { name: zh ? "授权详情" : "Grant details", exact: true })
    await expect(details.getByRole("status")).toContainText(zh ? "5000 个已记录工具，涉及 100 个 MCP" : "5000 recorded tools across 100 MCPs")
    const scopeSearch = details.getByRole("textbox", { name: zh ? "搜索当前范围内的工具" : "Search tools in the current scope", exact: true })
    await scopeSearch.fill("Named tool 4999")
    await expect(details.getByRole("cell").filter({ hasText: "Named tool 4999" })).toBeVisible()
    await expect(details.getByRole("cell").filter({ hasText: "Named MCP 99" })).toBeVisible()
    await details.getByRole("button", { name: zh ? "重置筛选" : "Reset filters", exact: true }).click()
    await expect(details.getByText("1–50 / 5000", { exact: true })).toBeVisible()
    await details.getByRole("button", { name: zh ? "复制授权 ID" : "Copy grant ID", exact: true }).click()
    await expect(details.getByText(zh ? "标识已复制。" : "Identifier copied.", { exact: true })).toBeVisible()
    await page.keyboard.press("Escape")
    await search.fill("")
    await stateTab(page, zh ? "有效" : "Active").click()
    await expect(page.getByText("1–15 / 50", { exact: true })).toBeVisible()
  })
  test(`OAuth zero/one record and expired active metadata are accurate ${locale}`, async ({ page }) => {
    const model = await setup(page, locale, [])
    await expect(page.getByText(zh ? "尚无授权。请从客户端连接并同意工具范围。" : "No grants yet. Connect from a client and consent to tool scope.", { exact: true })).toBeVisible()
    const one = { ...grant(1), expires_at: now - 1, created_at: undefined }
    model.records = [one]
    await page.getByRole("button", { name: zh ? "刷新" : "Refresh", exact: true }).click()
    await expect(page.getByRole("button", { name: zh ? "查看全部授权" : "Show all grants", exact: true })).toBeVisible()
    await stateTab(page, zh ? "已过期" : "Expired").click()
    await expect(rows(page)).toHaveCount(1)
    await expect(rows(page).getByRole("button", { name: zh ? "缩小范围" : "Reduce scope", exact: true })).toHaveCount(0)
    await expect(rows(page).getByRole("button", { name: zh ? "撤销" : "Revoke", exact: true })).toHaveCount(0)
    await expect(rows(page).first().locator("td").first()).not.toContainText("UTC")
  })
  test(`OAuth reduction and revocation keep explicit confirmations ${locale} @permissions`, async ({ page }) => {
    const model = await setup(page, locale, [grant(1)])
    await page.getByRole("button", { name: zh ? "缩小范围" : "Reduce scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "查看 / 缩小授权" : "View / reduce grant", exact: true })
    await editor.getByRole("spinbutton", { name: zh ? "每分钟调用上限" : "Calls per minute", exact: true }).fill("30")
    await editor.getByRole("button", { name: zh ? "保存缩小后的授权" : "Save reduced grant", exact: true }).click()
    const reduction = page.getByRole("alertdialog", { name: zh ? "保存缩小后的授权？" : "Save reduced grant?", exact: true })
    expect(model.writes).toHaveLength(0)
    await reduction.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await editor.getByRole("button", { name: zh ? "保存缩小后的授权" : "Save reduced grant", exact: true }).click()
    await reduction.getByRole("button", { name: zh ? "保存缩小后的授权" : "Save reduced grant", exact: true }).click()
    await expect(editor).toHaveCount(0)
    expect(model.writes).toHaveLength(1)
    expect(model.writes[0].body.rate_per_minute).toBe(30)
    expect(model.writes[0].body.tool_ids).toEqual(grant(1).tools.map(tool => tool.id))
    await page.getByRole("button", { name: zh ? "撤销" : "Revoke", exact: true }).click()
    const revoke = page.getByRole("alertdialog", { name: zh ? "撤销授权？" : "Revoke authorization?", exact: true })
    await revoke.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    expect(model.writes).toHaveLength(1)
    await page.getByRole("button", { name: zh ? "撤销" : "Revoke", exact: true }).click()
    await revoke.getByRole("button", { name: zh ? "撤销授权" : "Revoke grant", exact: true }).click()
    await expect.poll(() => model.writes.length).toBe(2)
    await expect(rows(page)).toHaveCount(0)
    await stateTab(page, zh ? "已撤销" : "Revoked").click()
    await expect(rows(page)).toHaveCount(1)
    await expect(rows(page).getByRole("button", { name: zh ? "详情" : "Details", exact: true })).toBeVisible()
  })
}

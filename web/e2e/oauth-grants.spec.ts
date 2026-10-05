import { expect, test, type Page } from "@playwright/test"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import type { OAuthGrant, OAuthScopeUnavailableServer, OAuthTool } from "../src/features/external-connections/oauth-api"
import { expectInViewportAndUnobscured } from "./helpers"

// Built Console UI, owner-scoped synthetic responses only; no real credentials.
const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static/console")
const sourceVersion = readFileSync(path.resolve(assets, "../../_version.py"), "utf8").match(/^__version__\s*=\s*["']([^"']+)["']/m)?.[1]
if (!sourceVersion) throw new Error("The OAuth fixture requires the current source version")
const now = Math.floor(Date.now() / 1000)
const tools = Array.from({ length: 5000 }, (_, index) => ({ id: `synthetic-tool-${index}`, name: `Named tool ${index}`, server_id: `synthetic-mcp-${Math.floor(index / 50)}`, server_name: `Named MCP ${Math.floor(index / 50)}`, access: index % 2 ? "write" as const : "read" as const, snapshot: "synthetic", currently_authorized: true }))
function grant(index: number, state = "active", large = false): OAuthGrant {
  return { id: `synthetic-grant-${String(index).padStart(8, "0")}`, client_id: "lgc_synthetic_personal", client_name: "Synthetic research client", resource: "https://gate.example.test/mcp", scopes: ["tools.read", "tools.invoke"], tools: large ? tools : tools.slice(0, 112), created_at: now - index * 60, state, expires_at: state === "expired" ? now - 60 : now + 86400, rate_per_minute: 300, concurrency: 5, revision: 1, scope_currently_authorized: true, effective_tool_count: large ? 5000 : 112 }
}
type Locale = "en-US" | "zh-CN"
async function setup(page: Page, locale: Locale, records: OAuthGrant[], theme = "light") {
  const model = { records, writes: [] as { path: string; body: Record<string, unknown> }[], failure: false,
    candidates: null as OAuthTool[] | null, previews: [] as Record<string, unknown>[], confirmation: "", scopeFailure: false, previewFailure: false, writeFailure: false,
    familyScopes: ["tools.read", "tools.invoke"] as string[], optionsReads: 0,
    unavailable: [] as OAuthScopeUnavailableServer[], canReview: false }
  await page.addInitScript(({ locale, theme }) => {
    localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme)
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => undefined } })
  }, { locale, theme })
  await page.route("**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(assets, "index.html"), "utf8") }))
  await page.route("**/console/assets/**", route => { const name = path.basename(new URL(route.request().url()).pathname); return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(assets, "assets", name)) }) })
  await page.route("**/healthz", route => route.fulfill({ json: { version: sourceVersion } }))
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-owner", username: "synthetic-owner", display_name: "Synthetic owner", status: "active", role: "custom", roles: ["custom"], permissions: ["console.view", "credentials.manage.self"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/grants") return route.fulfill(model.failure ? { status: 503, json: { error: "request_failed" } } : { json: { grants: model.records } })
    if (pathname.startsWith("/v1/auth/oauth/grants/")) {
      const id = pathname.split("/")[5]
      const existing = model.records.find(grant => grant.id === id)!
      if (pathname.endsWith('/scope-options')) {
        model.optionsReads++
        return route.fulfill(model.scopeFailure ? { status: 503, json: { error: 'request_failed' } } : {
        json: { csrf: 'synthetic-options-csrf-' + 's'.repeat(32), expires_at: now + 600, grant_revision: existing.revision,
          tools: model.candidates || existing.tools, scopes: existing.scopes, effective_scopes: existing.scopes, family_scope_limits: [{ scopes: model.familyScopes, count: 1 }],
          unavailable_servers: model.unavailable, can_review_classifications: model.canReview },
      })
      }
      const body = route.request().postDataJSON()
      if (pathname.endsWith('/scope-preview')) {
        if (model.previewFailure) return route.fulfill({ status: 409, json: { error: 'tool_scope_changed' } })
        model.previews.push(body)
        model.confirmation = 'synthetic-scope-confirmation-' + model.previews.length
        const chosen = body.tool_ids as string[]
        const catalog = model.candidates || existing.tools
        const selected = chosen.map(id => catalog.find(tool => tool.id === id)!)
        return route.fulfill({ json: { confirmation: model.confirmation, confirmation_expires_at: now + 600, ...body,
          added: selected.filter(tool => !existing.tools.some(old => old.id === tool.id && old.snapshot === tool.snapshot && old.server_id === tool.server_id && old.access === tool.access)).map(tool => tool.id),
          removed: existing.tools.filter(tool => !chosen.includes(tool.id)).map(tool => tool.id), previous_tools: existing.tools, tools: selected } })
      }
      if (pathname.endsWith('/scope') && (model.writeFailure || body.confirmation !== model.confirmation)) return route.fulfill({ status: 409, json: { error: 'revision_conflict' } })
      model.writes.push({ path: pathname, body })
      const catalog = model.candidates || existing.tools
      const next = pathname.endsWith("/revoke") ? { ...existing, state: "revoked", revision: existing.revision + 1 } : { ...existing, rate_per_minute: Number(body.rate_per_minute), concurrency: Number(body.concurrency), expires_at: Number(body.expires_at), tools: catalog.filter(tool => (body.tool_ids as string[]).includes(tool.id)), revision: existing.revision + 1 }
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

for (const locale of ["en-US", "zh-CN"] as const) {
  const zh = locale === "zh-CN"
  test(`OAuth bulk selection replaces the full current catalog across filters and pages ${locale} @large-data`, async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 })
    const model = await setup(page, locale, [grant(1)])
    model.candidates = tools
    await page.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整授权范围" : "Adjust authorization scope", exact: true })
    await expect(editor.getByText(zh ? "正在读取本人可授权范围…" : "Loading your available scope…", { exact: true })).toHaveCount(0)
    await editor.locator(".ant-pagination-next").click()
    await editor.getByRole("textbox", { name: zh ? "搜索当前范围内的工具" : "Search tools in the current scope", exact: true }).fill("synthetic-tool-4999")
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(1)
    await editor.getByRole("radio", { name: zh ? "仅选全部当前只读" : "All current read-only tools", exact: true }).check()
    await expect(editor.locator(".oauth-selection [role=status]")).toContainText("2500 / 5000")
    await expect(editor.locator('tr[data-row-key="synthetic-tool-4999"]').getByRole("checkbox")).not.toBeChecked()
    const update = editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true })
    await update.click()
    const review = page.getByRole("alertdialog")
    expect(model.previews[0].tool_ids).toEqual(tools.filter(tool => tool.access === "read").map(tool => tool.id))
    expect(model.writes).toHaveLength(0)
    await review.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await editor.getByRole("radio", { name: zh ? "选中全部当前工具" : "All current tools", exact: true }).check()
    await expect(editor.locator(".oauth-selection [role=status]")).toContainText("5000 / 5000")
    await editor.getByRole("radio", { name: zh ? "自定义" : "Custom", exact: true }).check()
    await update.click()
    expect(model.previews[1].tool_ids).toEqual(tools.map(tool => tool.id))
    await review.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    expect(model.writes).toHaveLength(0)
  })

  test(`OAuth MCP group checkbox spans hidden tools and group pages ${locale} @large-data`, async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 })
    const model = await setup(page, locale, [grant(1)])
    model.candidates = tools
    await page.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整授权范围" : "Adjust authorization scope", exact: true })
    await editor.getByRole("button", { name: zh ? "清空选择" : "Clear selection", exact: true }).click()
    await editor.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    await expect(editor.getByText("1–15 / 100", { exact: true })).toBeVisible()
    await editor.locator(".ant-pagination-next").click()
    const row = editor.locator("tr[data-row-key]").first()
    const groupId = await row.getAttribute("data-row-key")
    await row.getByRole("checkbox").check()
    await expect(row).toContainText("50 / 50")
    await row.getByRole("button", { name: zh ? "查看工具" : "View tools", exact: true }).click()
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(50)
    await editor.getByRole("textbox", { name: zh ? "搜索当前范围内的工具" : "Search tools in the current scope", exact: true }).fill(tools.find(tool => tool.server_id === groupId)!.id)
    await editor.locator("tr[data-row-key]").getByRole("checkbox").uncheck()
    await editor.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    const group = editor.locator(`tr[data-row-key="${groupId}"]`)
    await expect(group).toContainText("49 / 50")
    await expect(group.getByRole("checkbox")).toHaveJSProperty("indeterminate", true)
    await group.getByRole("checkbox").check()
    await expect(group).toContainText("50 / 50")
    await editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true }).click()
    expect(model.previews[0].tool_ids).toEqual(expect.arrayContaining(tools.filter(tool => tool.server_id === groupId).map(tool => tool.id)))
    expect(model.previews[0].tool_ids).toHaveLength(50)
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await group.getByRole("checkbox").uncheck()
    await expect(group).toContainText("0 / 50")
    expect(model.writes).toHaveLength(0)
  })

  test(`OAuth refresh retains quota and unavailable draft without selecting later services ${locale}`, async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 })
    const original = { ...grant(1), tools: tools.slice(0, 2), effective_tool_count: 2 }
    const model = await setup(page, locale, [original])
    await page.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整授权范围" : "Adjust authorization scope", exact: true })
    const refresh = editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true })
    await expect(refresh).toBeEnabled()
    await editor.getByRole("radio", { name: zh ? "选中全部当前工具" : "All current tools", exact: true }).check()
    await editor.getByRole("spinbutton", { name: zh ? "每分钟调用上限" : "Calls per minute", exact: true }).fill("30")
    model.scopeFailure = true
    await refresh.click()
    await expect(editor.getByRole("alert")).toBeVisible()
    await expect(editor.locator(".oauth-selection [role=status]")).toContainText(zh ? "草稿保留 2 个工具选择；可授权目录尚未读取" : "2 draft tool selections retained; the available catalog has not been loaded")
    await expect(editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole("checkbox")).toBeChecked()
    model.scopeFailure = false
    const later = { ...tools[1], id: "synthetic-later-tool", server_id: "synthetic-later-mcp", server_name: "Later MCP" }
    model.candidates = [tools[0], later]
    await refresh.click()
    await expect(editor.locator(".oauth-unavailable-selection")).toContainText(zh ? "草稿中 1 项当前不可授权" : "1 draft selection is unavailable")
    await expect(editor.getByRole("radio", { name: zh ? "自定义" : "Custom", exact: true })).toBeChecked()
    await expect(editor.getByRole("spinbutton", { name: zh ? "每分钟调用上限" : "Calls per minute", exact: true })).toHaveValue("30")
    await expect(editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole("checkbox")).toBeChecked()
    await expect(editor.locator('tr[data-row-key="synthetic-later-tool"]').getByRole("checkbox")).not.toBeChecked()
    const update = editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true })
    await expect(update).toBeDisabled()
    await editor.getByRole("button", { name: zh ? "移除不可授权选择" : "Remove unavailable selections", exact: true }).click()
    await expect(editor.locator('tr[data-row-key="synthetic-tool-1"]')).toHaveCount(0)
    await update.click()
    expect(model.previews[0].tool_ids).toEqual([tools[0].id])
    expect(model.previews[0].rate_per_minute).toBe(30)
    expect(model.optionsReads).toBe(3)
    expect(model.writes).toHaveLength(0)
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
  })

  test(`OAuth owner-visible exclusions provide classification review without a mutation ${locale}`, async ({ page }) => {
    const model = await setup(page, locale, [grant(1)])
    model.unavailable = [{ server_id: "synthetic-plane", server_name: "Synthetic Plane MCP", reasons: [{ code: "classification_not_published", count: 30 }] }]
    model.canReview = true
    await page.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整授权范围" : "Adjust authorization scope", exact: true })
    await editor.getByRole("button", { name: zh ? "查看不可授权原因" : "Why unavailable", exact: true }).click()
    const reasons = page.getByRole("dialog", { name: zh ? "不可授权原因" : "Unavailable scope reasons", exact: true })
    await expect(reasons).toContainText("Synthetic Plane MCP")
    await expect(reasons).toContainText(zh ? "分类尚未发布；需审核并发布 · 30" : "Classification is unpublished; review and publish it · 30")
    const review = reasons.getByRole("link", { name: zh ? "在新页审核工具分类" : "Review tool classifications in a new tab", exact: true })
    await expect(review).toHaveAttribute("href", "#/toolClassifications")
    await expect(review).toHaveAttribute("target", "_blank")
    expect(model.writes).toHaveLength(0)
    expect(model.previews).toHaveLength(0)
    await page.keyboard.press("Escape")
    await expect(reasons).toHaveCount(0)
    await expect(editor).toBeVisible()
  })
}

const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) {
  test(`OAuth bulk controls and unavailable draft fit desktop ${locale}-${size.width}x${size.height}`, async ({ page }, testInfo) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize(size)
    const model = await setup(page, locale, [grant(1)])
    model.candidates = tools.slice(1)
    model.unavailable = [{ server_id: "synthetic-plane", server_name: "Synthetic Plane MCP", reasons: [{ code: "classification_not_published", count: 30 }] }]
    await page.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整授权范围" : "Adjust authorization scope", exact: true })
    await expect(editor.getByRole("button", { name: zh ? "移除不可授权选择" : "Remove unavailable selections", exact: true })).toBeVisible()
    await editor.getByRole("radio", { name: zh ? "MCP 整组" : "MCP groups", exact: true }).check()
    await editor.evaluate(async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)) })
    await expect(page.locator(".console-header").getByText(`v${sourceVersion}`, { exact: true })).toBeVisible()
    const controls = [
      editor.getByRole("radio", { name: zh ? "仅选全部当前只读" : "All current read-only tools", exact: true }),
      editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }),
      editor.getByRole("button", { name: zh ? "查看不可授权原因" : "Why unavailable", exact: true }),
      editor.getByRole("button", { name: zh ? "查看范围与授权规则" : "Scope details", exact: true }),
      editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true }),
      editor.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).filter({ hasNot: page.locator("svg") }),
      editor.locator(".ant-pagination-next"),
    ]
    for (const control of controls) await expectInViewportAndUnobscured(control)
    const layout = await editor.evaluate(element => {
      const body = element.querySelector(".oauth-grant-scope-body")!
      const labels = Array.from(element.querySelectorAll(".oauth-grant-limits label")).map(label => {
        const range = document.createRange(); range.selectNode(label.firstChild!)
        const text = range.getBoundingClientRect()
        const control = label.querySelector("input")!.getBoundingClientRect()
        return { oneLine: range.getClientRects().length === 1, sameRow: Math.abs((text.top + text.bottom) / 2 - (control.top + control.bottom) / 2) < 3 }
      })
      const table = element.querySelector(".ant-table-body")!.getBoundingClientRect()
      const fullyVisibleRows = Array.from(element.querySelectorAll(".ant-table-body tr[data-row-key]")).filter(row => { const rect = row.getBoundingClientRect(); return rect.height > 0 && rect.top >= table.top - 1 && rect.bottom <= table.bottom + 1 }).length
      const sameRow = (items: Element[]) => {
        const centers = items.map(item => { const rect = item.getBoundingClientRect(); return rect.top + rect.height / 2 })
        return Math.max(...centers) - Math.min(...centers) < 3
      }
      const bulk = element.querySelector(".oauth-bulk-selection")!
      const bulkSameRow = sameRow([bulk.querySelector(".oauth-bulk-label")!, ...Array.from(bulk.querySelectorAll(".ant-radio-wrapper")), bulk.querySelector(":scope > .ant-btn")!])
      const filtersSameRow = sameRow(Array.from(element.querySelector(".oauth-filters")!.children))
      const toolbarSameRow = sameRow(Array.from(element.querySelector(".oauth-selection")!.children))
      const footer = element.querySelector(":scope > .border-t")!.getBoundingClientRect()
      return { labels, overflow: body.scrollHeight - body.clientHeight, pageWidth: document.documentElement.scrollWidth, dialog: element.getBoundingClientRect().toJSON(), tableHeight: table.height, fullyVisibleRows, bulkSameRow, filtersSameRow, toolbarSameRow, footerHeight: footer.height }
    })
    expect(layout.labels.every(label => label.oneLine && label.sameRow)).toBe(true)
    expect(layout.overflow).toBe(0)
    expect(layout.pageWidth).toBeLessThanOrEqual(size.width)
    expect(layout.dialog.top).toBeGreaterThanOrEqual(32)
    expect(layout.dialog.bottom).toBeLessThanOrEqual(size.height - 32)
    expect(layout.tableHeight).toBeGreaterThanOrEqual(240)
    expect(layout.fullyVisibleRows).toBeGreaterThanOrEqual(6)
    expect(layout.bulkSameRow && layout.filtersSameRow && layout.toolbarSameRow).toBe(true)
    expect(layout.footerHeight).toBeLessThanOrEqual(56)
    writeFileSync(testInfo.outputPath("oauth-bulk-layout.json"), JSON.stringify({ locale, viewport: size, sourceVersion, ...layout }, null, 2))
    await page.screenshot({ path: testInfo.outputPath("oauth-bulk-draft.png"), animations: "disabled" })
    await editor.getByRole("button", { name: zh ? "移除不可授权选择" : "Remove unavailable selections", exact: true }).click()
    await expect(editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true })).toBeEnabled()
    await page.screenshot({ path: testInfo.outputPath("oauth-bulk-edit.png"), animations: "disabled" })
    expect(model.writes).toHaveLength(0)
  })
}
for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) for (const theme of ["light", "dark"]) {
  const suffix = `${locale}-${theme}-${size.width}x${size.height}`
  test(`grant reduction has one main scroll and single-line MCP IDs ${suffix}`, async ({ page }, testInfo) => {
    const zh = locale === 'zh-CN'
    await page.setViewportSize(size)
    const record = grant(1, 'active', true)
    record.client_name = 'Synthetic long client name '.repeat(5)
    record.tools = record.tools.map(tool => ({ ...tool,
      name: tool.name + ' · Synthetic long tool name '.repeat(4),
      server_name: `Long synthetic MCP name ${tool.server_id.split('-').at(-1)}` + ' · Presentation fixture '.repeat(3),
    }))
    const model = await setup(page, locale, [record], theme)
    const trigger = page.getByRole('button', { name: zh ? '调整授权范围' : 'Adjust scope', exact: true })
    await trigger.click()
    const editor = page.getByRole('dialog', { name: zh ? '调整授权范围' : 'Adjust authorization scope', exact: true })
    await expect(editor).toHaveCSS('opacity', '1')
    await expect(editor.getByText(zh ? '正在读取本人可授权范围…' : 'Loading your available scope…', { exact: true })).toHaveCount(0)
    const body = editor.locator('.oauth-grant-scope-body')
    const viewport = editor.locator('.ant-table-body')
    const header = editor.locator('.ant-table-header')
    const pager = editor.locator('.ant-pagination')
    const expiry = editor.getByRole('textbox', { name: zh ? '到期时间（UTC）' : 'Expiry (UTC)', exact: true })
    const rate = editor.getByRole('spinbutton', { name: zh ? '每分钟调用上限' : 'Calls per minute', exact: true })
    const close = editor.getByRole('button', { name: zh ? '关闭' : 'Close', exact: true }).filter({ hasNot: page.locator('svg') })
    await expectInViewportAndUnobscured(expiry)
    await expectInViewportAndUnobscured(rate)
    await expectInViewportAndUnobscured(pager.locator('.ant-pagination-next'))
    await expectInViewportAndUnobscured(close)
    const fixedBefore = await Promise.all([header.boundingBox(), pager.boundingBox(), expiry.boundingBox(), rate.boundingBox()])
    expect(await body.evaluate(e => e.scrollHeight - e.clientHeight)).toBe(0)
    expect(await viewport.evaluate(e => getComputedStyle(e).overscrollBehaviorY)).toBe('contain')
    await viewport.hover()
    await page.mouse.wheel(0, 10000)
    await expect.poll(() => viewport.evaluate(e => e.scrollTop)).toBeGreaterThan(0)
    await page.mouse.wheel(0, 10000)
    expect(await body.evaluate(e => e.scrollTop)).toBe(0)
    expect(await page.evaluate(() => document.scrollingElement!.scrollTop)).toBe(0)
    expect(await Promise.all([header.boundingBox(), pager.boundingBox(), expiry.boundingBox(), rate.boundingBox()])).toEqual(fixedBefore)
    await page.screenshot({ path: testInfo.outputPath('grant-single-scroll.png'), animations: 'disabled' })
    await editor.getByRole('textbox', { name: zh ? '搜索当前范围内的工具' : 'Search tools in the current scope', exact: true }).fill('synthetic-tool-4999')
    await expect(editor.locator('.ant-table-tbody tr[data-row-key]')).toHaveCount(1)
    await expect(editor.getByText('synthetic-tool-4999', { exact: true })).toBeVisible()
    await editor.getByRole('button', { name: zh ? '重置筛选' : 'Reset filters', exact: true }).click()
    const select = editor.getByRole('combobox', { name: zh ? '按 MCP 筛选' : 'Filter by MCP', exact: true })
    await select.fill('Long synthetic MCP name 99')
    const dropdown = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
    const option = dropdown.locator('.ant-select-item-option-content')
    await expect(option).toHaveText(['synthetic-mcp-99'])
    await page.screenshot({ path: testInfo.outputPath('grant-single-line-mcp-filter.png'), animations: 'disabled' })
    await option.click()
    await expect(editor.locator('.oauth-filters .ant-select').getByText('synthetic-mcp-99', { exact: true })).toBeVisible()
    await expect(editor.locator('.ant-table-tbody tr[data-row-key]')).toHaveCount(50)
    await editor.getByRole('button', { name: zh ? '重置筛选' : 'Reset filters', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(editor).toHaveCount(0)
    expect(model.writes).toHaveLength(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width)
  })
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
    await expect(revoked.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true })).toHaveCount(0)
    await expect(revoked.getByRole("button", { name: zh ? "撤销" : "Revoke", exact: true })).toHaveCount(0)
    await capture(page, `grants-all-${suffix}`)
    const trigger = revoked.getByRole("button", { name: zh ? "112 个工具" : "112 tools", exact: true })
    await trigger.click()
    const details = page.getByRole("dialog", { name: zh ? "授权详情" : "Grant details", exact: true })
    // Measure the settled dialog, rather than a fractional enter-animation frame.
    await details.evaluate(async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)) })
    await expect(details.getByLabel("Grant ID", { exact: true })).toHaveValue(grant(2).id)
    await expect(details.getByRole("textbox", { name: zh ? "搜索当前范围内的工具" : "Search tools in the current scope", exact: true })).toBeEnabled()
    await expect(details.getByRole("checkbox")).toHaveCount(0)
    await expect(details.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true })).toHaveCount(0)
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

for (const locale of ['en-US', 'zh-CN'] as const) for (const mixed of [false, true]) {
  test(`Gate confirmation updates the existing connection ${locale} mixed=${mixed}`, async ({ page }) => {
    const zh = locale === 'zh-CN'
    const original = { ...grant(1), tools: [tools[0]], effective_tool_count: 1 }
    const model = await setup(page, locale, [original])
    model.candidates = tools.slice(0, 2)
    model.familyScopes = ['tools.read']
    await page.getByRole('button', { name: zh ? '调整授权范围' : 'Adjust scope', exact: true }).click()
    const editor = page.getByRole('dialog', { name: zh ? '调整授权范围' : 'Adjust authorization scope', exact: true })
    const scopeDetails = editor.getByRole('button', { name: zh ? '查看范围与授权规则' : 'Scope details', exact: true })
    await scopeDetails.click()
    await expect(editor.locator('.oauth-scope-info')).toContainText(zh ? '仅有 tools.read 的令牌不能调用新增写工具' : 'a tools.read-only token cannot invoke newly added write tools')
    await expect(scopeDetails).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Escape')
    await expect(scopeDetails).toHaveAttribute('aria-expanded', 'false')
    await expect(editor).toBeVisible()
    expect(model.previews).toHaveLength(0)
    expect(model.writes).toHaveLength(0)
    await editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole('checkbox').check()
    if (mixed) await editor.locator('tr[data-row-key="synthetic-tool-0"]').getByRole('checkbox').uncheck()
    // Closing the read-only disclosure must retain an unsaved selection as well.
    await scopeDetails.click()
    await page.keyboard.press('Escape')
    await expect(scopeDetails).toHaveAttribute('aria-expanded', 'false')
    await expect(editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole('checkbox')).toBeChecked()
    if (mixed) await expect(editor.locator('tr[data-row-key="synthetic-tool-0"]').getByRole('checkbox')).not.toBeChecked()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    const update = editor.getByRole('button', { name: zh ? '核对并更新连接' : 'Review connection update', exact: true })
    await update.click()
    const review = page.getByRole('alertdialog', { name: zh ? '确认更新当前连接？' : 'Update this connection?', exact: true })
    await expect(review).toContainText('synthetic-tool-1')
    await expect(review).toContainText(zh ? '写入' : 'Write')
    await expect(review).toContainText(zh ? '无需客户端再次 OAuth' : 'without another client OAuth flow')
    if (mixed) await expect(review).toContainText('synthetic-tool-0')
    expect(model.writes).toHaveLength(0)
    expect(model.records).toEqual([original])
    await review.getByRole('button', { name: zh ? '取消' : 'Cancel', exact: true }).click()
    expect(model.writes).toHaveLength(0)
    await update.click()
    await review.getByRole('button', { name: zh ? '确认并更新' : 'Confirm update', exact: true }).click()
    await expect(editor).toHaveCount(0)
    expect(model.writes).toHaveLength(1)
    expect(model.writes[0].path).toMatch(/\/scope$/)
    expect(model.writes[0].body.tool_ids).toEqual(mixed ? ['synthetic-tool-1'] : ['synthetic-tool-0', 'synthetic-tool-1'])
    expect(model.writes[0].body.confirmation).toBe(model.confirmation)
    expect(model.records[0].id).toBe(original.id)
    expect(model.records[0].scopes).toEqual(original.scopes)
    expect(model.records[0].revision).toBe(2)
    expect(model.records[0].tools.map(tool => tool.id)).toEqual(model.writes[0].body.tool_ids)
    await expect(page.getByText(zh ? '连接工具范围已更新；下一次请求按新范围检查。' : 'Connection tools updated; the next request uses the new scope.', { exact: true })).toBeVisible()
  })
}

test('late available-scope read cannot reopen a closed editor', async ({ page }) => {
  const model = await setup(page, 'en-US', [grant(1)])
  let release!: () => void
  let arrived!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const received = new Promise<void>(resolve => { arrived = resolve })
  await page.route('**/scope-options', async route => {
    arrived(); await pending
    await route.fulfill({ json: { csrf: 'synthetic-csrf-' + 'a'.repeat(32), expires_at: now + 600, grant_revision: 1, tools, scopes: ["tools.read", "tools.invoke"], effective_scopes: ["tools.read", "tools.invoke"], family_scope_limits: [] } })
  })
  await page.getByRole('button', { name: 'Adjust scope', exact: true }).click()
  await received
  await expect(page.getByText('Loading your available scope…', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const response = page.waitForResponse(response => response.url().endsWith('/scope-options'))
  release(); await response
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(model.writes).toHaveLength(0)
})

test('available-scope failure remains visible and retries only the read', async ({ page }) => {
  const model = await setup(page, 'en-US', [grant(1)])
  model.scopeFailure = true
  await page.getByRole('button', { name: 'Adjust scope', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Adjust authorization scope', exact: true })
  await expect(editor.getByRole('alert')).toBeVisible()
  expect(model.writes).toHaveLength(0)
  model.scopeFailure = false
  await editor.getByRole('button', { name: 'Refresh available scope', exact: true }).click()
  await expect(editor.getByRole('alert')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(editor).toHaveCount(0)
  expect(model.writes).toHaveLength(0)
})

for (const locale of ['en-US', 'zh-CN'] as const) for (const stage of ['preview', 'save'] as const) {
  test(`scope ${stage} failure keeps the selection and requires renewed review ${locale}`, async ({ page }) => {
    const zh = locale === 'zh-CN'
    const model = await setup(page, locale, [{ ...grant(1), tools: [tools[0]] }])
    model.candidates = tools.slice(0, 2)
    model.previewFailure = stage === 'preview'; model.writeFailure = stage === 'save'
    await page.getByRole('button', { name: zh ? '调整授权范围' : 'Adjust scope', exact: true }).click()
    const editor = page.getByRole('dialog', { name: zh ? '调整授权范围' : 'Adjust authorization scope', exact: true })
    await editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole('checkbox').check()
    const review = editor.getByRole('button', { name: zh ? '核对并更新连接' : 'Review connection update', exact: true })
    await review.click()
    if (stage === 'save') await page.getByRole('alertdialog').getByRole('button', { name: zh ? '确认并更新' : 'Confirm update', exact: true }).click()
    await expect(editor.getByRole('alert')).toBeVisible()
    await expect(editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole('checkbox')).toBeChecked()
    expect(model.writes).toHaveLength(0)
    model.previewFailure = false; model.writeFailure = false
    await editor.getByRole('button', { name: zh ? '刷新可授权范围' : 'Refresh available scope', exact: true }).click()
    await expect(editor.getByRole('alert')).toHaveCount(0)
    expect(model.writes).toHaveLength(0)
    await review.click()
    await page.getByRole('alertdialog').getByRole('button', { name: zh ? '确认并更新' : 'Confirm update', exact: true }).click()
    await expect(editor).toHaveCount(0)
    expect(model.writes).toHaveLength(1)
  })
}

test('pending scope preview blocks duplicate submission, keyboard close and mode switch', async ({ page }) => {
  const model = await setup(page, 'en-US', [{ ...grant(1), tools: [tools[0]] }])
  model.candidates = tools.slice(0, 2)
  let release!: () => void
  let arrived!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const received = new Promise<void>(resolve => { arrived = resolve })
  await page.route('**/scope-preview', async route => { arrived(); await pending; await route.fallback() })
  await page.getByRole('button', { name: 'Adjust scope', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Adjust authorization scope', exact: true })
  await editor.locator('tr[data-row-key="synthetic-tool-1"]').getByRole('checkbox').check()
  await editor.getByRole('button', { name: 'Review connection update', exact: true }).click()
  await received
  await page.keyboard.press('Escape')
  await expect(editor).toHaveCount(1)
  await expect(editor.getByRole('button', { name: 'Review connection update', exact: true })).toBeDisabled()
  await expect(page.getByRole('tab', { name: 'External identity provider', exact: true, includeHidden: true })).toHaveAttribute('aria-disabled', 'true')
  release()
  const confirmation = page.getByRole('alertdialog', { name: 'Update this connection?', exact: true })
  await expect(confirmation).toBeVisible()
  expect(model.previews).toHaveLength(1)
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(model.writes).toHaveLength(0)
})

test('a late scope response cannot overwrite another grant editor', async ({ page }) => {
  const second = { ...grant(2), client_name: 'Synthetic second client' }
  const model = await setup(page, 'en-US', [grant(1), second])
  let release!: () => void
  let arrived!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const received = new Promise<void>(resolve => { arrived = resolve })
  await page.route(`**/${grant(1).id}/scope-options`, async route => {
    arrived(); await pending
    await route.fulfill({ json: { csrf: 'synthetic-stale-csrf-' + 'a'.repeat(32), expires_at: now + 600, grant_revision: 99,
      tools: [...tools, { ...tools[0], id: 'synthetic-foreign-tool' }], scopes: ['tools.read'], effective_scopes: ['tools.read'], family_scope_limits: [] } })
  })
  await page.locator(`[data-row-key="${grant(1).id}"]`).getByRole('button', { name: 'Adjust scope', exact: true }).click()
  await received
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Adjust authorization scope', exact: true })).toHaveCount(0)
  await page.locator(`[data-row-key="${second.id}"]`).getByRole('button', { name: 'Adjust scope', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Adjust authorization scope', exact: true })
  await expect(editor.getByText('Loading your available scope…', { exact: true })).toHaveCount(0)
  await expect(editor).toContainText(second.client_name)
  const response = page.waitForResponse(response => response.url().endsWith(`/${grant(1).id}/scope-options`))
  release(); await response
  await expect(editor.getByRole('alert')).toHaveCount(0)
  await expect(editor).toContainText(second.client_name)
  await editor.getByRole('textbox', { name: 'Search tools in the current scope', exact: true }).fill('synthetic-foreign-tool')
  await expect(editor.locator('tr[data-row-key]')).toHaveCount(0)
  expect(model.writes).toHaveLength(0)
})

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
    await expect(rows(page).getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true })).toHaveCount(0)
    await expect(rows(page).getByRole("button", { name: zh ? "撤销" : "Revoke", exact: true })).toHaveCount(0)
    await expect(rows(page).first().locator("td").first()).not.toContainText("UTC")
  })
  test(`OAuth reduction and revocation keep explicit confirmations ${locale} @permissions`, async ({ page }) => {
    const model = await setup(page, locale, [grant(1)])
    await page.getByRole("button", { name: zh ? "调整授权范围" : "Adjust scope", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整授权范围" : "Adjust authorization scope", exact: true })
    await editor.getByRole("spinbutton", { name: zh ? "每分钟调用上限" : "Calls per minute", exact: true }).fill("30")
    await editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true }).click()
    const reduction = page.getByRole("alertdialog", { name: zh ? "确认更新当前连接？" : "Update this connection?", exact: true })
    expect(model.writes).toHaveLength(0)
    await reduction.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await editor.getByRole("button", { name: zh ? "核对并更新连接" : "Review connection update", exact: true }).click()
    await reduction.getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
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

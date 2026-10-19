import { expect, test, type Locator, type Page } from "@playwright/test"
import { createHash } from "node:crypto"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expectInViewportAndUnobscured } from "./helpers"
import type { OAuthClient, OAuthConfig, OAuthGrant, OAuthTool } from "../src/features/external-connections/oauth-api"

const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static/console")
const sourceVersion = readFileSync(path.join(assets, "../../_version.py"), "utf8").match(/^__version__\s*=\s*["']([^"']+)["']/m)![1]
const bundleSha = createHash("sha256").update(readFileSync(path.join(assets, "index.html"))).digest("hex")
type Locale = "en-US" | "zh-CN"
const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
// Compact table contract: 32px control + project-wide 8px compact padding on each side + 1px border.
// Capture actual control/cell/token metrics before these assertions for CSS review.
const compactClientRowHeight = 32 + 8 + 8 + 1
const now = Math.floor(Date.now() / 1000)
async function fixture(page: Page, locale: Locale, theme = "light", count = 61) {
  const tools: OAuthTool[] = Array.from({ length: 137 }, (_, index) => ({ id: `mcp.synthetic-density-${Math.floor(index / 23)}.tool-${index}`, name: index < 2 ? locale === "zh-CN" ? "项目详情" : "Project details" : locale === "zh-CN" ? `项目工具 ${index}` : `Project tool ${index}`, server_id: `synthetic-density-${Math.floor(index / 23)}`, server_name: `Synthetic MCP ${Math.floor(index / 23)}`, access: index % 2 ? "write" : "read", snapshot: "synthetic-density", currently_authorized: true }))
  const grant: OAuthGrant = { id: "synthetic-density-grant", client_id: "synthetic-density-client", client_name: "Synthetic project client", resource: "https://gate.example.test/mcp", scopes: ["tools.read", "tools.invoke"], tools, created_at: now - 60, expires_at: now + 86400, state: "active", rate_per_minute: 30, concurrency: 2, revision: 1, scope_currently_authorized: true, effective_tool_count: 137 }
  const config: OAuthConfig = { enabled: true, issuer: "https://gate.example.test", resource: "https://gate.example.test/mcp", revision: 1, metadata_url: "https://gate.example.test/.well-known/oauth-authorization-server", authorization_endpoint: "https://gate.example.test/oauth/authorize", token_endpoint: "https://gate.example.test/oauth/token", jwks_uri: "https://gate.example.test/oauth/jwks", signing_keys: [{ kid: "synthetic-active", active: true, retire_at: null }] }
  const clients: OAuthClient[] = Array.from({ length: count }, (_, index) => ({ id: `lgc_synthetic_density_client_${String(index).padStart(3, "0")}`, name: `Synthetic client ${index}`, scopes: ["tools.read", "tools.invoke"], resources: ["business"], redirect_uris: ["https://client.example.test/callback"], enabled: index % 4 !== 3, revision: 1, created_at: now - 60 }))
  const model = { grant, config, clients, clientWriteFailure: false, reads: 0, writes: [] as { path: string; body: Record<string, unknown> }[] }
  await page.addInitScript(({ locale, theme }) => { localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme); Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => undefined } }) }, { locale, theme })
  await page.route("**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(assets, "index.html")) }))
  await page.route("**/assets/**", route => { const name = path.basename(new URL(route.request().url()).pathname); return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(assets, "assets", name)) }) })
  await page.route("**/healthz", route => route.fulfill({ json: { version: sourceVersion } }))
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname, method = route.request().method()
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-density-owner", username: "synthetic-density-owner", display_name: "Synthetic owner", status: "active", role: "custom", roles: ["custom"], permissions: ["console.view", "credentials.manage.self", "external_connections.manage"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/config" && method === "GET") return route.fulfill({ json: model.config })
    if (pathname === "/v1/auth/oauth/clients") return route.fulfill({ json: { clients: model.clients } })
    if (pathname === "/v1/auth/oauth/management/config") return route.fulfill({ json: { enabled: false, active: false, resource: "https://gate.example.test/mcp/manage", revision: 1 } })
    if (pathname === "/v1/auth/tokens" && method === "GET") return route.fulfill({ json: { tokens: [] } })
    if (pathname === "/v1/auth/external-grants" && method === "GET") return route.fulfill({ json: { grants: [], connection_ready: true, activation_errors: [], allowed_client_ids: [] } })
    if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [model.grant] } })
    if (pathname.endsWith("/scope-options")) { model.reads++; return route.fulfill({ json: { csrf: "synthetic-density-csrf-" + "s".repeat(32), expires_at: now + 600, grant_revision: model.grant.revision, tools: model.grant.tools, scopes: model.grant.scopes, effective_scopes: model.grant.scopes, family_scope_limits: [{ scopes: ["tools.read"], count: 1 }], unavailable_servers: [], can_review_classifications: false } }) }
    if (method !== "GET") model.writes.push({ path: pathname, body: route.request().postDataJSON() })
    if (method === "PATCH" && pathname.startsWith("/v1/auth/oauth/clients/")) {
      if (model.clientWriteFailure) return route.fulfill({ status: 409, json: { error: "revision_conflict" } })
      const body = route.request().postDataJSON(), client = model.clients.find(client => pathname.endsWith(`/${client.id}`))!
      const next = { ...client, enabled: body.enabled, revision: client.revision + 1 }
      model.clients = model.clients.map(client => client.id === next.id ? next : client)
      return route.fulfill({ json: { client: next, ...(body.rotate_secret ? { client_secret: "synthetic-density-rotated-secret" } : {}) } })
    }
    return route.fulfill({ status: 404, json: { error: "unmocked_synthetic_request" } })
  })
  return model
}
function moreActions(row: Locator, zh: boolean, clientName: string) {
  return row.getByRole("button", { name: `${zh ? "更多操作" : "More actions"} ${clientName}`, exact: true })
}
async function clientAction(page: Page, row: Locator, zh: boolean, clientName: string, action: string) {
  await moreActions(row, zh, clientName).click()
  await page.getByRole("menu").getByRole("menuitem", { name: action, exact: true }).click()
}
async function expectClientActionEnabled(page: Page, row: Locator, zh: boolean, clientName: string, action: string) {
  const trigger = moreActions(row, zh, clientName)
  await trigger.click()
  await expect(page.getByRole("menu").getByRole("menuitem", { name: action, exact: true })).toBeEnabled()
  await page.keyboard.press("Escape")
  await expect(trigger).toBeFocused()
}
async function scope(page: Page, locale: Locale, expected = 137) {
  await page.goto("/console/#/myConnections")
  await page.getByRole("radiogroup", { name: locale === "zh-CN" ? "授权方式" : "Authorization type", exact: true }).getByRole("radio", { name: "Gate OAuth", exact: true }).check()
  await page.locator('tr[data-row-key="builtin:synthetic-density-grant"]').getByRole("button", { name: locale === "zh-CN" ? "调整授权" : "Adjust", exact: true }).click()
  const editor = page.getByRole("dialog", { name: locale === "zh-CN" ? "调整授权范围" : "Adjust authorization scope", exact: true })
  await expect(editor.locator(".oauth-selection")).toContainText(`${expected} / ${expected}`)
  await editor.evaluate(async element => { await Promise.allSettled(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished)) })
  return editor
}
async function capture(page: Page, name: string, metrics: unknown) {
  const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" })
  writeFileSync(path.join(directory, `${name}.json`), JSON.stringify({ source_sha: process.env.GATE_UI_SOURCE_SHA || null, bundle_sha256: bundleSha, allOAuthApisMocked: true, fixture_tools: 137, fixture_mcps: 6, viewport: page.viewportSize(), ...metrics as object }, null, 2) + "\n")
}

for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) {
  const zh = locale === "zh-CN"
  test(`scope density ${locale} ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size)
    const model = await fixture(page, locale)
    const editor = await scope(page, locale)
    await expect(editor.locator(".oauth-scope-rule-summary")).toHaveText(zh ? "有效" : "Active")
    await expect(editor.locator(".oauth-scope-rule-summary")).not.toContainText("137")
    const body = editor.locator(".oauth-grant-edit-body"), tools = editor.locator(".oauth-tools")
    const limits = editor.locator(".authorization-quota-settings")
    const quotaToggle = limits.locator('.ant-collapse-header[role="button"]')
    await expect(quotaToggle).toHaveAttribute("aria-expanded", "false")
    await expect(limits.locator(".authorization-quota-values")).toHaveText(zh ? "30 次/分钟 · 并发 2" : "30/min · 2 concurrent")
    await quotaToggle.click()
    await expect(limits.locator(".authorization-field")).toHaveCount(2)
    const rate = limits.getByRole("spinbutton", { name: zh ? "每分钟调用上限" : "Calls per minute", exact: true })
    await expect(rate).toHaveValue("30")
    await expect(limits.getByRole("spinbutton", { name: zh ? "并发上限" : "Concurrent calls", exact: true })).toHaveValue("2")
    // Enable Save so the footer's hit testing also verifies a usable control.
    await rate.fill("31")
    await editor.evaluate(async element => { await Promise.allSettled(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished)) })
    await body.evaluate(element => { element.scrollTop = 0 })
    const labelMetrics = await limits.evaluate(element => Array.from(element.querySelectorAll(".authorization-field")).map(field => {
      const label = field.querySelector("label")!, input = field.querySelector("input")!
      const range = document.createRange(); range.selectNodeContents(label)
      const text = range.getBoundingClientRect(), control = input.getBoundingClientRect()
      return { label: label.textContent, lines: range.getClientRects().length, centerOffset: Math.abs((text.top + text.bottom - control.top - control.bottom) / 2), labelRight: text.right, controlLeft: control.left, controlWidth: control.width }
    }))
    await capture(page, `scope-limits-${locale}-${size.width}x${size.height}`, { labels: labelMetrics })
    expect(labelMetrics).toHaveLength(2)
    expect(labelMetrics.every(label => label.lines === 1 && label.centerOffset < 3 && label.labelRight < label.controlLeft && label.controlWidth > 0)).toBe(true)
    const save = editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true })
    const cancel = editor.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true })
    const refresh = body.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true }).first()
    await expect(save).toBeEnabled()
    for (const control of [save, cancel, refresh]) { await expectInViewportAndUnobscured(control); await control.click({ trial: true }) }
    const mcpRows = editor.locator(".authorization-mcp-editor tr[data-row-key]")
    await expect(mcpRows).toHaveCount(6)
    for (const row of await mcpRows.all()) {
      await expect(row.locator('input[type="radio"]:checked')).toHaveCount(1)
      await expect(row.getByRole("radio", { name: zh ? "指定工具" : "Selected tools", exact: true })).toBeChecked()
    }
    await expect(tools.locator("tr[data-row-key]")).toHaveCount(50)
    const footer = editor.locator(".oauth-grant-delta"), footerBounds = await footer.boundingBox()
    const pageScroll = await page.evaluate(() => document.scrollingElement?.scrollTop || 0)
    // Editing has two catalogs: the dialog body owns vertical scrolling. Details
    // dialogs keep their existing table scroll contract and are not targeted here.
    await body.evaluate(element => { element.scrollTop = element.scrollHeight })
    const metrics = await editor.evaluate(element => {
      const body = element.querySelector<HTMLElement>(".oauth-grant-edit-body")!, bodyBounds = body.getBoundingClientRect()
      const table = element.querySelector<HTMLElement>(".oauth-tools .ant-table-body")!, tableBounds = table.getBoundingClientRect()
      const rows = Array.from(table.querySelectorAll("tr[data-row-key]")), rowBounds = rows.map(row => row.getBoundingClientRect())
      const top = Math.max(bodyBounds.top + body.clientTop, tableBounds.top, 0), bottom = Math.min(bodyBounds.bottom, tableBounds.bottom, innerHeight)
      const firstCell = rows[0].querySelector<HTMLElement>("td:has(.oauth-tool-name)")!, cell = getComputedStyle(firstCell), tokens = getComputedStyle(element)
      const nestedScroll = Array.from(element.querySelectorAll<HTMLElement>(".authorization-mcp-editor .ant-table-content, .oauth-tools .ant-table-body")).map(node => ({ overflow: node.scrollHeight - node.clientHeight, top: node.scrollTop, overflowY: getComputedStyle(node).overflowY }))
      return { rows: rowBounds.filter(row => row.top >= top - 1 && row.bottom <= bottom + 1).length, renderedRows: rows.length, rowHeights: rowBounds.map(row => row.height), toolButtonHeights: Array.from(table.querySelectorAll(".oauth-tool-name")).map(button => button.getBoundingClientRect().height), cellPadding: [cell.paddingTop, cell.paddingBottom], cellBorder: [cell.borderTopWidth, cell.borderBottomWidth], controlHeightToken: tokens.getPropertyValue("--control-height-sm").trim(), space1Token: tokens.getPropertyValue("--space-1").trim(), nestedScroll, bodyOverflow: body.scrollHeight - body.clientHeight, bodyScrollTop: body.scrollTop, bodyHeight: body.clientHeight, pageOverflow: document.documentElement.scrollWidth - innerWidth }
    })
    await capture(page, `scope-${locale}-${size.width}x${size.height}`, { ...metrics, labels: labelMetrics, scrollOwner: "dialog-body" })
    expect(metrics.renderedRows).toBe(50)
    expect(metrics.rows).toBeGreaterThanOrEqual(8)
    expect(metrics.rowHeights.every(height => Math.abs(height - compactClientRowHeight) < 1)).toBe(true)
    expect(metrics.toolButtonHeights.every(height => Math.abs(height - 32) < 1)).toBe(true)
    expect(metrics.cellPadding).toEqual(["8px", "8px"])
    expect(metrics.nestedScroll).toHaveLength(2)
    expect(metrics.nestedScroll.every(scroll => scroll.overflow <= 1 && scroll.top === 0)).toBe(true)
    expect(metrics.bodyOverflow).toBeGreaterThan(0)
    expect(metrics.bodyScrollTop).toBeGreaterThan(0)
    expect(Math.abs(metrics.bodyScrollTop - metrics.bodyOverflow)).toBeLessThanOrEqual(1)
    expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
    expect(await footer.boundingBox()).toEqual(footerBounds)
    expect(await page.evaluate(() => document.scrollingElement?.scrollTop || 0)).toBe(pageScroll)
    for (const control of [save, cancel, tools.getByRole("button", { name: `${model.grant.tools[49].name} · ${model.grant.tools[49].id}`, exact: true }), tools.locator(".ant-pagination-next")]) await expectInViewportAndUnobscured(control)
    await save.click({ trial: true }); await cancel.click({ trial: true })
    expect(model.writes).toHaveLength(0)
  })
  test(`managed OAuth density ${locale} ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size)
    const model = await fixture(page, locale)
    await page.goto("/console/#/connectionInfrastructure")
    await expect(page.locator("#oauth-issuer")).toHaveValue(model.config.issuer)
    const metrics = await page.evaluate(() => {
      const panel = document.querySelector(".oauth-admin-layout")!
      const labels = Array.from(panel.querySelectorAll(".oauth-inline-form .ant-form-item-row")).map(row => { const label = row.querySelector("label")!.getBoundingClientRect(), control = row.querySelector(".ant-form-item-control input, .ant-form-item-control [role=switch], .ant-form-item-control #oauth-generate-key")!.getBoundingClientRect(); return Math.abs((label.top + label.bottom - control.top - control.bottom) / 2) < 4 })
      const body = panel.querySelector<HTMLElement>(".oauth-client-table .ant-table-body")!, bounds = body.getBoundingClientRect()
      const rows = Array.from(body.querySelectorAll("tr[data-row-key]")), rowBounds = rows.map(row => row.getBoundingClientRect())
      const cells = Array.from(rows[0].querySelectorAll("td")).map(cell => { const style = getComputedStyle(cell); return { paddingTop: style.paddingTop, paddingBottom: style.paddingBottom, borderTop: style.borderTopWidth, borderBottom: style.borderBottomWidth } })
      const tokens = getComputedStyle(panel)
      return { labels, clientBodyHeight: body.clientHeight, clientRowHeights: rowBounds.map(row => row.height), clientButtonHeights: Array.from(body.querySelectorAll("button")).map(button => button.getBoundingClientRect().height), clientCellMetrics: cells, controlHeightToken: tokens.getPropertyValue("--control-height-sm").trim(), space1Token: tokens.getPropertyValue("--space-1").trim(), completeClientRows: rowBounds.filter(row => row.top >= bounds.top - 1 && row.bottom <= bounds.bottom + 1).length, pageOverflow: document.documentElement.scrollWidth - innerWidth, setupGuidance: document.querySelectorAll(".oauth-setup-guidance").length }
    })
    await capture(page, `infrastructure-${locale}-${size.width}x${size.height}`, { ...metrics, fixture_clients: 61 })
    expect(metrics.setupGuidance).toBe(0)
    expect(metrics.labels.length).toBeGreaterThan(0)
    expect(metrics.labels.every(Boolean)).toBe(true)
    expect(metrics.clientButtonHeights.length).toBeGreaterThan(0)
    expect(metrics.clientButtonHeights.every(height => Math.abs(height - 32) < 1)).toBe(true)
    expect(metrics.clientRowHeights.every(height => Math.abs(height - compactClientRowHeight) < 1)).toBe(true)
    expect(Math.abs(metrics.clientBodyHeight - Math.round(metrics.clientBodyHeight / compactClientRowHeight) * compactClientRowHeight)).toBeLessThanOrEqual(1)
    expect(metrics.completeClientRows).toBeGreaterThanOrEqual(5)
    expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
    const table = page.locator(".oauth-client-table")
    await expect(table.locator("tr[data-row-key]")).toHaveCount(25)
    await expect(table.getByRole("button", { name: zh ? "详情" : "Details", exact: true })).toHaveCount(0)
    await expect(page.locator("#oauth-generate-key")).toHaveAccessibleName(zh ? "轮换签名密钥" : "Rotate signing key")
    await expect(page.locator("#oauth-issuer")).toBeDisabled()
    await expect(page.locator("#oauth-resource")).toBeDisabled()
    await expect(page.locator("#oauth-enable-help")).toHaveText(zh ? "先停用并保存，才能修改地址。" : "Disable and save before editing URLs.")
    const fifth = table.locator("tr[data-row-key]").nth(4)
    const fifthMore = moreActions(fifth, zh, model.clients[4].name)
    for (const control of [fifth.getByRole("button", { name: "Synthetic client 4", exact: true }), fifth.getByRole("button", { name: `${zh ? "复制客户端 ID" : "Copy client ID"} ${model.clients[4].id}`, exact: true }), fifth.getByRole("button", { name: zh ? "编辑" : "Edit", exact: true }), fifthMore, table.locator(".ant-pagination-next")]) await expectInViewportAndUnobscured(control)
    for (const control of [page.getByRole("button", { name: zh ? "接入指引" : "Connection guide", exact: true }), page.getByRole("button", { name: zh ? "登记客户端" : "Register client", exact: true }), page.locator("#oauth-generate-key"), page.getByRole("switch", { name: zh ? "启用管理 OAuth" : "Enable management OAuth", exact: true })]) await expectInViewportAndUnobscured(control)
    await fifthMore.click()
    for (const name of [zh ? "轮换密钥" : "Rotate secret", zh ? "停用" : "Disable"]) await expectInViewportAndUnobscured(page.getByRole("menu").getByRole("menuitem", { name, exact: true }))
    await page.keyboard.press("Escape")
    await expect(fifthMore).toBeFocused()
    const scroll = table.locator(".ant-table-body")
    expect(await scroll.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
    await scroll.evaluate(element => { element.scrollTop = element.scrollHeight })
    await expectInViewportAndUnobscured(table.getByRole("button", { name: "Synthetic client 24", exact: true }))
    await table.locator(".ant-pagination-next").click()
    await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBe(0)
    await expect(table.getByRole("button", { name: "Synthetic client 25", exact: true })).toBeVisible()
    await page.getByRole("textbox", { name: zh ? "搜索客户端" : "Search clients", exact: true }).fill("Synthetic client 60")
    await expect(table.locator("tr[data-row-key]")).toHaveCount(1)
    await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBe(0)
    expect(model.writes).toHaveLength(0)
  })
}

for (const locale of ["en-US", "zh-CN"] as const) {
  const zh = locale === "zh-CN"
  test(`small MCP radios keep keyboard filters separate from whole-catalog selection ${locale}`, async ({ page }) => {
    await page.setViewportSize(sizes[0])
    const model = await fixture(page, locale)
    model.grant.tools = model.grant.tools.slice(0, 46); model.grant.effective_tool_count = 46
    const editor = await scope(page, locale, 46)
    const filters = editor.getByRole("radiogroup", { name: zh ? "按 MCP 筛选" : "Filter by MCP", exact: true })
    await expect(filters.getByRole("radio")).toHaveCount(3)
    await filters.getByRole("radio", { name: zh ? "全部 MCP" : "All MCPs", exact: true }).focus()
    await page.keyboard.press("ArrowRight")
    await expect(filters.getByRole("radio", { name: "Synthetic MCP 0", exact: true })).toBeChecked()
    await page.keyboard.press("ArrowRight")
    await expect(filters.getByRole("radio", { name: "Synthetic MCP 1", exact: true })).toBeChecked()
    await expect(editor.locator(".oauth-tools tr[data-row-key]")).toHaveCount(23)
    await expect(editor.locator(".oauth-selection")).toContainText("46 / 46")
    await editor.getByRole("radio", { name: zh ? "仅选全部当前只读" : "All current read-only tools", exact: true }).check()
    await expect(editor.locator(".oauth-selection")).toContainText("23 / 46")
    expect(model.writes).toHaveLength(0)
  })
  test(`scope keyboard identity and lossless disclosure ${locale}`, async ({ page }) => {
    await page.setViewportSize(sizes[0])
    const model = await fixture(page, locale, "dark")
    const editor = await scope(page, locale)
    const row = editor.locator('.oauth-tools tr[data-row-key="mcp.synthetic-density-0.tool-1"]')
    const tool = row.getByRole("button", { name: `${model.grant.tools[1].name} · ${model.grant.tools[1].id}`, exact: true })
    await tool.focus(); await page.keyboard.press("Enter")
    const details = page.getByRole("dialog", { name: zh ? "工具详情" : "Tool details", exact: true })
    await expect(details.getByRole("textbox", { name: "Tool ID", exact: true })).toHaveValue(model.grant.tools[1].id)
    await details.getByRole("button", { name: zh ? "复制工具 ID" : "Copy tool ID", exact: true }).click()
    await expect(details.getByRole("status")).toContainText(zh ? "已复制" : "copied")
    await page.keyboard.press("Escape")
    await expect(tool).toBeFocused()
    await expect(row.getByRole("checkbox")).toBeChecked()
    const rules = editor.getByRole("button", { name: zh ? "查看范围与授权规则" : "Scope details", exact: true })
    await rules.focus(); await page.keyboard.press("Enter")
    await expect(editor.locator(".oauth-scope-info")).toContainText("tools.read")
    await expect(editor.locator(".oauth-scope-info")).toContainText(zh ? "各令牌族" : "Each token family")
    await page.keyboard.press("Escape")
    await expect(editor.locator(".oauth-scope-info")).toBeHidden()
    await expect(rules).toHaveAttribute("aria-expanded", "false")
    await expect(rules).toBeFocused()
    await editor.getByRole("radio", { name: zh ? "仅选全部当前只读" : "All current read-only tools", exact: true }).check()
    await editor.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    const discard = page.getByRole("alertdialog")
    await discard.getByRole("button", { name: zh ? "继续编辑" : "Continue editing", exact: true }).click()
    await expect(editor.locator(".oauth-selection")).toContainText("69 / 137")
    expect(model.writes).toHaveLength(0)
  })
  test(`same-name MCPs retain distinct searchable identities ${locale}`, async ({ page }) => {
    await page.setViewportSize(sizes[0])
    const model = await fixture(page, locale)
    model.grant.tools = model.grant.tools.slice(0, 46).map(tool => ({ ...tool, server_name: "Synthetic MCP" }))
    model.grant.effective_tool_count = 46
    const editor = await scope(page, locale, 46)
    const filter = editor.getByRole("combobox", { name: zh ? "按 MCP 筛选" : "Filter by MCP", exact: true })
    await filter.fill("Synthetic MCP")
    const options = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content")
    await expect(options).toHaveText(["synthetic-density-0", "synthetic-density-1"])
    await options.filter({ hasText: /^synthetic-density-1$/ }).click()
    await expect(editor.locator(".oauth-tools tr[data-row-key]")).toHaveCount(23)
    await expect(editor.locator(".oauth-selection")).toContainText("46 / 46")
    expect(model.writes).toHaveLength(0)
  })
  test(`managed OAuth keyboard guide and scoped client details ${locale}`, async ({ page }) => {
    await page.setViewportSize(sizes[0])
    const model = await fixture(page, locale, "dark", 1)
    await page.goto("/console/#/connectionInfrastructure")
    const guideButton = page.getByRole("button", { name: zh ? "接入指引" : "Connection guide", exact: true })
    await guideButton.focus(); await page.keyboard.press("Enter")
    const guide = page.getByRole("dialog", { name: zh ? "接入指引" : "Connection guide", exact: true })
    await expect(guide).toContainText("/mcp/manage")
    await expect(guide).toContainText(zh ? "四个外部配置工具及精确创建/更新目标" : "four external configuration tools and exact create/update targets")
    await expect(guide).toContainText(zh ? "保存配置和启用服务都不代表外部连接验收" : "Saving or enabling is not external connection verification")
    await page.keyboard.press("Tab")
    expect(await guide.evaluate(element => element.contains(document.activeElement))).toBe(true)
    await page.keyboard.press("Escape")
    await expect(guideButton).toBeFocused()
    const info = page.locator(".oauth-client-table").getByRole("button", { name: model.clients[0].name, exact: true })
    await expect(info).toHaveAttribute("aria-haspopup", "dialog")
    await info.focus(); await page.keyboard.press("Enter")
    const details = page.getByRole("dialog", { name: zh ? "客户端详情" : "Client details", exact: true })
    await expect(details.getByRole("textbox", { name: "Client ID", exact: true })).toHaveValue(model.clients[0].id)
    await expect(details).toContainText("tools.invoke")
    await expect(details).toContainText("https://client.example.test/callback")
    await page.keyboard.press("Escape")
    await expect(info).toBeFocused()
    await page.keyboard.press("Enter")
    await details.getByRole("button", { name: zh ? "编辑客户端" : "Edit client", exact: true }).click()
    const editing = page.getByRole("dialog", { name: zh ? "编辑客户端" : "Edit client", exact: true })
    await expect(editing.getByLabel(zh ? "客户端名称" : "Client name", { exact: true })).toHaveValue(model.clients[0].name)
    await editing.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await expect(info).toBeFocused()
    const directEdit = page.locator(".oauth-client-table tr[data-row-key]").first().getByRole("button", { name: zh ? "编辑" : "Edit", exact: true })
    await directEdit.focus(); await page.keyboard.press("Enter")
    await expect(editing.getByLabel(zh ? "客户端名称" : "Client name", { exact: true })).toHaveValue(model.clients[0].name)
    await editing.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await expect(directEdit).toBeFocused()
    await capture(page, `infrastructure-dark-${locale}-1600x900`, { fixture_clients: 1, keyboardGuideDetailsAndEdit: true })
    expect(model.writes).toHaveLength(0)
  })
  test(`compact client danger actions preserve confirmation revision failure and secrets ${locale}`, async ({ page }) => {
    const model = await fixture(page, locale, "light", 1)
    await page.goto("/console/#/connectionInfrastructure")
    await expect(page.locator("#oauth-enable-help")).toHaveText(zh ? "先停用并保存，才能修改地址。" : "Disable and save before editing URLs.")
    await page.getByRole("switch", { name: zh ? "启用内置 OAuth" : "Enable built-in OAuth", exact: true }).click()
    await expect(page.locator("#oauth-enable-help")).toHaveText(zh ? "保存停用后可修改地址；现有连接需重新授权。" : "Save disablement to edit URLs; existing connections need new authorization.")
    await expect(page.locator("#oauth-issuer")).toBeDisabled()
    await expect(page.locator("#oauth-resource")).toBeDisabled()
    await page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click()
    const disableOAuth = page.getByRole("alertdialog", { name: zh ? "关闭内置 OAuth？" : "Disable built-in OAuth?", exact: true })
    await expect(disableOAuth).toContainText(zh ? "现有令牌族将撤销" : "Existing token families will be revoked")
    await disableOAuth.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    expect(model.writes).toHaveLength(0)
    await page.getByRole("button", { name: zh ? "放弃配置修改" : "Discard configuration edits", exact: true }).click()
    const row = page.locator(".oauth-client-table tr[data-row-key]").first()
    const more = moreActions(row, zh, model.clients[0].name)
    for (const name of [zh ? "轮换密钥" : "Rotate secret", zh ? "停用" : "Disable"]) {
      await clientAction(page, row, zh, model.clients[0].name, name)
      const confirmation = page.getByRole("alertdialog")
      await expect(confirmation).toContainText(model.clients[0].id)
      await confirmation.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
      await expect(more).toBeFocused()
    }
    expect(model.writes).toHaveLength(0)
    model.clientWriteFailure = true
    await clientAction(page, row, zh, model.clients[0].name, zh ? "停用" : "Disable")
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "停用" : "Disable", exact: true }).click()
    await expect(page.getByRole("alert")).toContainText(zh ? "对象已改变" : "This item changed")
    await expectClientActionEnabled(page, row, zh, model.clients[0].name, zh ? "停用" : "Disable")
    expect(model.writes[0].body).toMatchObject({ enabled: false, expected_revision: 1, rotate_secret: false })
    model.clientWriteFailure = false
    for (const [name, enabled, revision] of [[zh ? "停用" : "Disable", false, 1], [zh ? "启用" : "Enable", true, 2]] as const) {
      await clientAction(page, row, zh, model.clients[0].name, name)
      await page.getByRole("alertdialog").getByRole("button", { name, exact: true }).click()
      await expectClientActionEnabled(page, row, zh, model.clients[0].name, enabled ? zh ? "停用" : "Disable" : zh ? "启用" : "Enable")
      expect(model.writes.at(-1)!.body).toMatchObject({ enabled, expected_revision: revision, rotate_secret: false })
    }
    await clientAction(page, row, zh, model.clients[0].name, zh ? "轮换密钥" : "Rotate secret")
    const rotate = page.getByRole("alertdialog")
    await expect(rotate).toContainText(zh ? "旧密钥立即失效" : "old secret stops working immediately")
    await rotate.getByRole("button", { name: zh ? "轮换密钥" : "Rotate secret", exact: true }).click()
    const secret = page.getByRole("dialog", { name: zh ? "仅展示一次的客户端密钥" : "One-time client secret", exact: true })
    await expect(secret.getByLabel("Client Secret", { exact: true })).toHaveValue("synthetic-density-rotated-secret")
    expect(model.writes.at(-1)!.body).toMatchObject({ enabled: true, expected_revision: 3, rotate_secret: true })
    await secret.getByRole("button", { name: zh ? "已保存，关闭" : "Saved, close", exact: true }).click()
    await expect(secret).toHaveCount(0)
    await expect(page.getByText("synthetic-density-rotated-secret", { exact: true })).toHaveCount(0)
    await expect(more).toBeFocused()
    expect(model.writes).toHaveLength(4)
  })
}

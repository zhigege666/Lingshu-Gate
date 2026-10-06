import { expect, test, type Page } from "@playwright/test"
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
const now = Math.floor(Date.now() / 1000)
async function fixture(page: Page, locale: Locale, theme = "light", count = 61) {
  const tools: OAuthTool[] = Array.from({ length: 137 }, (_, index) => ({ id: `mcp.synthetic-density-${Math.floor(index / 23)}.tool-${index}`, name: index < 2 ? locale === "zh-CN" ? "项目详情" : "Project details" : locale === "zh-CN" ? `项目工具 ${index}` : `Project tool ${index}`, server_id: `synthetic-density-${Math.floor(index / 23)}`, server_name: `Synthetic MCP ${Math.floor(index / 23)}`, access: index % 2 ? "write" : "read", snapshot: "synthetic-density", currently_authorized: true }))
  const grant: OAuthGrant = { id: "synthetic-density-grant", client_id: "synthetic-density-client", client_name: "Synthetic project client", resource: "https://gate.example.test/mcp", scopes: ["tools.read", "tools.invoke"], tools, created_at: now - 60, expires_at: now + 86400, state: "active", rate_per_minute: 30, concurrency: 2, revision: 1, scope_currently_authorized: true, effective_tool_count: 137 }
  const config: OAuthConfig = { enabled: true, issuer: "https://gate.example.test", resource: "https://gate.example.test/mcp", revision: 1, metadata_url: "https://gate.example.test/.well-known/oauth-authorization-server", authorization_endpoint: "https://gate.example.test/oauth/authorize", token_endpoint: "https://gate.example.test/oauth/token", jwks_uri: "https://gate.example.test/oauth/jwks", signing_keys: [{ kid: "synthetic-active", active: true, retire_at: null }] }
  const clients: OAuthClient[] = Array.from({ length: count }, (_, index) => ({ id: `lgc_synthetic_density_client_${String(index).padStart(3, "0")}`, name: `Synthetic client ${index}`, scopes: ["tools.read", "tools.invoke"], resources: ["business"], redirect_uris: ["https://client.example.test/callback"], enabled: index % 4 !== 3, revision: 1, created_at: now - 60 }))
  const model = { grant, config, clients, reads: 0, writes: [] as { path: string; body: Record<string, unknown> }[] }
  await page.addInitScript(({ locale, theme }) => { localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme); Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => undefined } }) }, { locale, theme })
  await page.route("**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(assets, "index.html")) }))
  await page.route("**/console/assets/**", route => { const name = path.basename(new URL(route.request().url()).pathname); return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(assets, "assets", name)) }) })
  await page.route("**/healthz", route => route.fulfill({ json: { version: sourceVersion } }))
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname, method = route.request().method()
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-density-owner", username: "synthetic-density-owner", display_name: "Synthetic owner", status: "active", role: "custom", roles: ["custom"], permissions: ["console.view", "credentials.manage.self", "external_connections.manage"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/config") return route.fulfill({ json: model.config })
    if (pathname === "/v1/auth/oauth/clients") return route.fulfill({ json: { clients: model.clients } })
    if (pathname === "/v1/auth/oauth/management/config") return route.fulfill({ json: { enabled: false, resource: "https://gate.example.test/mcp/manage", revision: 1 } })
    if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [model.grant] } })
    if (pathname.endsWith("/scope-options")) { model.reads++; return route.fulfill({ json: { csrf: "synthetic-density-csrf-" + "s".repeat(32), expires_at: now + 600, grant_revision: model.grant.revision, tools: model.grant.tools, scopes: model.grant.scopes, effective_scopes: model.grant.scopes, family_scope_limits: [{ scopes: ["tools.read"], count: 1 }], unavailable_servers: [], can_review_classifications: false } }) }
    if (method !== "GET") model.writes.push({ path: pathname, body: route.request().postDataJSON() })
    return route.fulfill({ status: 404, json: { error: "unmocked_synthetic_request" } })
  })
  return model
}
async function scope(page: Page, locale: Locale, expected = 137) {
  await page.goto("/console/#/myConnections")
  await page.getByRole("tab", { name: locale === "zh-CN" ? "Gate 内置 OAuth" : "Gate built-in OAuth", exact: true }).click()
  await page.getByRole("button", { name: locale === "zh-CN" ? "调整授权范围" : "Adjust scope", exact: true }).click()
  const editor = page.getByRole("dialog", { name: locale === "zh-CN" ? "调整授权范围" : "Adjust authorization scope", exact: true })
  await expect(editor.locator(".oauth-selection")).toContainText(`${expected} / ${expected}`)
  await editor.evaluate(async element => { await Promise.all(element.getAnimations().map(animation => animation.finished)) })
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
    const metrics = await editor.evaluate(element => {
      const body = element.querySelector(".oauth-grant-scope-body")!
      const table = element.querySelector(".ant-table-body")!.getBoundingClientRect()
      const rows = Array.from(element.querySelectorAll(".ant-table-body tr[data-row-key]")).map(row => row.getBoundingClientRect())
      const labels = Array.from(element.querySelectorAll(".oauth-grant-limits label")).map(label => { const range = document.createRange(); range.selectNode(label.firstChild!); const text = range.getBoundingClientRect(), input = label.querySelector("input")!.getBoundingClientRect(); return range.getClientRects().length === 1 && Math.abs((text.top + text.bottom - input.top - input.bottom) / 2) < 3 })
      return { rows: rows.filter(row => row.top >= table.top - 1 && row.bottom <= table.bottom + 1).length, rowHeights: rows.map(row => row.height), labels, bodyOverflow: body.scrollHeight - body.clientHeight, pageOverflow: document.documentElement.scrollWidth - innerWidth }
    })
    await capture(page, `scope-${locale}-${size.width}x${size.height}`, metrics)
    expect(metrics.rows).toBeGreaterThanOrEqual(8)
    expect(metrics.rowHeights.every(height => height >= 36 && height <= 44)).toBe(true)
    expect(metrics.labels.every(Boolean)).toBe(true)
    expect(metrics.bodyOverflow).toBeLessThanOrEqual(1)
    expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
    for (const control of [editor.getByRole("button", { name: zh ? "保存授权" : "Save authorization", exact: true }), editor.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }), editor.getByRole("button", { name: zh ? "刷新可授权范围" : "Refresh available scope", exact: true })]) await expectInViewportAndUnobscured(control)
    const table = editor.locator(".ant-table-body"), footer = editor.locator(".oauth-grant-delta")
    const bounds = await footer.boundingBox()
    await table.evaluate(element => { element.scrollTop = element.scrollHeight })
    expect(await footer.boundingBox()).toEqual(bounds)
    expect(await editor.locator(".oauth-grant-scope-body").evaluate(element => element.scrollTop)).toBe(0)
    expect(model.writes).toHaveLength(0)
  })
  test(`managed OAuth density ${locale} ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size)
    const model = await fixture(page, locale)
    await page.goto("/console/#/connectionInfrastructure")
    await expect(page.locator("#oauth-issuer")).toHaveValue(model.config.issuer)
    const metrics = await page.evaluate(() => {
      const panel = document.querySelector(".oauth-admin-layout")!
      const labels = Array.from(panel.querySelectorAll(".oauth-inline-form .ant-form-item-row")).map(row => { const label = row.querySelector("label")!.getBoundingClientRect(), control = row.querySelector("input, [role=switch]")!.getBoundingClientRect(); return Math.abs((label.top + label.bottom - control.top - control.bottom) / 2) < 4 })
      return { labels, pageOverflow: document.documentElement.scrollWidth - innerWidth, setupSteps: document.querySelectorAll(".oauth-setup-steps li").length }
    })
    await capture(page, `infrastructure-${locale}-${size.width}x${size.height}`, { ...metrics, fixture_clients: 61 })
    expect(metrics.setupSteps).toBe(0)
    expect(metrics.labels.every(Boolean)).toBe(true)
    expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
    const table = page.locator(".oauth-client-table")
    await expect(table.locator("tr[data-row-key]")).toHaveCount(25)
    for (const control of [page.getByRole("button", { name: zh ? "接入指引" : "Connection guide", exact: true }), page.getByRole("button", { name: zh ? "登记客户端" : "Register client", exact: true }), page.locator("#oauth-generate-key"), table.getByRole("button", { name: zh ? "轮换密钥" : "Rotate secret", exact: true }).first(), page.getByRole("switch", { name: zh ? "启用管理 OAuth" : "Enable management OAuth", exact: true })]) await expectInViewportAndUnobscured(control)
    const scroll = table.locator(".ant-table-body")
    expect(await scroll.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true)
    await scroll.evaluate(element => { element.scrollTop = element.scrollHeight })
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
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(23)
    await expect(editor.locator(".oauth-selection")).toContainText("46 / 46")
    await editor.getByRole("radio", { name: zh ? "仅选全部当前只读" : "All current read-only tools", exact: true }).check()
    await expect(editor.locator(".oauth-selection")).toContainText("23 / 46")
    expect(model.writes).toHaveLength(0)
  })
  test(`scope keyboard identity and lossless disclosure ${locale}`, async ({ page }) => {
    await page.setViewportSize(sizes[0])
    const model = await fixture(page, locale, "dark")
    const editor = await scope(page, locale)
    const row = editor.locator('tr[data-row-key="mcp.synthetic-density-0.tool-1"]')
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
    await expect(editor.locator("tr[data-row-key]")).toHaveCount(23)
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
    await expect(guide).toContainText(zh ? "保存配置和启用服务都不代表外部连接验收" : "Saving or enabling is not external connection verification")
    await page.keyboard.press("Tab")
    expect(await guide.evaluate(element => element.contains(document.activeElement))).toBe(true)
    await page.keyboard.press("Escape")
    await expect(guideButton).toBeFocused()
    const info = page.locator(".oauth-client-table").getByRole("button", { name: zh ? "详情" : "Details", exact: true })
    await info.focus(); await page.keyboard.press("Enter")
    const details = page.getByRole("dialog", { name: zh ? "客户端详情" : "Client details", exact: true })
    await expect(details.getByRole("textbox", { name: "Client ID", exact: true })).toHaveValue(model.clients[0].id)
    await expect(details).toContainText("tools.invoke")
    await expect(details).toContainText("https://client.example.test/callback")
    await page.keyboard.press("Escape")
    await expect(info).toBeFocused()
    await capture(page, `infrastructure-dark-${locale}-1600x900`, { fixture_clients: 1, keyboardGuideAndDetails: true })
    expect(model.writes).toHaveLength(0)
  })
}

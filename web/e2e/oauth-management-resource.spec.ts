import { expect, test, type Page } from "@playwright/test"
import { mkdirSync, readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import type { OAuthGrant, OAuthTool } from "../src/features/external-connections/oauth-api"
import { expectInViewportAndUnobscured } from "./helpers"

// Built assets with synthetic responses only. Real ASGI authorization has
// separate backend coverage; no production client, signing key or peer is used.
const staticRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static")
const now = Math.floor(Date.now() / 1000)
const toolIds = ["gate_mcp_config_plan", "gate_mcp_config_apply", "gate_mcp_config_status", "gate_mcp_config_cancel"]
const tools: OAuthTool[] = toolIds.map((id, index) => ({ id, name: id, server_id: "gate_mcp_configuration", server_name: "Gate configuration", access: index % 2 ? "write" : "read", snapshot: "synthetic-schema", currently_authorized: true }))
const targets = Object.fromEntries(Array.from({ length: 1000 }, (_, i) => [`service-${String(i).padStart(4, "0")}`, ["create", "update"]]))
const initialGrant: OAuthGrant = { id: "synthetic-management-grant", client_id: "lgc_synthetic_management", client_name: "Synthetic management client", resource: "https://gate.example.test/mcp/manage", resource_kind: "management", scopes: ["operations.manage", "tools.invoke"], tools, state: "active", created_at: now - 60, expires_at: now + 86400, rate_per_minute: 300, concurrency: 5, revision: 1, target_revision: 1, management_targets: targets, scope_currently_authorized: true, effective_tool_count: 4 }
type Locale = "en-US" | "zh-CN"
async function assets(page: Page, locale: Locale, theme: string, publicPage = false) {
  await page.addInitScript(({ locale, theme }) => { localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme) }, { locale, theme })
  const directory = path.join(staticRoot, publicPage ? "oauth" : "console")
  await page.route(publicPage ? "**/oauth/consent" : "**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(directory, publicPage ? "oauth.html" : "index.html"), "utf8") }))
  await page.route(publicPage ? "**/oauth/assets/**" : "**/console/assets/**", route => { const name = path.basename(new URL(route.request().url()).pathname); return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(directory, "assets", name)) }) })
  await page.route("**/healthz", route => route.fulfill({ json: { version: "0.4.3" } }))
}
async function setup(page: Page, locale: Locale, theme = "light", signingKeys: unknown = [{ kid: "synthetic-active", active: true, retire_at: null }]) {
  await assets(page, locale, theme)
  const model = { grant: { ...initialGrant, management_targets: { ...targets } }, management: { enabled: false, active: false, revision: 1, resource: initialGrant.resource }, keys: signingKeys,
    reads: 0, managementFailure: false, targetFailure: false, previewFailure: false, saveFailure: false, holdTargets: null as (() => Promise<void>) | null,
    writes: [] as { path: string; body: Record<string, unknown>; csrf?: string }[], previews: [] as Record<string, unknown>[], clients: [] as Record<string, unknown>[] }
  await page.route("**/v1/**", async route => {
    const pathname = new URL(route.request().url()).pathname, method = route.request().method()
    if (pathname === "/v1/mcp/servers") return route.fulfill({ json: { servers: [], load_errors: [] } })
    if (pathname === "/v1/mcp/configs") return route.fulfill({ json: { configs: [], errors: [] } })
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-admin", username: "synthetic-admin", display_name: "Synthetic administrator", status: "active", role: "admin", roles: ["admin"], permissions: ["console.view", "credentials.manage.self", "external_connections.manage", "operations.manage", "tools.invoke"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/config") return route.fulfill({ json: { enabled: true, issuer: "https://gate.example.test", resource: "https://gate.example.test/mcp", revision: 1, metadata_url: "https://gate.example.test/.well-known/oauth-authorization-server", authorization_endpoint: "https://gate.example.test/oauth/authorize", token_endpoint: "https://gate.example.test/oauth/token", jwks_uri: "https://gate.example.test/oauth/jwks", signing_keys: model.keys } })
    if (pathname === "/v1/auth/oauth/management/config") {
      if (method === "GET") { model.reads++; return route.fulfill(model.managementFailure ? { status: 503, json: { error: "request_failed" } } : { json: model.management }) }
      const body = route.request().postDataJSON(); model.writes.push({ path: pathname, body, csrf: route.request().headers()["x-csrf-token"] })
      model.management = { ...model.management, enabled: body.enabled, active: body.enabled, revision: model.management.revision + 1 }
      return route.fulfill({ json: model.management })
    }
    if (pathname === "/v1/auth/oauth/management/csrf") { model.writes.push({ path: pathname, body: route.request().postDataJSON() }); return route.fulfill({ json: { csrf: "synthetic-management-csrf" } }) }
    if (pathname === "/v1/auth/oauth/clients") {
      if (method === "GET") return route.fulfill({ json: { clients: model.clients } })
      const body = route.request().postDataJSON(); model.writes.push({ path: pathname, body })
      const client = { ...body, id: "lgc_synthetic_new", enabled: true, revision: 1, created_at: now }
      model.clients.push(client)
      return route.fulfill({ json: { client, client_secret: "synthetic-one-time-secret" } })
    }
    if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [model.grant] } })
    if (pathname === `/v1/auth/oauth/grants/${model.grant.id}/management-targets` && method === "GET") {
      if (model.holdTargets) await model.holdTargets()
      return route.fulfill(model.targetFailure ? { status: 503, json: { error: "request_failed" } } : { json: { csrf: "synthetic-options-csrf", expires_at: now + 600, expected_revision: model.grant.revision, expected_target_revision: model.grant.target_revision, targets: model.grant.management_targets, scopes: model.grant.scopes, tool_ids: toolIds } })
    }
    if (pathname.endsWith("/management-targets/preview")) {
      const body = route.request().postDataJSON(); model.previews.push(body)
      return route.fulfill(model.previewFailure ? { status: 409, json: { error: "management_confirmation_changed" } } : { json: { ...body, previous_targets: model.grant.management_targets, confirmation: "synthetic-target-confirmation", confirmation_expires_at: now + 600, scopes_unchanged: true, tools_unchanged: true } })
    }
    if (pathname.endsWith("/management-targets") && method === "POST") {
      const body = route.request().postDataJSON(); model.writes.push({ path: pathname, body })
      if (model.saveFailure) return route.fulfill({ status: 409, json: { error: "management_confirmation_changed" } })
      model.grant = { ...model.grant, management_targets: body.targets, revision: model.grant.revision + 1, target_revision: model.grant.target_revision! + 1 }
      return route.fulfill({ json: model.grant })
    }
    return route.fulfill({ status: 404, json: { error: "unmocked_synthetic_request" } })
  })
  return model
}
async function infrastructure(page: Page, zh: boolean) {
  await page.goto("/console/#/connectionInfrastructure")
  await expect(page.getByRole("button", { name: zh ? "登记客户端" : "Register client", exact: true })).toBeEnabled()
}
async function personal(page: Page, zh: boolean) {
  await page.goto("/console/#/myConnections")
  await page.getByRole("tab", { name: zh ? "Gate 内置 OAuth" : "Gate built-in OAuth", exact: true }).click()
  await expect(page.getByRole("button", { name: zh ? "调整管理目标" : "Adjust targets", exact: true })).toBeVisible()
}
async function capture(page: Page, name: string) {
  const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" })
}
async function centered(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  await expect(dialog).toHaveCSS("opacity", "1")
  const box = await dialog.boundingBox(), viewport = page.viewportSize()!
  expect(box).not.toBeNull()
  expect(Math.abs(box!.x + box!.width / 2 - viewport.width / 2)).toBeLessThan(2)
  expect(Math.abs(box!.y + box!.height / 2 - viewport.height / 2)).toBeLessThan(2)
  expect(box!.y).toBeGreaterThanOrEqual(16)
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height - 16)
}
const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) for (const theme of ["light", "dark"]) {
  const suffix = `${locale}-${theme}-${size.width}x${size.height}`, zh = locale === "zh-CN"
  test(`management resource confirmation and explicit client resource ${suffix}`, async ({ page }) => {
    await page.setViewportSize(size)
    const model = await setup(page, locale, theme)
    await infrastructure(page, zh)
    const toggle = page.getByRole("switch", { name: zh ? "启用管理 OAuth" : "Enable management OAuth", exact: true })
    await expect(toggle).toBeEnabled(); await expect(toggle).not.toBeChecked()
    await toggle.scrollIntoViewIfNeeded()
    await capture(page, `management-config-${suffix}`)
    await toggle.click()
    const confirm = page.getByRole("alertdialog", { name: zh ? "启用独立管理 OAuth？" : "Enable separate management OAuth?", exact: true })
    await expect(confirm).toContainText("operations.manage")
    expect(model.writes).toHaveLength(0)
    await confirm.getByRole("button", { name: zh ? "启用管理资源" : "Enable management resource", exact: true }).click()
    await expect(toggle).toBeChecked()
    expect(model.writes).toEqual([{ path: "/v1/auth/oauth/management/csrf", body: { enabled: true, expected_revision: 1 } }, { path: "/v1/auth/oauth/management/config", body: { enabled: true, expected_revision: 1 }, csrf: "synthetic-management-csrf" }])
    await page.getByRole("button", { name: zh ? "登记客户端" : "Register client", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "登记客户端" : "Register client", exact: true })
    await centered(page, editor)
    await editor.getByRole("radio", { name: zh ? "管理 /mcp/manage" : "Management /mcp/manage", exact: true }).check()
    const management = editor.getByRole("checkbox", { name: zh ? "管理权限 (operations.manage)" : "Management (operations.manage)", exact: true })
    await expect(management).toBeChecked(); await expect(management).toBeDisabled()
    await expect(editor.getByRole("checkbox", { name: /tools.read/ })).toHaveCount(0)
    await editor.getByLabel(zh ? "客户端名称" : "Client name", { exact: true }).fill("Synthetic explicit management client")
    await editor.getByLabel(zh ? "回调地址 1" : "Redirect URI 1", { exact: true }).fill("https://client.example.test/callback")
    expect(await editor.locator(".ant-form-item-row").evaluateAll(rows => rows.every(row => { const label = row.querySelector(".ant-form-item-label")!, control = row.querySelector(".ant-form-item-control")!; return Math.abs(label.getBoundingClientRect().top - control.getBoundingClientRect().top) < 2 && label.getBoundingClientRect().right < control.getBoundingClientRect().left }))).toBe(true)
    await capture(page, `management-client-${suffix}`)
    await editor.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click()
    await expect(page.getByRole("dialog", { name: zh ? "仅展示一次的客户端密钥" : "One-time client secret", exact: true })).toBeVisible()
    expect(model.writes.at(-1)!.body).toEqual({ name: "Synthetic explicit management client", redirect_uris: ["https://client.example.test/callback"], resources: ["management"], scopes: ["operations.manage"] })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
  test(`management targets retain the full 1000-target policy across pages ${suffix}`, async ({ page }) => {
    await page.setViewportSize(size)
    const model = await setup(page, locale, theme)
    await personal(page, zh)
    const trigger = page.getByRole("button", { name: zh ? "调整管理目标" : "Adjust targets", exact: true })
    await trigger.click()
    const editor = page.getByRole("dialog", { name: zh ? "调整管理目标" : "Adjust management targets", exact: true })
    const first = editor.getByRole("textbox", { name: zh ? "服务 ID 1" : "Server ID 1", exact: true })
    await expect(first).toHaveValue("service-0000"); await centered(page, editor)
    const review = editor.getByRole("button", { name: zh ? "核对目标变更" : "Review target changes", exact: true })
    await expectInViewportAndUnobscured(review)
    const footerBefore = await review.boundingBox(), body = editor.locator(".oauth-management-target-body")
    await body.evaluate(element => { element.scrollTop = element.scrollHeight })
    expect(await review.boundingBox()).toEqual(footerBefore)
    expect(await editor.evaluate(element => Array.from(element.querySelectorAll("*")).filter(node => { const style = getComputedStyle(node); return ["auto", "scroll"].includes(style.overflowY) && node.scrollHeight > node.clientHeight + 1 }).length)).toBeLessThanOrEqual(1)
    expect(await page.evaluate(() => document.scrollingElement!.scrollTop)).toBe(0)
    await capture(page, `management-targets-${suffix}`)
    await first.fill("service-replacement")
    await editor.locator(".ant-pagination-next").click()
    await expect(editor.getByRole("textbox", { name: zh ? "服务 ID 11" : "Server ID 11", exact: true })).toHaveValue("service-0010")
    await review.click()
    const confirmation = page.getByRole("alertdialog", { name: zh ? "确认管理目标变更？" : "Confirm management target changes?", exact: true })
    expect(model.writes).toHaveLength(0)
    expect(Object.keys(model.previews[0].targets as object)).toHaveLength(1000)
    await confirmation.getByRole("button", { name: zh ? "确认并更新" : "Confirm update", exact: true }).click()
    await expect(editor).toHaveCount(0)
    expect(model.writes).toHaveLength(1)
    const expectedTargets: Record<string, string[]> = { ...targets, "service-replacement": ["create", "update"] }
    delete expectedTargets["service-0000"]
    expect(model.writes[0].body).toEqual({ expected_revision: 1, expected_target_revision: 1, targets: expectedTargets, confirmation: "synthetic-target-confirmation" })
    expect(model.grant.scopes).toEqual(initialGrant.scopes)
    expect(model.grant.tools).toEqual(initialGrant.tools)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
for (const locale of ["en-US", "zh-CN"] as const) {
  const zh = locale === "zh-CN"
  test(`management unknown key state prevents enable but preserves explicit disable ${locale}`, async ({ page }) => {
    const model = await setup(page, locale, "light", null)
    await infrastructure(page, zh)
    const toggle = page.getByRole("switch", { name: zh ? "启用管理 OAuth" : "Enable management OAuth", exact: true })
    await expect(toggle).toBeDisabled()
    model.management = { ...model.management, enabled: true, active: true }
    await page.getByRole("button", { name: zh ? "重读管理状态" : "Reload management state", exact: true }).click()
    await expect(toggle).toBeEnabled(); await expect(toggle).toBeChecked()
    model.managementFailure = true
    await page.getByRole("button", { name: zh ? "重读管理状态" : "Reload management state", exact: true }).click()
    await expect(toggle).toBeChecked(); await expect(toggle).toBeEnabled()
    await toggle.click()
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "关闭管理资源" : "Disable management resource", exact: true }).click()
    await expect(toggle).not.toBeChecked()
    expect(model.writes.at(-1)!.body).toEqual({ enabled: false, expected_revision: 1 })
  })
  test(`management target error and dirty keyboard close retain edits ${locale}`, async ({ page }) => {
    const model = await setup(page, locale)
    await personal(page, zh)
    await page.getByRole("button", { name: zh ? "调整管理目标" : "Adjust targets", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整管理目标" : "Adjust management targets", exact: true })
    const first = editor.getByRole("textbox", { name: zh ? "服务 ID 1" : "Server ID 1", exact: true })
    await first.fill("service-retry")
    await page.keyboard.press("Escape")
    await page.getByRole("alertdialog", { name: zh ? "放弃尚未保存的修改？" : "Discard unsaved changes?", exact: true }).getByRole("button", { name: zh ? "继续编辑" : "Continue editing", exact: true }).click()
    await expect(first).toHaveValue("service-retry")
    model.previewFailure = true
    await editor.getByRole("button", { name: zh ? "核对目标变更" : "Review target changes", exact: true }).click()
    await expect(editor.locator('[data-slot="alert"]')).toContainText(zh ? "授权或目标版本已改变" : "The grant or target revision changed")
    expect(model.writes).toHaveLength(0)
    await expect(first).toHaveValue("service-retry")
    await editor.getByRole("button", { name: zh ? "重新读取已保存目标" : "Reload saved targets", exact: true }).click()
    const reload = page.getByRole("alertdialog", { name: zh ? "重新读取已保存目标？" : "Reload saved targets?", exact: true })
    await reload.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    await expect(reload).toHaveCount(0)
    await expect(editor.getByRole("button", { name: zh ? "重新读取已保存目标" : "Reload saved targets", exact: true })).toBeFocused()
    await expect(first).toHaveValue("service-retry")
    await page.keyboard.press("Escape")
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "放弃修改" : "Discard changes", exact: true }).click()
    await expect(editor).toHaveCount(0)
    await expect(page.getByRole("button", { name: zh ? "调整管理目标" : "Adjust targets", exact: true })).toBeFocused()
    expect(model.writes).toHaveLength(0)
  })
  test(`management pending read cannot be closed by keyboard ${locale}`, async ({ page }) => {
    const model = await setup(page, locale)
    let release!: () => void
    const held = new Promise<void>(resolve => { release = resolve })
    model.holdTargets = () => held
    await personal(page, zh)
    await page.getByRole("button", { name: zh ? "调整管理目标" : "Adjust targets", exact: true }).click()
    const editor = page.getByRole("dialog", { name: zh ? "调整管理目标" : "Adjust management targets", exact: true })
    await expect(editor).toHaveAttribute("aria-busy", "true")
    await page.keyboard.press("Escape"); await expect(editor).toBeVisible()
    release()
    await expect(editor.getByRole("textbox", { name: zh ? "服务 ID 1" : "Server ID 1", exact: true })).toHaveValue("service-0000")
    await page.keyboard.press("Escape"); await expect(editor).toHaveCount(0)
    await expect(page.getByRole("button", { name: zh ? "调整管理目标" : "Adjust targets", exact: true })).toBeFocused()
    expect(model.writes).toHaveLength(0)
  })
  test(`management consent validates exact targets and keeps read-only scope ${locale}`, async ({ page }) => {
    await assets(page, locale, "light", true)
    const decisions: Record<string, unknown>[] = []
    await page.route("**/oauth/context?**", route => route.fulfill({ json: { csrf: "synthetic-public-csrf", completed: false, phase: "authenticated", expires_at: now + 600, client: { id: "lgc_synthetic_read_management", name: "Synthetic read management" }, resource: initialGrant.resource, resource_kind: "management", scopes: ["operations.manage"], user: { id: "synthetic-admin", username: "synthetic-admin", display_name: "Synthetic administrator" }, tools: tools.filter(tool => tool.access === "read"), max_grant_days: 30, access_seconds: 600, refresh_days: 30 } }))
    await page.route("**/oauth/decision", route => { decisions.push(route.request().postDataJSON()); return route.fulfill({ status: 409, json: { error: "authorization_completed" } }) })
    await page.goto("/oauth/consent#request=synthetic-management-request")
    const picker = page.getByRole("region", { name: zh ? "MCP 和工具授权范围" : "MCP and tool authorization scope", exact: true })
    await picker.getByRole("checkbox").first().check()
    const allow = page.getByRole("button", { name: zh ? "允许 2 个工具" : "Allow 2 tools", exact: true })
    await allow.click()
    expect(decisions).toHaveLength(0)
    await expect(page.getByText(zh ? "逐项填写精确服务 ID 和创建/更新操作；不支持重复 ID、通配符或其他操作。" : "Enter exact server IDs and create/update actions. Duplicate IDs, wildcards and other actions are unsupported.", { exact: true })).toBeVisible()
    await page.getByRole("textbox", { name: zh ? "服务 ID 1" : "Server ID 1", exact: true }).fill("service-exact")
    await expect(allow).toBeEnabled()
    await allow.click()
    await expect.poll(() => decisions.length).toBe(1)
    expect(decisions[0].management_targets).toEqual({ "service-exact": ["create"] })
    expect(decisions[0].tool_ids).toEqual(["gate_mcp_config_plan", "gate_mcp_config_status"])
    expect(decisions[0]).not.toHaveProperty("scopes")
    await expect(allow).toHaveCount(0)
  })
}

import { expect, test, type Page } from "@playwright/test"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

// Actual compiled UI; every OAuth API, key and credential here is synthetic.
// No live key/client generation, external account or user connection is used.
const assets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static/console")
const activeKeys = [{ kid: "synthetic-active", active: true, retire_at: null }]
const initialConfig = { enabled: false, issuer: "https://gate.example.test", resource: "https://gate.example.test/mcp", revision: 1,
  metadata_url: "https://gate.example.test/.well-known/oauth-authorization-server", authorization_endpoint: "https://gate.example.test/oauth/authorize", token_endpoint: "https://gate.example.test/oauth/token", jwks_uri: "https://gate.example.test/oauth/jwks", signing_keys: [] as unknown }
const initialClient = { id: "lgc_synthetic_setup", name: "Synthetic setup client", redirect_uris: ["https://client.example.test/callback"], scopes: ["tools.read"], enabled: true, revision: 1, created_at: 1000 }
type Locale = "en-US" | "zh-CN"
type Model = { config: typeof initialConfig; reads: number; writes: Record<string, unknown>[]; rotations: number; configFailure: boolean; clientFailure: boolean; afterRotateRead: (() => Promise<void>) | null; client: typeof initialClient }
async function setup(page: Page, locale: Locale, theme = "light", overrides: Partial<typeof initialConfig> = {}) {
  const model: Model = { config: { ...initialConfig, ...overrides }, reads: 0, writes: [], rotations: 0, configFailure: false, clientFailure: false, afterRotateRead: null, client: { ...initialClient } }
  await page.addInitScript(({ locale, theme }) => { localStorage.setItem("lingshu-gate-console-locale", locale); localStorage.setItem("lingshu-gate-console-theme", theme) }, { locale, theme })
  await page.route("**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(assets, "index.html"), "utf8") }))
  await page.route("**/console/assets/**", route => {
    const name = path.basename(new URL(route.request().url()).pathname)
    return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(assets, "assets", name)) })
  })
  await page.route("**/healthz", route => route.fulfill({ json: { version: "0.4.1" } }))
  await page.route("**/v1/**", async route => {
    const pathname = new URL(route.request().url()).pathname, method = route.request().method()
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-manager", username: "synthetic-manager", display_name: "Synthetic manager", status: "active", role: "custom", roles: ["custom"], permissions: ["console.view", "external_connections.manage"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/config") {
      if (method === "GET") {
        model.reads++
        if (model.rotations && model.afterRotateRead) await model.afterRotateRead()
        return route.fulfill(model.configFailure ? { status: 503, json: { error: "request_failed" } } : { json: model.config })
      }
      if (method === "PUT") {
        const body = route.request().postDataJSON(); model.writes.push(body)
        if (body.enabled && !Array.isArray(model.config.signing_keys)) return route.fulfill({ status: 409, json: { error: "signing_key_required" } })
        model.config = { ...model.config, issuer: body.issuer, resource: body.resource, enabled: body.enabled, revision: model.config.revision + 1 }
        return route.fulfill({ json: model.config })
      }
    }
    if (pathname === "/v1/auth/oauth/keys/rotate" && method === "POST") {
      model.rotations++; model.config = { ...model.config, signing_keys: activeKeys }
      return route.fulfill({ json: model.config })
    }
    if (pathname === "/v1/auth/oauth/clients") return route.fulfill({ json: { clients: [model.client] } })
    if (pathname === `/v1/auth/oauth/clients/${model.client.id}` && method === "PATCH") {
      if (model.clientFailure) return route.fulfill({ status: 409, json: { error: "revision_conflict" } })
      model.client = { ...model.client, ...route.request().postDataJSON(), revision: model.client.revision + 1 }
      return route.fulfill({ json: { client: model.client } })
    }
    return route.fulfill({ status: 404, json: { error: "unmocked_synthetic_request" } })
  })
  await page.goto("/console/#/connectionInfrastructure")
  await expect(page.locator("#oauth-issuer")).toHaveValue(model.config.issuer)
  await expect(page.getByRole("button", { name: locale === "zh-CN" ? "登记客户端" : "Register client", exact: true })).toBeEnabled()
  return model
}
function enableSwitch(page: Page, zh: boolean) { return page.getByRole("switch", { name: zh ? "启用内置 OAuth" : "Enable built-in OAuth", exact: true }) }
function save(page: Page, zh: boolean) { return page.getByRole("button", { name: zh ? "保存" : "Save", exact: true }) }
async function capture(page: Page, name: string, state: string) {
  const directory = process.env.GATE_OAUTH_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" })
  writeFileSync(path.join(directory, `${name}.json`), JSON.stringify({ viewport: page.viewportSize(), state, allOAuthApisMocked: true, liveKeyGeneration: false }, null, 2))
}

const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
for (const size of sizes) for (const locale of ["en-US", "zh-CN"] as const) for (const theme of ["light", "dark"]) {
  const suffix = `${locale}-${theme}-${size.width}x${size.height}`
  test(`OAuth setup hints and controlled resource derivation ${suffix}`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize(size)
    const model = await setup(page, locale, theme)
    const issuer = page.locator("#oauth-issuer"), resource = page.locator("#oauth-resource"), toggle = enableSwitch(page, zh)
    await expect(toggle).toBeDisabled()
    await expect(resource).toHaveAttribute("placeholder", "https://gate.example.test/mcp")
    await expect(page.locator(".oauth-setup-steps li")).toHaveCount(4)
    await expect(page.locator("#oauth-enable-help")).toContainText(zh ? "先保存地址" : "Save URLs")
    await capture(page, `no-key-${suffix}`, "saved URLs; no key; disabled enable switch; four prerequisite steps")
    await page.getByRole("button", { name: zh ? "前往生成密钥" : "Go to generate key", exact: true }).click()
    await expect(page.locator("#oauth-generate-key")).toBeFocused()
    expect(model.rotations).toBe(0)
    await issuer.fill("https://next.example.test")
    await expect(resource).toHaveValue(initialConfig.resource)
    await resource.fill("")
    await issuer.fill("https://auto.example.test")
    await expect(resource).toHaveValue("https://auto.example.test/mcp")
    await issuer.fill("https://auto.example.test/")
    await expect(resource).toHaveValue("")
    await issuer.fill("https://again.example.test")
    await expect(resource).toHaveValue("https://again.example.test/mcp")
    await resource.fill("https://manual.example.test/mcp")
    await issuer.fill("https://last.example.test")
    await expect(resource).toHaveValue("https://manual.example.test/mcp")
    expect(model.writes).toHaveLength(0)
    await capture(page, `manual-resource-${suffix}`, "manual resource retained; no auto-save or key/client generation")
    await expect(save(page, zh)).toBeEnabled()
    await save(page, zh).click()
    await expect(page.getByRole("status").filter({ hasText: zh ? "配置已保存" : "Configuration saved" })).toBeVisible()
    expect(model.writes).toEqual([{ issuer: "https://last.example.test", resource: "https://manual.example.test/mcp", enabled: false, expected_revision: 1 }])
    await expect(toggle).toBeDisabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await capture(page, `saved-toast-${suffix}`, "lightweight saved message; addresses saved with OAuth disabled and no key")
  })
}

for (const locale of ["en-US", "zh-CN"] as const) {
  const zh = locale === "zh-CN"
  test(`OAuth key generation needs confirmation and a fresh successful read ${locale} @permissions`, async ({ page }) => {
    const model = await setup(page, locale)
    let releaseRead!: () => void
    const held = new Promise<void>(resolve => { releaseRead = resolve })
    model.afterRotateRead = () => held
    await page.locator("#oauth-generate-key").click()
    const confirmation = page.getByRole("alertdialog", { name: zh ? "生成或轮换签名密钥？" : "Generate or rotate signing key?", exact: true })
    expect(model.rotations).toBe(0)
    await confirmation.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    expect(model.rotations).toBe(0)
    await page.locator("#oauth-generate-key").click()
    await confirmation.getByRole("button", { name: zh ? "生成密钥" : "Generate key", exact: true }).click()
    await expect.poll(() => model.rotations).toBe(1)
    await expect(enableSwitch(page, zh)).toBeDisabled()
    await expect.poll(() => model.reads).toBeGreaterThanOrEqual(2)
    releaseRead()
    await expect(enableSwitch(page, zh)).toBeEnabled()
    await enableSwitch(page, zh).click()
    expect(model.writes).toHaveLength(0)
    await save(page, zh).click()
    const enable = page.getByRole("alertdialog", { name: zh ? "启用内置 OAuth？" : "Enable built-in OAuth?", exact: true })
    await enable.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    expect(model.writes).toHaveLength(0)
    await save(page, zh).click()
    await enable.getByRole("button", { name: zh ? "启用" : "Enable", exact: true }).click()
    await expect.poll(() => model.writes.length).toBe(1)
    expect(model.writes[0]).toMatchObject({ enabled: true, expected_revision: 1 })
  })
  test(`OAuth failed fresh key read fails closed and can retry without generation ${locale} @permissions`, async ({ page }) => {
    const model = await setup(page, locale)
    model.configFailure = true
    await page.locator("#oauth-generate-key").click()
    await page.getByRole("alertdialog").getByRole("button", { name: zh ? "生成密钥" : "Generate key", exact: true }).click()
    await expect(page.getByRole("button", { name: zh ? "重试密钥状态" : "Retry key status", exact: true })).toBeEnabled()
    await expect(enableSwitch(page, zh)).toBeDisabled()
    expect(model.rotations).toBe(1)
    await capture(page, `key-read-failed-${locale}`, "confirmed mock key operation; follow-up read fails; enable remains unavailable")
    model.configFailure = false
    await page.getByRole("button", { name: zh ? "重试密钥状态" : "Retry key status", exact: true }).click()
    await expect(enableSwitch(page, zh)).toBeEnabled()
    expect(model.rotations).toBe(1)
  })
  test(`OAuth key retry preserves dirty URLs and refuses revision rebasing ${locale} @permissions`, async ({ page }) => {
    const model = await setup(page, locale, "light", { signing_keys: null })
    await page.locator("#oauth-resource").fill("https://manual.example.test/mcp")
    model.config = { ...model.config, revision: 2, signing_keys: activeKeys }
    await page.getByRole("button", { name: zh ? "重试密钥状态" : "Retry key status", exact: true }).click()
    await expect(page.getByText(zh ? "对象已改变。刷新后核对，再保存。" : "This item changed. Refresh and review before saving.", { exact: true })).toBeVisible()
    await expect(page.locator("#oauth-resource")).toHaveValue("https://manual.example.test/mcp")
    await expect(enableSwitch(page, zh)).toBeDisabled()
    expect(model.writes).toHaveLength(0)
  })
  test(`OAuth enabled config stays enabled after failed load and can be explicitly disabled ${locale} @permissions`, async ({ page }) => {
    const model = await setup(page, locale, "light", { enabled: true, signing_keys: activeKeys })
    model.configFailure = true
    await page.getByRole("button", { name: zh ? "刷新" : "Refresh", exact: true }).click()
    await expect(page.getByRole("button", { name: zh ? "重试密钥状态" : "Retry key status", exact: true })).toBeEnabled()
    await expect(enableSwitch(page, zh)).toBeChecked()
    await expect(enableSwitch(page, zh)).toBeEnabled()
    expect(model.writes).toHaveLength(0)
    await enableSwitch(page, zh).click()
    await save(page, zh).click()
    const disable = page.getByRole("alertdialog", { name: zh ? "关闭内置 OAuth？" : "Disable built-in OAuth?", exact: true })
    await disable.getByRole("button", { name: zh ? "取消" : "Cancel", exact: true }).click()
    expect(model.writes).toHaveLength(0)
    await save(page, zh).click()
    await disable.getByRole("button", { name: zh ? "关闭 OAuth" : "Disable OAuth", exact: true }).click()
    await expect.poll(() => model.writes.length).toBe(1)
    expect(model.writes[0]).toMatchObject({ enabled: false })
  })
  test(`OAuth client success messages dismiss, expire, clear and never contain secrets ${locale}`, async ({ page }) => {
    const model = await setup(page, locale)
    async function editAndSave(name: string) {
      await page.getByRole("button", { name: model.client.name, exact: true }).click()
      const dialog = page.getByRole("dialog", { name: zh ? "编辑客户端" : "Edit client", exact: true })
      await expect(page.getByRole("status").filter({ hasText: zh ? "客户端已保存" : "Client saved" })).toHaveCount(0)
      await dialog.getByLabel(zh ? "客户端名称" : "Client name", { exact: true }).fill(name)
      await dialog.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click()
      return dialog
    }
    await editAndSave("Synthetic first")
    const message = page.getByRole("status").filter({ hasText: zh ? "客户端已保存。" : "Client saved." })
    await expect(message).toBeVisible()
    await expect(message).toHaveAttribute("aria-live", "polite")
    expect(await message.evaluate(element => getComputedStyle(element).position)).toBe("fixed")
    await expect(message).not.toContainText("secret")
    await capture(page, `client-toast-${locale}`, "synthetic client edit; dismissible fixed polite success; no secret")
    await message.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).click()
    await expect(message).toHaveCount(0)
    await editAndSave("Synthetic second")
    await expect(message).toBeVisible()
    // Ordinary form input does not restart the success message's lifetime.
    await page.locator("#oauth-issuer").fill("https://changed.example.test")
    await expect(message).toHaveCount(0, { timeout: 7000 })
    await editAndSave("Synthetic third")
    await expect(message).toBeVisible()
    model.clientFailure = true
    const dialog = await editAndSave("Synthetic failed")
    await expect(dialog.getByRole("alert")).toContainText(zh ? "对象已改变" : "This item changed")
    await expect(message).toHaveCount(0)
    await expect(dialog.getByRole("alert")).toBeVisible()
  })
}

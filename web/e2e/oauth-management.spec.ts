import { expect, test, type Page } from "@playwright/test"
import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

// All API responses and credentials are synthetic. Uses built Console assets;
// this is UI behavior coverage, not an OAuth or external-account acceptance run.
const assetsPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static/console")
const syntheticClient = { id: "lgc_synthetic_management", name: "Synthetic research client", redirect_uris: ["https://client.example.test/callback"], scopes: ["tools.read"], enabled: true, revision: 1, created_at: 1000 }
const syntheticSecret = "synthetic-one-time-secret-only"
async function management(page: Page, locale: string, registered = false) {
  await page.addInitScript(value => {
    localStorage.setItem("lingshu-gate-console-locale", value)
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => undefined } })
  }, locale)
  await page.route("**/console/", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(assetsPath, "index.html"), "utf8") }))
  await page.route("**/console/assets/**", route => {
    const name = path.basename(new URL(route.request().url()).pathname)
    return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(assetsPath, "assets", name)) })
  })
  await page.route("**/healthz", route => route.fulfill({ json: { status: "ok", service: "lingshu-gate", version: "0.3.1" } }))
  let clients = registered ? [syntheticClient] : []
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-manager", username: "synthetic-manager", display_name: "Synthetic manager", status: "active", role: "custom", roles: ["custom"], permissions: ["console.view", "external_connections.manage"], auth_type: "session", scopes: [], must_change_password: false } })
    if (pathname === "/v1/auth/oauth/config") return route.fulfill({ json: { enabled: false, issuer: "https://gate.example.test", resource: "https://gate.example.test/mcp", revision: 1, metadata_url: "https://gate.example.test/.well-known/oauth-authorization-server", authorization_endpoint: "https://gate.example.test/oauth/authorize", token_endpoint: "https://gate.example.test/oauth/token", jwks_uri: "https://gate.example.test/oauth/jwks", signing_keys: [] } })
    if (pathname === "/v1/auth/oauth/clients") {
      if (route.request().method() === "GET") return route.fulfill({ json: { clients } })
      if (route.request().method() === "POST") {
        clients = [syntheticClient]
        return route.fulfill({ status: 201, json: { client: syntheticClient, client_secret: syntheticSecret } })
      }
    }
    return route.fulfill({ status: 404, json: { detail: "Unmocked synthetic UI request" } })
  })
  await page.goto("/console/#/connectionInfrastructure")
  await expect(page.getByRole("button", { name: locale === "zh-CN" ? "登记客户端" : "Register client", exact: true })).toBeEnabled()
}

for (const locale of ["en-US", "zh-CN"]) {
  test(`OAuth clients distinguish no records from filtered records ${locale} @large-data`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await management(page, locale, true)
    const search = page.getByRole("textbox", { name: zh ? "搜索客户端" : "Search clients", exact: true })
    await search.fill("no-match-synthetic")
    await expect(page.getByText(zh ? "没有匹配的客户端。" : "No matching clients.", { exact: true })).toBeVisible()
    await expect(page.getByText(zh ? "尚未登记客户端。" : "No clients registered.", { exact: true })).toHaveCount(0)
    await page.getByRole("button", { name: zh ? "清除筛选" : "Clear filter", exact: true }).click()
    await expect(search).toHaveValue("")
    await expect(page.getByRole("button", { name: syntheticClient.name, exact: true })).toBeVisible()
  })
  for (const closeMethod of ["X", "Escape"]) {
    test(`OAuth one-time secret ${closeMethod} retains value unless saved ${locale} @permissions`, async ({ page }) => {
      const zh = locale === "zh-CN"
      await management(page, locale)
      await expect(page.getByText(zh ? "尚未登记客户端。" : "No clients registered.", { exact: true })).toBeVisible()
      await page.getByRole("button", { name: zh ? "登记客户端" : "Register client", exact: true }).click()
      const create = page.getByRole("dialog", { name: zh ? "登记客户端" : "Register client", exact: true })
      await create.getByLabel(zh ? "客户端名称" : "Client name", { exact: true }).fill(syntheticClient.name)
      await create.getByLabel(zh ? "回调地址 1" : "Redirect URI 1", { exact: true }).fill(syntheticClient.redirect_uris[0])
      await create.getByRole("button", { name: zh ? "保存" : "Save", exact: true }).click()
      const secret = page.getByRole("dialog", { name: zh ? "仅展示一次的客户端密钥" : "One-time client secret", exact: true })
      await expect(secret.getByLabel("Client Secret", { exact: true })).toHaveValue(syntheticSecret)
      await secret.getByRole("button", { name: zh ? "复制密钥" : "Copy secret", exact: true }).click()
      await expect(secret.getByRole("button", { name: zh ? "已复制" : "Copied", exact: true })).toBeVisible()
      if (closeMethod === "X") await secret.getByRole("button", { name: zh ? "关闭" : "Close", exact: true }).click()
      else { await secret.getByLabel("Client Secret", { exact: true }).focus(); await page.keyboard.press("Escape") }
      const warning = page.getByRole("alertdialog", { name: zh ? "关闭后无法再次查看密钥" : "The secret cannot be viewed after closing", exact: true })
      await expect(warning).toContainText(zh ? "复制到剪贴板不代表已安全保存" : "Copying to the clipboard is not confirmation of safe storage")
      await warning.getByRole("button", { name: zh ? "保留密钥窗口" : "Keep secret open", exact: true }).click()
      await expect(secret.getByLabel("Client Secret", { exact: true })).toHaveValue(syntheticSecret)
      await secret.getByRole("button", { name: zh ? "已保存，关闭" : "Saved, close", exact: true }).click()
      await expect(secret).toHaveCount(0)
      await expect(page.getByRole("alertdialog")).toHaveCount(0)
    })
  }
}

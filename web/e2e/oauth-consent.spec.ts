import { expect, test, type Page } from "@playwright/test"
import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

// Browser behavior with built public assets and synthetic, mocked OAuth APIs.
// This does not exercise real OAuth, cookie transport or a ChatGPT connection.
const publicAssets = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/lingshu_gate/static/oauth")
const tools = Array.from({ length: 5000 }, (_, index) => ({ id: `mcp.service-${Math.floor(index / 50)}.tool-${index}`, name: `Tool ${index}`, server_id: `service-${Math.floor(index / 50)}`, server_name: `Synthetic catalog ${Math.floor(index / 50)}`, access: index % 2 ? "write" : "read", snapshot: "synthetic" }))
const requestId = "synthetic-request-" + "a".repeat(32)
function context(loggedIn = true) {
  return { csrf: "synthetic-csrf-" + "b".repeat(32), completed: false, phase: loggedIn ? "authenticated" : "preauth", expires_at: Math.floor(Date.now() / 1000) + 600,
    client: { id: "lgc_synthetic", name: "Research client" }, resource: "https://gate.example.test/mcp",
    scopes: ["tools.read", "tools.invoke"], user: loggedIn ? { id: "immutable-alice", username: "alice", display_name: "Alice" } : null,
    tools: loggedIn ? tools : [], max_grant_days: 30, access_seconds: 600, refresh_days: 30 }
}

for (const locale of ["en-US", "zh-CN"]) {
  test(`OAuth direct access filters and reset preserve selected scope ${locale} @large-data`, async ({ page }) => {
    const zh = locale === "zh-CN"
    await page.setViewportSize({ width: 1600, height: 900 })
    await assets(page, locale)
    await page.route("**/oauth/context?**", route => route.fulfill({ json: context() }))
    await page.goto(`/oauth/consent#request=${requestId}`)
    const picker = page.getByRole("region", { name: zh ? "MCP 和工具授权范围" : "MCP and tool authorization scope" })
    const all = picker.getByRole("radio", { name: zh ? "全部" : "All", exact: true })
    await expect(all).toBeChecked()
    await picker.getByRole("checkbox").first().check()
    await picker.getByRole("radio", { name: zh ? "只读" : "Read", exact: true }).check()
    await expect(picker.getByRole("status")).toContainText(zh ? "筛选匹配 2500 项" : "2500 filter matches")
    const mcp = picker.getByRole("combobox", { name: zh ? "按 MCP 筛选" : "Filter by MCP" })
    await mcp.click()
    await mcp.fill("Synthetic catalog 99")
    const option = page.locator(".ant-select-item-option").filter({ hasText: "Synthetic catalog 99" })
    await expect(option).toContainText("service-99")
    await option.click()
    await expect(picker.getByRole("status")).toContainText(zh ? "筛选匹配 25 项" : "25 filter matches")
    await picker.getByRole("radio", { name: zh ? "写入" : "Write", exact: true }).check()
    const search = picker.getByRole("textbox", { name: zh ? "搜索当前范围内的工具" : "Search tools in the current scope" })
    await search.fill("tool-4999")
    await expect(picker.getByText("mcp.service-99.tool-4999", { exact: true })).toBeVisible()
    await expect(picker.locator("tbody")).toContainText("Synthetic catalog 99")
    await picker.getByRole("button", { name: zh ? "重置筛选" : "Reset filters", exact: true }).click()
    await expect(search).toHaveValue("")
    await expect(all).toBeChecked()
    await expect(picker.getByRole("status")).toContainText(zh ? "已选 50 / 5000" : "50 / 5000 tools selected")
    await expect(picker.getByRole("status")).toContainText(zh ? "筛选匹配 5000 项" : "5000 filter matches")
    await picker.locator(".ant-pagination-next").click()
    await expect(picker.getByText("1–50 / 5000", { exact: true })).toHaveCount(0)
    await picker.getByRole("button", { name: zh ? "重置筛选" : "Reset filters", exact: true }).click()
    await expect(picker.getByText("1–50 / 5000", { exact: true })).toBeVisible()
    await expect(picker.getByRole("checkbox").first()).toBeChecked()
  })
}
async function assets(page: Page, locale: string) {
  await page.addInitScript(value => localStorage.setItem("lingshu-gate-console-locale", value), locale)
  await page.route("**/oauth/consent", route => route.fulfill({ contentType: "text/html", body: readFileSync(path.join(publicAssets, "oauth.html"), "utf8") }))
  await page.route("**/oauth/assets/**", route => {
    const name = path.basename(new URL(route.request().url()).pathname)
    return route.fulfill({ contentType: name.endsWith(".css") ? "text/css" : "application/javascript", body: readFileSync(path.join(publicAssets, "assets", name)) })
  })
}
for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) {
  for (const locale of ["en-US", "zh-CN"]) {
    test(`OAuth tool scope ${width}x${height} ${locale} @large-data`, async ({ page }) => {
      await page.setViewportSize({ width, height })
      await assets(page, locale)
      let privateRequests = 0
      await page.route("**/v1/**", route => { privateRequests++; return route.abort() })
      await page.route("**/oauth/context?**", route => route.fulfill({ json: context() }))
      await page.goto(`/oauth/consent#request=${requestId}`)
      await expect(page.getByRole("heading", { name: "Research client" })).toBeVisible()
      await expect(page.getByText("Alice", { exact: true })).toBeVisible()
      await page.getByRole("checkbox").first().check()
      await expect(page.getByRole("button", { name: locale === "zh-CN" ? "允许 50 个工具" : "Allow 50 tools" })).toBeVisible()
      await page.getByLabel(locale === "zh-CN" ? "搜索当前范围内的工具" : "Search tools in the current scope").fill("tool-4999")
      await expect(page.getByText("mcp.service-99.tool-4999", { exact: true })).toBeVisible()
      await expect(page.getByRole("button", { name: locale === "zh-CN" ? "允许 50 个工具" : "Allow 50 tools" })).toBeEnabled()
      expect(await page.locator("body").evaluate(element => element.scrollWidth <= window.innerWidth)).toBe(true)
      expect(privateRequests).toBe(0)
    })
  }
}

test("OAuth login expiry preserves selection and requires reauthentication @permissions", async ({ page }) => {
  await assets(page, "en-US")
  let loggedIn = false
  let decisions = 0
  await page.route("**/oauth/context?**", route => route.fulfill({ json: context(loggedIn) }))
  await page.route("**/oauth/login", route => { loggedIn = true; return route.fulfill({ json: context(true) }) })
  await page.route("**/oauth/decision", route => { decisions++; loggedIn = false; return route.fulfill({ status: 401, json: { error: "login_required" } }) })
  await page.goto(`/oauth/consent#request=${requestId}`)
  await page.getByLabel("Username", { exact: true }).fill("alice")
  await page.getByLabel("Password", { exact: true }).fill("Synthetic-Only-123!")
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await page.getByRole("checkbox").first().check()
  await page.getByRole("button", { name: "Allow 50 tools" }).click()
  await expect(page.getByText(/Sign-in expired/)).toBeVisible()
  await page.getByLabel("Password", { exact: true }).fill("Synthetic-Only-123!")
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await expect(page.getByRole("button", { name: "Allow 50 tools" })).toBeVisible()
  expect(decisions).toBe(1)
})

test("OAuth completed submission cannot be repeated @permissions", async ({ page }) => {
  await assets(page, "en-US")
  let decisions = 0
  await page.route("**/oauth/context?**", route => route.fulfill({ json: context() }))
  await page.route("**/oauth/decision", async route => {
    decisions++
    await new Promise(resolve => setTimeout(resolve, 100))
    await route.fulfill({ status: 409, json: { error: "authorization_completed" } })
  })
  await page.goto(`/oauth/consent#request=${requestId}`)
  await page.getByRole("checkbox").first().check()
  await page.getByRole("button", { name: "Allow 50 tools" }).dblclick({ force: true })
  await expect(page.getByText(/already processed/)).toBeVisible()
  expect(decisions).toBe(1)
  await expect(page.getByRole("button", { name: "Allow 50 tools" })).toHaveCount(0)
})

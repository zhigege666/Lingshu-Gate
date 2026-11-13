import { expect, test, type Page } from "@playwright/test"
import { mkdirSync } from "node:fs"
import path from "node:path"
import { login, expectInViewportAndUnobscured } from "./helpers"

async function setup(page: Page, independent = false, scopes = ["tools.read", "tools.invoke"]) {
  await login(page)
  await page.addInitScript(() => {
    localStorage.setItem("lingshu-gate-console-locale", "zh-CN")
    localStorage.setItem("lingshu-gate-console-theme", "light")
  })
  const token = { id: "synthetic-scope-editor", name: "桌面测试授权", token_prefix: "synthetic", scopes, created_at: "2026-01-01T00:00:00Z", authorization_mode: independent ? "independent" : "account" }
  const tokenPath = `/v1/auth/tokens/${token.id}`
  const servers = Array.from({ length: 100 }, (_, index) => ({ server_id: `synthetic-mcp-${index}`, server_name: `测试 MCP ${index}`, server_binding: `synthetic-binding-${index}`, tool_count: 1 }))
  const tools = servers.map(server => ({ id: `${server.server_id}.read`, name: "读取测试数据", server_id: server.server_id, access: "read", snapshot: "synthetic-snapshot", currently_authorized: true }))
  let reads = 0
  const writes: { path: string; body: Record<string, unknown> }[] = []
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname
    if (route.request().method() === "GET") {
      if (pathname === "/v1/auth/tokens") return route.fulfill({ json: { tokens: [token] } })
      if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [] } })
      if (pathname === "/v1/auth/external-grants") return route.fulfill({ json: { grants: [], connection_ready: false, activation_errors: [] } })
      if (pathname === `${tokenPath}/authorization-options`) {
        reads++
        return route.fulfill({ json: { revision: reads, mode: token.authorization_mode, scopes: token.scopes, tool_ids: [], server_policies: [], rate_per_minute: independent ? 300 : null, concurrency: independent ? 5 : null, csrf: "synthetic-csrf", catalog_revision: `synthetic-catalog-${reads}`, tools, servers } })
      }
      return route.continue()
    }
    const body = route.request().postDataJSON()
    writes.push({ path: pathname, body })
    if (pathname === `${tokenPath}/authorization-preview`) return route.fulfill({ json: { ...body, confirmation: "synthetic-confirmation", added: [], removed: [] } })
    if (pathname === `${tokenPath}/authorization`) return route.fulfill({ json: token })
    return route.fulfill({ status: 500, json: { error: "Unexpected synthetic mutation" } })
  })
  await page.goto("/console/#/myConnections")
  await page.getByRole("row").filter({ hasText: token.name }).getByRole("button", { name: "调整授权", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "调整授权", exact: true })
  await expect(dialog.getByRole("tab", { name: "MCP 范围", exact: true })).toBeVisible()
  return { dialog, writes, tokenPath }
}

async function capture(page: Page, name: string) {
  const directory = process.env.GATE_UI_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" })
}

for (const [width, height] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]]) {
  test(`Token access scope layout ${width}x${height} @visual`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const { dialog, writes } = await setup(page)
    await expect(dialog.getByText("尚未修改", { exact: true })).toBeVisible()
    await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
    await expect(dialog.getByRole("spinbutton", { name: "每分钟调用上限", exact: true })).toHaveValue("6000")
    await expect(dialog.getByText(/当前：未设置/)).toBeVisible()
    await dialog.getByRole("tab", { name: "MCP 范围", exact: true }).click()
    await expectInViewportAndUnobscured(dialog.getByRole("button", { name: "取消", exact: true }))
    await capture(page, `token-access-account-${width}x${height}`)
    await dialog.getByRole("radio", { name: "独立 MCP 范围", exact: true }).check()
    await expect(dialog.getByRole("table")).toBeVisible()
    await expect(dialog.getByRole("radio", { name: "跟随账号权限", exact: true })).toBeEnabled()
    expect(await dialog.locator(".gate-dialog-body").evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    await expectInViewportAndUnobscured(dialog.getByRole("button", { name: "保存授权", exact: true }))
    await capture(page, `token-access-independent-${width}x${height}`)
    await dialog.getByRole("radio", { name: "跟随账号权限", exact: true }).check()
    await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeDisabled()
    await dialog.getByRole("button", { name: "取消", exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(writes).toEqual([])
  })
}

test("Token mode drafts survive refresh and only active scope is submitted @permissions", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const { dialog, writes, tokenPath } = await setup(page)
  const modes = dialog.getByRole("radiogroup", { name: "范围模式", exact: true })
  await modes.getByRole("radio", { name: "独立 MCP 范围", exact: true }).check()
  const serverMode = dialog.getByRole("radiogroup", { name: "synthetic-mcp-0 授权方式", exact: true })
  await serverMode.getByRole("radio", { name: "服务只读", exact: true }).check()
  await dialog.getByRole("button", { name: "刷新可授权范围", exact: true }).click()
  await expect(serverMode.getByRole("radio", { name: "服务只读", exact: true })).toBeChecked()
  await expect(dialog.getByRole("radiogroup", { name: "synthetic-mcp-1 授权方式", exact: true }).getByRole("radio", { name: "不授权", exact: true })).toBeChecked()
  await modes.getByRole("radio", { name: "跟随账号权限", exact: true }).check()
  await expect(dialog.getByText("尚未修改", { exact: true })).toBeVisible()
  await modes.getByRole("radio", { name: "独立 MCP 范围", exact: true }).check()
  await expect(serverMode.getByRole("radio", { name: "服务只读", exact: true })).toBeChecked()
  await modes.getByRole("radio", { name: "跟随账号权限", exact: true }).check()
  await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
  await dialog.getByRole("spinbutton", { name: "每分钟调用上限", exact: true }).fill("301")
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  await expect(page.getByRole("region", { name: "授权变更明细", exact: true })).toHaveCount(0)
  await expect(dialog).toHaveCount(0)
  expect(writes.map(write => write.path)).toEqual([`${tokenPath}/authorization-preview`, `${tokenPath}/authorization`])
  for (const write of writes) {
    expect(write.body.mode).toBe("account")
    expect(write.body.tool_ids).toEqual([])
    expect(write.body.server_policies).toEqual([])
    expect(write.body.rate_per_minute).toBe(301)
    expect(write.body.expected_revision).toBe(2)
  }
})

test("Saved independent token can explicitly switch to account inheritance @permissions", async ({ page }) => {
  const { dialog, writes, tokenPath } = await setup(page, true)
  await expect(dialog.getByRole("radio", { name: "跟随账号权限", exact: true })).toBeEnabled()
  await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
  await expect(dialog.getByRole("spinbutton", { name: "每分钟调用上限", exact: true })).toHaveValue("300")
  await expect(dialog.getByRole("spinbutton", { name: "并发上限", exact: true })).toHaveValue("5")
  await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeDisabled()
  expect(writes).toEqual([])
  await dialog.getByRole("tab", { name: "MCP 范围", exact: true }).click()
  await dialog.getByRole("radio", { name: "跟随账号权限", exact: true }).check()
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  const review = page.getByRole("dialog", { name: "检查授权变更", exact: true })
  await expect(review).toContainText("后续")
  expect(writes.map(write => write.path)).toEqual([`${tokenPath}/authorization-preview`])
  await review.getByRole("button", { name: "确认扩大授权", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes.map(write => write.path)).toEqual([`${tokenPath}/authorization-preview`, `${tokenPath}/authorization`])
  for (const write of writes) expect(write.body).toMatchObject({ mode: "account", scopes: ["tools.read", "tools.invoke"],
    tool_ids: [], server_policies: [], rate_per_minute: 300, concurrency: 5, expected_revision: 1 })
})

test("Choosing MCP scope adds only the required grantable functional permission in place @permissions", async ({ page }) => {
  const { dialog, writes } = await setup(page, true, ["operations.manage"])
  await dialog.getByRole("radiogroup", { name: "synthetic-mcp-0 授权方式", exact: true }).getByRole("radio", { name: "服务只读", exact: true }).check()
  await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeEnabled()
  await expect(dialog.getByRole("button", { name: "补齐上述功能权限", exact: true })).toHaveCount(0)
  await expect(dialog.getByRole("tab", { name: "MCP 范围", exact: true })).toHaveAttribute("aria-selected", "true")
  expect(writes).toEqual([])
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  expect(writes).toHaveLength(1)
  expect(writes[0].body.scopes).toEqual(["operations.manage", "tools.read"])
  expect(writes[0].body.scopes).not.toContain("tools.invoke")
})

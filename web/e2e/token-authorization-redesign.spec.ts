import { expect, test, type Locator, type Page } from "@playwright/test"
import { mkdirSync, writeFileSync } from "node:fs"
import path from "node:path"
import { login, expectInViewportAndUnobscured } from "./helpers"

let runtimeErrors: string[] = []
let consoleErrors: string[] = []
test.beforeEach(({ page }) => {
  runtimeErrors = []; consoleErrors = []
  page.on("pageerror", error => runtimeErrors.push(error.message))
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()) })
})
test.afterEach(async ({}, info) => {
  await info.attach("browser-errors", { body: JSON.stringify({ runtimeErrors, consoleErrors }), contentType: "application/json" })
  expect(runtimeErrors).toEqual([])
  expect(consoleErrors.filter(message => !/Failed to load resource.*503/.test(message))).toEqual([])
})

async function setup(page: Page, settings: { cross?: boolean; scopeEditable?: boolean; create?: boolean; unknown?: false | "server" | "invalid" | "missing-secret"; reclassified?: boolean } = {}) {
  await login(page)
  await page.addInitScript(() => {
    localStorage.setItem("lingshu-gate-console-locale", "zh-CN")
    localStorage.setItem("lingshu-gate-console-theme", "light")
  })
  const servers = [
    { server_id: "docs", server_name: "内部文档", server_binding: settings.cross ? "docs-replaced" : "docs-original", tool_count: 1 },
    { server_id: "projects", server_name: "项目管理", server_binding: "projects-original", tool_count: 4 },
    { server_id: "code", server_name: "代码仓库", server_binding: "code-original", tool_count: 2 },
    { server_id: "data", server_name: "数据查询", server_binding: "data-original", tool_count: 1 },
  ]
  const tools = [
    { id: "docs.search", name: "搜索文档", server_id: "docs", access: "read" },
    { id: "projects.list", name: "查询项目", server_id: "projects", access: "read" },
    { id: "projects.tasks", name: "读取任务", server_id: "projects", access: "read" },
    { id: "projects.members", name: "查看成员", server_id: "projects", access: "read" },
    { id: "projects.create", name: "创建任务", server_id: "projects", access: "write" },
    { id: "code.read", name: "读取代码", server_id: "code", access: "read" },
    { id: "code.write", name: "创建分支", server_id: "code", access: "write" },
    { id: "data.query", name: "查询数据", server_id: "data", access: "read" },
  ].map(tool => ({ ...tool, server_name: servers.find(server => server.server_id === tool.server_id)!.server_name, currently_authorized: true, snapshot: "synthetic-1" }))
  const initialIds = settings.create ? [] : ["projects.list", "projects.tasks", ...(settings.cross ? ["code.read"] : [])]
  const token = { id: "synthetic-redesign-token", name: "研发工作台", token_prefix: "synthetic", scopes: settings.reclassified ? ["tools.read"] : ["tools.read", "tools.invoke"], created_at: "2026-01-01T00:00:00Z", authorization_mode: "independent", rate_per_minute: 6000, concurrency: 100 }
  const tokenPath = settings.create ? "/v1/auth/tokens" : `/v1/auth/tokens/${token.id}`
  const writes: { path: string; body: any }[] = []
  let reads = 0
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname
    if (route.request().method() === "GET") {
      if (pathname === "/v1/auth/tokens") return route.fulfill({ json: { tokens: settings.create ? [] : [token] } })
      if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [] } })
      if (pathname === "/v1/auth/external-grants") return route.fulfill({ json: { grants: [], connection_ready: false, activation_errors: [] } })
      if (pathname === `${tokenPath}/authorization-options`) {
        reads++
        return route.fulfill({ json: {
          revision: reads, mode: "independent", scopes: token.scopes, tool_ids: initialIds,
          server_policies: settings.create ? [] : [{ server_id: "docs", server_binding: "docs-original", mode: "continuous", access: "read" }],
          rate_per_minute: 6000, concurrency: 100, csrf: "synthetic-csrf", catalog_revision: `synthetic-catalog-${reads}`,
          tools: settings.reclassified ? tools.map(tool => tool.id === "projects.tasks" ? { ...tool, access: "write" } : tool) : settings.cross && reads > 1 ? tools.filter(tool => tool.id !== "projects.members") : tools,
          selected_tools: tools.filter(tool => initialIds.includes(tool.id)), servers, scope_editable: settings.scopeEditable !== false,
        } })
      }
      return route.continue()
    }
    const body = route.request().postDataJSON()
    writes.push({ path: pathname, body })
    if (pathname === `${tokenPath}/authorization-preview`) return route.fulfill({ json: { ...body, confirmation: `synthetic-confirmation-${writes.length}`, added: body.tool_ids.filter((id: string) => !initialIds.includes(id)), removed: initialIds.filter(id => !body.tool_ids.includes(id)) } })
    if (pathname === `${tokenPath}/authorization`) return settings.unknown === "missing-secret" ? route.fulfill({ json: token }) : settings.unknown === "invalid" ? route.fulfill({ status: 200, contentType: "application/json", body: "{broken" }) : settings.unknown ? route.fulfill({ status: 503, json: { detail: "Synthetic unknown result" } }) : route.fulfill({ json: { ...token, ...(settings.create ? { token: "synthetic-one-time-secret" } : {}) } })
    return route.fulfill({ status: 500, json: { error: "Unexpected synthetic mutation" } })
  })
  await page.goto("/console/#/myConnections")
  if (settings.create) {
    await page.getByRole("button", { name: "创建 API 令牌", exact: true }).click()
  } else await page.getByRole("row").filter({ hasText: token.name }).getByRole("button", { name: "调整授权", exact: true }).click()
  const dialog = page.locator('[role="dialog"].token-authorization-dialog')
  await expect(dialog.getByRole("tab", { name: "MCP 范围", exact: true })).toBeVisible()
  return { dialog, writes, tokenPath }
}

async function capture(page: Page, dialog: Locator, name: string) {
  const directory = process.env.GATE_UI_SCREENSHOT_DIR
  const metrics = await dialog.evaluate(element => {
    const body = element.querySelector<HTMLElement>(".gate-dialog-body")!
    const rect = element.getBoundingClientRect()
    return { width: rect.width, top: rect.top, bottom: rect.bottom, bodyOverflow: body.scrollWidth - body.clientWidth, pageOverflow: document.documentElement.scrollWidth - innerWidth }
  })
  expect(metrics.bodyOverflow).toBeLessThanOrEqual(1)
  expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
  expect(metrics.top).toBeGreaterThanOrEqual(0)
  expect(metrics.bottom).toBeLessThanOrEqual(page.viewportSize()!.height)
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" })
  await dialog.screenshot({ path: path.join(directory, `${name}-dialog.png`), animations: "disabled" })
  writeFileSync(path.join(directory, `${name}.json`), JSON.stringify(metrics, null, 2))
}

for (const [width, height] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]]) {
  test(`Token redesign inline and review ${width}x${height} @visual`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    const { dialog, writes } = await setup(page)
    await expect(dialog.getByRole("radio", { name: "跟随账号权限", exact: true })).toBeEnabled()
    await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeDisabled()
    await capture(page, dialog, `redesign-default-${width}x${height}`)
    await dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true }).click()
    const member = dialog.getByRole("checkbox", { name: "查看成员 (projects.members)", exact: true })
    await member.check()
    await expect(dialog.getByRole("row").filter({ has: page.getByRole("button", { name: "项目管理 选择指定工具", exact: true }) })).toContainText("指定 3 个工具")
    await expect(dialog.getByText("已修改 1 个 MCP，尚未保存", { exact: true })).toBeVisible()
    await expectInViewportAndUnobscured(dialog.getByRole("button", { name: "保存授权", exact: true }))
    await capture(page, dialog, `redesign-inline-${width}x${height}`)
    await dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true }).click()
    await dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true }).click()
    await expect(member).toBeChecked()
    await dialog.getByRole("tab", { name: "功能权限", exact: true }).click()
    await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
    await expect(dialog.getByRole("spinbutton", { name: "每分钟调用上限", exact: true })).toHaveValue("6000")
    await dialog.getByRole("tab", { name: "MCP 范围", exact: true }).click()
    await expect(member).toBeChecked()
    expect(writes).toEqual([])
    await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
    const review = dialog.getByRole("region", { name: "授权变更明细", exact: true })
    await expect(review).toContainText("指定 2 个工具")
    await expect(review).toContainText("指定 3 个工具")
    await expect(review.getByRole("heading", { name: "新增工具", exact: true })).toBeVisible()
    await expect(review).not.toContainText("每分钟调用上限")
    await expect(review).not.toContainText("内部文档")
    expect(writes).toHaveLength(1)
    await capture(page, dialog, `redesign-review-${width}x${height}`)
    await dialog.getByRole("button", { name: "返回编辑", exact: true }).click()
    await expect(member).toBeChecked()
    await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeFocused()
  })
}

test("Token redesign isolates MCP drafts, retains unavailable tools and explicitly rebinds identities @permissions", async ({ page }) => {
  const { dialog, writes, tokenPath } = await setup(page, { cross: true })
  await dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true }).click()
  await dialog.getByRole("checkbox", { name: "查看成员 (projects.members)", exact: true }).check()
  await dialog.getByRole("button", { name: "代码仓库 选择指定工具", exact: true }).click()
  await expect(dialog.getByRole("checkbox", { name: "读取代码 (code.read)", exact: true })).toBeChecked()
  await dialog.getByRole("checkbox", { name: "创建分支 (code.write)", exact: true }).check()
  await dialog.getByRole("radiogroup", { name: "docs 授权方式", exact: true }).getByRole("radio", { name: "服务读写", exact: true }).check()
  await dialog.getByRole("tab", { name: "功能权限", exact: true }).click()
  await dialog.getByRole("switch", { name: "写入工具", exact: true }).click()
  await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeDisabled()
  await expect(dialog.locator(".token-authorization-conflict")).toContainText("内部文档")
  await expect(dialog.locator(".token-authorization-conflict")).toContainText("代码仓库")
  await dialog.getByRole("switch", { name: "只读工具", exact: true }).click()
  await expect(dialog.locator(".token-authorization-conflict")).toContainText("项目管理")
  await dialog.getByRole("tab", { name: "MCP 范围", exact: true }).click()
  await expect(dialog.getByRole("radiogroup", { name: "docs 授权方式", exact: true }).getByRole("radio", { name: "服务读写", exact: true })).toBeChecked()
  await expect(dialog.getByRole("radiogroup", { name: "docs 授权方式", exact: true }).getByRole("radio", { name: "服务读写", exact: true })).toBeEnabled()
  await dialog.getByRole("button", { name: "调整功能权限", exact: true }).click()
  await dialog.getByRole("switch", { name: "只读工具", exact: true }).click()
  await dialog.getByRole("switch", { name: "写入工具", exact: true }).click()
  await dialog.getByRole("tab", { name: "MCP 范围", exact: true }).click()
  await dialog.getByRole("button", { name: "刷新可授权范围", exact: true }).click()
  await dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true }).click()
  const unavailable = dialog.getByRole("checkbox", { name: "查看成员 (projects.members)", exact: true })
  await expect(unavailable).toBeChecked()
  await expect(dialog.getByText("当前不可用", { exact: true })).toBeVisible()
  await unavailable.uncheck()
  await expect(unavailable).toBeDisabled()
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  expect(writes[0].body.server_policies).toEqual([{ server_id: "docs", mode: "continuous", access: "write", server_binding: "docs-original" }])
  await dialog.getByRole("button", { name: "返回编辑", exact: true }).click()
  await dialog.getByRole("button", { name: "重新确认服务", exact: true }).click()
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  await expect(dialog.getByText("重新绑定当前服务身份", { exact: true })).toBeVisible()
  await dialog.getByRole("button", { name: "确认扩大授权", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes.map(write => write.path)).toEqual([`${tokenPath}/authorization-preview`, `${tokenPath}/authorization-preview`, `${tokenPath}/authorization`])
  const saved = writes[2].body
  expect(saved.tool_ids.sort()).toEqual(["projects.list", "projects.tasks", "code.read", "code.write"].sort())
  expect(saved.server_policies).toEqual([{ server_id: "docs", mode: "continuous", access: "write", server_binding: "docs-replaced" }])
  expect(saved.expected_revision).toBe(2)
  expect(saved.catalog_revision).toBe("synthetic-catalog-2")
  const { csrf: _csrf, ...previewBody } = writes[1].body
  expect(saved).toEqual({ ...previewBody, confirmation: "synthetic-confirmation-2" })
})

test("Token redesign retains permission restrictions and quota-only fallback @permissions", async ({ page }) => {
  const { dialog, writes } = await setup(page, { scopeEditable: false })
  await expect(dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true })).toBeDisabled()
  for (const radio of await dialog.getByRole("radiogroup", { name: "projects 授权方式", exact: true }).getByRole("radio").all()) await expect(radio).toBeDisabled()
  await dialog.getByRole("tab", { name: "功能权限", exact: true }).click()
  for (const control of await dialog.getByRole("switch").all()) await expect(control).toBeDisabled()
  await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
  await dialog.getByRole("spinbutton", { name: "并发上限", exact: true }).fill("90")
  await dialog.getByRole("tab", { name: "MCP 范围", exact: true }).click()
  await dialog.getByRole("button", { name: "刷新可授权范围", exact: true }).click()
  await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
  await expect(dialog.getByRole("spinbutton", { name: "并发上限", exact: true })).toHaveValue("90")
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole("region", { name: "授权变更明细", exact: true })).toHaveCount(0)
  expect(writes).toHaveLength(2)
  for (const write of writes) {
    expect(write.body.tool_ids).toEqual(["projects.list", "projects.tasks"])
    expect(write.body.concurrency).toBe(90)
  }
})

for (const unknown of [false, "server", "invalid", "missing-secret"] as const) test(`Token redesign create ${unknown ? `${unknown} result blocks replay` : "secret remains one-time"} @permissions`, async ({ page }) => {
  const { writes, tokenPath } = await setup(page, { create: true, unknown })
  const dialog = page.getByRole("dialog", { name: "创建 API 令牌", exact: true })
  await dialog.getByRole("textbox", { name: "授权名称", exact: true }).fill("新建测试授权")
  const saved = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === `${tokenPath}/authorization`)
  await dialog.getByRole("button", { name: "创建令牌", exact: true }).click()
  expect((await saved).status()).toBe(unknown === "server" ? 503 : 200)
  await expect(dialog.getByRole("region", { name: "授权变更明细", exact: true })).toHaveCount(0)
  if (unknown) {
    // The alert contains both the notice and its readback button. Its complete
    // element text therefore cannot exactly equal the notice sentence alone.
    const notice = dialog.getByRole("alert").filter({ hasText: "保存结果未知。" })
    await expect(notice).toBeVisible()
    await expect(notice).toContainText("草稿已保留，请先读取实际记录；不要重复创建令牌。")
    await expect(dialog.getByRole("button", { name: "创建令牌", exact: true })).toBeDisabled()
    await notice.getByRole("button", { name: "读取实际记录", exact: true }).click()
    await expect(dialog.getByText(/令牌明文无法再次读取/)).toBeVisible()
    await expect(dialog.getByRole("button", { name: "创建令牌", exact: true })).toBeDisabled()
  } else {
    await expect(dialog.getByText("synthetic-one-time-secret", { exact: true })).toBeVisible()
    await dialog.getByRole("button", { name: "关闭", exact: true }).last().click()
    await page.getByRole("alertdialog").getByRole("button", { name: "返回保存", exact: true }).click()
    await expect(dialog.getByText("synthetic-one-time-secret", { exact: true })).toBeVisible()
    await dialog.getByRole("button", { name: "关闭", exact: true }).last().click()
    await page.getByRole("alertdialog").getByRole("button", { name: "已保存，关闭", exact: true }).click()
    await expect(page.getByText("synthetic-one-time-secret", { exact: true })).toHaveCount(0)
  }
  expect(writes.map(write => write.path)).toEqual([`${tokenPath}/authorization-preview`, `${tokenPath}/authorization`])
})


test("Token quota save preserves saved classifications; an explicit scope edit completes required permissions @permissions", async ({ page }) => {
  const { dialog, writes } = await setup(page, { reclassified: true })
  await dialog.getByRole("tab", { name: "调用限制", exact: true }).click()
  await dialog.getByRole("spinbutton", { name: "并发上限", exact: true }).fill("90")
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(2)
  for (const write of writes) {
    expect(write.body.scopes).toEqual(["tools.read"])
    expect(write.body.tool_ids).toEqual(["projects.list", "projects.tasks"])
  }
  await page.getByRole("row").filter({ hasText: "研发工作台" }).getByRole("button", { name: "调整授权", exact: true }).click()
  await dialog.getByRole("button", { name: "项目管理 选择指定工具", exact: true }).click()
  await dialog.getByRole("checkbox", { name: "查询项目 (projects.list)", exact: true }).uncheck()
  await expect(dialog.getByRole("button", { name: "保存授权", exact: true })).toBeEnabled()
  await dialog.getByRole("button", { name: "保存授权", exact: true }).click()
  await expect(dialog.getByRole("region", { name: "授权变更明细", exact: true })).toBeVisible()
  expect(writes).toHaveLength(3)
  expect(writes[2].body.scopes).toEqual(["tools.read", "tools.invoke"])
  expect(writes[2].body.tool_ids).toEqual(["projects.tasks"])
})

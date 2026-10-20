import { expect, test, type Page } from "@playwright/test"

// UI fixtures only: every API call is intercepted, no node or business account is contacted.
const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
const timestamp = "2026-10-20T00:00:00Z"
const credential = () => ({ id: "synthetic-account", owner_id: "synthetic-admin", name: "测试环境医生", environment: "测试环境", business_role: "门诊医生",
  login_url: "https://app.example.test/#/login", scope: "shared", enabled: true, allow_http: false, version: 2,
  username_masked: "***", password_configured: true, allowed_user_ids: [], allowed_role_ids: ["role-doctor"],
  selectors: { username: null, password: null, submit: null }, created_at: timestamp, updated_at: timestamp,
  bindings: [{ id: "synthetic-binding", credential_id: "synthetic-account", server_id: "browser-test", adapter: "agent_browser", tool_prefix: "agent_browser_", enabled: true, revision: 1,
    synced_version: 1, sync_status: "pending", last_sync_at: timestamp, last_error_code: null as string | null }] })

async function openBusiness(page: Page, viewport = sizes[0], locale = "zh-CN", theme = "light", scope: "shared" | "personal" = "shared") {
  await page.setViewportSize(viewport)
  await page.addInitScript(({ locale, theme }) => {
    localStorage.setItem("lingshu-gate-console-locale", locale)
    localStorage.setItem("lingshu-gate-console-theme", theme)
  }, { locale, theme })
  let saved = { ...credential(), scope }
  let sessions = [{ id: "synthetic-session", server_id: "browser-test", logical_session: "task-demo", status: "active", credential_version: 1, created_at: timestamp, updated_at: timestamp }]
  const writes: { path: string; method: string; body: Record<string, unknown> }[] = []
  await page.route("**/healthz", route => route.fulfill({ json: { status: "ok", version: "0.5.1" } }))
  await page.route("**/v1/**", route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    if (path === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-admin", username: "synthetic-admin", display_name: "Synthetic admin", role: "admin", roles: ["admin"], status: "active", must_change_password: false, permissions: ["*"], scopes: ["*"], auth_type: "session" } })
    if (path === "/v1/credentials") return route.fulfill({ json: [] })
    if (path === "/v1/auth/downstream-credentials") return route.fulfill({ json: { credentials: [] } })
    if (path === "/v1/business-credentials/csrf") return route.fulfill({ json: { csrf: "synthetic-csrf" } })
    if (path === "/v1/business-credentials/targets") return route.fulfill({ json: {
      servers: [{ server_id: "browser-test", name: "测试浏览器节点", compatible: true, managed: true }, { server_id: "browser-next", name: "另一个测试节点", compatible: true, managed: false }],
      users: [{ id: "synthetic-user", label: "Synthetic user" }], roles: [{ id: "role-doctor", label: "Doctor" }],
    } })
    if (path === "/v1/business-credentials" && method === "GET") return route.fulfill({ json: { credentials: [saved] } })
    if (path === "/v1/business-credentials/synthetic-account/sessions" && method === "GET") return route.fulfill({ json: { sessions } })
    if (method !== "GET") {
      const body = request.postDataJSON() || {}
      writes.push({ path, method, body })
      if (path === "/v1/business-credentials" && method === "POST") {
        const { username: _username, password: _password, ...metadata } = body
        saved = { ...saved, ...metadata, version: 1, username_masked: "***", password_configured: true, bindings: [] }
        return route.fulfill({ json: saved })
      }
      if (path === "/v1/business-credentials/synthetic-account" && method === "PUT") {
        saved = { ...saved, ...body, version: saved.version + 1 }
        return route.fulfill({ json: saved })
      }
      if (path === "/v1/business-credentials/synthetic-account/bindings" && method === "POST") {
        const binding = { ...saved.bindings[0], ...body, id: "synthetic-new-binding", synced_version: null, sync_status: "pending", last_sync_at: null }
        saved = { ...saved, bindings: [...saved.bindings, binding] }
        return route.fulfill({ json: binding })
      }
      if (path.endsWith("/sync")) {
        saved.bindings[0] = { ...saved.bindings[0], sync_status: "synced", synced_version: saved.version }
        return route.fulfill({ json: saved.bindings[0] })
      }
      if (path.endsWith("/delete-remote")) {
        saved.bindings[0] = { ...saved.bindings[0], sync_status: "deleted" }
        return route.fulfill({ json: saved.bindings[0] })
      }
      if (path.endsWith("/close")) {
        sessions = sessions.map(session => ({ ...session, status: "closed" }))
        return route.fulfill({ json: { status: "closed", website_logout_verified: false } })
      }
      return route.fulfill({ status: 400, json: { detail: { code: "unexpected_ui_fixture_write" } } })
    }
    return route.fulfill({ status: 404, json: { detail: { code: "unexpected_ui_fixture_read" } } })
  })
  await page.goto(scope === "shared" ? "/console/#/credentials" : "/console/#/downstreamCredentials")
  await page.getByRole("tab", { name: locale === "zh-CN" ? "业务账号" : "Business accounts", exact: true }).click()
  await expect(page.getByRole("button", { name: "测试环境医生", exact: true })).toBeVisible()
  return { writes, getSaved: () => saved }
}

for (const viewport of sizes) {
  test(`business credential editor fits ${viewport.width}x${viewport.height} @full`, async ({ page }, testInfo) => {
    await openBusiness(page, viewport)
    await page.getByRole("button", { name: "编辑", exact: true }).click()
    const dialog = page.getByRole("dialog", { name: "编辑业务账号", exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel("账号", { exact: true })).toHaveValue("")
    await expect(dialog.getByLabel("密码", { exact: true })).toHaveValue("")
    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width)
    expect(box!.y).toBeGreaterThanOrEqual(0)
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height)
    await expect(dialog.getByRole("button", { name: "保存", exact: true })).toBeInViewport()
    const fields = await dialog.locator(".business-field").evaluateAll(elements => elements.filter(element => (element as HTMLElement).offsetParent).map(element => {
      const label = element.firstElementChild!.getBoundingClientRect()
      const input = element.querySelector(".business-field-control")!.getBoundingClientRect()
      return { labelRight: label.right, inputLeft: input.left, labelTop: label.top, inputTop: input.top }
    }))
    for (const field of fields) { expect(field.labelRight).toBeLessThanOrEqual(field.inputLeft); expect(Math.abs(field.labelTop - field.inputTop)).toBeLessThan(4) }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`business-editor-${viewport.width}x${viewport.height}.png`) })
  })
}

test("business edit preserves secrets, cancels discard, then saves one revision @full", async ({ page }) => {
  const fixture = await openBusiness(page)
  await page.getByRole("button", { name: "编辑", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "编辑业务账号", exact: true })
  await dialog.getByLabel("凭据名称", { exact: true }).fill("测试环境医生 · 更新")
  await page.keyboard.press("Escape")
  await expect(page.getByRole("alertdialog")).toBeVisible()
  await page.getByRole("button", { name: "继续编辑", exact: true }).click()
  await expect(dialog.getByLabel("凭据名称", { exact: true })).toHaveValue("测试环境医生 · 更新")
  await dialog.getByRole("button", { name: "保存", exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(fixture.writes).toHaveLength(1)
  expect(fixture.writes[0]).toMatchObject({ method: "PUT", body: { username: null, password: null, expected_version: 2, login_url: "https://app.example.test/#/login" } })
  expect(fixture.writes[0].body.scope).toBeUndefined()
  expect(await page.evaluate(() => Object.values(localStorage).join(" "))).not.toContain("测试环境医生 · 更新")
})

test("node sync, remote deletion and browser closure remain independent actions @full", async ({ page }, testInfo) => {
  test.setTimeout(60_000)
  const fixture = await openBusiness(page)
  await page.getByRole("button", { name: "管理节点", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "授权节点 · 测试环境医生", exact: true })
  await expect(dialog.getByText("节点版本 v1 / 目标 v2")).toBeVisible()
  await dialog.getByRole("button", { name: "同步密码", exact: true }).click()
  await expect(dialog.getByText("已同步", { exact: true })).toBeVisible()
  expect(fixture.writes[0].path).toBe("/v1/business-credentials/synthetic-account/bindings/synthetic-binding/sync")
  await dialog.getByRole("button", { name: "操作", exact: true }).click()
  await page.getByRole("menuitem", { name: "删除节点密码", exact: true }).click()
  const confirm = page.getByRole("alertdialog")
  await expect(confirm).toContainText("已经登录的网站会话不会退出")
  await confirm.getByRole("button", { name: "确认", exact: true }).click()
  await expect(dialog.getByText("节点密码已删除", { exact: true })).toBeVisible()
  await dialog.locator("summary").filter({ hasText: "浏览器会话" }).click()
  await expect(dialog.getByText("浏览器打开", { exact: true })).toBeVisible()
  await dialog.getByRole("button", { name: "关闭浏览器会话", exact: true }).click()
  await expect(confirm).toContainText("不保证网站服务端登录态已经撤销")
  await confirm.getByRole("button", { name: "确认", exact: true }).click()
  await expect(dialog.getByText("已关闭", { exact: true })).toBeVisible()
  expect(fixture.writes.map(write => write.path)).toEqual([
    "/v1/business-credentials/synthetic-account/bindings/synthetic-binding/sync",
    "/v1/business-credentials/synthetic-account/bindings/synthetic-binding/delete-remote",
    "/v1/business-credentials/synthetic-account/sessions/synthetic-session/close",
  ])
  await page.screenshot({ path: testInfo.outputPath("business-node-states.png") })
})

test("English dark business editor keeps field labels on one row @full", async ({ page }, testInfo) => {
  await openBusiness(page, sizes[0], "en-US", "dark")
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Edit business account", exact: true })
  await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeInViewport()
  const fields = await dialog.locator(".business-field > :is(label, .field-label)").evaluateAll(elements => elements.filter(element => (element as HTMLElement).offsetParent).map(element => ({ scroll: element.scrollWidth, client: element.clientWidth })))
  for (const field of fields) expect(field.scroll).toBeLessThanOrEqual(field.client + 1)
  await page.screenshot({ path: testInfo.outputPath("business-editor-en-dark.png") })
})

test("business grants and node selectors stay inside dialogs and require managed-mode confirmation @full", async ({ page }) => {
  test.setTimeout(60_000)
  const fixture = await openBusiness(page)
  await page.getByRole("button", { name: "编辑", exact: true }).click()
  const editor = page.getByRole("dialog", { name: "编辑业务账号", exact: true })
  await editor.getByRole("combobox", { name: "Gate 用户", exact: true }).click()
  await editor.getByText("Synthetic user", { exact: true }).click()
  await editor.getByLabel("凭据名称", { exact: true }).click()
  await editor.getByRole("button", { name: "保存", exact: true }).click()
  await expect(editor).not.toBeVisible()
  expect(fixture.writes[0].body.allowed_user_ids).toEqual(["synthetic-user"])
  await page.getByRole("button", { name: "管理节点", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "授权节点 · 测试环境医生", exact: true })
  await dialog.getByRole("combobox", { name: "MCP 实例", exact: true }).click()
  await dialog.getByText("另一个测试节点 · browser-next", { exact: true }).click()
  await dialog.getByRole("radio", { name: "auth_*", exact: true }).click()
  await dialog.getByRole("button", { name: "添加绑定", exact: true }).click()
  const confirm = page.getByRole("alertdialog")
  await expect(confirm).toContainText("每次调用必须指定 session")
  expect(fixture.writes).toHaveLength(1)
  await confirm.getByRole("button", { name: "确认绑定", exact: true }).click()
  await expect(dialog.getByRole("code").filter({ hasText: /^browser-next$/ })).toBeVisible()
  expect(fixture.writes[1]).toMatchObject({ method: "POST", body: { server_id: "browser-next", tool_prefix: "", expected_version: 3, confirm_managed_mode: true } })
})

test("personal business account creation clears submitted secrets and has no shared grants @full", async ({ page }) => {
  test.setTimeout(60_000)
  const fixture = await openBusiness(page, sizes[0], "zh-CN", "light", "personal")
  await page.getByRole("button", { name: "新增业务账号", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "新增业务账号", exact: true })
  await dialog.getByLabel("凭据名称", { exact: true }).fill("Synthetic personal account")
  await dialog.getByLabel("登录地址", { exact: true }).fill("https://app.example.test/#/login")
  await dialog.getByLabel("账号", { exact: true }).fill("synthetic-user")
  await dialog.getByLabel("密码", { exact: true }).fill("Synthetic-test-only-value")
  await expect(dialog.getByLabel("Gate 用户", { exact: true })).toHaveCount(0)
  await dialog.getByRole("button", { name: "保存", exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole("button", { name: "Synthetic personal account", exact: true })).toBeVisible()
  expect(fixture.writes).toHaveLength(1)
  expect(fixture.writes[0].body).toMatchObject({ scope: "personal", allowed_user_ids: [], allowed_role_ids: [], username: "synthetic-user", password: "Synthetic-test-only-value" })
  expect(await page.evaluate(() => Object.values(localStorage).join(" "))).not.toContain("Synthetic-test-only-value")
  await page.getByRole("button", { name: "新增业务账号", exact: true }).click()
  await expect(dialog.getByLabel("账号", { exact: true })).toHaveValue("")
  await expect(dialog.getByLabel("密码", { exact: true })).toHaveValue("")
})

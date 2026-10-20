import { test, expect } from "@playwright/test"

// Presentation regression for long source identities; no real MCP instance is queried.
const source = "nx3-playwright-mcp"
const longSource = "synthetic-internal-browser-with-a-very-long-environment-and-region-identifier"
const records = [source, longSource].map((server_id, index) => ({
  id: `synthetic-source-${index}`, server_id, tool_id: `mcp.${server_id}.browser_click`, tool_name: "browser_click",
  suggested_access: "write", effective_access: "write", status: "published", confidence: .62,
  source: "manual", registry_source: null, destructive: true, idempotent: false, open_world: false,
  fingerprint: `synthetic-${index}`, evidence: {}, created_at: "2026-10-20T00:00:00Z", updated_at: "2026-10-20T00:00:00Z",
}))

for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) {
  test(`tool-review source and origin badge stay on one row ${width}x${height} @full`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    await page.addInitScript(() => { localStorage.setItem("lingshu-gate-console-locale", "zh-CN"); localStorage.setItem("lingshu-gate-console-theme", "light") })
    const writes: string[] = []
    await page.route("**/healthz", route => route.fulfill({ json: { status: "ok", version: "0.5.1" } }))
    await page.route("**/v1/**", route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (request.method() !== "GET") { writes.push(path); return route.fulfill({ status: 400, json: { detail: "unexpected synthetic write" } }) }
      if (path === "/v1/auth/me") return route.fulfill({ json: { id: "synthetic-admin", username: "synthetic-admin", display_name: "Synthetic admin", role: "admin", roles: ["admin"], status: "active", must_change_password: false, permissions: ["*"], scopes: ["*"], auth_type: "session" } })
      if (path === "/v1/access/tool-classifications") return route.fulfill({ json: { classifications: records } })
      return route.fulfill({ status: 404, json: { detail: "unexpected synthetic read" } })
    })
    await page.goto("/console/#/toolClassifications")
    const selector = page.getByRole("combobox", { name: "按 MCP 服务筛选", exact: true })
    await selector.click()
    await page.getByRole("option").filter({ has: page.getByText(source, { exact: true }) }).click()
    await expect(selector.getByText("来源未确认", { exact: true })).toBeVisible()
    await expect(page.locator("main tbody tr")).toHaveCount(1)
    const layout = await selector.evaluate(element => {
      const trigger = element.getBoundingClientRect(), label = element.querySelector(".tool-review-source-label")!.getBoundingClientRect()
      const name = element.querySelector(".tool-review-source-name")!.getBoundingClientRect(), badge = element.querySelector(".tool-review-source-label > :last-child")!.getBoundingClientRect()
      return { trigger: { left: trigger.left, right: trigger.right, top: trigger.top, bottom: trigger.bottom }, label: { left: label.left, right: label.right }, name: { right: name.right, top: name.top, bottom: name.bottom, height: name.height }, badge: { left: badge.left, top: badge.top, bottom: badge.bottom } }
    })
    expect(layout.name.right).toBeLessThanOrEqual(layout.badge.left)
    expect(layout.name.height).toBeLessThanOrEqual(24)
    expect(layout.name.top).toBeGreaterThanOrEqual(layout.trigger.top)
    expect(layout.name.bottom).toBeLessThanOrEqual(layout.trigger.bottom)
    expect(layout.badge.top).toBeGreaterThanOrEqual(layout.trigger.top)
    expect(layout.badge.bottom).toBeLessThanOrEqual(layout.trigger.bottom)
    expect(layout.label.right).toBeLessThanOrEqual(layout.trigger.right)
    expect((await page.getByRole("textbox", { name: "搜索来源或工具", exact: true }).boundingBox())!.width).toBeGreaterThan(180)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`tool-source-${width}x${height}.png`), animations: "disabled" })
    await selector.click()
    await page.getByRole("option").filter({ has: page.getByText(longSource, { exact: true }) }).click()
    const name = selector.locator(".tool-review-source-name")
    await expect(name).toHaveAttribute("title", longSource)
    expect(await name.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
    expect(writes).toEqual([])
  })
}

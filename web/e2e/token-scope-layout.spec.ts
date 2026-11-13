import { expect, test, type Locator, type Page } from "@playwright/test"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { login, expectInViewportAndUnobscured } from "./helpers"

const permissionSource = readFileSync(new URL("../../src/lingshu_gate/access_control.py", import.meta.url), "utf8")
const permissionBlock = permissionSource.match(/CONTROL_PERMISSIONS = \(([\s\S]*?)\r?\n\)/)?.[1]
if (!permissionBlock) throw new Error("Missing backend control permission catalog")
const permissions = [...permissionBlock.matchAll(/^\s+\("([^"]+)",/gm)].map(match => match[1])
type Locale = "zh-CN" | "en-US"

async function setup(page: Page, locale: Locale, long = false) {
  await login(page)
  await page.addInitScript(({ locale, long }) => {
    localStorage.setItem("lingshu-gate-console-locale", locale)
    localStorage.setItem("lingshu-gate-console-theme", long ? "dark" : "light")
  }, { locale, long })
  const legacy = "legacy." + "review_long_permission_identifier_".repeat(8)
  const scopes = [...permissions, ...(long ? [legacy] : [])]
  const token = { id: "synthetic-layout-token", name: long ? "Synthetic authorization " + "long name ".repeat(12) : "Synthetic desktop authorization", token_prefix: "synthetic", scopes, authorization_mode: "account", created_at: "2026-01-01T00:00:00Z", rate_per_minute: 6000, concurrency: 100 }
  const tokenPath = `/v1/auth/tokens/${token.id}`
  const options = { revision: 1, mode: "account", scopes, tool_ids: [], server_policies: [], rate_per_minute: 6000, concurrency: 100, csrf: "synthetic-csrf", catalog_revision: "synthetic-catalog", tools: [], servers: [] }
  const writes: { path: string; body: Record<string, unknown> }[] = []
  await page.route("**/v1/**", route => {
    const pathname = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (method === "GET") {
      if (pathname === "/v1/auth/tokens") return route.fulfill({ json: { tokens: [token] } })
      if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [] } })
      if (pathname === "/v1/auth/external-grants") return route.fulfill({ json: { grants: [], connection_ready: false, activation_errors: [] } })
      if (pathname === `${tokenPath}/authorization-options` || pathname === "/v1/auth/tokens/authorization-options") return route.fulfill({ json: options })
      return route.continue()
    }
    if (pathname.startsWith(tokenPath)) {
      const body = route.request().postDataJSON()
      writes.push({ path: pathname, body })
      if (pathname.endsWith("/authorization-preview")) return route.fulfill({ json: { ...body, confirmation: "synthetic-confirmation", added: [], removed: [] } })
      if (pathname.endsWith("/authorization")) return route.fulfill({ json: { ...token, scopes: body.scopes } })
    }
    return route.fulfill({ status: 500, json: { error: "Unexpected synthetic mutation" } })
  })
  await page.goto("/console/#/personalTokens")
  const trigger = page.getByRole("row").filter({ hasText: token.name }).getByRole("button", { name: locale === "zh-CN" ? "调整授权" : "Adjust", exact: true })
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: locale === "zh-CN" ? "调整授权" : "Adjust authorization", exact: true })
  const toggle = dialog.getByRole("tab", { name: locale === "zh-CN" ? "功能权限" : "Functional permissions", exact: true })
  await toggle.click()
  await expect(dialog.getByRole("switch")).toHaveCount(scopes.length)
  await dialog.evaluate(async element => { await Promise.allSettled(element.getAnimations({ subtree: true }).filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished)) })
  return { dialog, trigger, toggle, scopes, tokenPath, writes, legacy }
}

async function capture(page: Page, name: string, metrics?: unknown) {
  const directory = process.env.GATE_UI_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" })
  if (metrics) writeFileSync(path.join(directory, `${name}.json`), JSON.stringify({ viewport: page.viewportSize(), ...metrics as object }, null, 2) + "\n")
}

async function layoutMetrics(dialog: Locator) {
  return dialog.evaluate(element => {
    const body = element.querySelector<HTMLElement>(".gate-dialog-body")!
    const box = (node: Element) => { const r = node.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height } }
    const groups = [...element.querySelectorAll("fieldset")].map(group => ({ name: group.querySelector("legend")?.textContent, ...box(group) }))
    const items = [...element.querySelectorAll('button[role="switch"]')].map(control => {
      const label = control.closest("label")!
      const copy = label.querySelector("span")!
      return { label: control.getAttribute("aria-label"), text: box(copy), control: box(control), row: box(label) }
    })
    const permissions = element.querySelector("fieldset")!.closest('[role="tabpanel"]')!
    const tabs = element.querySelector('[role="tablist"]')!
    return { groups, items, permissions: box(permissions), tabs: box(tabs), dialog: box(element), body: box(body), footer: box(element.querySelector(".gate-dialog-footer")!), bodyOverflow: body.scrollWidth - body.clientWidth, pageOverflow: document.documentElement.scrollWidth - innerWidth, groupGap: parseFloat(getComputedStyle(element).getPropertyValue("--panel-gap")) }
  })
}

const sizes = [{ width: 2560, height: 1440 }, { width: 1920, height: 1080 }, { width: 1600, height: 900 }, { width: 2560, height: 1080 }]
for (const size of sizes) {
  test(`Token permission layout zh-CN ${size.width}x${size.height} @visual`, async ({ page }) => {
    await page.setViewportSize(size)
    const { dialog, scopes, writes } = await setup(page, "zh-CN")
    const body = dialog.locator(".gate-dialog-body")
    const metrics = await layoutMetrics(dialog)
    await capture(page, `token-scopes-zh-CN-${size.width}x${size.height}-top`, metrics)
    expect(metrics.groups).toHaveLength(5)
    expect(metrics.permissions.top - metrics.tabs.bottom, "The active panel follows the tabs").toBeGreaterThanOrEqual(metrics.groupGap - 1)
    await expect(dialog.getByRole("tab")).toHaveText(["MCP 范围", "功能权限", "调用限制"])
    for (const [index, group] of metrics.groups.entries()) {
      expect(Math.abs(group.left - metrics.groups[0].left), "Permission groups must use the same full content width").toBeLessThanOrEqual(1)
      expect(Math.abs(group.right - metrics.groups[0].right)).toBeLessThanOrEqual(1)
      if (index) {
        const gap = group.top - metrics.groups[index - 1].bottom
        expect(gap, "Groups must follow reading order without shared-row empty space").toBeGreaterThanOrEqual(0)
        expect(gap, "No tall empty blocks between permission groups").toBeLessThanOrEqual(metrics.groupGap + 2)
      }
    }
    for (const item of metrics.items) {
      expect(item.text.right + 8, item.label || "Permission text").toBeLessThanOrEqual(item.control.left)
      expect(item.control.right).toBeLessThanOrEqual(item.row.right + 1)
    }
    expect(metrics.bodyOverflow).toBeLessThanOrEqual(1)
    expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
    expect(metrics.dialog.top).toBeGreaterThanOrEqual(0)
    expect(metrics.dialog.bottom).toBeLessThanOrEqual(size.height)
    await expectInViewportAndUnobscured(dialog.getByRole("button", { name: "取消", exact: true }))
    await body.evaluate(element => { element.scrollTop = element.scrollHeight })
    await expectInViewportAndUnobscured(dialog.getByRole("switch").last())
    await expectInViewportAndUnobscured(dialog.getByRole("button", { name: "取消", exact: true }))
    await capture(page, `token-scopes-zh-CN-${size.width}x${size.height}-bottom`)
    expect(await page.evaluate(() => window.scrollY)).toBe(0)
    expect(await dialog.getByRole("switch", { checked: true }).count()).toBe(scopes.length)
    expect(writes).toEqual([])
  })
}

test("Token permission layout English dark long content @visual", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const { dialog, scopes, legacy, writes } = await setup(page, "en-US", true)
  const body = dialog.locator(".gate-dialog-body")
  const metrics = await layoutMetrics(dialog)
  expect(metrics.bodyOverflow).toBeLessThanOrEqual(1)
  expect(metrics.pageOverflow).toBeLessThanOrEqual(1)
  for (const item of metrics.items) expect(item.text.right + 8).toBeLessThanOrEqual(item.control.left)
  await capture(page, "token-scopes-en-US-dark-long-1600x900-top", metrics)
  await body.evaluate(element => { element.scrollTop = element.scrollHeight })
  await expectInViewportAndUnobscured(dialog.getByRole("switch", { name: legacy, exact: true }))
  await expectInViewportAndUnobscured(dialog.getByRole("button", { name: "Cancel", exact: true }))
  await capture(page, "token-scopes-en-US-dark-long-1600x900-bottom")
  expect(await dialog.getByRole("switch", { checked: true }).count()).toBe(scopes.length)
  expect(writes).toEqual([])
})

test("Token permissions preserve keyboard order, drafts and one-step narrowing payload", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const { dialog, trigger, scopes, tokenPath, writes, legacy } = await setup(page, "en-US", true)
  const switches = dialog.getByRole("switch")
  await switches.first().focus()
  for (let index = 0; index < scopes.length; index++) {
    await expect(switches.nth(index)).toBeFocused()
    if (index < scopes.length - 1) await page.keyboard.press("Tab")
  }
  // Reach both ends of the focus trap without changing permissions.
  await dialog.getByRole("button", { name: "Close", exact: true }).focus()
  await page.keyboard.press("Tab")
  expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press("Shift+Tab")
  await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused()
  const write = dialog.getByRole("switch", { name: "Write tools", exact: true })
  await write.click()
  const expected = scopes.filter(scope => scope !== "tools.invoke")
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click()
  const discard = page.getByRole("alertdialog")
  await discard.getByRole("button", { name: "Continue editing", exact: true }).click()
  await expect(write).not.toBeChecked()
  await expect(dialog.getByRole("switch", { name: legacy, exact: true })).toBeChecked()
  expect(writes).toEqual([])
  await dialog.getByRole("tab", { name: "Call limits", exact: true }).click()
  await dialog.getByRole("spinbutton", { name: "Calls per minute", exact: true }).fill("")
  await dialog.getByRole("tab", { name: "MCP scope", exact: true }).click()
  await expect(dialog.getByRole("button", { name: "Save authorization", exact: true })).toBeDisabled()
  await dialog.getByRole("button", { name: "Edit call limits", exact: true }).click()
  await expect(dialog.getByRole("tab", { name: "Call limits", exact: true })).toHaveAttribute("aria-selected", "true")
  await dialog.getByRole("spinbutton", { name: "Calls per minute", exact: true }).fill("6000")
  await dialog.getByRole("tab", { name: "Functional permissions", exact: true }).click()
  await expect(write).not.toBeChecked()
  await dialog.getByRole("button", { name: "Save authorization", exact: true }).click()
  await expect(page.getByRole("region", { name: "Authorization change details", exact: true })).toHaveCount(0)
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  expect(writes.map(write => write.path)).toEqual([`${tokenPath}/authorization-preview`, `${tokenPath}/authorization`])
  for (const write of writes) {
    expect(write.body.scopes).toEqual(expected)
    expect(write.body.mode).toBe("account")
    expect(write.body.rate_per_minute).toBe(6000)
    expect(write.body.concurrency).toBe(100)
    expect(write.body.tool_ids).toEqual([])
    expect(write.body.server_policies).toEqual([])
  }
  await trigger.click()
  const reopened = page.getByRole("dialog", { name: "Adjust authorization", exact: true })
  await expect(reopened.locator(".gate-dialog-body")).toHaveJSProperty("scrollTop", 0)
  await reopened.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(trigger).toBeFocused()
})

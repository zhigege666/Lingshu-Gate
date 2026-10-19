import { expect, test } from "@playwright/test"
import { login } from "./helpers"
import { grants, listFixtures, tools, tokens } from "./synthetic-data"

test("My authorizations loads each source once and retries tools only inside an editor @smoke", async ({ page }) => {
  await login(page)
  const counts = new Map<string, number>()
  const external = { id: "external-synthetic", enabled: true, client_id: "synthetic-client", server_allowlist: ["synthetic-mcp"], tool_allowlist: ["synthetic-read"], access: ["read"], expires_at: "2099-01-01T00:00:00Z", rate_per_minute: 6000, concurrency: 100, revision: 1, state: "enabled", scope_currently_authorized: true }
  const fixtures: Record<string, unknown> = {
    "/v1/auth/tokens": { tokens },
    "/v1/auth/oauth/grants": { grants: [] },
    "/v1/auth/external-grants": { grants: [external], connection_ready: true, activation_errors: [], allowed_client_ids: [external.client_id] },
  }
  await page.route("**/v1/**", async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== "GET") return route.continue()
    if (path === "/v1/tools") {
      counts.set(path, (counts.get(path) || 0) + 1)
      if (counts.get(path) === 1) return route.fulfill({ status: 503, json: { detail: "Synthetic catalog unavailable" } })
      return route.fulfill({ json: [{ ...tools[0], id: "synthetic-read", name: "Synthetic read", metadata: { server_id: "synthetic-mcp", gate_access: { classification_status: "published", required_access: "read" } } }] })
    }
    if (path in fixtures) {
      counts.set(path, (counts.get(path) || 0) + 1)
      return route.fulfill({ json: fixtures[path] })
    }
    return route.continue()
  })
  await page.goto("/console/#/myConnections")
  await expect(page.getByRole("button", { name: "Synthetic token 0", exact: true })).toBeVisible()
  expect(Object.fromEntries(counts)).toEqual({ "/v1/auth/tokens": 1, "/v1/auth/oauth/grants": 1, "/v1/auth/external-grants": 1 })
  await page.getByRole("radiogroup", { name: "Authorization type", exact: true }).getByRole("radio", { name: "External OAuth", exact: true }).check()
  await page.getByRole("row").filter({ hasText: "synthetic-client" }).getByRole("button", { name: "Adjust", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Adjust authorization", exact: true })
  await expect(dialog.getByText("Tool catalog could not be loaded. Your draft is retained.")).toBeVisible()
  await dialog.getByLabel("Client ID", { exact: true }).fill("retained-draft")
  await expect(dialog.getByRole("button", { name: "Save personal grant", exact: true })).toBeDisabled()
  await dialog.getByRole("button", { name: "Retry", exact: true }).click()
  await expect(dialog.getByRole("checkbox", { name: "synthetic-read", exact: true })).toBeChecked()
  await expect(dialog.getByLabel("Client ID", { exact: true })).toHaveValue("retained-draft")
  expect(counts.get("/v1/tools")).toBe(2)
  for (const path of Object.keys(fixtures)) expect(counts.get(path)).toBe(1)
})

test("My authorizations resets all filters and pagination without reloading catalogs @large-data", async ({ page }) => {
  await login(page)
  const fixtures: Record<string, unknown> = { "/v1/auth/tokens": { tokens }, "/v1/auth/oauth/grants": { grants: [] }, "/v1/auth/external-grants": { grants: [], connection_ready: false, activation_errors: [] } }
  let reads = 0
  await page.route("**/v1/**", route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === "GET" && path in fixtures) { reads++; return route.fulfill({ json: fixtures[path] }) }
    return route.continue()
  })
  await page.goto("/console/#/personalTokens")
  await page.locator(".ant-table-pagination .ant-pagination-next").click()
  await expect(page.getByRole("button", { name: "Synthetic token 15", exact: true })).toBeVisible()
  await page.getByLabel("Search authorizations", { exact: true }).fill("Synthetic token 0")
  await expect(page.getByRole("button", { name: "Synthetic token 0", exact: true })).toBeVisible()
  await page.getByRole("radiogroup", { name: "Authorization status", exact: true }).getByRole("radio", { name: "Revoked", exact: true }).check()
  await page.getByRole("button", { name: "Reset Filters", exact: true }).click()
  await expect(page.getByLabel("Search authorizations", { exact: true })).toHaveValue("")
  await expect(page.getByRole("radiogroup", { name: "Authorization type", exact: true }).getByRole("radio", { name: "API token", exact: true })).toBeChecked()
  await expect(page.getByRole("radiogroup", { name: "Authorization status", exact: true }).getByRole("radio", { name: "Active", exact: true })).toBeChecked()
  await expect(page.getByRole("button", { name: "Synthetic token 0", exact: true })).toBeVisible()
  await expect(page.locator(".ant-table-pagination .ant-pagination-item-active")).toHaveText("1")
  expect(reads).toBe(3)
})

test("Editing an existing resource grant preserves its identity and exact expiry @permissions", async ({ page }) => {
  await login(page)
  let current = { ...grants[0], expires_at: "2099-01-01T08:09:10.123Z" }
  const writes: Record<string, unknown>[] = []
  const fixtures: Record<string, unknown> = {
    ...listFixtures,
    "/v1/access/resources": { resources: [{ server_id: current.server_id, tool_id: current.tool_id, tool_name: "Synthetic read", classification: "read", classification_status: "published" }] },
    "/v1/access/permission-types": { permission_types: [{ id: "read", code: "read", name: "Read", base_level: "read", enabled: true }, { id: "write", code: "write", name: "Read & write", base_level: "write", enabled: true }] },
  }
  await page.route("**/v1/**", route => {
    const path = new URL(route.request().url()).pathname
    if (path === "/v1/access/grants") {
      if (route.request().method() === "PUT") {
        const payload = route.request().postDataJSON()
        writes.push(payload)
        current = { ...current, ...payload, permission_type_name: "Read & write", base_level: "write" }
        return route.fulfill({ json: current })
      }
      if (route.request().method() === "GET") return route.fulfill({ json: { grants: [current] } })
    }
    if (route.request().method() === "GET" && path in fixtures) return route.fulfill({ json: fixtures[path] })
    return route.continue()
  })
  await page.goto("/console/#/accessGrants")
  const edit = page.getByRole("row").filter({ hasText: "Synthetic user 0" }).getByRole("button", { name: "Edit", exact: true })
  await edit.click()
  const dialog = page.getByRole("dialog", { name: "Edit grant", exact: true })
  await expect(dialog.locator("#grant-server")).toHaveValue(current.server_id)
  await expect(dialog.locator("#grant-server")).toHaveAttribute("readonly", "")
  await expect(dialog.locator("#grant-tool")).toHaveValue(current.tool_id)
  await expect(dialog.getByRole("radiogroup", { name: "Subject type", exact: true }).getByRole("radio").first()).toBeDisabled()
  await dialog.locator("#grant-permissionType").click()
  await page.getByRole("option", { name: "Read & write", exact: true }).click()
  await dialog.getByRole("button", { name: "Save grant", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual([{ subject_type: current.subject_type, subject_id: current.subject_id, server_id: current.server_id, tool_id: current.tool_id, permission_type_code: "write", expires_at: "2099-01-01T08:09:10.123Z" }])
  await expect(edit).toBeFocused()
})

test("Token save waits for list refresh and restores focus to Retry when the saved source cannot be reloaded", async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  const token = { ...tokens[0], authorization_mode: "account", rate_per_minute: 300, concurrency: 5 }
  const tokenPath = `/v1/auth/tokens/${token.id}`
  const options = { revision: 1, mode: "account", scopes: token.scopes, tool_ids: [], server_policies: [], rate_per_minute: 300, concurrency: 5, csrf: "synthetic-csrf", catalog_revision: "synthetic-catalog", tools: [], servers: [] }
  const writes: string[] = []
  let saved = false
  let refreshStarted = false
  let failRefresh = true
  let releaseRefresh: () => void = () => {}
  const refresh = new Promise<void>(resolve => { releaseRefresh = resolve })
  await page.route("**/v1/**", async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== "GET") {
      writes.push(path)
      if (path === `${tokenPath}/authorization-preview`) return route.fulfill({ json: { ...route.request().postDataJSON(), confirmation: "synthetic-confirmation", added: [], removed: [] } })
      if (path === `${tokenPath}/authorization`) { saved = true; return route.fulfill({ json: { ...token, rate_per_minute: 301 } }) }
      return route.fulfill({ status: 500, json: { error: "Unexpected synthetic mutation" } })
    }
    if (path === "/v1/auth/tokens") {
      if (saved && failRefresh) { refreshStarted = true; await refresh; return route.fulfill({ status: 503, json: { detail: "Synthetic token list unavailable" } }) }
      return route.fulfill({ json: { tokens: [token] } })
    }
    if (path === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [] } })
    if (path === "/v1/auth/external-grants") return route.fulfill({ json: { grants: [], connection_ready: false, activation_errors: [] } })
    if (path === `${tokenPath}/authorization-options`) return route.fulfill({ json: options })
    return route.continue()
  })
  try {
    await page.goto("/console/#/personalTokens")
    const edit = page.getByRole("row").filter({ hasText: token.name }).getByRole("button", { name: "Adjust", exact: true })
    await edit.click()
    const dialog = page.getByRole("dialog", { name: "Adjust authorization", exact: true })
    await dialog.getByText("Advanced · Call limits", { exact: true }).click()
    await dialog.getByRole("spinbutton", { name: "Calls per minute", exact: true }).fill("301")
    await dialog.getByRole("button", { name: "Save authorization", exact: true }).click()
    const review = page.getByRole("alertdialog", { name: "Save authorization?", exact: true })
    await review.getByRole("button", { name: "Confirm", exact: true }).click()
    await expect.poll(() => refreshStarted).toBe(true)
    await expect(dialog).toHaveCount(0)
    await expect(edit).toBeDisabled()
    await expect(page.getByRole("button", { name: "New authorization", exact: true })).toBeDisabled()
    await expect(page.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0)
    releaseRefresh()
    await expect(page.getByText("API token load failed", { exact: true })).toBeVisible()
    const retry = page.getByRole("button", { name: "Retry", exact: true })
    await expect(retry).toBeEnabled()
    await expect(retry).toBeFocused()
    await expect(edit).toBeDisabled()
    expect(writes).toEqual([`${tokenPath}/authorization-preview`, `${tokenPath}/authorization`])
    failRefresh = false
    await retry.click()
    await expect(edit).toBeEnabled()
    await expect(page.getByText("API token load failed", { exact: true })).toHaveCount(0)
    expect(writes).toHaveLength(2)
  } finally {
    releaseRefresh()
  }
})

import { expect, test, type Page } from "@playwright/test"
import { login } from "./helpers"
import type { OAuthGrant, OAuthScopeCatalog, OAuthScopeGroup, OAuthTool } from "../src/features/external-connections/oauth-api"

// Bounded synthetic responses exercise the actual editor; no external MCP is contacted.
async function setup(page: Page) {
  await login(page)
  const now = Math.floor(Date.now() / 1000)
  const group = (index: number): OAuthScopeGroup => ({ server_id: `synthetic-${String(index).padStart(4, "0")}`, server_name: `Service ${index}`, server_binding: `binding-${index}`, tool_count: 4, read_count: 2, write_count: 2 })
  const groups = Array.from({ length: 5000 }, (_, index) => group(index))
  const tool = (id: string): OAuthTool => {
    const [, server, number] = /^mcp\.(synthetic-\d+)\.tool-(\d+)$/.exec(id)!
    return { id, name: `Tool ${number}`, server_id: server, access: Number(number) % 2 ? "write" : "read", snapshot: "synthetic-policy", currently_authorized: true }
  }
  const first = "mcp.synthetic-0000.tool-0"
  let saved: OAuthGrant = { id: "synthetic-paged-editor", client_id: "synthetic-client", client_name: "Paged client", resource: "https://gate.example.test/mcp", scopes: ["tools.read", "tools.invoke"], tools: [tool(first)], server_policies: [], created_at: now, expires_at: now + 86400, rate_per_minute: 30, concurrency: 2, revision: 1, state: "active", scope_currently_authorized: true, effective_tool_count: 1, scope_catalog_mode: "paged" }
  const path = `/v1/auth/oauth/grants/${saved.id}`
  const model = { reads: [] as URL[], previews: [] as Record<string, any>[], writes: [] as Record<string, any>[], failPage: false, loseSaveResponse: false, fullReads: 0 }
  const counts = { mcps: 5000, tools: 20000, read: 10000, write: 10000 }
  function difference(ids: string[]) {
    const previous = saved.tools.map(item => item.id), added = ids.filter(id => !previous.includes(id)), removed = previous.filter(id => !ids.includes(id))
    return { added: added.length, removed: removed.length, added_write: added.filter(id => tool(id).access === "write").length, removed_write: removed.filter(id => tool(id).access === "write").length, write: ids.filter(id => tool(id).access === "write").length }
  }
  await page.route("**/v1/**", route => {
    const request = route.request(), url = new URL(request.url()), pathname = url.pathname
    if (request.method() === "GET") {
      if (pathname === "/v1/auth/tokens") return route.fulfill({ json: { tokens: [] } })
      if (pathname === "/v1/auth/oauth/grants") return route.fulfill({ json: { grants: [saved] } })
      if (pathname === "/v1/auth/external-grants") return route.fulfill({ json: { grants: [], connection_ready: false, activation_errors: [] } })
      if (pathname === "/v1/tools" || pathname.endsWith("/scope-options")) { model.fullReads++; return route.fulfill({ status: 500, json: { error: "unexpected_full_catalog" } }) }
      if (pathname === `${path}/scope-catalog`) {
        model.reads.push(url)
        const view = url.searchParams.get("view") || "tools", limit = Number(url.searchParams.get("limit") || 50), offset = Number(url.searchParams.get("cursor") || 0), query = url.searchParams.get("query") || "", server = url.searchParams.get("server_id") || "synthetic-0000"
        if (view === "groups" && offset && model.failPage) { model.failPage = false; return route.fulfill({ status: 503, json: { error: "scope_catalog_unavailable" } }) }
        const matches = groups.filter(item => `${item.server_id} ${item.server_name}`.toLowerCase().includes(query.toLowerCase()))
        const items = view === "groups" ? matches.slice(offset, offset + limit) : Array.from({ length: 4 }, (_, index) => tool(`mcp.${server}.tool-${index}`))
        const result: OAuthScopeCatalog = { csrf: "synthetic-csrf", expires_at: now + 600, grant_revision: saved.revision, scopes: saved.scopes, effective_scopes: saved.scopes, family_scope_limits: [], complete: false, view: view as "groups" | "tools", catalog_revision: `catalog-${saved.revision}`, items, next_cursor: view === "groups" && offset + limit < matches.length ? String(offset + limit) : null, matching_counts: view === "groups" ? { ...counts, mcps: matches.length, tools: matches.length * 4 } : { tools: 4, mcps: 1, read: 2, write: 2 }, catalog_counts: counts, unavailable_counts: { tools: 0, mcps: 0, read: 0, write: 0 }, selection_limits: { tools: 5000, mcps: 100 } }
        return route.fulfill({ json: result })
      }
      return route.continue()
    }
    if (pathname === `${path}/scope-selection`) {
      const body = request.postDataJSON()
      let ids = body.tool_ids as string[]
      if (body.mode === "groups") {
        ids = ids.filter(id => !body.server_ids.includes(tool(id).server_id))
        if (body.checked) ids.push(...body.server_ids.flatMap((server: string) => Array.from({ length: 4 }, (_, index) => `mcp.${server}.tool-${index}`)))
      }
      const selectedGroups = [...new Set(ids.map(id => tool(id).server_id))]
      return route.fulfill({ json: { catalog_revision: `catalog-${saved.revision}`, tool_ids: ids, available_ids: ids, unavailable_ids: [], tools: ids.map(tool), selected_counts: { tools: ids.length, mcps: selectedGroups.length, read: ids.filter(id => tool(id).access === "read").length, write: ids.filter(id => tool(id).access === "write").length }, group_selected_counts: selectedGroups.map(server_id => ({ server_id, selected_count: ids.filter(id => tool(id).server_id === server_id).length })), difference_summary: difference(ids) } })
    }
    if (pathname === `${path}/scope-preview`) {
      const body = request.postDataJSON(), ids = body.tool_ids as string[]
      model.previews.push(body)
      return route.fulfill({ json: { ...body, confirmation: `ticket-${model.previews.length}`, confirmation_expires_at: now + 600, previous_server_policies: saved.server_policies, previous_tools: saved.tools, tools: ids.map(tool), added: ids.filter(id => !saved.tools.some(item => item.id === id)), removed: saved.tools.filter(item => !ids.includes(item.id)).map(item => item.id), difference_summary: difference(ids) } })
    }
    if (pathname === `${path}/scope`) {
      const body = request.postDataJSON()
      model.writes.push(body)
      saved = { ...saved, ...body, tools: body.tool_ids.map(tool), revision: saved.revision + 1 }
      if (model.loseSaveResponse) { model.loseSaveResponse = false; return route.fulfill({ status: 503, json: { error: "request_failed" } }) }
      return route.fulfill({ json: saved })
    }
    return route.continue()
  })
  await page.goto("/console/#/myConnections")
  await page.getByRole("row").filter({ hasText: "Paged client" }).getByRole("button", { name: "Adjust", exact: true }).click()
  const editor = page.getByRole("dialog", { name: "Adjust authorization scope", exact: true })
  await expect(editor.locator(".authorization-mcp-editor tr[data-row-key]")).toHaveCount(10)
  await expect(editor.locator('.oauth-paged-tools tr[data-row-key="mcp.synthetic-0000.tool-0"]').getByRole("checkbox")).toBeChecked()
  return { editor, model, first, getSaved: () => saved }
}

test("@permissions paged OAuth reads ten services and confirms only an explicit new continuous policy", async ({ page }) => {
  const { editor, model, first, getSaved } = await setup(page)
  expect(model.reads.filter(url => url.searchParams.get("view") === "groups")).toHaveLength(1)
  expect(model.fullReads).toBe(0)
  await editor.getByRole("textbox", { name: "Search MCP", exact: true }).fill("synthetic-4999")
  const row = editor.locator('.authorization-mcp-editor tr[data-row-key="synthetic-4999"]')
  await expect(row.getByRole("radio", { name: "None", exact: true })).toBeChecked()
  await row.getByRole("radio", { name: "Service read", exact: true }).check()
  await editor.getByRole("button", { name: "Save authorization", exact: true }).click()
  const confirm = page.getByRole("alertdialog", { name: "Allow the added tools and service access?", exact: true })
  await expect(confirm).toContainText("synthetic-4999")
  expect(model.writes).toHaveLength(0)
  await confirm.getByRole("button", { name: "Confirm update", exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(model.writes).toHaveLength(1)
  expect(model.writes[0].tool_ids).toEqual([first])
  expect(getSaved().server_policies).toEqual([{ server_id: "synthetic-4999", server_binding: "binding-4999", mode: "continuous", access: "read" }])
  expect(model.reads.filter(url => url.searchParams.get("view") === "groups").every(url => url.searchParams.get("limit") === "10")).toBe(true)
})

test("@permissions paged OAuth exact-tool drafts survive service search and keyboard page retry", async ({ page }) => {
  const { editor, model, first } = await setup(page)
  const search = editor.getByRole("textbox", { name: "Search MCP", exact: true })
  await search.fill("synthetic-0017")
  await editor.locator('.authorization-mcp-editor tr[data-row-key="synthetic-0017"]').getByRole("radio", { name: "Selected tools", exact: true }).check()
  const added = "mcp.synthetic-0017.tool-1"
  await editor.locator(`.oauth-paged-tools tr[data-row-key="${added}"]`).getByRole("checkbox").check()
  await search.fill("")
  await expect(editor.locator(".authorization-mcp-editor tr[data-row-key]")).toHaveCount(10)
  model.failPage = true
  const next = editor.getByRole("navigation", { name: "MCP pages", exact: true }).getByRole("button", { name: "Next page", exact: true })
  await next.focus(); await page.keyboard.press("Enter")
  const retry = editor.getByRole("button", { name: "Retry MCP page", exact: true })
  await expect(retry).toBeEnabled()
  await retry.focus(); await page.keyboard.press("Space")
  await expect(editor.getByRole("navigation", { name: "MCP pages", exact: true })).toContainText("Page 2")
  await expect(retry).toHaveCount(0)
  await expect(editor.locator(`.oauth-paged-tools tr[data-row-key="${added}"]`).getByRole("checkbox")).toBeChecked()
  await editor.getByRole("button", { name: "Save authorization", exact: true }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm update", exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(model.writes[0].tool_ids.sort()).toEqual([first, added].sort())
  expect(model.writes[0].server_policies).toEqual([])
  expect(model.fullReads).toBe(0)
})

test("@permissions paged OAuth quota save reconciles an unknown committed result without replay", async ({ page }) => {
  const { editor, model, first, getSaved } = await setup(page)
  await editor.locator(".authorization-quota-settings [aria-expanded]").first().click()
  const rate = editor.getByRole("spinbutton", { name: "Calls per minute", exact: true })
  const save = editor.getByRole("button", { name: "Save authorization", exact: true })
  model.loseSaveResponse = true
  await rate.fill("29")
  await save.click()
  await expect(page.getByRole("alertdialog")).toHaveCount(0)
  await expect(editor.getByRole("alert")).toContainText("result is unknown")
  await expect(save).toBeDisabled()
  expect(model.writes).toHaveLength(1)
  expect(getSaved().revision).toBe(2)
  await editor.getByRole("button", { name: "Refresh available scope", exact: true }).click()
  await expect(editor.locator(".oauth-scope-refresh-status")).toContainText("Saved grant revision 2")
  await expect(save).toBeDisabled()
  expect(model.writes).toHaveLength(1)
  await rate.fill("28")
  await save.click()
  await expect(editor).toHaveCount(0)
  await expect(page.getByRole("alertdialog")).toHaveCount(0)
  expect(model.writes).toHaveLength(2)
  expect(model.previews.map(body => body.expected_revision)).toEqual([1, 2])
  expect(model.writes.map(body => body.confirmation)).toEqual(["ticket-1", "ticket-2"])
  for (const body of model.writes) expect(body.tool_ids).toEqual([first])
})

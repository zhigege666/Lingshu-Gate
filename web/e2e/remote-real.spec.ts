import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

test('E2E-009 @remote real loopback remote creation, connection, reconfiguration and call', async ({ page }) => {
  test.setTimeout(60_000)
  const root = process.env.GATE_E2E_TEMP_ROOT!
  const endpoint = JSON.parse(readFileSync(join(root, 'http-peer.json'), 'utf8')).endpoint
  const peer = () => JSON.parse(readFileSync(join(root, 'http-peer-state.json'), 'utf8'))
  const before = peer()
  await login(page)
  await page.goto('/console/#/servers')
  await page.getByRole('button', { name: /Connect remote MCP/ }).click()
  const editor = page.getByRole('dialog', { name: 'New MCP config', exact: true })
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  await editor.locator('textarea[data-manifest-json]').fill(JSON.stringify({
    id: 'synthetic-remote-browser', name: 'Synthetic remote browser', enabled: true,
    launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint }, timeout_seconds: 3,
    restart_policy: { enabled: false },
  }, null, 2))
  await editor.getByRole('button', { name: 'Save Config', exact: true }).click()
  await expect(editor).toHaveCount(0)
  const row = page.getByRole('row').filter({ hasText: 'synthetic-remote-browser' })
  await row.getByRole('button', { name: 'Apply', exact: true }).click()
  await page.getByRole('alertdialog', { name: 'Apply configuration and leave stopped?', exact: true }).getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(async () => (await page.request.get('/v1/mcp/servers/synthetic-remote-browser')).status()).toBe(200)
  await page.goto('/console/#/servers/synthetic-remote-browser')
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect.poll(async () => (await (await page.request.get('/v1/mcp/servers/synthetic-remote-browser')).json()).status).toBe('running')
  expect(peer().discoveries).toBeGreaterThan(before.discoveries)
  expect(peer().lists).toBeGreaterThan(before.lists)
  await page.getByRole('tab', { name: 'Configuration', exact: true }).click()
  await page.getByRole('button', { name: 'Edit configuration', exact: true }).click()
  const serviceEditor = page.getByRole('dialog', { name: 'Edit configuration · synthetic-remote-browser', exact: true })
  await serviceEditor.getByLabel('Name', { exact: true }).fill('Synthetic remote reconnected')
  await serviceEditor.getByRole('button', { name: 'Replace endpoint', exact: true }).click()
  await serviceEditor.getByLabel('MCP Endpoint', { exact: true }).fill(endpoint.replace('/mcp', '/reconnected'))
  await serviceEditor.getByRole('radio', { name: 'Save, apply and start', exact: true }).check()
  const lists = peer().lists
  const reconnect = serviceEditor.getByRole('button', { name: 'Save configuration', exact: true })
  await expectInViewportAndUnobscured(reconnect)
  await reconnect.click()
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && new URL(response.url()).pathname === '/v1/mcp/configs/synthetic-remote-browser')
  await page.getByRole('alertdialog', { name: 'Save and reconnect · synthetic-remote-browser', exact: true }).getByRole('button', { name: 'Save and reconnect', exact: true }).click()
  const result = await saved
  expect(result.status()).toBe(200)
  expect((await result.json()).server.status).toBe('running')
  await expect(page.getByRole('alertdialog', { name: 'Save and reconnect · synthetic-remote-browser', exact: true, includeHidden: true })).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: 'Edit configuration · synthetic-remote-browser', exact: true, includeHidden: true })).toHaveCount(0)
  expect(peer().lists).toBeGreaterThan(lists)
  expect(peer().last_list_path).toBe('/reconnected')
  expect((await (await page.request.get('/v1/mcp/configs/synthetic-remote-browser')).json()).manifest.name).toBe('Synthetic remote reconnected')
  await page.getByRole('tab', { name: /^Tools/ }).click()
  await page.getByRole('tabpanel', { name: /^Tools/ }).getByRole('button', { name: 'echo', exact: true }).click()
  await page.getByRole('button', { name: 'Test tool', exact: true }).click()
  await page.getByRole('button', { name: 'Run tool', exact: true }).click()
  // Structured results initially collapse nested MCP content. Use the visible
  // text-view control to inspect the returned content, preserving the real call.
  await page.getByRole('button', { name: 'Text', exact: true }).click()
  await expect(page.getByText('synthetic-loopback-ok', { exact: false }).first()).toBeVisible()
  expect(peer().calls).toBe(before.calls + 1)
  expect(peer().last_call_path).toBe('/reconnected')
})

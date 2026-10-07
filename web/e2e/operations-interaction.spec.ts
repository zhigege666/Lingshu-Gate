import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { cache, logs, events } from './synthetic-data'

test('E2E-412 cache permissions, empty states and cancelled cleanup never send DELETE @operations', async ({ page }) => {
  await login(page)
  const base = cache.caches[0]
  const entries = [
    { ...base, name: 'synthetic-empty', size_bytes: 0, file_count: 0 },
    { ...base, name: 'synthetic-missing', exists: false, size_bytes: 0, file_count: 0 },
    { ...base, name: 'synthetic-readonly', writable: false },
    { ...base, name: 'synthetic-ready' },
  ]
  let deletes = 0
  await page.route('**/v1/runtime/cache**', route => {
    if (route.request().method() === 'DELETE') { deletes++; return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } }) }
    return route.fulfill({ json: { ...cache, caches: entries } })
  })
  await page.goto('/console/#/runtimeCache')
  const row = (name: string) => page.locator('tbody tr').filter({ hasText: name })
  await expect(row('synthetic-empty').getByRole('button', { name: 'Nothing to clear', exact: true })).toBeDisabled()
  await expect(row('synthetic-missing')).toContainText('Can create')
  await expect(row('synthetic-missing').getByRole('button', { name: 'Nothing to clear', exact: true })).toBeDisabled()
  await expect(row('synthetic-readonly')).toContainText('Not writable')
  await expect(row('synthetic-readonly').getByRole('button', { name: 'Cannot clear', exact: true })).toBeDisabled()
  await row('synthetic-ready').getByRole('button', { name: 'Clear Cache', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('synthetic-ready')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  expect(deletes).toBe(0)
})

for (const width of [1280, 390]) test(`E2E-${width === 1280 ? 413 : 414} MCP selector name/ID keyboard and authorized-all ${width} @operations`, async ({ page }, testInfo) => {
  await login(page)
  await page.setViewportSize({ width, height: width === 390 ? 844 : 600 })
  const scopes = Array.from({ length: 100 }, (_, i) => ({ id: `allowed-${String(i).padStart(3, '0')}`, name: `Visible MCP ${i}`, availability: 'current' }))
  const requests: string[] = []
  await page.route('**/v1/observability/mcp-scopes**', route => {
    const q = new URL(route.request().url()).searchParams
    const found = scopes.filter(s => q.has('server_id') ? s.id === q.get('server_id') : `${s.id} ${s.name}`.toLowerCase().includes((q.get('q') || '').toLowerCase()))
    const offset = Number(q.get('offset') || 0), limit = Number(q.get('limit') || 50)
    return route.fulfill({ json: { scopes: found.slice(offset, offset + limit), total: found.length, offset, limit, capabilities: { can_read_all: false, all_scope: 'authorized_services' } } })
  })
  await page.route('**/v1/logs**', route => { requests.push(route.request().url()); return route.fulfill({ json: { logs } }) })
  await page.route('**/v1/events**', route => route.fulfill({ json: { events } }))
  await page.goto('/console/#/logs')
  const combo = page.getByRole('combobox', { name: 'MCP', exact: true })
  await combo.click()
  const popup = page.locator('.ant-select-dropdown:visible')
  await expect(popup).toContainText('All authorized MCPs')
  await expect(popup).not.toContainText('All MCPs and system records')
  await expectInViewportAndUnobscured(popup.getByRole('button', { name: 'Next', exact: true }))
  await popup.getByRole('button', { name: 'Next', exact: true }).click()
  await expect(popup.getByRole('status')).toContainText('41–80 / 100')
  await combo.fill('Visible MCP 99')
  await expect(popup.locator('.ant-select-item-option')).toHaveCount(2)
  await popup.locator('.ant-select-item-option').filter({ hasText: 'Visible MCP 99' }).click()
  await expect(page.locator('.ant-select').filter({ has: combo })).toContainText('allowed-099')
  await page.getByRole('button', { name: 'Apply Filters', exact: true }).click()
  await expect.poll(() => requests.some(url => new URL(url).searchParams.get('server_id') === 'allowed-099')).toBe(true)
  await combo.click()
  await combo.fill('allowed-042')
  // The retained selected option can render before the debounced search resolves.
  await expect(popup.locator('.ant-select-item-option').filter({ hasText: 'Visible MCP 42 · allowed-042' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath(`mcp-selector-${width}x${width === 390 ? 844 : 600}.png`) })
  const active = popup.locator('.ant-select-item-option-active')
  for (let attempt = 0; attempt < 3; attempt++) {
    if ((await active.allTextContents()).join(' ').includes('allowed-042')) break
    await combo.press('ArrowDown')
  }
  await expect(active).toContainText('allowed-042')
  await combo.press('Enter')
  await expect(page.locator('.ant-select').filter({ has: combo })).toContainText('allowed-042')
  const appliedRequests = requests.length
  const clear = page.getByRole('button', { name: 'Clear MCP filter', exact: true })
  await clear.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.ant-select').filter({ has: combo })).toContainText('All authorized MCPs')
  expect(requests).toHaveLength(appliedRequests)
  await page.getByRole('button', { name: 'Apply Filters', exact: true }).click()
  await expect.poll(() => new URL(requests.at(-1)!).searchParams.has('server_id')).toBe(false)
  await page.getByRole('tab', { name: /Events/ }).click()
  await expect(page.getByRole('combobox', { name: 'MCP', exact: true })).toBeVisible()
})

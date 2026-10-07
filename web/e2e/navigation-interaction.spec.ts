import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('E2E-203 @full late personal-service detail cannot replace current selection', async ({ page }) => {
  await login(page)
  const summaries = ['a', 'b'].map(id => ({ id: `synthetic-${id}`, name: `Synthetic ${id.toUpperCase()}`, tool_count: 1, read_tool_count: 1, write_tool_count: 0 }))
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/me/mcp-servers?*', route => route.fulfill({ json: { servers: summaries, total: 2 } }))
  await page.route('**/v1/me/mcp-servers/*', async route => {
    const a = route.request().url().endsWith('synthetic-a')
    if (a) await gate
    await route.fulfill({ json: { ...summaries[a ? 0 : 1], tools: [{ id: a ? 'tool-a' : 'tool-b', name: a ? 'Tool A late' : 'Tool B current', description: '', required_access: 'read' }] } })
  })
  await page.goto('/console/#/myServers')
  await page.getByRole('button', { name: 'Synthetic A', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('button', { name: 'Synthetic B', exact: true }).click()
  await expect(page.getByText('Tool B current', { exact: true })).toBeVisible()
  const delayed = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/synthetic-a'))
  release!()
  await delayed
  await expect(page.getByRole('dialog')).toContainText('Tool B current')
  await expect(page.getByText('Tool A late', { exact: true })).toHaveCount(0)
})

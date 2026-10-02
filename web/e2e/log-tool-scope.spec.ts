import { test, expect, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { logs, events } from './synthetic-data'

const output = process.env.GATE_LOG_TOOL_DIR
async function choose(page: Page, label: string, query: string, text: string) {
  const combo = page.getByRole('combobox', { name: label, exact: true })
  await combo.click(); await combo.fill(query)
  await page.locator('.ant-select-dropdown:visible:not(.ant-slide-up-leave) .ant-select-item-option').filter({ hasText: text }).click()
}
for (const [width, height] of [[1188, 761], [390, 844]]) test(`E2E-${width === 1188 ? 540 : 541} @log-tool-scope scoped tools, history, empty and repeated reset ${width}`, async ({ page }) => {
  test.skip(!output, 'Opt-in scoped log tool interaction evidence')
  await login(page)
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  await page.setViewportSize({ width, height })
  const mcps = [{ id: 'allowed-a', name: 'Allowed current A', availability: 'current' }, { id: 'allowed-empty', name: 'Allowed empty', availability: 'current' }, { id: 'allowed-history', name: 'Allowed history', availability: 'historical' }]
  const toolScopes = Array.from({ length: 100 }, (_, i) => ({ id: `mcp.allowed-a.read${i}`, name: `Read records ${i}`, availability: 'current' }))
  const requested: string[] = [], logQueries: string[] = [], mutations: string[] = []
  await page.route('**/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), q = url.searchParams
    if (request.method() !== 'GET') { mutations.push(request.url()); return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } }) }
    if (url.pathname === '/v1/observability/mcp-scopes') {
      const found = mcps.filter(item => q.has('server_id') ? item.id === q.get('server_id') : `${item.id} ${item.name}`.toLowerCase().includes((q.get('q') || '').toLowerCase()))
      return route.fulfill({ json: { scopes: found, total: found.length, offset: 0, limit: 40, capabilities: { can_read_all: false, all_scope: 'authorized_services' } } })
    }
    if (url.pathname === '/v1/observability/tool-scopes') {
      requested.push(url.toString())
      const server = q.get('server_id')
      if (!mcps.some(item => item.id === server)) return route.fulfill({ status: 404, json: { detail: 'Scope unavailable' } })
      const candidates = server === 'allowed-a' ? toolScopes : server === 'allowed-history' ? [{ id: 'mcp.allowed-history.retired', name: 'Retired reader', availability: 'historical' }] : []
      const found = candidates.filter(item => q.has('tool_id') ? item.id === q.get('tool_id') : `${item.id} ${item.name}`.toLowerCase().includes((q.get('q') || '').toLowerCase()))
      const offset = Number(q.get('offset') || 0), limit = Number(q.get('limit') || 40)
      return route.fulfill({ json: { scopes: found.slice(offset, offset + limit), total: found.length, offset, limit } })
    }
    if (url.pathname === '/v1/logs') { logQueries.push(url.toString()); return route.fulfill({ json: { logs } }) }
    if (url.pathname === '/v1/events') return route.fulfill({ json: { events } })
    return route.continue()
  })
  await page.goto('/console/#/logs')
  const tool = page.getByRole('combobox', { name: '工具', exact: true })
  await expect(tool).toBeDisabled()
  expect(requested).toEqual([])
  await choose(page, 'MCP', 'allowed-a', 'Allowed current A')
  await expect(tool).toBeEnabled()
  await tool.click()
  const popup = page.locator('.ant-select-dropdown:visible:not(.ant-slide-up-leave)')
  await expect(popup).toContainText('1–40 / 100')
  await expectInViewportAndUnobscured(popup.getByRole('button', { name: '下一页', exact: true }))
  await popup.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(popup).toContainText('41–80 / 100')
  await tool.fill('read42')
  await popup.locator('.ant-select-item-option').filter({ hasText: 'Read records 42' }).click()
  await choose(page, 'MCP', 'allowed-a', 'Allowed current A')
  await expect(page.locator('.ant-select').filter({ has: tool })).toContainText('read42')
  await page.getByRole('button', { name: '应用筛选', exact: true }).click()
  await expect.poll(() => new URL(logQueries.at(-1)!).searchParams.get('tool_id')).toBe('mcp.allowed-a.read42')
  const applied = logQueries.length
  await choose(page, 'MCP', 'allowed-empty', 'Allowed empty')
  await expect(page.locator('.ant-select').filter({ has: tool })).toContainText('全部工具')
  await tool.click()
  await expect(popup).toContainText('此范围内没有匹配工具')
  await expect(popup).not.toContainText('Read records')
  mkdirSync(output!, { recursive: true })
  await page.screenshot({ path: join(output!, `log-empty-tools-${width}x${height}.png`) })
  await tool.press('Escape')
  expect(logQueries).toHaveLength(applied)
  await choose(page, 'MCP', 'allowed-history', 'Allowed history')
  await tool.click()
  await expect(popup).toContainText('历史工具')
  await popup.locator('.ant-select-item-option').filter({ hasText: 'Retired reader' }).click()
  await page.getByRole('button', { name: '应用筛选', exact: true }).click()
  await expect.poll(() => new URL(logQueries.at(-1)!).searchParams.get('tool_id')).toBe('mcp.allowed-history.retired')
  await tool.click(); await tool.fill('mcp.allowed-history.uncatalogued')
  const exact = popup.getByRole('button', { name: '按精确 ID 筛选：mcp.allowed-history.uncatalogued', exact: true })
  await expect(exact).toBeVisible(); await exact.click()
  await expect(page.locator('.ant-select').filter({ has: tool })).toContainText('mcp.allowed-history.uncatalogued')
  await page.getByRole('button', { name: '清除工具筛选', exact: true }).focus(); await page.keyboard.press('Enter')
  await expect(page.locator('.ant-select').filter({ has: tool })).toContainText('全部工具')
  const beforeReset = logQueries.length
  await page.getByRole('button', { name: '重置条件', exact: true }).click()
  await page.getByRole('button', { name: '重置条件', exact: true }).click()
  await expect(tool).toBeDisabled()
  expect(logQueries).toHaveLength(beforeReset)
  await page.getByRole('button', { name: '应用筛选', exact: true }).click()
  await expect.poll(() => new URL(logQueries.at(-1)!).searchParams.has('tool_id')).toBe(false)
  expect(requested.every(url => mcps.some(item => item.id === new URL(url).searchParams.get('server_id')))).toBe(true)
  await page.getByRole('tab', { name: /事件/ }).click()
  await expect(page.getByRole('combobox', { name: '工具', exact: true })).toHaveCount(0)
  expect(mutations).toEqual([])
  writeFileSync(join(output!, `log-tool-scope-${width}x${height}.json`), JSON.stringify({ synthetic: true, requested, logQueries, mutations }, null, 2))
})

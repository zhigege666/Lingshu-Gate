import { expect, test, type Page } from '@playwright/test'
import { login } from './helpers'
import { audits, servers, tools } from './synthetic-data'

// All changing resources in these scenarios are synthetic. No service action,
// invocation, installation or network execution is dispatched to the backend.
const time = '2026-01-01T00:00:00Z'
const log = (version: number) => ({ id: `synthetic-log-${version}`, level: 'info', source: 'synthetic', server_id: null, event_type: 'synthetic.snapshot', message: `Log snapshot ${version}`, payload: { version }, created_at: time })
const event = (version: number) => ({ id: `synthetic-event-${version}`, type: `synthetic.event.snapshot.${version}`, source: 'synthetic', subject_id: null, payload: { version }, created_at: time })
const scopes = { scopes: [], total: 0, offset: 0, limit: 40, capabilities: { can_read_all: true, all_scope: 'global' } }
const statistics = (requests: number) => ({ period_start: time, period_end: '2026-01-02T00:00:00Z', bucket_hours: 1, totals: { requests, calls: requests, mcp_calls: requests, success: requests, errors: 0, not_invoked: 0 }, series: [{ start: time, requests, calls: requests, mcp_calls: requests }], top_tools: [] })
const refresh = (page: Page) => page.getByRole('button', { name: 'Refresh current page', exact: true })

test.beforeEach(async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
})

test('workspace route reads are scoped and direct server entry reads its shared collection once', async ({ page }) => {
  const reads: string[] = []
  const fixtures: Record<string, unknown> = {
    '/v1/access/invocation-audits': { audits: audits.slice(0, 1), filter_options: { users: [], servers: [], tools: [] } },
    '/v1/mcp/configs': { configs: [], errors: [] },
    '/v1/mcp/servers': { servers: servers.slice(0, 1), load_errors: [] },
    '/v1/tools': tools.slice(0, 1),
    '/v1/access/tool-classifications': { classifications: [] },
  }
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    reads.push(path)
    if (path in fixtures) return route.fulfill({ json: fixtures[path] })
    if (/^\/v1\/mcp\/servers\/[^/]+\/detail$/.test(path)) return route.fulfill({ json: { server: servers[0], manifest: {}, tools: [], logs: [], events: [] } })
    return route.continue()
  })
  await page.goto('/console/#/invocationAudit')
  await expect(page.getByRole('button', { name: audits[0].tool_id, exact: true })).toBeVisible()
  await expect(refresh(page)).not.toHaveClass(/ant-btn-loading/)
  expect(reads.filter(path => ['/v1/mcp/configs', '/v1/mcp/servers', '/v1/tools'].includes(path))).toEqual([])

  await page.goto('/console/#/configs')
  await expect.poll(() => reads.filter(path => path === '/v1/mcp/configs').length).toBe(1)
  await expect(refresh(page)).not.toHaveClass(/ant-btn-loading/)
  expect(reads.filter(path => ['/v1/mcp/servers', '/v1/tools'].includes(path))).toEqual([])

  // A new document catches the former mount refresh + route refresh duplicate.
  await page.goto('/console/?workspace-read-test=servers#/servers')
  await expect.poll(() => reads.filter(path => path === '/v1/mcp/servers').length).toBe(1)
  await expect.poll(() => reads.filter(path => path === '/v1/tools').length).toBe(1)
  await expect(page.getByText(servers[0].name, { exact: true }).first()).toBeVisible()
  await expect(refresh(page)).not.toHaveClass(/ant-btn-loading/)
  expect(reads.filter(path => path === '/v1/mcp/configs')).toHaveLength(1)
  expect(reads.filter(path => path === '/v1/mcp/servers')).toHaveLength(1)
})

test('dashboard loads statistics initially and keeps top refresh pending until the new statistics settle', async ({ page }) => {
  let statisticsReads = 0
  let serverReads = 0
  let toolReads = 0
  let configReads = 0
  let releaseInitial!: () => void
  let releaseRefresh!: () => void
  const initialStatistics = new Promise<void>(resolve => { releaseInitial = resolve })
  const refreshedStatistics = new Promise<void>(resolve => { releaseRefresh = resolve })
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    if (path === '/v1/access/invocation-statistics') {
      const request = ++statisticsReads
      if (request === 1) await initialStatistics
      if (request === 2) await refreshedStatistics
      return route.fulfill({ json: statistics(request * 111) })
    }
    if (path === '/v1/mcp/servers') { serverReads += 1; return route.fulfill({ json: { servers: [], load_errors: [] } }) }
    if (path === '/v1/tools') { toolReads += 1; return route.fulfill({ json: [] }) }
    if (path === '/v1/mcp/configs') { configReads += 1; return route.fulfill({ json: { configs: [], errors: [] } }) }
    return route.continue()
  })
  try {
    await page.goto('/console/#/dashboard')
    await expect.poll(() => statisticsReads).toBe(1)
    await expect(page.locator('[data-resource="servers"]')).toHaveAttribute('aria-busy', 'false')
    await expect(page.locator('[data-resource="tools"]')).toHaveAttribute('aria-busy', 'false')
    await expect(refresh(page)).toHaveClass(/ant-btn-loading/)
    releaseInitial()
    await expect(page.locator('.dashboard-metric-grid')).toContainText('111')
    await expect(refresh(page)).not.toHaveClass(/ant-btn-loading/)
    expect([serverReads, toolReads, configReads]).toEqual([1, 1, 0])

    await refresh(page).click()
    await expect.poll(() => statisticsReads).toBe(2)
    await expect(refresh(page)).toHaveClass(/ant-btn-loading/)
    releaseRefresh()
    await expect(page.locator('.dashboard-metric-grid')).toContainText('222')
    await expect(refresh(page)).not.toHaveClass(/ant-btn-loading/)
    expect([serverReads, toolReads, configReads, statisticsReads]).toEqual([2, 2, 0, 2])
  } finally {
    releaseInitial()
    releaseRefresh()
  }
})

for (const failed of ['logs', 'events'] as const) {
  test(`logs workspace retains each snapshot and retries only failed ${failed}`, async ({ page }) => {
    const sibling = failed === 'logs' ? 'events' : 'logs'
    const requests: Record<'logs' | 'events', URL[]> = { logs: [], events: [] }
    let directoryReads = 0
    let version = 1
    let failure = false
    await page.route('**/v1/**', async route => {
      const url = new URL(route.request().url())
      if (route.request().method() !== 'GET') return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
      if (url.pathname === '/v1/observability/mcp-scopes') { directoryReads += 1; return route.fulfill({ json: scopes }) }
      const source = url.pathname === '/v1/logs' ? 'logs' : url.pathname === '/v1/events' ? 'events' : null
      if (source) {
        requests[source].push(url)
        if (failure && source === failed) return route.fulfill({ status: 503, json: { detail: `synthetic ${failed} failure` } })
        return route.fulfill({ json: source === 'logs' ? { logs: [log(version)] } : { events: [event(version)] } })
      }
      return route.continue()
    })
    const tab = (source: 'logs' | 'events') => page.getByRole('tab', { name: new RegExp(`^${source === 'logs' ? 'Logs' : 'Events'} \\(`) })
    const snapshot = (source: 'logs' | 'events', value: number) => page.getByRole('button', { name: source === 'logs' ? `Log snapshot ${value}` : `synthetic.event.snapshot.${value}`, exact: true })
    await page.goto(`/console/#/logs/?tab=${failed}`)
    await expect(snapshot(failed, 1)).toBeVisible()
    await expect(page.getByText('All MCPs and system records', { exact: true })).toBeVisible()
    expect(directoryReads).toBe(1)
    await expect(page.getByRole('combobox', { name: 'MCP', exact: true })).toHaveCount(1)
    expect(requests.logs).toHaveLength(1)
    expect(requests.events).toHaveLength(1)

    await page.getByRole('textbox', { name: 'Keyword', exact: true }).fill(`retry-${failed}`)
    version = 2; failure = true
    await page.getByRole('button', { name: 'Apply Filters', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText(`synthetic ${failed} failure`)
    await expect(snapshot(failed, 1)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Apply Filters', exact: true })).toBeEnabled()
    await tab(sibling).click()
    await expect(snapshot(sibling, 2)).toBeVisible()
    await expect(page.getByText('All MCPs and system records', { exact: true })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await tab(failed).click()
    await expect(page.getByText('All MCPs and system records', { exact: true })).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Keyword', exact: true })).toHaveValue(`retry-${failed}`)
    version = 3; failure = false
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(snapshot(failed, 3)).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(requests[failed]).toHaveLength(3)
    expect(requests[failed].at(-1)!.searchParams.get('keyword')).toBe(`retry-${failed}`)
    expect(requests[sibling]).toHaveLength(2)
    await tab(sibling).click()
    await expect(snapshot(sibling, 2)).toBeVisible()
    await expect(page.getByText('All MCPs and system records', { exact: true })).toBeVisible()
    // Switching a tab reads only the newly visible selector, not both panels.
    await expect.poll(() => directoryReads).toBe(4)
  })
}

test('JSON output reports clipboard failure, retains content and supports retry', async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as typeof window & { copyAttempts: number; copiedText: string }
    state.copyAttempts = 0; state.copiedText = ''
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => {
      state.copyAttempts += 1
      if (state.copyAttempts === 1) throw new Error('Synthetic clipboard denial')
      state.copiedText = value
    } } })
  })
  await page.route('**/v1/logs**', route => route.fulfill({ json: { logs: [log(1)] } }))
  await page.route('**/v1/events**', route => route.fulfill({ json: { events: [] } }))
  await page.route('**/v1/observability/mcp-scopes**', route => route.fulfill({ json: scopes }))
  await page.goto('/console/#/logs')
  await page.getByRole('button', { name: 'Log snapshot 1', exact: true }).click()
  const detail = page.getByRole('dialog', { name: 'Selected Detail', exact: true })
  const original = await detail.locator('pre').innerText()
  await detail.getByRole('button', { name: 'Copy', exact: true }).click()
  await expect(detail.getByRole('alert')).toContainText('Copy failed. Retry')
  await expect(detail.locator('pre')).toHaveText(original)
  await detail.getByRole('button', { name: 'Copy', exact: true }).click()
  await expect(detail.getByRole('alert')).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { copyAttempts: number }).copyAttempts)).toBe(2)
  expect(await page.evaluate(() => (window as typeof window & { copiedText: string }).copiedText)).toBe(original)
})

test('invocation short choices preserve false, zero, null, absence and invalid JSON recovery', async ({ page }) => {
  const fixture = { ...tools[0], input_schema: { type: 'object', properties: { enabled: { type: 'boolean' }, count: { type: 'integer', enum: [0, 1] }, nullable: { type: ['string', 'null'], enum: [null, 'value'] } } } }
  await page.route('**/v1/tools', route => route.fulfill({ json: [fixture] }))
  await page.route('**/v1/mcp/servers', route => route.fulfill({ json: { servers: servers.slice(0, 1), load_errors: [] } }))
  await page.goto('/console/#/invoke')
  const mode = page.getByRole('radiogroup', { name: 'Argument editor mode', exact: true })
  await expect(page.getByRole('radiogroup', { name: 'enabled', exact: true }).getByRole('radio', { checked: true })).toHaveCount(0)
  await page.getByRole('radiogroup', { name: 'enabled', exact: true }).getByRole('radio', { name: 'No (false)', exact: true }).check()
  await page.getByRole('radiogroup', { name: 'count', exact: true }).getByRole('radio', { name: '0', exact: true }).check()
  await page.getByRole('radiogroup', { name: 'nullable', exact: true }).getByRole('radio', { name: 'Empty value (null)', exact: true }).check()
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  const editor = page.locator('#invoke-arguments')
  expect(JSON.parse(await editor.inputValue())).toEqual({ enabled: false, count: 0, nullable: null })
  await mode.getByRole('radio', { name: 'Form', exact: true }).check()
  await page.getByRole('button', { name: 'Omit nullable', exact: true }).click()
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await editor.inputValue())).toEqual({ enabled: false, count: 0 })
  await editor.fill('{"enabled": false,')
  // The rejected mode change leaves the raw editor and its exact text intact.
  await mode.getByRole('radio', { name: 'Form', exact: true }).click()
  await expect(mode.getByRole('radio', { name: 'JSON', exact: true })).toBeChecked()
  await expect(editor).toHaveValue('{"enabled": false,')
})

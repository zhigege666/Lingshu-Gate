import { test, expect, type Page, type Route } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

const output = process.env.GATE_PAYLOAD_EVIDENCE_DIR
const audit = (id: string) => ({ id, server_id: 'synthetic-service', tool_id: `synthetic-tool-${id}`, created_at: '2026-01-01T00:00:00Z', outcome: 'success', decision: 'allow', correlation_id: id })
const detail = (id: string, input: object, result: object = input) => ({ audit: audit(id), input, output: result, recording_mode: 'redacted' })
async function setup(page: Page, ids: string[], respond: (id: string, route: Route) => Promise<unknown>) {
  await login(page, 'viewer')
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  await page.route('**/v1/me/invocations**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/v1/me/invocations') return route.fulfill({ json: { audits: ids.map(audit) } })
    return respond(decodeURIComponent(path.split('/').at(-1)!), route)
  })
  await page.goto('/console/#/myInvocations')
  await expect(page.locator('tbody tr[data-row-key]')).toHaveCount(ids.length)
}
const drawer = (page: Page) => page.getByRole('dialog', { name: '本人调用详情', exact: true })
async function open(page: Page, id: string) {
  await page.locator('tbody tr').filter({ hasText: `synthetic-tool-${id}` }).getByRole('button', { name: '查看详情', exact: true }).click()
  await expect(drawer(page)).toBeVisible()
}
async function close(page: Page) {
  await drawer(page).getByRole('button', { name: /Close|关闭/ }).click()
  await expect(drawer(page)).toHaveCount(0)
}

test('E2E-570 @personal-payload recorded primitives and unavailable statuses remain distinct', async ({ page, context }) => {
  test.skip(!output, 'Opt-in synthetic payload presentation; not API permission proof')
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const values: Record<string, object> = {
    null: { status: 'recorded', value: null }, false: { status: 'recorded', value: false }, zero: { status: 'recorded', value: 0 },
    absent: { status: 'not_recorded' }, denied: { status: 'not_invoked' }, truncated: { status: 'truncated', value: { retained: 'synthetic partial' } }, failed: { status: 'serialization_error' },
  }
  const calls: string[] = []
  await setup(page, Object.keys(values), async (id, route) => { calls.push(id); await route.fulfill({ json: detail(id, values[id]) }) })
  for (const [id, expected] of [['null', 'null'], ['false', 'false'], ['zero', '0']]) {
    await open(page, id)
    const input = drawer(page).getByRole('region', { name: '输入', exact: true })
    await expect(input.locator('pre')).toHaveText(expected)
    const count = calls.length
    await input.getByRole('button', { name: '复制 JSON', exact: true }).click()
    await expect.poll(() => calls.length).toBe(count + 1)
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(expected)
    await close(page)
  }
  for (const [id, text] of [['absent', '未记录：'], ['denied', '未执行：'], ['truncated', '内容已截断'], ['failed', '序列化失败']]) {
    await open(page, id)
    const input = drawer(page).getByRole('region', { name: '输入', exact: true })
    await expect(input).toContainText(text)
    await expect(input.getByRole('button', { name: '复制 JSON', exact: true })).toHaveCount(id === 'truncated' ? 1 : 0)
    await close(page)
  }
  mkdirSync(output!, { recursive: true })
  writeFileSync(join(output!, 'payload-status-calls.json'), JSON.stringify({ calls, synthetic: true }, null, 2))
})

test('E2E-571 @personal-payload phone JSON search and expansion preserve full retained copy', async ({ page, context }) => {
  test.skip(!output, 'Opt-in synthetic payload interaction')
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.setViewportSize({ width: 390, height: 844 })
  const value = { marker: 'synthetic-find-me', long_line: 'synthetic-long-value-'.repeat(80), rows: Array.from({ length: 60 }, (_, i) => ({ index: i, label: `synthetic-${i}` })) }
  let count = 0
  await setup(page, ['long'], async (id, route) => { count++; await route.fulfill({ json: detail(id, { status: 'recorded', value }) }) })
  await open(page, 'long')
  const input = drawer(page).getByRole('region', { name: '输入', exact: true })
  await input.getByRole('searchbox', { name: '输入 搜索 JSON 行', exact: true }).fill('synthetic-find-me')
  await expect(input.locator('pre')).toHaveText('"marker": "synthetic-find-me",')
  await input.locator('summary').click()
  await expect(input.locator('pre')).not.toBeVisible()
  await input.locator('summary').click()
  await expect(input.locator('pre')).toBeVisible()
  await input.getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect.poll(() => count).toBe(2)
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(JSON.stringify(value, null, 2))
  await input.getByRole('searchbox', { name: '输入 搜索 JSON 行', exact: true }).fill('')
  const pre = input.locator('pre')
  await expect.poll(() => pre.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
  await pre.evaluate(el => { el.scrollTop = el.scrollHeight })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await expectInViewportAndUnobscured(drawer(page).getByRole('button', { name: /Close|关闭/ }))
  mkdirSync(output!, { recursive: true })
  await page.screenshot({ path: join(output!, 'personal-payload-long-390x844.png') })
})

test('E2E-572 @personal-payload late detail after close cannot replace another record', async ({ page }) => {
  test.skip(!output, 'Opt-in synthetic request ownership')
  let release!: () => void, started!: () => void
  const gate = new Promise<void>(resolve => { release = resolve }), began = new Promise<void>(resolve => { started = resolve })
  await setup(page, ['late', 'current'], async (id, route) => {
    if (id === 'late') { started(); await gate }
    await route.fulfill({ json: detail(id, { status: 'recorded', value: id === 'late' ? 'STALE_PAYLOAD' : 'CURRENT_PAYLOAD' }) })
  })
  await open(page, 'late')
  await began
  await close(page)
  await open(page, 'current')
  await expect(drawer(page)).toContainText('CURRENT_PAYLOAD')
  const returned = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/late'))
  release(); await returned
  await expect(drawer(page)).toContainText('CURRENT_PAYLOAD')
  await expect(drawer(page)).not.toContainText('STALE_PAYLOAD')
})

test('E2E-573 @personal-payload copy rechecks access and clears obsolete content on403', async ({ page }) => {
  test.skip(!output, 'Opt-in mock403 presentation; backend ownership checks are separate')
  let count = 0
  await setup(page, ['revoked'], async (id, route) => {
    count++
    if (count > 1) return route.fulfill({ status: 403, json: { detail: 'Synthetic permission revoked' } })
    return route.fulfill({ json: detail(id, { status: 'recorded', value: 'SYNTHETIC_OLD_VALUE' }) })
  })
  await open(page, 'revoked')
  await drawer(page).getByRole('region', { name: '输入', exact: true }).getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect(drawer(page).getByRole('alert')).toContainText('Synthetic permission revoked')
  await expect(drawer(page)).not.toContainText('SYNTHETIC_OLD_VALUE')
  await expect(drawer(page).getByRole('button', { name: '复制 JSON', exact: true })).toHaveCount(0)
  expect(count).toBe(2)
})

test('E2E-574 @personal-payload browser clipboard failure remains visible without false success', async ({ page }) => {
  test.skip(!output, 'Opt-in browser clipboard failure feedback')
  let count = 0
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new DOMException('Synthetic clipboard denial', 'NotAllowedError') } } }))
  await setup(page, ['clipboard'], async (id, route) => { count++; await route.fulfill({ json: detail(id, { status: 'recorded', value: 0 }) }) })
  await open(page, 'clipboard')
  const input = drawer(page).getByRole('region', { name: '输入', exact: true })
  await input.getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect(input.getByRole('alert')).toContainText('复制失败')
  await expect(input).not.toContainText('已复制保留内容')
  await expect(input.locator('pre')).toHaveText('0')
  expect(count).toBe(2)
})

test('E2E-576 @personal-payload older successful input copy cannot undo newer output denial', async ({ page, context }) => {
  test.skip(!output, 'Opt-in concurrent response ownership; synthetic API errors')
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  let calls = 0, release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await setup(page, ['race'], async (id, route) => {
    const current = ++calls
    if (current === 2) await gate
    if (current === 3) return route.fulfill({ status: 403, json: { detail: 'Synthetic concurrent revocation' } })
    return route.fulfill({ json: detail(id, { status: 'recorded', value: 'STALE_INPUT_MUST_NOT_COPY' }, { status: 'recorded', value: 'SYNTHETIC_OUTPUT' }) })
  })
  await page.evaluate(() => navigator.clipboard.writeText('SYNTHETIC_CLIPBOARD_BASELINE'))
  await open(page, 'race')
  await drawer(page).getByRole('region', { name: '输入', exact: true }).getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect.poll(() => calls).toBe(2)
  await drawer(page).getByRole('region', { name: '输出', exact: true }).getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect(drawer(page).getByRole('alert')).toContainText('Synthetic concurrent revocation')
  const returned = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/race') && response.status() === 200)
  release(); await (await returned).finished()
  await page.evaluate(async () => { await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))) })
  await expect(drawer(page).getByRole('alert')).toContainText('Synthetic concurrent revocation')
  await expect(drawer(page)).not.toContainText('STALE_INPUT_MUST_NOT_COPY')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('SYNTHETIC_CLIPBOARD_BASELINE')
})

test('E2E-577 @personal-payload administrator copy retains mounted success feedback', async ({ page, context }) => {
  test.skip(!output, 'Opt-in synthetic admin content UI; separate API authorization evidence')
  await login(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  const record = { ...audit('admin-copy'), user_id: 'synthetic-user', username: 'synthetic-user', auth_type: 'session', required_access: 'read', granted_access: 'read', payload: {}, reason: 'synthetic' }
  let requests = 0
  await page.route('**/v1/access/invocation-audits**', route => {
    if (new URL(route.request().url()).pathname === '/v1/access/invocation-audits') return route.fulfill({ json: { audits: [record], filter_options: { users: [], servers: [], tools: [] } } })
    requests++
    return route.fulfill({ json: detail('admin-copy', { status: 'recorded', value: { retained: 'SYNTHETIC_ADMIN_COPY' } }) })
  })
  await page.goto('/console/#/invocationAudit')
  await page.getByRole('button', { name: 'synthetic-tool-admin-copy', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '审计详情', exact: true })
  await dialog.getByRole('button', { name: '读取输入/输出', exact: true }).click()
  const input = dialog.getByRole('region', { name: '输入', exact: true })
  await input.getByRole('button', { name: '复制 JSON', exact: true }).click()
  await expect(input.getByRole('alert')).toContainText('已复制保留内容')
  expect(requests).toBe(2)
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(JSON.stringify({ retained: 'SYNTHETIC_ADMIN_COPY' }, null, 2))
})

import { test, expect, type Page, type Route } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

const output = process.env.GATE_RETENTION_EVIDENCE_DIR
const defaults = { runtime_logs_retention_days: 7, events_retention_days: 7, call_records_retention_days: 7, payload_mode: 'metadata_only' }
const cutoffs = { logs: '2026-01-01T00:00:00Z', events: '2026-01-01T00:00:00Z', invocation_audits: '2026-01-01T00:00:00Z' }
const counts = { logs: 3, events: 2, invocation_audits: 1 }
const preview = (policy: object, revision = 1) => ({ preview_id: 'synthetic-preview', revision, policy, cutoffs, counts, expires_at: '2099-01-01T00:00:00Z', shortened: ['logs'] })
const modal = (page: Page) => page.getByRole('dialog', { name: '记录与保留策略', exact: true })
type Call = { method: string; path: string; body: unknown }
async function setup(page: Page, handler: (route: Route, call: Call) => Promise<unknown>) {
  await login(page)
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  const calls: Call[] = []
  await page.route('**/v1/retention/**', async route => {
    const request = route.request(), call = { method: request.method(), path: new URL(request.url()).pathname, body: request.postData() ? request.postDataJSON() : null }
    calls.push(call); await handler(route, call)
  })
  await page.goto('/console/#/logs')
  await expect(page.getByRole('button', { name: '记录与保留策略', exact: true })).toBeVisible()
  expect(calls).toEqual([])
  await page.getByRole('button', { name: '记录与保留策略', exact: true }).click()
  await expect(modal(page).getByRole('spinbutton', { name: '运行日志保留天数', exact: true })).toBeVisible()
  return calls
}
const count = (calls: Call[], method: string, path: string) => calls.filter(call => call.method === method && call.path === path).length

test('E2E-580 @retention-ui phone defaults, disabled cleanup, shorten cancellation and save-only semantics', async ({ page }) => {
  test.skip(!output, 'Opt-in synthetic retention UI; no real cleanup')
  await page.setViewportSize({ width: 390, height: 844 })
  let snapshot = { ...defaults, revision: 1, worker_enabled: false }
  const calls = await setup(page, async (route, call) => {
    if (call.method === 'GET') return route.fulfill({ json: snapshot })
    if (call.path.endsWith('/preview')) return route.fulfill({ json: preview(call.body as object, snapshot.revision) })
    if (call.method === 'PUT') { snapshot = { ...snapshot, ...(call.body as object), revision: 2 }; return route.fulfill({ json: snapshot }) }
    return route.fulfill({ status: 500, json: { detail: 'Unexpected cleanup request' } })
  })
  const dialog = modal(page)
  for (const label of ['运行日志保留天数', '事件保留天数', '调用记录保留天数']) await expect(dialog.getByRole('spinbutton', { name: label, exact: true })).toHaveValue('7')
  await expect(dialog).toContainText('仅元数据（默认）')
  await expect(dialog.getByRole('button', { name: '立即清理', exact: true })).toBeDisabled()
  const save = dialog.getByRole('button', { name: '保存策略', exact: true })
  await expect(save).toBeDisabled()
  await dialog.getByRole('spinbutton', { name: '运行日志保留天数', exact: true }).fill('3')
  await expectInViewportAndUnobscured(save)
  await save.click()
  let confirmation = page.getByRole('alertdialog', { name: '确认缩短保留时间？', exact: true })
  await expect(confirmation).toContainText('7 → 3')
  await confirmation.getByRole('button', { name: '取消', exact: true }).click()
  await expect(save).toBeEnabled()
  expect(count(calls, 'PUT', '/v1/retention/policy')).toBe(0)
  expect(count(calls, 'POST', '/v1/retention/jobs')).toBe(0)
  await save.click()
  confirmation = page.getByRole('alertdialog', { name: '确认缩短保留时间？', exact: true })
  await confirmation.getByRole('button', { name: '确认', exact: true }).click()
  await expect(dialog).toContainText('策略已保存；未请求立即清理。')
  expect(count(calls, 'PUT', '/v1/retention/policy')).toBe(1)
  expect(count(calls, 'POST', '/v1/retention/jobs')).toBe(0)
  expect(calls.find(call => call.method === 'PUT')?.body).toMatchObject({ ...defaults, runtime_logs_retention_days: 3, expected_revision: 1, confirmed: true, preview_id: 'synthetic-preview' })
  await dialog.locator('#retention-policy-form').locator('..').locator('..').evaluate(el => { el.scrollTop = el.scrollHeight })
  const savedBounds = (await save.boundingBox())!
  expect(savedBounds.y).toBeGreaterThanOrEqual(0)
  expect(savedBounds.y + savedBounds.height).toBeLessThanOrEqual(844)
  await expectInViewportAndUnobscured(dialog.getByRole('button', { name: '取消', exact: true }))
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  mkdirSync(output!, { recursive: true })
  await page.screenshot({ path: join(output!, 'retention-save-only-390x844.png') })
  writeFileSync(join(output!, 'retention-save-only.json'), JSON.stringify({ calls, synthetic: true }, null, 2))
})

test('E2E-581 @retention-ui explicit cleanup confirmation, manual refresh and cancellation', async ({ page }) => {
  test.skip(!output, 'Opt-in synthetic jobs only; worker not enabled on real backend')
  const snapshot = { ...defaults, revision: 1, worker_enabled: true }
  const job = { id: 'synthetic-cleanup-job', state: 'queued', policy_revision: 1, cutoffs, counts, error_code: null }
  const calls = await setup(page, async (route, call) => {
    if (call.path.endsWith('/policy')) return route.fulfill({ json: snapshot })
    if (call.path.endsWith('/preview')) return route.fulfill({ json: preview(defaults) })
    if (call.path.endsWith('/cancel')) return route.fulfill({ json: { ...job, state: 'cancelled' } })
    return route.fulfill({ json: { ...job, state: call.method === 'GET' ? 'running' : 'queued' } })
  })
  const dialog = modal(page), cleanup = dialog.getByRole('button', { name: '立即清理', exact: true })
  await cleanup.click()
  await page.getByRole('alertdialog', { name: '确认立即清理到期记录？', exact: true }).getByRole('button', { name: '取消', exact: true }).click()
  expect(count(calls, 'POST', '/v1/retention/jobs')).toBe(0)
  await cleanup.click()
  await page.getByRole('alertdialog', { name: '确认立即清理到期记录？', exact: true }).getByRole('button', { name: '确认', exact: true }).click()
  await expect(dialog).toContainText('已提交清理任务；尚未确认清理完成。')
  await page.clock.install()
  await page.clock.fastForward(60_000)
  expect(count(calls, 'GET', '/v1/retention/jobs/synthetic-cleanup-job')).toBe(0)
  await dialog.getByRole('button', { name: '刷新任务状态', exact: true }).click()
  await expect(dialog).toContainText('synthetic-cleanup-job · running')
  expect(count(calls, 'GET', '/v1/retention/jobs/synthetic-cleanup-job')).toBe(1)
  await dialog.getByRole('button', { name: '取消清理任务', exact: true }).click()
  await page.getByRole('alertdialog', { name: '停止后续清理批次？', exact: true }).getByRole('button', { name: '确认', exact: true }).click()
  await expect(dialog).toContainText('清理任务已取消；已删除的批次无法恢复。')
  expect(count(calls, 'POST', '/v1/retention/jobs/synthetic-cleanup-job/cancel')).toBe(1)
  expect(count(calls, 'PUT', '/v1/retention/policy')).toBe(0)
})

for (const [width, height] of [[1280, 720], [1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) test(`E2E-582 @retention-ui conflict preserves draft and delayed stale preview cannot save ${width}x${height}`, async ({ page }) => {
  test.skip(!output, 'Opt-in mock CAS and stale preview recovery')
  mkdirSync(output!, { recursive: true })
  await page.setViewportSize({ width, height })
  let stale = false, release!: () => void
  const delayed = new Promise<void>(resolve => { release = resolve })
  const calls = await setup(page, async (route, call) => {
    if (call.method === 'GET') return route.fulfill({ json: { ...defaults, revision: 1, worker_enabled: false } })
    if (call.method === 'PUT') return route.fulfill({ status: 409, json: { detail: 'Synthetic revision conflict' } })
    if (stale) await delayed
    return route.fulfill({ json: preview(call.body as object, stale ? 2 : 1) })
  })
  const dialog = modal(page), save = dialog.getByRole('button', { name: '保存策略', exact: true })
  // Policy warnings and submission errors have different semantics; keep both
  // warnings visible and locate only FormDialog's persistent failure region.
  await expect(dialog.locator('.ant-alert[role="alert"]')).toHaveCount(2)
  await expect(dialog.locator('.ant-alert[role="alert"]').filter({ hasText: '敏感字段会脱敏' })).toBeVisible()
  await expect(dialog.locator('.ant-alert[role="alert"]').filter({ hasText: '清理工作进程未启用' })).toBeVisible()
  await dialog.getByRole('spinbutton', { name: '运行日志保留天数', exact: true }).fill('3')
  await expect(save).toBeEnabled()
  await expectInViewportAndUnobscured(save)
  await save.click()
  await page.getByRole('alertdialog', { name: '确认缩短保留时间？', exact: true }).getByRole('button', { name: '确认', exact: true }).click()
  const formError = dialog.locator('[data-slot="alert"][role="alert"]')
  await expect(formError).toBeVisible()
  await expect(formError).toContainText('Synthetic revision conflict')
  await expectInViewportAndUnobscured(formError)
  await page.screenshot({ path: join(output!, `retention-conflict-${width}x${height}.png`) })
  await expect(save).toBeDisabled()
  await dialog.getByRole('button', { name: '重新读取策略', exact: true }).click()
  await expect(dialog.getByRole('spinbutton', { name: '运行日志保留天数', exact: true })).toHaveValue('3')
  stale = true
  await save.click()
  await expect(save).toBeDisabled()
  await expect(dialog.getByRole('button', { name: '取消', exact: true })).toBeDisabled()
  await expect.poll(() => count(calls, 'POST', '/v1/retention/preview')).toBe(2)
  release()
  await expect(formError).toBeVisible()
  await expect(formError).toContainText('预览已过期或策略已改变')
  await expectInViewportAndUnobscured(formError)
  await expectInViewportAndUnobscured(dialog.getByRole('button', { name: '重新读取策略', exact: true }))
  await page.screenshot({ path: join(output!, `retention-stale-${width}x${height}.png`) })
  expect(count(calls, 'PUT', '/v1/retention/policy')).toBe(1)
  expect(count(calls, 'POST', '/v1/retention/jobs')).toBe(0)
})

test('E2E-583 @retention-ui no capability means no policy entry or requests', async ({ page }) => {
  test.skip(!output, 'UI boundary only; real API refusal is tested separately')
  await login(page, 'viewer')
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  const requests: string[] = []
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/v1/retention/')) requests.push(request.url()) })
  await page.goto('/console/#/logs')
  await expect(page.getByText('当前账号无权访问此页面', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '记录与保留策略', exact: true })).toHaveCount(0)
  expect(requests).toEqual([])
})

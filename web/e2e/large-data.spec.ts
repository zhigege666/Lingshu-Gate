import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers, tools, classifications, credentials, listFixtures } from './synthetic-data'

test.beforeEach(async ({ page }) => {
  await login(page)
  const fixtures: Record<string, unknown> = {
    ...listFixtures,
    '/v1/mcp/servers': { servers, load_errors: [] }, '/v1/tools': tools,
    '/v1/access/tool-classifications': { classifications }, '/v1/credentials': credentials,
  }
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'GET' && path in fixtures) await route.fulfill({ json: fixtures[path] })
    else await route.continue()
  })
  await page.setViewportSize({ width: 1280, height: 600 })
})

test('E2E-101 @large-data 5000 tools render one page and reset internal scroll', async ({ page }) => {
  await page.goto('/console/#/tools')
  const cards = page.locator('.tool-catalog-card')
  await expect(cards.first()).toBeVisible()
  expect(await cards.count()).toBeLessThanOrEqual(100)
  const next = page.getByRole('button', { name: 'Next page', exact: true })
  await expectInViewportAndUnobscured(next)
  await expectInViewportAndUnobscured(cards.first().getByRole('button').first())
  const viewport = page.locator('.tool-catalog-scroll')
  await viewport.evaluate(el => { el.scrollTop = el.scrollHeight })
  await next.click()
  await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBe(0)
  await expect(cards.first()).not.toContainText('Synthetic tool 0000')
})

test('E2E-102 @large-data 5000 classifications bound DOM and keep review action visible', async ({ page }, testInfo) => {
  await page.goto('/console/#/toolClassifications')
  const rows = page.locator('tbody tr')
  await expect(rows.first()).toContainText('Synthetic')
  expect(await rows.count()).toBeLessThanOrEqual(50)
  await expectInViewportAndUnobscured(rows.first().getByRole('button').last())
  await page.screenshot({ path: testInfo.outputPath('mock-classifications-short.png') })
  const writes: string[] = []
  page.on('request', request => { if (request.method() !== 'GET') writes.push(request.url()) })
  await page.getByRole('checkbox', { name: 'Select tools on this page', exact: true }).check()
  await expect(page.getByText('50 selected', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Next page', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: 'Select tools on this page', exact: true })).not.toBeChecked()
  await expect(page.getByText(/50 selected, including 50 outside this page/)).toBeVisible()
  await rows.first().getByRole('checkbox').check()
  await expect(page.getByText(/51 selected, including 50 outside this page/)).toBeVisible()
  await page.getByRole('button', { name: 'Clear selection', exact: true }).click()
  await expect(rows.first().getByRole('checkbox')).not.toBeChecked()
  expect(writes).toEqual([])
})

test('E2E-103 @large-data 200 credentials bound DOM', async ({ page }) => {
  await page.goto('/console/#/credentials')
  const rows = page.locator('tbody tr')
  await expect(rows.first()).toContainText('Synthetic credential')
  expect(await rows.count()).toBeLessThanOrEqual(50)
})

test('E2E-104 @large-data 100 services bound document height and show primary action', async ({ page }) => {
  await page.goto('/console/#/servers')
  await expect(page.getByText('Synthetic service 0', { exact: true }).first()).toBeVisible()
  const height = await page.evaluate(() => document.documentElement.scrollHeight)
  expect(height).toBeLessThanOrEqual(900)
  await expectInViewportAndUnobscured(page.locator('main button').filter({ hasText: /remote|create|add|connect/i }).first())
})

;['accessUsers', 'accessRoles', 'accessGrants', 'invocationAudit', 'personalTokens', 'downstreamCredentials', 'runtimeCache', 'logs'].forEach((view, index) => {
  test(`E2E-${110 + index} @large-data ${view} renders a bounded synthetic page`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(`/console/#/${view}`)
    const rows = page.locator('tbody tr:visible')
    await expect(rows.first()).toContainText(/synthetic/i)
    expect(await rows.count()).toBeLessThanOrEqual(50)
    expect(errors).toEqual([])
  })
})

test('E2E-118 @large-data events render a bounded page', async ({ page }) => {
  await page.goto('/console/#/logs')
  await page.getByRole('tab', { name: /Events/ }).click()
  const rows = page.locator('tbody tr:visible')
  await expect(rows.first()).toContainText('synthetic.event')
  expect(await rows.count()).toBeLessThanOrEqual(15)
})

test('E2E-119 @large-data build and deployment records render bounded pages', async ({ page }) => {
  await page.goto('/console/#/builds')
  await page.getByRole('tab', { name: /Build history/i }).click()
  const rows = page.locator('tbody tr:visible')
  await expect(rows.first()).toContainText('build-')
  expect(await rows.count()).toBeLessThanOrEqual(50)
  await page.getByRole('tab', { name: /Deployment history/i }).click()
  await expect(rows.first()).toContainText('synthetic-service')
  expect(await rows.count()).toBeLessThanOrEqual(50)
})

test('E2E-120 @large-data upload history renders 20 synthetic projects', async ({ page }) => {
  await page.goto('/console/#/uploads')
  await page.getByRole('button', { name: 'View upload history', exact: true }).click()
  const projects = page.getByRole('button', { name: /synthetic-project-\d+\.zip/ })
  await expect(projects.first()).toBeVisible()
  expect(await projects.count()).toBe(20)
})

test('E2E-121 @large-data advanced configs render 50 of 100 manifests', async ({ page }) => {
  await page.route('**/v1/mcp/configs', route => route.fulfill({ json: { errors: [], configs: Array.from({ length: 100 }, (_, i) => ({ id: `synthetic-config-${i}`, path: `/synthetic/config-${i}.json`, format: 'json', manifest: { id: `synthetic-config-${i}`, name: `Synthetic config ${i}`, enabled: false, launch: { type: 'remote' }, transport: { type: 'streamable_http', url: 'http://127.0.0.1:1/mcp' } } })) } }))
  await page.goto('/console/#/configs')
  const rows = page.locator('tbody tr:visible')
  await expect(rows.first()).toContainText('synthetic-config')
  expect(await rows.count()).toBeLessThanOrEqual(50)
})


test('E2E-122 @large-data 200 disabled personal scope drafts render one page', async ({ page }) => {
  await page.goto('/console/#/myConnections')
  const rows = page.locator('tbody tr:visible')
  await expect(rows.first()).toContainText('synthetic-client')
  expect(await rows.count()).toBeLessThanOrEqual(50)
  await expectInViewportAndUnobscured(page.getByRole('button', { name: 'New personal grant', exact: true }))
})

test('E2E-123 @large-data 30 permission types remain bounded', async ({ page }) => {
  await page.goto('/console/#/accessRoles')
  await page.getByRole('tab', { name: /Permission types/ }).click()
  const rows = page.locator('tbody tr:visible')
  await expect(rows.first()).toContainText('Synthetic type')
  await expect(rows).toHaveCount(30)
})

test('E2E-124 @large-data dashboard displays the 100-service authorized fixture', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/console/#/dashboard')
  await expect(page.locator('main')).toContainText('100')
  expect(errors).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280)
})

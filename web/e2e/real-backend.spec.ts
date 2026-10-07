import { test, expect } from '@playwright/test'
import { expectInViewportAndUnobscured, initialize, login } from './helpers'

test('E2E-001 @smoke real login on short screen using keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 600 })
  await initialize(page)
  await page.goto('/console/')
  await page.getByLabel('Username', { exact: true }).fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('Synthetic-admin-123!')
  const submit = page.getByRole('button', { name: 'Sign in', exact: true })
  await expectInViewportAndUnobscured(submit)
  await submit.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Username', { exact: true })).toHaveCount(0)
  expect((await page.request.get('/v1/auth/me')).status()).toBe(200)
  await expect(page.locator('main')).toBeVisible()
})

test('E2E-002 @smoke @permissions viewer is denied real control-plane APIs', async ({ page }) => {
  await login(page, 'viewer')
  for (const path of ['/v1/mcp/servers', '/v1/mcp/configs', '/v1/credentials', '/v1/builds', '/v1/projects/uploads']) {
    const response = await page.request.get(path)
    expect(response.status(), path).toBe(403)
  }
  expect((await page.request.get('/v1/auth/tokens')).status()).toBe(200)
  await page.goto('/console/#/dashboard')
  await expect(page.locator('main')).toBeVisible()
})

test('E2E-003 @full failed login preserves recovery and a later valid submission works', async ({ page }) => {
  await initialize(page)
  await page.goto('/console/')
  await page.getByLabel('Username', { exact: true }).fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('synthetic-invalid')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByLabel('Password', { exact: true }).fill('Synthetic-admin-123!')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('main')).toBeVisible()
})

test('E2E-004 @permissions personal routes use authorized summaries and self records', async ({ page }) => {
  await login(page, 'viewer')
  const managedRequests: string[] = []
  page.on('request', request => {
    if (/\/v1\/mcp\/(servers|configs)/.test(new URL(request.url()).pathname)) managedRequests.push(request.url())
  })
  for (const [view, endpoint] of [['myServers', '/v1/me/mcp-servers'], ['myInvocations', '/v1/me/invocations']]) {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === endpoint)
    await page.goto(`/console/#/${view}`)
    expect((await response).status()).toBe(200)
    await expect(page.locator('main')).toBeVisible()
  }
  await page.goto('/console/#/myConnections')
  await page.getByRole('tab', { name: 'External identity provider', exact: true }).click()
  await expectInViewportAndUnobscured(page.getByRole('button', { name: 'New personal grant', exact: true }))
  await expect(page.getByText('Gate OAuth token verification and personal grants')).toBeVisible()
  expect(managedRequests).toEqual([])
})

test('E2E-005 @smoke narrow-screen login action is visible and keyboard usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await initialize(page)
  await page.goto('/console/')
  await page.getByLabel('Username', { exact: true }).fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('Synthetic-admin-123!')
  const action = page.getByRole('button', { name: 'Sign in', exact: true })
  await expectInViewportAndUnobscured(action)
  await action.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('main')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('E2E-006 @permissions real disabled scope draft save, ownership deny and revoke', async ({ page, playwright }) => {
  await login(page, 'viewer')
  await page.setViewportSize({ width: 1280, height: 600 })
  await page.goto('/console/#/myConnections')
  await page.getByRole('tab', { name: 'External identity provider', exact: true }).click()
  const create = page.getByRole('button', { name: 'New personal grant', exact: true })
  await expectInViewportAndUnobscured(create)
  await create.click()
  const dialog = page.getByRole('dialog', { name: 'Personal grant scope', exact: true })
  await expect(dialog.getByText(/Call quotas are counted in one Core process's memory and reset on restart; multiple processes or instances do not share quotas/)).toBeVisible()
  await expect(dialog.getByRole('switch', { name: 'Enable my grant', exact: true })).not.toBeChecked()
  await expect(dialog.getByRole('switch', { name: 'Enable my grant', exact: true })).toBeDisabled()
  await dialog.getByLabel('Client ID', { exact: true }).fill('synthetic-browser-client')
  const expiry = new Date(Date.now() + 86400_000).toISOString().slice(0, 16)
  await dialog.getByLabel('Expiry (UTC)', { exact: true }).fill(expiry)
  await dialog.getByRole('checkbox', { name: 'mcp.synthetic.read', exact: true }).check()
  const save = dialog.getByRole('button', { name: 'Save personal grant', exact: true })
  await expectInViewportAndUnobscured(save)
  const created = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/v1/auth/external-grants')
  await save.click()
  const response = await created
  expect(response.status()).toBe(201)
  const grant = await response.json()
  expect(grant).toMatchObject({ enabled: false, connected: false, oauth_authorized: false, state: 'disabled', limits_enforced: false })
  await expect(dialog).toHaveCount(0)
  const other = await playwright.request.newContext({ baseURL: 'http://127.0.0.1:18763' })
  try {
    expect((await other.post('/v1/auth/login', { data: { username: 'admin', password: 'Synthetic-admin-123!' } })).status()).toBe(200)
    expect((await other.get(`/v1/auth/external-grants/${grant.id}`)).status()).toBe(404)
    expect((await other.delete(`/v1/auth/external-grants/${grant.id}`)).status()).toBe(404)
  } finally { await other.dispose() }
  const row = page.getByRole('row').filter({ hasText: 'synthetic-browser-client' })
  let deleteRequests = 0
  page.on('request', request => { if (request.method() === 'DELETE') deleteRequests++ })
  await row.getByRole('button', { name: 'Revoke', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  expect(deleteRequests).toBe(0)
  await row.getByRole('button', { name: 'Revoke', exact: true }).click()
  const revoked = page.waitForResponse(r => r.request().method() === 'DELETE' && new URL(r.url()).pathname.endsWith(grant.id))
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  expect((await revoked).status()).toBe(200)
  await expect(row).toContainText('revoked')
  expect((await page.request.get(`/v1/auth/external-grants/${grant.id}`)).status()).toBe(200)
})

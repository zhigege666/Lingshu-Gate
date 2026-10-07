import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { login } from './helpers'

test('E2E-008 @delivery real failed build can be retried successfully', async ({ page }) => {
  test.setTimeout(60_000)
  const archive = join(process.env.GATE_E2E_TEMP_ROOT!, 'synthetic-build-recovery.zip')
  execFileSync('../.venv/bin/python', ['../scripts/e2e/make_failure_bundle.py', archive], { timeout: 10_000 })
  await login(page)
  await page.goto('/console/#/uploads')
  await page.locator('input[type=file]').setInputFiles(archive)
  const uploaded = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/v1/projects/upload')
  await page.getByRole('button', { name: 'Upload & Analyze', exact: true }).click()
  const uploadResponse = await uploaded
  expect(uploadResponse.status()).toBe(200)
  await page.getByText('Advanced build options', { exact: true }).click()
  await page.getByRole('checkbox', { name: 'Install dependencies using detected settings', exact: true }).uncheck()
  const created = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/v1/builds')
  await page.getByRole('button', { name: 'Create Build', exact: true }).last().click()
  const build = await (await created).json()
  await expect.poll(async () => (await (await page.request.get(`/v1/builds/${build.id}`)).json()).status, { timeout: 20_000 }).toBe('failed')
  await page.reload()
  await page.getByRole('tab', { name: /Build history/ }).click()
  const row = page.getByRole('row').filter({ has: page.locator(`code[title="${build.id}"]`) })
  await expect(row).toContainText(/failed/i)
  const retried = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/v1/builds')
  await row.getByRole('button', { name: 'Rebuild', exact: true }).click()
  const response = await retried
  expect(response.status()).toBe(200)
  const retry = await response.json()
  expect(retry.id).not.toBe(build.id)
  expect(retry.upload_id).toBe(build.upload_id)
  await expect.poll(async () => (await (await page.request.get(`/v1/builds/${retry.id}`)).json()).status, { timeout: 20_000 }).toBe('success')
  expect((await (await page.request.get(`/v1/builds/${build.id}`)).json()).status).toBe('failed')
})

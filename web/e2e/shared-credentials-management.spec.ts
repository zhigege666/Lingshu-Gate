import { test, expect, type Page } from '@playwright/test'
import { login } from './helpers'

const credential = { id: 'synthetic-shared-token', name: 'Synthetic shared token', description: 'Existing description', value_masked: '***',
  created_at: '2026-10-23T08:00:00+00:00', updated_at: '2026-10-23T08:00:00+00:00',
  http_scopes: [{ server_id: 'synthetic-http', origin: 'https://service.example:443', server_binding: 'synthetic-generation' }] }

async function openCredential(page: Page) {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.route('**/v1/credentials', route => route.fulfill({ json: [credential] }))
  await page.goto('/console/#/credentials')
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  return page.getByRole('dialog', { name: 'Edit Credential', exact: true })
}

test('shared credential metadata update keeps the secret with null and retains the checked version across a conflict', async ({ page }) => {
  const writes: Record<string, unknown>[] = []
  const editor = await openCredential(page)
  await page.route('**/v1/credentials/synthetic-shared-token', route => {
    writes.push(route.request().postDataJSON())
    return route.fulfill({ status: 409, json: { detail: 'Synthetic credential revision changed; reload before updating.' } })
  })
  await editor.getByLabel('Description', { exact: true }).fill('Synthetic edited metadata')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(editor.getByRole('alert')).toContainText('Synthetic credential revision changed')
  await expect(editor.getByLabel('Description', { exact: true })).toHaveValue('Synthetic edited metadata')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[0]).toMatchObject({ value: null, expected_revision: credential.updated_at, description: 'Synthetic edited metadata' })
  expect(writes[0]).not.toHaveProperty('http_scopes')
  expect(writes[0].idempotency_key).toMatch(/^credential-[a-f0-9]{48}$/)
  expect(writes[1]).toEqual(writes[0])
})

test('shared credential secret replacement keeps only this attempted input and changes its key only after an edit', async ({ page }) => {
  const writes: Record<string, unknown>[] = []
  const editor = await openCredential(page)
  await page.route('**/v1/credentials/synthetic-shared-token', route => {
    writes.push(route.request().postDataJSON())
    return route.fulfill({ status: 503, json: { detail: 'Synthetic credential service unavailable' } })
  })
  await editor.getByRole('radio', { name: 'Replace secret', exact: true }).check()
  const secret = editor.locator('#credential-value')
  await expect(secret).toHaveValue('')
  await secret.fill('Synthetic-first-secret-123!')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(editor.getByRole('alert')).toHaveText('Synthetic credential service unavailable')
  await expect(secret).toHaveValue('Synthetic-first-secret-123!')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1]).toEqual(writes[0])
  await secret.fill('Synthetic-second-secret-456!')
  await editor.getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(3)
  expect(writes[2].idempotency_key).not.toBe(writes[0].idempotency_key)
  expect(writes[2]).toMatchObject({ expected_revision: credential.updated_at, value: 'Synthetic-second-secret-456!' })
})

test('shared credential delete uses the displayed revision and keeps in-use failure visible', async ({ page }) => {
  const requests: URL[] = []
  const editor = await openCredential(page)
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.route('**/v1/credentials/synthetic-shared-token?*', route => {
    requests.push(new URL(route.request().url()))
    return route.fulfill({ status: 409, json: { detail: 'Credential is referenced by a configuration. Remove the reference first.' } })
  })
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Credential is referenced by a configuration' })).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0].searchParams.get('expected_revision')).toBe(credential.updated_at)
  expect(requests[0].searchParams.get('idempotency_key')).toMatch(/^credential-[a-f0-9]{48}$/)
  await expect(page.getByRole('button', { name: credential.id, exact: true })).toBeVisible()
})

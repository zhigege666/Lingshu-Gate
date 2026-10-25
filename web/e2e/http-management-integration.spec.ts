import { expect, test } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'

// Real local REST contracts and built UI. The isolated fixture owns all data;
// save-only never applies or starts this synthetic private HTTP service.
test('HTTP management saves a scoped credential and permission together, preserves revocation, and restores explicitly @full', async ({ page }, testInfo) => {
  await login(page)
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-theme', 'light'))
  await page.setViewportSize({ width: 1600, height: 900 })
  const serverId = 'synthetic-http-management-integration'
  const credentialId = 'synthetic-http-management-token'
  const secret = 'Synthetic-integration-secret-123!'
  const manifest = { id: serverId, name: 'Synthetic HTTP management integration', enabled: true, auto_start: false, startup_policy: 'gate_start_v1',
    launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'http://10.23.45.67:8080/mcp' }, timeout_seconds: 30 }
  const writes: { path: string; body: Record<string, unknown> }[] = []
  page.on('request', request => {
    if (['POST', 'PUT', 'DELETE'].includes(request.method()) && new URL(request.url()).pathname.startsWith('/v1/mcp/')) {
      writes.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() || {} })
    }
  })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'New Config', exact: true }).click()
  let editor = page.getByRole('dialog', { name: 'New MCP config', exact: true })
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  await editor.getByLabel('Manifest JSON', { exact: true }).fill(JSON.stringify(manifest, null, 2))
  await editor.getByRole('button', { name: 'Form', exact: true }).click()
  await expect(editor.getByText('Saving this configuration establishes permission for this service and exact address.', { exact: true })).toBeVisible()
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
  const inline = editor.getByRole('region', { name: 'New service credential', exact: true })
  await inline.getByText('Credential ID (generated, editable)', { exact: true }).click()
  await inline.getByLabel('Credential ID', { exact: true }).fill(credentialId)
  await inline.getByLabel('Credential name', { exact: true }).fill('Synthetic scoped credential')
  await inline.getByRole('button', { name: 'Save and use credential', exact: true }).scrollIntoViewIfNeeded()
  await expectInViewportAndUnobscured(inline.getByLabel('Credential ID', { exact: true }))
  await page.screenshot({ path: testInfo.outputPath('http-credential-inline-real.png'), animations: 'disabled' })
  await inline.getByLabel('Token', { exact: true }).fill(secret)
  await inline.getByRole('button', { name: 'Save and use credential', exact: true }).click()
  await expect(inline).toHaveCount(0)
  await expect(editor.getByText('The authentication header is set automatically; no Add step is needed. The secret stays outside the configuration.', { exact: true })).toBeVisible()
  const save = editor.getByRole('button', { name: 'Save Config', exact: true })
  await expectInViewportAndUnobscured(save)
  await save.click()
  await expect(editor).toHaveCount(0)

  const readTrust = async () => {
    const response = await page.request.get(`/v1/mcp/http-trust/${serverId}`)
    expect(response.ok()).toBe(true)
    return response.json()
  }
  const firstTrust = await readTrust()
  expect(firstTrust).toMatchObject({ state: 'active', origins: [{ ip: '10.23.45.67', port: 8080 }] })
  const credentialResponse = await page.request.get(`/v1/credentials/${credentialId}`)
  expect(credentialResponse.ok()).toBe(true)
  const credential = await credentialResponse.json()
  expect(credential).toMatchObject({ value_masked: '***', http_scopes: [{ server_id: serverId, origin: 'http://10.23.45.67:8080', server_binding: firstTrust.server_binding }] })
  expect(JSON.stringify(credential)).not.toContain(secret)
  expect(writes.filter(write => write.path.includes('/http-trust/'))).toHaveLength(0)
  expect(writes.find(write => write.path === '/v1/mcp/configs')?.body).toMatchObject({ apply: false, start: false, http_trust_action: 'auto', expected_http_trust_revision: 0,
    manifest: { transport: { headers: { Authorization: 'Bearer ${credential:' + credentialId + '}' } } } })

  const reopen = async () => {
    await page.getByRole('row').filter({ hasText: serverId }).getByRole('button', { name: 'Edit', exact: true }).click()
    editor = page.getByRole('dialog', { name: `Edit · ${serverId}`, exact: true })
    await editor.getByText('Connection permission details', { exact: true }).click()
  }
  await reopen()
  await editor.getByRole('button', { name: 'Revoke connection permission', exact: true }).click()
  await editor.getByRole('button', { name: 'Confirm revocation', exact: true }).click()
  await expect(editor.getByText('Connection permission was revoked. A normal save will not restore it.', { exact: true })).toBeVisible()
  await expect(editor.getByRole('radio', { name: 'Bearer Token', exact: true })).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath('http-permission-revoked-real.png'), animations: 'disabled' })
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic metadata after revocation')
  await editor.getByRole('button', { name: 'Save Config', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(await readTrust()).toMatchObject({ state: 'revoked', origins: [], revoked: true })

  await reopen()
  await editor.getByRole('button', { name: 'Restore this address permission on save', exact: true }).click()
  await editor.getByRole('button', { name: 'Save Config', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(await readTrust()).toMatchObject({ state: 'active', revoked: false, origins: [{ ip: '10.23.45.67', port: 8080 }] })
  expect(writes.filter(write => write.path.includes('/http-trust/'))).toHaveLength(1)
  expect(writes.filter(write => write.path === `/v1/mcp/configs/${serverId}`).map(write => write.body.http_trust_action)).toEqual(['auto', 'restore'])
  await page.goto('/console/#/credentials')
  await page.getByRole('row').filter({ hasText: credentialId }).getByRole('button', { name: 'Edit', exact: true }).click()
  const credentialEditor = page.getByRole('dialog', { name: 'Edit Credential', exact: true })
  await expect(credentialEditor.getByRole('radio', { name: /Keep current secret$/ })).toBeChecked()
  await expectInViewportAndUnobscured(credentialEditor.getByRole('button', { name: 'Save', exact: true }))
  expect(await credentialEditor.locator('.gate-form-row').evaluateAll(rows => rows.every(row => {
    const label = row.querySelector('.gate-form-label')!, control = row.querySelector('.gate-form-control')!
    const a = label.getBoundingClientRect(), b = control.getBoundingClientRect()
    return b.left >= a.right && b.top < a.bottom && b.bottom > a.top && getComputedStyle(label).whiteSpace === 'nowrap'
  }))).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('http-credential-edit-real.png'), animations: 'disabled' })
})

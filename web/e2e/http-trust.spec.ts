import { test, expect, type Page } from '@playwright/test'
import { login } from './helpers'
import { servers } from './synthetic-data'

const server = { ...servers[0], launch_type: 'external', status: 'running', enabled: true }
const manifest = { id: server.id, name: server.name, enabled: true, launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'http://10.23.45.67:8080/mcp' }, timeout_seconds: 30 }
async function openHttpEditor(page: Page) {
  await login(page)
  await page.route('**/v1/mcp/servers', route => route.fulfill({ json: { servers: [server], load_errors: [] } }))
  await page.route('**/v1/mcp/servers/*/detail?*', route => route.fulfill({ json: { server, manifest, tools: [] } }))
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] } }))
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/console/#/servers')
  await page.getByRole('tab', { name: 'Configuration', exact: true }).click()
  await page.getByRole('button', { name: 'Edit configuration', exact: true }).click()
  return page.getByRole('dialog', { name: `Edit configuration · ${server.id}`, exact: true })
}

test('E2E-210 @full private HTTP trust confirms the exact draft target, invalidates edits and never saves configuration', async ({ page }, testInfo) => {
  let policy = { server_id: server.id, revision: 0, origins: [] as Array<{ ip: string; port: number }> }
  let trustWrites = 0, configWrites = 0, validations = 0
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/mcp/http-trust/*', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: policy })
    trustWrites++
    const body = route.request().postDataJSON()
    expect(body.expected_revision).toBe(0)
    expect(body.confirmed).toBe(true)
    expect(body.origins).toEqual([{ ip: '10.23.45.68', port: 8080 }])
    await gate
    policy = { ...policy, revision: 1, origins: body.origins }
    await route.fulfill({ json: policy })
  })
  const editor = await openHttpEditor(page)
  await page.route('**/v1/mcp/configs/*', route => {
    if (route.request().method() === 'PUT') { configWrites++; return route.fulfill({ status: 500, json: { detail: 'Unexpected configuration write' } }) }
    return route.fallback()
  })
  await page.route('**/v1/mcp/configs/*/validate', route => {
    validations++
    expect(route.request().postDataJSON().manifest.name).toBe('Synthetic unsaved name')
    return route.fulfill({ json: { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [{ name: 'transport.http_trust', severity: 'ok', message: 'Synthetic exact origin approved', metadata: { authorized: true } }] } })
  })
  const endpoint = editor.getByLabel('MCP Endpoint', { exact: true })
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic unsaved name')
  await editor.getByRole('button', { name: 'Authorize this address', exact: true }).click()
  await expect(editor.getByRole('group', { name: 'Confirm internal address authorization' })).toContainText('10.23.45.67')
  await endpoint.fill('http://10.23.45.68:8080/mcp')
  await expect(editor.getByRole('group', { name: 'Confirm internal address authorization' })).toHaveCount(0)
  expect(trustWrites).toBe(0)
  await editor.getByRole('button', { name: 'Authorize this address', exact: true }).click()
  const confirmation = editor.getByRole('group', { name: 'Confirm internal address authorization' })
  await expect(confirmation).toContainText(server.id)
  await expect(confirmation).toContainText('10.23.45.68')
  await expect(confirmation).toContainText('8080')
  await expect(page.getByRole('dialog')).toHaveCount(1)
  await page.screenshot({ path: testInfo.outputPath('private-http-trust-confirmation.png') })
  await confirmation.getByRole('button', { name: 'Confirm address authorization', exact: true }).click()
  await expect.poll(() => trustWrites).toBe(1)
  await expect(endpoint).toBeDisabled()
  await expect(editor.getByRole('button', { name: 'Save and reconnect', exact: true })).toBeDisabled()
  await page.keyboard.press('Enter')
  expect(trustWrites).toBe(1)
  release!()
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toBeVisible()
  await expect(editor.getByText('Backend Precheck: Can save', { exact: true })).toBeVisible()
  await expect(editor.getByLabel('Name', { exact: true })).toHaveValue('Synthetic unsaved name')
  expect(validations).toBe(1)
  expect(configWrites).toBe(0)
})

test('E2E-211 @full HTTP trust failure remains visible and retries only after a fresh read', async ({ page }) => {
  let writes = 0, reads = 0
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() === 'GET') { reads++; return route.fulfill({ json: { server_id: server.id, revision: 0, origins: [] } }) }
    writes++
    return route.fulfill({ status: 409, json: { detail: 'Synthetic concurrent HTTP trust update' } })
  })
  const editor = await openHttpEditor(page)
  await editor.getByRole('button', { name: 'Authorize this address', exact: true }).click()
  await editor.getByRole('button', { name: 'Confirm address authorization', exact: true }).click()
  await expect(editor.getByRole('alert').filter({ hasText: 'Synthetic concurrent HTTP trust update' })).toBeVisible()
  await expect(editor.getByLabel('MCP Endpoint', { exact: true })).toHaveValue(manifest.transport.endpoint)
  await expect(editor.getByRole('button', { name: 'Authorize this address', exact: true })).toBeDisabled()
  expect(writes).toBe(1)
  await editor.getByRole('button', { name: 'Reload authorization state', exact: true }).click()
  await expect(editor.getByRole('button', { name: 'Authorize this address', exact: true })).toBeEnabled()
  expect(reads).toBe(3)
  expect(writes).toBe(1)
})

test('E2E-212 @full ordinary operator receives guidance without reading trust records', async ({ page }, testInfo) => {
  let reads = 0
  await page.route('**/v1/auth/me', async route => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, role: 'operator', roles: ['operator'] } })
  })
  await page.route('**/v1/mcp/http-trust/*', route => { reads++; return route.fulfill({ status: 403, json: { detail: 'Unexpected policy read' } }) })
  const editor = await openHttpEditor(page)
  await expect(editor.getByText('Contact a Gate administrator to authorize this address.', { exact: true })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Authorize this address', exact: true })).toHaveCount(0)
  expect(reads).toBe(0)
  await page.screenshot({ path: testInfo.outputPath('private-http-operator-guidance.png') })
})


test('E2E-213 @full changing the draft service ID invalidates HTTP trust confirmation without a write', async ({ page }) => {
  let writes = 0
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { server_id: server.id, revision: 0, origins: [] } })
    writes++
    return route.fulfill({ status: 500, json: { detail: 'Unexpected trust write' } })
  })
  const editor = await openHttpEditor(page)
  await editor.getByRole('button', { name: 'Authorize this address', exact: true }).click()
  await expect(editor.getByRole('group', { name: 'Confirm internal address authorization' })).toContainText(server.id)
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const json = editor.getByLabel('Manifest JSON', { exact: true })
  await json.fill(JSON.stringify({ ...manifest, id: 'synthetic-changed-service' }, null, 2))
  await editor.getByRole('button', { name: 'Form', exact: true }).click()
  await expect(editor.getByRole('group', { name: 'Confirm internal address authorization' })).toHaveCount(0)
  await editor.getByRole('button', { name: 'Authorize this address', exact: true }).click()
  const confirmation = editor.getByRole('group', { name: 'Confirm internal address authorization' })
  await expect(confirmation).toContainText('synthetic-changed-service')
  await expect(confirmation).toContainText('10.23.45.67')
  expect(writes).toBe(0)
})


test('E2E-214 @full current denial overrides cached authorization and reloads each new revision before confirmation', async ({ page }) => {
  let policy = { server_id: server.id, revision: 1, origins: [{ ip: '10.23.45.67', port: 8080 }] as Array<{ ip: string; port: number }> }
  let reads = 0, writes = 0
  let releaseRead: (() => void) | undefined
  const delayedRead = new Promise<void>(resolve => { releaseRead = resolve })
  await page.route('**/v1/mcp/http-trust/*', async route => {
    if (route.request().method() === 'GET') {
      reads++
      if (reads === 2) await delayedRead
      return route.fulfill({ json: policy })
    }
    writes++
    const body = route.request().postDataJSON()
    expect(body.expected_revision).toBe(3)
    expect(body.confirmed).toBe(true)
    expect(body.origins).toEqual([{ ip: '10.23.45.67', port: 8080 }])
    policy = { ...policy, revision: 4, origins: body.origins }
    return route.fulfill({ json: policy })
  })
  const editor = await openHttpEditor(page)
  await page.route('**/v1/mcp/configs/*/validate', route => {
    const authorized = policy.origins.length > 0
    return route.fulfill({ json: { ok: authorized, can_apply: authorized, manifest_id: server.id,
      summary: { errors: authorized ? 0 : 1, warnings: 0, info: 0, ok: authorized ? 1 : 0 },
      checks: authorized ? [{ name: 'transport.http_trust', severity: 'ok', message: 'Synthetic current trust', metadata: { authorized: true } }]
        : [{ name: 'transport.endpoint', severity: 'error', message: 'Synthetic revoked trust', metadata: { code: 'private_http_untrusted' } }] } })
  })
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toBeVisible()
  await editor.getByRole('button', { name: 'Backend Precheck', exact: true }).click()
  await expect(editor.getByText('Backend Precheck: Can save', { exact: true })).toBeVisible()
  policy = { ...policy, revision: 2, origins: [] }
  await editor.getByRole('button', { name: 'Backend Precheck', exact: true }).click()
  await expect.poll(() => reads).toBe(2)
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toHaveCount(0)
  const authorize = editor.getByRole('button', { name: 'Authorize this address', exact: true })
  await expect(authorize).toBeDisabled()
  expect(writes).toBe(0)
  releaseRead!()
  await expect(authorize).toBeEnabled()
  await expect(editor.getByText('This internal address is not authorized.', { exact: true })).toBeVisible()
  await authorize.click()
  await expect(editor.getByRole('group', { name: 'Confirm internal address authorization' })).toBeVisible()
  policy = { ...policy, revision: 3 }
  await editor.getByRole('button', { name: 'Backend Precheck', exact: true }).click()
  await expect.poll(() => reads).toBe(3)
  await expect(editor.getByRole('group', { name: 'Confirm internal address authorization' })).toHaveCount(0)
  await authorize.click()
  await editor.getByRole('button', { name: 'Confirm address authorization', exact: true }).click()
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toBeVisible()
  expect(writes).toBe(1)
})

test('E2E-215 @full revoked cached trust with a failed refresh remains denied until explicit read retry', async ({ page }) => {
  let reads = 0, writes = 0
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() !== 'GET') { writes++; return route.fulfill({ status: 500, json: { detail: 'Unexpected write' } }) }
    reads++
    if (reads === 2) return route.fulfill({ status: 503, json: { detail: 'Synthetic unavailable current trust' } })
    return route.fulfill({ json: { server_id: server.id, revision: reads === 1 ? 1 : 2, origins: reads === 1 ? [{ ip: '10.23.45.67', port: 8080 }] : [] } })
  })
  const editor = await openHttpEditor(page)
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toBeVisible()
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: false, can_apply: false, manifest_id: server.id,
    summary: { errors: 1, warnings: 0, info: 0, ok: 0 }, checks: [{ name: 'transport.endpoint', severity: 'error', message: 'Synthetic revoked trust', metadata: { code: 'private_http_untrusted' } }] } }))
  await editor.getByRole('button', { name: 'Backend Precheck', exact: true }).click()
  await expect(editor.getByRole('alert').filter({ hasText: 'Synthetic unavailable current trust' })).toBeVisible()
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toHaveCount(0)
  await expect(editor.getByRole('button', { name: 'Authorize this address', exact: true })).toBeDisabled()
  expect(reads).toBe(2)
  expect(writes).toBe(0)
  await editor.getByRole('button', { name: 'Reload authorization state', exact: true }).click()
  await expect(editor.getByRole('button', { name: 'Authorize this address', exact: true })).toBeEnabled()
  await expect(editor.getByText('This internal address is not authorized.', { exact: true })).toBeVisible()
  expect(reads).toBe(3)
  expect(writes).toBe(0)
})

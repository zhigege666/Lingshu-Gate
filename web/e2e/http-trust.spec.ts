import { test, expect, type Page } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers } from './synthetic-data'

// Built Console renderer; synthetic data exercises request ownership without contacting a private peer.
const server = { ...servers[0], launch_type: 'external', status: 'running', enabled: true }
const manifest = { id: server.id, name: server.name, enabled: true, launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'http://10.23.45.67:8080/mcp' }, timeout_seconds: 30 }
const origin = { ip: '10.23.45.67', port: 8080 }
const policy = (state: 'unconfigured' | 'active' | 'revoked', revision = 0) => ({ server_id: server.id, revision, state,
  origins: state === 'active' ? [origin] : [], server_binding: state === 'unconfigured' ? null : 'synthetic-binding', revoked: state === 'revoked', needs_review: false })
const validation = { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 1, info: 0, ok: 0 }, checks: [
  { name: 'transport.http_trust', severity: 'warning', message: 'The exact private target will be permitted when saved.', metadata: { code: 'private_http_pending' } },
] }

async function openHttpEditor(page: Page, viewport = { width: 1600, height: 900 }, locale = 'en-US', draftManifest: Record<string, unknown> = manifest) {
  await login(page)
  await page.addInitScript(locale => { localStorage.setItem('lingshu-gate-console-locale', locale); localStorage.setItem('lingshu-gate-console-theme', 'light') }, locale)
  await page.route('**/v1/mcp/servers', route => route.fulfill({ json: { servers: [server], load_errors: [] } }))
  await page.route('**/v1/mcp/servers/*/detail?*', route => route.fulfill({ json: { server, manifest: draftManifest, config_digest: 'c'.repeat(64), tools: [] } }))
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: validation }))
  await page.setViewportSize(viewport)
  await page.goto('/console/#/servers')
  await page.getByRole('tab', { name: locale === 'zh-CN' ? '配置' : 'Configuration', exact: true }).click()
  await page.getByRole('button', { name: locale === 'zh-CN' ? '修改配置' : 'Edit configuration', exact: true }).click()
  return page.getByRole('dialog', { name: `${locale === 'zh-CN' ? '修改配置' : 'Edit configuration'} · ${server.id}`, exact: true })
}

async function confirmSaveOnly(page: Page) {
  await page.getByRole('alertdialog').getByRole('button', { name: 'Save only (not applied)', exact: true }).click()
}

test('E2E-210 @full a private target saves once with its revision and no separate authorization write', async ({ page }) => {
  let trustWrites = 0
  const configWrites: Record<string, unknown>[] = []
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() !== 'GET') trustWrites++
    return route.fulfill({ json: policy('unconfigured') })
  })
  const editor = await openHttpEditor(page)
  await page.route('**/v1/mcp/configs/*', route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const body = route.request().postDataJSON(); configWrites.push(body)
    return route.fulfill({ json: { config: { id: server.id, manifest: body.manifest }, server: null, message: 'updated' } })
  })
  await expect(editor.getByText('Saving this configuration establishes permission for this service and exact address.', { exact: true })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Authorize this address', exact: true })).toHaveCount(0)
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic retained draft')
  await editor.getByRole('button', { name: 'Save configuration', exact: true }).click()
  await confirmSaveOnly(page)
  await expect(editor).toHaveCount(0)
  expect(trustWrites).toBe(0)
  expect(configWrites).toEqual([expect.objectContaining({ apply: false, start: false, http_trust_action: 'auto', expected_http_trust_revision: 0,
    expected_config_digest: 'c'.repeat(64), manifest: expect.objectContaining({ name: 'Synthetic retained draft' }) })])
})

test('E2E-211 @full an unreadable permission blocks saving and retry only reads policy', async ({ page }) => {
  let reads = 0, writes = 0
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() !== 'GET') { writes++; return route.fulfill({ status: 500, json: { detail: 'Unexpected write' } }) }
    reads++
    return reads === 1 ? route.fulfill({ status: 503, json: { detail: 'Synthetic policy unavailable' } }) : route.fulfill({ json: policy('unconfigured') })
  })
  const editor = await openHttpEditor(page)
  await expect(editor.getByRole('alert').filter({ hasText: 'Synthetic policy unavailable' })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeDisabled()
  await editor.getByRole('button', { name: 'Reload connection permission', exact: true }).click()
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
  expect(reads).toBe(2); expect(writes).toBe(0)
})

test('E2E-212 @full an ordinary operator sees preservation guidance without policy reads', async ({ page }) => {
  let reads = 0
  await page.route('**/v1/auth/me', async route => {
    const response = await route.fetch(); const body = await response.json()
    await route.fulfill({ response, json: { ...body, role: 'operator', roles: ['operator'] } })
  })
  await page.route('**/v1/mcp/http-trust/*', route => { reads++; return route.fulfill({ status: 403, json: { detail: 'Unexpected read' } }) })
  const editor = await openHttpEditor(page)
  await expect(editor.getByText('An administrator must save a new private target. Existing connection permission is preserved.', { exact: true })).toBeVisible()
  await expect(editor.getByText('Connection permission details', { exact: true })).toHaveCount(0)
  expect(reads).toBe(0)
})

test('E2E-213 @full JSON target changes receive a fresh policy snapshot without a permission write', async ({ page }) => {
  let reads = 0, writes = 0
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() !== 'GET') writes++
    reads++
    return route.fulfill({ json: { ...policy('unconfigured', reads), server_id: new URL(route.request().url()).pathname.split('/').at(-1) } })
  })
  const editor = await openHttpEditor(page)
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  await editor.getByLabel('Manifest JSON', { exact: true }).fill(JSON.stringify({ ...manifest, id: 'synthetic-changed-target' }, null, 2))
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
  await editor.getByText('Connection permission details', { exact: true }).click()
  await expect(editor.locator('.manifest-http-permission')).toContainText('synthetic-changed-target')
  expect(reads).toBeGreaterThanOrEqual(2); expect(writes).toBe(0)
})

test('E2E-214 @full restoring revoked permission is an explicit save intent and draft changes clear it', async ({ page }) => {
  let writes = 0
  const configWrites: Record<string, unknown>[] = []
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() !== 'GET') writes++
    return route.fulfill({ json: policy('revoked', 4) })
  })
  const editor = await openHttpEditor(page)
  await expect(editor.getByText('Connection permission was revoked. A normal save will not restore it.', { exact: true })).toBeVisible()
  await editor.getByText('Connection permission details', { exact: true }).click()
  const restore = editor.getByRole('button', { name: 'Restore this address permission on save', exact: true })
  await restore.click()
  await expect(editor.getByRole('button', { name: 'Cancel restoration', exact: true })).toBeVisible()
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic changed after restore choice')
  await expect(editor.getByRole('button', { name: 'Cancel restoration', exact: true })).toHaveCount(0)
  await restore.click()
  await page.route('**/v1/mcp/configs/*', route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const body = route.request().postDataJSON(); configWrites.push(body)
    return route.fulfill({ json: { config: { id: server.id, manifest: body.manifest }, message: 'updated' } })
  })
  await editor.getByRole('button', { name: 'Save configuration', exact: true }).click()
  await confirmSaveOnly(page)
  await expect(editor).toHaveCount(0)
  expect(configWrites).toEqual([expect.objectContaining({ http_trust_action: 'restore', expected_http_trust_revision: 4 })])
  expect(writes).toBe(0)
})

test('E2E-215 @full explicit revocation blocks subsequent requests and preserves the unsaved draft', async ({ page }) => {
  let current = policy('active', 3)
  const writes: unknown[] = []
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body)
      current = policy('revoked', 4)
    }
    return route.fulfill({ json: current })
  })
  const editor = await openHttpEditor(page)
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic unsaved name')
  await editor.getByText('Connection permission details', { exact: true }).click()
  await editor.getByRole('button', { name: 'Revoke connection permission', exact: true }).click()
  const confirmation = editor.getByRole('group', { name: 'Confirm connection revocation', exact: true })
  await expect(confirmation).toContainText(server.id)
  await confirmation.getByRole('button', { name: 'Confirm revocation', exact: true }).click()
  await expect(editor.getByText('Connection permission was revoked. A normal save will not restore it.', { exact: true })).toBeVisible()
  await expect(editor.getByLabel('Name', { exact: true })).toHaveValue('Synthetic unsaved name')
  expect(writes).toEqual([{ origins: [], expected_revision: 3, confirmed: true }])
})

test('a saved masked endpoint keeps permission recovery and scoped credential creation available @full', async ({ page }) => {
  let trustWrites = 0
  const writes: Record<string, unknown>[] = []
  await page.route('**/v1/mcp/http-trust/*', route => {
    if (route.request().method() !== 'GET') trustWrites++
    return route.fulfill({ json: { ...policy('revoked', 7), configured_origin: origin, configured_endpoint_origin: 'http://10.23.45.67:8080' } })
  })
  const editor = await openHttpEditor(page, undefined, 'en-US', { ...manifest, transport: { ...manifest.transport, endpoint: '[REDACTED]' } })
  await expect(editor.getByText('Use saved endpoint', { exact: true })).toBeVisible()
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await expect(editor.getByRole('radio', { name: 'New credential', exact: true })).toBeEnabled()
  await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
  const credentialEditor = editor.getByRole('region', { name: 'New service credential', exact: true })
  await expect(credentialEditor).toContainText('http://10.23.45.67:8080')
  await expect(credentialEditor.getByRole('button', { name: 'Save and use credential', exact: true })).toBeEnabled()
  await credentialEditor.getByRole('button', { name: 'Cancel and clear input', exact: true }).click()
  await editor.getByRole('radio', { name: 'None', exact: true }).check()
  await expect(editor.getByText('Connection permission was revoked. A normal save will not restore it.', { exact: true })).toBeVisible()
  await editor.getByText('Connection permission details', { exact: true }).click()
  await expect(editor.locator('.manifest-http-permission')).toContainText('10.23.45.67:8080')
  await editor.getByRole('button', { name: 'Restore this address permission on save', exact: true }).click()
  await page.route('**/v1/mcp/configs/*', route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const body = route.request().postDataJSON(); writes.push(body)
    return route.fulfill({ json: { config: { id: server.id, manifest: body.manifest }, message: 'updated' } })
  })
  await editor.getByRole('button', { name: 'Save configuration', exact: true }).click()
  await confirmSaveOnly(page)
  await expect(editor).toHaveCount(0)
  expect(writes).toEqual([expect.objectContaining({ http_trust_action: 'restore', expected_http_trust_revision: 7,
    manifest: expect.objectContaining({ transport: expect.objectContaining({ endpoint: '[REDACTED]' }) }) })])
  expect(trustWrites).toBe(0)
})

for (const [width, height] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]]) {
  test(`HTTP management fits desktop ${width}x${height} @full @visual`, async ({ page }, testInfo) => {
    await page.route('**/v1/mcp/http-trust/*', route => route.fulfill({ json: policy('unconfigured') }))
    const editor = await openHttpEditor(page, { width, height }, 'zh-CN')
    const save = editor.getByRole('button', { name: '保存配置', exact: true })
    await expect(save).toBeEnabled()
    await expectInViewportAndUnobscured(save)
    await expect(editor.getByRole('button', { name: '授权此地址', exact: true })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath(`http-management-${width}x${height}.png`), animations: 'disabled' })
    expect(await editor.evaluate(element => element.scrollWidth > element.clientWidth + 1)).toBe(false)
    expect(await editor.locator('.manifest-editor-body').evaluate(element => {
      const parents: Element[] = []; let parent = element.parentElement
      while (parent && parent.getAttribute('role') !== 'dialog') { parents.push(parent); parent = parent.parentElement }
      return parents.filter(item => ['auto', 'scroll'].includes(getComputedStyle(item).overflowY) && item.scrollHeight > item.clientHeight + 1).length
    })).toBe(0)
  })
}

test('inline shared credential keeps the secret outside the manifest and retries the same write key', async ({ page }) => {
  const secret = 'Synthetic-ui-secret-only-123!'
  const credentialWrites: Record<string, unknown>[] = []
  await page.route('**/v1/mcp/http-trust/*', route => route.fulfill({ json: policy('unconfigured') }))
  await page.route('**/v1/credentials', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [] })
    const body = route.request().postDataJSON(); credentialWrites.push(body)
    if (credentialWrites.length === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic credential save unavailable' } })
    return route.fulfill({ json: { id: 'synthetic-http-token', name: 'Synthetic HTTP token', description: '', value_masked: '***', created_at: 't1', updated_at: 't1', http_scopes: body.http_scopes } })
  })
  const editor = await openHttpEditor(page)
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
  const inline = editor.getByRole('region', { name: 'New service credential', exact: true })
  await inline.getByText('Credential ID (generated, editable)', { exact: true }).click()
  await inline.getByLabel('Credential ID', { exact: true }).fill('synthetic-http-token')
  await inline.getByLabel('Credential name', { exact: true }).fill('Synthetic HTTP token')
  await inline.getByLabel('Token', { exact: true }).fill(secret)
  await inline.getByRole('button', { name: 'Save and use credential', exact: true }).click()
  await expect(inline.getByRole('alert')).toContainText('Inputs are retained')
  await expect(inline.getByLabel('Token', { exact: true })).toHaveValue(secret)
  await inline.getByRole('button', { name: 'Save and use credential', exact: true }).click()
  await expect(inline).toHaveCount(0)
  expect(credentialWrites).toHaveLength(2)
  expect(credentialWrites[1]).toEqual(credentialWrites[0])
  expect(credentialWrites[0]).toMatchObject({ credential_id: 'synthetic-http-token', value: secret,
    http_scopes: [{ server_id: server.id, origin: 'http://10.23.45.67:8080' }] })
  await expect(editor.getByText('The authentication header is set automatically; no Add step is needed. The secret stays outside the configuration.', { exact: true })).toBeVisible()
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const json = editor.getByLabel('Manifest JSON', { exact: true })
  await expect(json).toHaveValue(/Bearer \$\{credential:synthetic-http-token\}/)
  expect(await json.inputValue()).not.toContain(secret)
})

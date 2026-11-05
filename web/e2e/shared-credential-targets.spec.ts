import { expect, test, type Locator, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

const peerEndpoint = () => JSON.parse(readFileSync(join(process.env.GATE_E2E_TEMP_ROOT!, 'http-peer.json'), 'utf8')).endpoint as string
const secret = 'Synthetic-auth-preset-value'

test('HTTP ID errors name the actual limit and recover without a permission-read dead end', async ({ page }, testInfo) => {
  await login(page)
  const editor = await openService(page, '_' + 'a'.repeat(128), true, 1600, 900)
  await editor.getByRole('radio', { name: '无鉴权', exact: true }).check()
  await editor.getByLabel('MCP 地址', { exact: true }).fill('http://10.23.45.67:8080/mcp')
  await expect(editor.getByText('HTTP 服务 ID 最长 128 个字符；请缩短 ID 后继续。', { exact: true }).first()).toBeVisible()
  await expect(editor.getByLabel('服务 ID', { exact: true })).toHaveAttribute('aria-invalid', 'true')
  await expect(editor.getByRole('button', { name: '保存配置', exact: true })).toBeDisabled()
  await expect(editor.getByText('请先读取当前连接许可，再保存配置。', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('http-id-actionable-error.png'), animations: 'disabled' })
  await editor.getByLabel('服务 ID', { exact: true }).fill('_synthetic-valid-http-id')
  await expect(editor.getByRole('button', { name: '保存配置', exact: true })).toBeEnabled()
})

async function openService(page: Page, serverId: string, zh: boolean, width: number, height: number) {
  await page.addInitScript(({ zh, dark }) => {
    localStorage.setItem('lingshu-gate-console-locale', zh ? 'zh-CN' : 'en-US')
    localStorage.setItem('lingshu-gate-console-theme', dark ? 'dark' : 'light')
  }, { zh, dark: !zh })
  await page.setViewportSize({ width, height })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: zh ? '新建配置' : 'New Config', exact: true }).click()
  const editor = page.getByRole('dialog', { name: zh ? '新建 MCP 配置' : 'New MCP config', exact: true })
  await editor.getByLabel(zh ? '服务 ID' : 'Server ID', { exact: true }).fill(serverId)
  await editor.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Synthetic reusable credential workflow')
  await editor.getByLabel(zh ? 'MCP 地址' : 'MCP Endpoint', { exact: true }).fill(peerEndpoint())
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  return editor
}

test('target authorization keeps the draft on a version conflict and only retries a reviewed current version', async ({ page }, testInfo) => {
  await login(page)
  const credentialId = 'synthetic-target-conflict'
  const response = await page.request.post('/v1/credentials', { data: { credential_id: credentialId, name: 'Synthetic conflict', value: secret, idempotency_key: 'create-target-conflict' } })
  expect(response.ok()).toBe(true)
  const original = await response.json()
  const editor = await openService(page, 'synthetic-target-conflict-service', false, 1600, 900)
  await (await selectCredential(page, editor, credentialId, false)).click()
  const changed = await page.request.put(`/v1/credentials/${credentialId}`, { data: {
    expected_revision: original.updated_at, idempotency_key: 'concurrent-target-conflict', description: 'Concurrent metadata retained',
  } })
  expect(changed.ok()).toBe(true)
  const current = await changed.json()
  const writes: Record<string, unknown>[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/v1/mcp/configs/with-credential') writes.push(request.postDataJSON())
  })
  const grant = editor.getByRole('region', { name: 'Credential target authorization', exact: true })
  const authorize = grant.getByRole('button', { name: 'Authorize this use on save', exact: true })
  const save = editor.getByRole('button', { name: 'Save Config', exact: true })
  await authorize.click()
  expect(writes).toHaveLength(0)
  await save.click()
  await expect(editor.getByRole('alert').filter({ hasText: 'rejected before changes' })).toBeVisible()
  expect(writes[0]).toMatchObject({ credential_write: { kind: 'authorize', expected_revision: original.updated_at, expected_http_scopes_revision: original.http_scopes_revision } })
  await expect(editor.getByLabel('Name', { exact: true })).toHaveValue('Synthetic reusable credential workflow')
  await expect(save).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath('target-version-conflict.png'), animations: 'disabled' })
  await save.click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1]).toEqual(writes[0])
  await editor.getByRole('button', { name: 'Reload and review credential', exact: true }).click()
  await expect(authorize).toBeEnabled()
  expect(writes).toHaveLength(2)
  await authorize.click()
  await expect(grant).toHaveCount(0)
  expect(writes).toHaveLength(2)
  await save.click()
  await expect(editor).toHaveCount(0)
  expect(writes[2]).toMatchObject({ credential_write: { kind: 'authorize', expected_revision: current.updated_at, expected_http_scopes_revision: current.http_scopes_revision } })
  expect(writes[2].idempotency_key).not.toBe(writes[0].idempotency_key)
  const updated = await (await page.request.get(`/v1/credentials/${credentialId}`)).json()
  expect(updated.description).toBe('Concurrent metadata retained')
})

async function selectCredential(page: Page, editor: Locator, credentialId: string, zh: boolean) {
  const selector = editor.getByRole('combobox', { name: zh ? '选择服务凭据' : 'Select service credential', exact: true })
  await selector.click()
  await selector.fill(credentialId)
  const option = page.locator('.ant-select-item-option').filter({ hasText: credentialId })
  await expect(option).toHaveCount(1)
  return option
}

for (const [index, [width, height]] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]].entries()) {
  test(`reuse shared credential without leaving service editor ${width}x${height} @visual`, async ({ page }, testInfo) => {
    const zh = index !== 1
    await login(page)
    const credentialId = `synthetic-reuse-${width}-${height}`
    const serverId = `synthetic-reuse-service-${width}-${height}`
    const created = await page.request.post('/v1/credentials', { data: {
      credential_id: credentialId, name: 'Synthetic reusable credential', value: secret,
      description: 'Preserve this description', idempotency_key: `create-${credentialId}`,
      http_scopes: [{ server_id: `synthetic-prior-${width}-${height}`, origin: 'https://prior.example.test:443' }],
    } })
    expect(created.ok()).toBe(true)
    if (index === 0) {
      const prior = await page.request.post('/v1/mcp/configs', { data: { apply: false, start: false, manifest: {
        id: `synthetic-prior-${width}-${height}`, auto_start: false, launch: { type: 'external' },
        transport: { type: 'streamable_http', endpoint: 'https://prior.example.test/mcp', headers: { Authorization: 'Bearer ${credential:' + credentialId + '}' } },
      } } })
      expect(prior.ok()).toBe(true)
    }
    const previous = await (await page.request.get(`/v1/credentials/${credentialId}`)).json()
    const editor = await openService(page, serverId, zh, width, height)
    const writes: Record<string, unknown>[] = []
    const separateWrites: string[] = []
    page.on('request', request => {
      const path = new URL(request.url()).pathname
      if (request.method() === 'POST' && path === '/v1/mcp/configs/with-credential') writes.push(request.postDataJSON())
      if (request.method() !== 'GET' && path.startsWith('/v1/credentials')) separateWrites.push(path)
    })
    const option = await selectCredential(page, editor, credentialId, zh)
    await page.screenshot({ path: testInfo.outputPath(`01-select-${width}x${height}.png`), animations: 'disabled' })
    await expect(option).not.toHaveClass(/ant-select-item-option-disabled/)
    await option.click()
    const grant = editor.getByRole('region', { name: zh ? '凭据使用授权' : 'Credential target authorization', exact: true })
    await expect(grant).toContainText(serverId)
    await expect(grant).toContainText(new URL(peerEndpoint()).origin)
    expect(writes).toHaveLength(0)
    const save = editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true })
    await expect(save).toBeDisabled()
    const authorize = grant.getByRole('button', { name: zh ? '保存时授权此用途' : 'Authorize this use on save', exact: true })
    await authorize.scrollIntoViewIfNeeded()
    await expectInViewportAndUnobscured(authorize)
    await page.screenshot({ path: testInfo.outputPath(`02-review-target-${width}x${height}.png`), animations: 'disabled' })
    await authorize.click()
    await expect(grant).toHaveCount(0)
    expect(writes).toHaveLength(0)
    expect(separateWrites).toHaveLength(0)
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    await expect(editor.getByLabel('Manifest JSON', { exact: true })).toHaveCount(0)
    await expectInViewportAndUnobscured(save)
    await expect(save).toBeEnabled()
    expect(await editor.evaluate(element => element.scrollWidth > element.clientWidth + 1)).toBe(false)
    await page.screenshot({ path: testInfo.outputPath(`03-ready-${width}x${height}.png`), animations: 'disabled' })
    await save.click()
    await expect(editor).toHaveCount(0)
    expect(writes).toHaveLength(1)
    expect(separateWrites).toHaveLength(0)
    expect(writes[0]).toMatchObject({ apply: false, start: false, credential_write: { kind: 'authorize', credential_id: credentialId,
      expected_revision: previous.updated_at, expected_http_scopes_revision: previous.http_scopes_revision,
      target: { server_id: serverId, origin: new URL(peerEndpoint()).origin } },
      manifest: { transport: { headers: { Authorization: 'Bearer ${credential:' + credentialId + '}' } } } })
    expect(writes[0].credential_write).not.toHaveProperty('value')
    expect(writes[0].credential_write).not.toHaveProperty('http_scopes')
    expect(writes[0].idempotency_key).toMatch(/^credential-[a-f0-9]{48}:00$/)
    expect(JSON.stringify(writes[0])).not.toContain(secret)
    const saved = await page.request.get(`/v1/credentials/${credentialId}`)
    expect(saved.ok()).toBe(true)
    const credential = await saved.json()
    expect(credential.http_scopes).toContainEqual(previous.http_scopes[0])
    expect(credential).toMatchObject({ name: previous.name, description: previous.description })
    expect(credential.http_scopes.find((scope: { server_id: string }) => scope.server_id === serverId)).toMatchObject({
      origin: new URL(peerEndpoint()).origin, server_binding: expect.any(String),
    })
    expect(JSON.stringify(credential)).not.toContain(secret)
  })
}

type HttpScopeSnapshot = { server_id: string; origin: string; server_binding?: string | null; pending_rebind?: boolean }

function targetScope(credential: { http_scopes: HttpScopeSnapshot[] }, serverId: string, origin: string) {
  const matches = credential.http_scopes.filter(scope => scope.server_id === serverId && scope.origin === origin)
  expect(matches).toHaveLength(1)
  return matches[0]
}

async function createBoundTarget(page: Page, suffix: string) {
  const serverId = `synthetic-same-origin-${suffix}`
  const credentialId = `synthetic-same-origin-token-${suffix}`
  const endpoint = peerEndpoint()
  const origin = new URL(endpoint).origin
  const next = new URL(endpoint)
  next.pathname = `/synthetic-replacement-${suffix}/mcp`
  const nextEndpoint = next.href
  expect(new URL(nextEndpoint).origin).toBe(origin)
  expect(new URL(nextEndpoint).pathname).not.toBe(new URL(endpoint).pathname)
  const created = await page.request.post('/v1/credentials', { data: {
    credential_id: credentialId, name: `Synthetic same-origin ${suffix}`, value: secret,
    idempotency_key: `create-same-origin-${suffix}`, http_scopes: [{ server_id: serverId, origin }],
  } })
  expect(created.ok()).toBe(true)
  const saved = await page.request.post('/v1/mcp/configs', { data: {
    apply: false, start: false, manifest: {
      id: serverId, name: `Synthetic same-origin ${suffix}`, enabled: true, auto_start: false, startup_policy: 'gate_start_v1',
      launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint, headers: { Authorization: 'Bearer ${credential:' + credentialId + '}' } },
    },
  } })
  expect(saved.ok()).toBe(true)
  const configResponse = await page.request.get(`/v1/mcp/configs/${serverId}`)
  expect(configResponse.ok()).toBe(true)
  const config = await configResponse.json()
  const credentialResponse = await page.request.get(`/v1/credentials/${credentialId}`)
  expect(credentialResponse.ok()).toBe(true)
  const credential = await credentialResponse.json()
  const scope = targetScope(credential, serverId, origin)
  expect(scope.server_binding).toEqual(expect.any(String))
  expect(scope.server_binding).not.toBe('')
  expect(scope.pending_rebind ?? false).toBe(false)
  expect(credential.http_scopes_revision).toMatch(/^[a-f0-9]{64}$/)
  const policyResponse = await page.request.get(`/v1/mcp/http-trust/${serverId}`)
  expect(policyResponse.ok()).toBe(true)
  expect((await policyResponse.json()).configured_server_binding).toBe(scope.server_binding)
  return { serverId, credentialId, origin, nextEndpoint, config, credential, scope }
}

async function openChangedTarget(page: Page, target: Awaited<ReturnType<typeof createBoundTarget>>) {
  await page.addInitScript(() => {
    localStorage.setItem('lingshu-gate-console-locale', 'en-US')
    localStorage.setItem('lingshu-gate-console-theme', 'light')
  })
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/console/#/configs')
  await page.getByPlaceholder(/ ID \/ /).fill(target.serverId)
  await page.getByRole('row').filter({ hasText: target.serverId }).getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = page.getByRole('dialog', { name: `Edit · ${target.serverId}`, exact: true })
  const save = editor.getByRole('button', { name: 'Save Config', exact: true })
  await expect(editor.getByRole('radio', { name: 'Custom', exact: true })).toBeChecked()
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await (await selectCredential(page, editor, target.credentialId, false)).click()
  const grant = editor.getByRole('region', { name: 'Credential target authorization', exact: true })
  await expect(grant).toHaveCount(0)
  await expect(save).toBeEnabled()
  await editor.getByRole('button', { name: 'Replace endpoint', exact: true }).click()
  await editor.getByLabel('MCP Endpoint', { exact: true }).fill(target.nextEndpoint)
  await expect(grant).toBeVisible()
  await expect(grant).toContainText(target.serverId)
  await expect(grant).toContainText(target.origin)
  await expect(save).toBeDisabled()
  return { editor, grant, save }
}

for (const saveConfiguration of [true, false]) {
  test(saveConfiguration
    ? 'same-origin endpoint replacement explicitly reauthorizes and seals a new credential binding on save @full'
    : 'cancelling an authorized same-origin endpoint replacement preserves the current service binding @full', async ({ page }, testInfo) => {
    await login(page)
    const target = await createBoundTarget(page, saveConfiguration ? 'save' : 'cancel')
    const credentialWrites: Record<string, unknown>[] = []
    const configWrites: Record<string, unknown>[] = []
    page.on('request', request => {
      const path = new URL(request.url()).pathname
      if (request.method() === 'PUT' && path === `/v1/credentials/${target.credentialId}`) credentialWrites.push(request.postDataJSON())
      if (request.method() === 'POST' && path === '/v1/mcp/configs/with-credential') configWrites.push(request.postDataJSON())
    })
    const { editor, grant, save } = await openChangedTarget(page, target)
    expect(credentialWrites).toHaveLength(0)
    expect(configWrites).toHaveLength(0)
    const authorize = grant.getByRole('button', { name: 'Authorize this use on save', exact: true })
    await authorize.scrollIntoViewIfNeeded()
    await expectInViewportAndUnobscured(authorize)
    if (saveConfiguration) await page.screenshot({ path: testInfo.outputPath('same-origin-replacement-needs-authorization.png'), animations: 'disabled' })
    await authorize.click()
    await expect(grant).toHaveCount(0)
    await expect(save).toBeEnabled()
    expect(credentialWrites).toHaveLength(0)
    const pendingResponse = await page.request.get(`/v1/credentials/${target.credentialId}`)
    expect(pendingResponse.ok()).toBe(true)
    const pending = await pendingResponse.json()
    expect(targetScope(pending, target.serverId, target.origin)).toEqual(target.scope)
    expect(pending.http_scopes_revision).toBe(target.credential.http_scopes_revision)
    expect(pending.updated_at).toBe(target.credential.updated_at)
    expect(configWrites).toHaveLength(0)

    if (saveConfiguration) {
      await save.click()
    } else {
      await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
      await page.getByRole('alertdialog').getByRole('button', { name: 'Discard changes', exact: true }).click()
    }
    await expect(editor).toHaveCount(0)
    const configResponse = await page.request.get(`/v1/mcp/configs/${target.serverId}`)
    expect(configResponse.ok()).toBe(true)
    const config = await configResponse.json()
    const credentialResponse = await page.request.get(`/v1/credentials/${target.credentialId}`)
    expect(credentialResponse.ok()).toBe(true)
    const credential = await credentialResponse.json()
    const scope = targetScope(credential, target.serverId, target.origin)
    const policyResponse = await page.request.get(`/v1/mcp/http-trust/${target.serverId}`)
    expect(policyResponse.ok()).toBe(true)
    const policy = await policyResponse.json()
    if (saveConfiguration) {
      expect(configWrites).toHaveLength(1)
      expect(configWrites[0]).toMatchObject({ apply: false, start: false, expected_config_digest: target.config.digest,
        manifest: { transport: { endpoint: target.nextEndpoint, headers: { Authorization: 'Bearer ${credential:' + target.credentialId + '}' } } },
        credential_write: { kind: 'authorize', credential_id: target.credentialId, expected_revision: target.credential.updated_at,
          expected_http_scopes_revision: target.credential.http_scopes_revision, target: { server_id: target.serverId, origin: target.origin } },
      })
      expect(configWrites[0].credential_write).not.toHaveProperty('value')
      expect(config.digest).not.toBe(target.config.digest)
      expect(scope.server_binding).toEqual(expect.any(String))
      expect(scope.server_binding).not.toBe(target.scope.server_binding)
      expect(scope.pending_rebind ?? false).toBe(false)
      expect(credential.http_scopes_revision).not.toBe(pending.http_scopes_revision)
    } else {
      expect(configWrites).toHaveLength(0)
      expect(config.digest).toBe(target.config.digest)
      expect(config.manifest).toEqual(target.config.manifest)
      expect(scope).toEqual(target.scope)
      expect(credential.http_scopes_revision).toBe(pending.http_scopes_revision)
      expect(credential.updated_at).toBe(target.credential.updated_at)
    }
    expect(policy.configured_server_binding).toBe(scope.server_binding)
    expect(credentialWrites).toHaveLength(0)
    expect(JSON.stringify(credential)).not.toContain(secret)
  })
}

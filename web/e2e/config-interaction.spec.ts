import { test, expect, type Page } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers } from './synthetic-data'

const server = { ...servers[0], launch_type: 'external', status: 'running', enabled: true }
const manifest = { id: server.id, name: server.name, enabled: true, launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'http://127.0.0.1:1/mcp' }, timeout_seconds: 30 }
async function openEditor(page: Page, historyForward = false, options: { locale?: 'en-US' | 'zh-CN'; viewport?: { width: number; height: number }; dark?: boolean; manifest?: Record<string, unknown>; configDigest?: string } = {}) {
  await login(page)
  if (options.locale || options.dark) await page.addInitScript(({ locale, dark }) => {
    localStorage.setItem('lingshu-gate-console-locale', locale || 'en-US')
    localStorage.setItem('lingshu-gate-console-theme', dark ? 'dark' : 'light')
  }, { locale: options.locale, dark: options.dark })
  await page.route('**/v1/mcp/servers', route => route.fulfill({ json: { servers: [server], load_errors: [] } }))
  await page.route('**/v1/mcp/servers/*/detail?*', route => route.fulfill({ json: { server, manifest: options.manifest || manifest, config_digest: options.configDigest, tools: [] } }))
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] } }))
  await page.setViewportSize(options.viewport || { width: 1280, height: 600 })
  if (historyForward) {
    await page.goto('/console/#/dashboard')
    await page.locator('.console-rail-item[href="#/servers"]').click()
    await page.locator('.console-rail-item[href="#/tools"]').click()
    await page.goBack()
  } else await page.goto('/console/#/servers')
  const zh = options.locale === 'zh-CN'
  await page.getByRole('tab', { name: zh ? '配置' : 'Configuration', exact: true }).click()
  await page.getByRole('button', { name: zh ? '修改配置' : 'Edit configuration', exact: true }).click()
  return page.getByRole('dialog', { name: `${zh ? '修改配置' : 'Edit configuration'} · ${server.id}`, exact: true })
}

test('E2E-201 @full cancelling save-only confirmation sends no mutation', async ({ page }, testInfo) => {
  const editor = await openEditor(page)
  const writes: string[] = []
  await page.route('**/v1/mcp/configs/*', async route => {
    if (route.request().method() === 'PUT') { writes.push(route.request().url()); await route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } }) }
    else await route.fallback()
  })
  await editor.getByRole('radio', { name: 'Save only (not applied)', exact: true }).check()
  const save = editor.getByRole('button', { name: 'Save configuration', exact: true })
  await expectInViewportAndUnobscured(save)
  await page.screenshot({ path: testInfo.outputPath('mock-service-config-short.png') })
  await save.click()
  const confirm = page.getByRole('alertdialog')
  await expect(confirm).toBeVisible()
  await expectInViewportAndUnobscured(confirm.getByRole('button', { name: 'Cancel', exact: true }))
  await confirm.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  await expect(save).toBeEnabled()
  await expect(save).toBeFocused()
  expect(writes).toEqual([])
})

test('E2E-202 @full HTTP200 failed activation retains editor and blocks duplicate save', async ({ page }) => {
  const editor = await openEditor(page)
  let writes = 0
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/mcp/configs/*', async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    writes++
    await gate
    await route.fulfill({ json: { config: { id: server.id, path: '/synthetic/config.json', format: 'json', manifest }, server: { ...server, status: 'failed', last_error: 'Synthetic activation failed' }, message: 'Synthetic failure' } })
  })
  await editor.getByRole('radio', { name: 'Save, apply and start', exact: true }).check()
  await editor.getByRole('button', { name: 'Save configuration', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Save and reconnect', exact: true }).click()
  await expect.poll(() => writes).toBe(1)
  await expect(editor.getByRole('button', { name: 'Saving…', exact: true })).toBeDisabled()
  await page.keyboard.press('Enter')
  expect(writes).toBe(1)
  release!()
  await expect(editor.getByText('Synthetic activation failed', { exact: true })).toBeVisible()
  await expect(editor).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
})

test('E2E-205 @full form and JSON share enabled state, preserve draft fields and keep invalid JSON invalid', async ({ page }) => {
  const editor = await openEditor(page, false, { manifest: { ...manifest, enabled: false, permissions: { default: 'read', custom: { count: 0 } }, synthetic_draft: { enabled: false, count: 0, value: '' } } })
  const enabled = editor.getByRole('switch', { name: 'Enable service', exact: true })
  await expect(enabled).not.toBeChecked()
  await enabled.click()
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const json = editor.locator('[data-manifest-json]')
  const draft = JSON.parse(await json.inputValue())
  expect(draft.enabled).toBe(true)
  expect(draft.synthetic_draft).toEqual({ enabled: false, count: 0, value: '' })
  expect(draft.permissions).toEqual({ default: 'read', custom: { count: 0 } })
  await json.fill('{"id":')
  await expect(json).toHaveValue('{"id":')
  await expect(editor.getByRole('button', { name: 'Form', exact: true })).toBeDisabled()
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeDisabled()
  await expect(editor.getByText('JSON syntax error', { exact: true })).toBeVisible()
  await json.fill(JSON.stringify({ ...draft, enabled: false }))
  await editor.getByRole('button', { name: 'Form', exact: true }).click()
  await expect(enabled).not.toBeChecked()
  await expect(editor.getByText('Access declarations', { exact: true })).not.toBeVisible()
  await editor.getByText('Advanced configuration', { exact: true }).click()
  await expect(editor.getByText('Declarations are for review; they do not grant user access or replace tool classification and connection grants.', { exact: true })).toBeVisible()
})

test('E2E-206 @full one precheck status, visible error location and edited drafts clear prior results', async ({ page }) => {
  const editor = await openEditor(page)
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: false, can_apply: false, manifest_id: server.id, summary: { errors: 1, warnings: 0, info: 0, ok: 2 }, checks: [
    { name: 'transport.endpoint', severity: 'error', message: 'Synthetic endpoint policy rejection', metadata: {} },
    { name: 'manifest.schema', severity: 'ok', message: 'Schema valid', metadata: {} },
  ] } }))
  await editor.getByRole('button', { name: 'Validate configuration', exact: true }).click()
  await expect(editor.locator('.manifest-validation')).toHaveCount(1)
  await expect(editor.getByText('Check failed · 1 Errors', { exact: true })).toBeVisible()
  await expect(editor.getByText('Additional checks', { exact: true })).toHaveCount(0)
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeDisabled()
  await editor.getByRole('button', { name: '/transport/endpoint: Synthetic endpoint policy rejection', exact: true }).click()
  const endpoint = editor.getByLabel('MCP Endpoint', { exact: true })
  await expect(endpoint).toBeFocused()
  await endpoint.fill('https://fixed.example.test/mcp')
  await expect(editor.locator('.manifest-validation')).toHaveCount(0)
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 1, info: 0, ok: 0 }, checks: [{ name: 'launch.cwd', severity: 'warning', message: 'Synthetic optional warning', metadata: {} }] } }))
  await editor.getByRole('button', { name: 'Validate configuration', exact: true }).click()
  await expect(editor.getByText('Check completed · 1 Warnings', { exact: true })).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
  await endpoint.fill('https://passed.example.test/mcp')
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] } }))
  await editor.getByRole('button', { name: 'Validate configuration', exact: true }).click()
  await expect(editor.getByText('Check passed', { exact: true })).toBeVisible()
  await expect(editor.getByText('Additional checks', { exact: true })).toHaveCount(0)
})

test('E2E-207 @full saving a disabled draft alone does not apply or start, reopening retains the enabled state', async ({ page }) => {
  const digest = 'a'.repeat(64)
  const editor = await openEditor(page, false, { configDigest: digest })
  let saved = { ...manifest }
  let writes = 0
  await page.route('**/v1/mcp/servers/*/detail?*', route => route.fulfill({ json: { server, manifest: saved, tools: [] } }))
  await page.route('**/v1/mcp/configs/*', async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const body = route.request().postDataJSON()
    expect(body.apply).toBe(false)
    expect(body.start).toBe(false)
    expect(body.manifest.enabled).toBe(false)
    expect(body.expected_config_digest).toBe(digest)
    saved = body.manifest
    writes++
    await route.fulfill({ json: { config: { id: server.id, path: '/synthetic/config.json', format: 'json', manifest: saved }, server: null, message: 'Saved without applying' } })
  })
  await editor.getByRole('switch', { name: 'Enable service', exact: true }).click()
  await editor.getByRole('radio', { name: 'Save only (not applied)', exact: true }).check()
  await editor.getByRole('button', { name: 'Save configuration', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Save only (not applied)', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(writes).toBe(1)
  await page.getByRole('button', { name: 'Edit configuration', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('switch', { name: 'Enable service', exact: true })).not.toBeChecked()
})

test('E2E-216 @full saved-config conflict retains the draft and does not auto-overwrite or replace its edit digest', async ({ page }) => {
  const digest = 'b'.repeat(64)
  const editor = await openEditor(page, false, { configDigest: digest })
  let writes = 0
  await page.route('**/v1/mcp/configs/*', route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    const body = route.request().postDataJSON()
    expect(body.expected_config_digest).toBe(digest)
    expect(body.apply).toBe(false)
    expect(body.start).toBe(false)
    expect(body.manifest.name).toBe('Synthetic conflicting draft')
    writes++
    return route.fulfill({ status: 409, json: { detail: 'MCP configuration changed; reopen the saved configuration before updating' } })
  })
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic conflicting draft')
  for (let attempt = 1; attempt <= 2; attempt++) {
    await editor.getByRole('button', { name: 'Save configuration', exact: true }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Save only (not applied)', exact: true }).click()
    await expect(editor.getByText('MCP configuration changed; reopen the saved configuration before updating', { exact: true })).toBeVisible()
    await expect(editor.getByLabel('Name', { exact: true })).toHaveValue('Synthetic conflicting draft')
    await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeEnabled()
    expect(writes).toBe(attempt)
  }
})

for (const external of [false, true]) {
  test(`E2E-217 @full ${external ? 'external' : 'managed'} startup policy changes only after an explicit switch edit`, async ({ page }) => {
    const draft = external ? manifest : { ...manifest, launch: { type: 'managed_process', command: 'synthetic-server' }, transport: { type: 'stdio' } }
    const editor = await openEditor(page, false, { manifest: draft })
    await editor.getByLabel('Name', { exact: true }).fill('Synthetic ordinary edit')
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    const json = editor.locator('[data-manifest-json]')
    expect(JSON.parse(await json.inputValue())).not.toHaveProperty('startup_policy')
    await editor.getByRole('button', { name: 'Form', exact: true }).click()
    const startup = editor.getByRole('switch', { name: 'Start automatically when Gate starts', exact: true })
    await expect(startup).not.toBeChecked()
    const helper = external ? 'Connect automatically without starting a remote process.' : 'Start the MCP process automatically and connect.'
    await expect(editor.getByText(`${helper} Legacy policy: restore the last state. Edit the switch to adopt the startup policy.`, { exact: true })).toBeVisible()
    await startup.click()
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    expect(JSON.parse(await json.inputValue())).toMatchObject({ auto_start: true, startup_policy: 'gate_start_v1' })
    await editor.getByRole('button', { name: 'Form', exact: true }).click()
    await startup.click()
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    expect(JSON.parse(await json.inputValue())).toMatchObject({ auto_start: false, startup_policy: 'gate_start_v1' })
  })
}

test('E2E-208 @full dirty escape retains the draft until discard and clean closure restores trigger focus', async ({ page }) => {
  const editor = await openEditor(page)
  const trigger = page.getByRole('button', { name: 'Edit configuration', exact: true })
  await editor.getByLabel('Name', { exact: true }).fill('Synthetic dirty edit')
  await page.keyboard.press('Escape')
  const guard = page.getByRole('alertdialog', { name: 'Discard unsaved changes?', exact: true })
  await expect(guard).toBeVisible()
  await guard.getByRole('button', { name: 'Continue editing', exact: true }).click()
  await expect(editor.getByLabel('Name', { exact: true })).toHaveValue('Synthetic dirty edit')
  await expect(editor.getByLabel('Name', { exact: true })).toBeFocused()
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Discard changes', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

for (const viewport of [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]) {
  for (const locale of ['en-US', 'zh-CN'] as const) for (const dark of [false, true]) {
    test(`E2E-209 @visual configuration Dialog ${viewport.width}x${viewport.height} ${locale} ${dark ? 'dark' : 'light'}`, async ({ page }, testInfo) => {
      const editor = await openEditor(page, false, { viewport, locale, dark, manifest: { ...manifest, name: 'Synthetic service', transport: { ...manifest.transport, endpoint: `https://synthetic.example.test/${'long-path/'.repeat(30)}mcp`, headers: Object.fromEntries(Array.from({ length: 80 }, (_, i) => [`X-Synthetic-${i}`, 'synthetic value'])) } } })
      const zh = locale === 'zh-CN'
      if (dark) await expect(page.locator('html')).toHaveClass(/dark/)
      else await expect(page.locator('html')).not.toHaveClass(/dark/)
      await expect(editor.getByRole('radio', { name: zh ? '外部 HTTP' : 'External HTTP', exact: true })).toBeChecked()
      await expect(editor.locator('.manifest-form').getByRole('radio')).toHaveCount(3)
      const save = editor.getByRole('button', { name: zh ? '保存配置' : 'Save configuration', exact: true })
      await expectInViewportAndUnobscured(save)
      const geometry = await editor.evaluate(element => {
        const rect = element.getBoundingClientRect()
        const body = element.querySelector('.service-config-dialog-body')!
        const fields = element.querySelector('.manifest-editor-body')!
        return { width: rect.width, height: rect.height, centerX: rect.x + rect.width / 2, centerY: rect.y + rect.height / 2, outerScroll: element.scrollHeight > element.clientHeight + 1, bodyScroll: body.scrollHeight > body.clientHeight + 1, fieldsScroll: fields.scrollHeight > fields.clientHeight + 1 }
      })
      expect(geometry.width).toBeLessThanOrEqual(Math.min(1200, viewport.width - 96))
      expect(geometry.height).toBeLessThanOrEqual(viewport.height - 64)
      expect(Math.abs(geometry.centerX - viewport.width / 2)).toBeLessThan(2)
      expect(Math.abs(geometry.centerY - viewport.height / 2)).toBeLessThan(2)
      expect(geometry.outerScroll).toBe(false)
      expect(geometry.bodyScroll).toBe(false)
      expect(geometry.fieldsScroll).toBe(true)
      const rowsAligned = await editor.locator('.manifest-form .manifest-field').evaluateAll(fields => fields.every(field => {
        const label = field.querySelector('label')!, control = field.querySelector('.manifest-field-control')!
        const a = label.getBoundingClientRect(), b = control.getBoundingClientRect()
        if (!a.width || !a.height) return true
        return b.left >= a.right && b.top < a.bottom && b.bottom > a.top && getComputedStyle(label).whiteSpace === 'nowrap'
      }))
      expect(rowsAligned).toBe(true)
      await page.screenshot({ path: testInfo.outputPath('configuration-form.png') })
      await editor.getByRole('button', { name: 'JSON', exact: true }).click()
      await expectInViewportAndUnobscured(save)
      const json = editor.locator('[data-manifest-json]')
      await expectInViewportAndUnobscured(json)
      expect((await json.boundingBox())?.height).toBeGreaterThanOrEqual(320)
      const scroll = await editor.evaluate(element => {
        const body = element.querySelector('.manifest-editor-body')!
        const textarea = element.querySelector('textarea')!
        return { body: body.scrollHeight > body.clientHeight + 1, textarea: textarea.scrollHeight > textarea.clientHeight + 1 }
      })
      expect(scroll.body).toBe(false)
      expect(scroll.textarea).toBe(true)
      await page.screenshot({ path: testInfo.outputPath('configuration-json.png') })
    })
  }
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
  const editor = await openEditor(page, false, { viewport: { width: 1600, height: 900 }, manifest: { ...manifest, transport: { ...manifest.transport, endpoint: 'http://10.23.45.67:8080/mcp' } } })
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
  await expect(editor.getByRole('button', { name: 'Save configuration', exact: true })).toBeDisabled()
  await page.keyboard.press('Enter')
  expect(trustWrites).toBe(1)
  release!()
  await expect(editor.getByText('This internal address is authorized.', { exact: true })).toBeVisible()
  await expect(editor.getByText('Check passed', { exact: true })).toBeVisible()
  await expect(editor.getByLabel('Name', { exact: true })).toHaveValue('Synthetic unsaved name')
  expect(validations).toBe(1)
  expect(configWrites).toBe(0)
})


test('E2E-204 @full cancelled Back and Forward preserve dirty service configuration', async ({ page }) => {
  const editor = await openEditor(page, true)
  const name = editor.getByLabel('Name', { exact: true })
  await name.fill('Synthetic unsaved draft')
  for (const direction of ['forward', 'back'] as const) {
    await page.evaluate(direction => history[direction](), direction)
    const dialog = page.getByRole('alertdialog', { name: 'Discard changes and leave?', exact: true })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Keep editing', exact: true }).click()
    await expect(page).toHaveURL(/#\/servers$/)
    await expect(name).toHaveValue('Synthetic unsaved draft')
  }
})

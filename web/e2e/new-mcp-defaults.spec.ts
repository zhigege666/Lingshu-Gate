import { test, expect, type Page } from '@playwright/test'
import { login } from './helpers'
import { servers } from './synthetic-data'

const id = 'synthetic-disabled-service'
const manifest = { id, name: 'Synthetic disabled service', enabled: false, startup_policy: 'gate_start_v1', auto_start: false,
  launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'https://synthetic.example.test/mcp' }, timeout_seconds: 30 }
const server = { ...servers[0], id, name: manifest.name, launch_type: 'external', status: 'external',
  enabled: false, tool_count: 0, desired_state: 'stopped', effective_should_run: false, pid: null,
  restore_blocked_reason: 'Server is disabled', allowed_actions: [] }
const config = { id, digest: 'a'.repeat(64), path: '/synthetic/disabled.json', format: 'json', manifest }

async function mock(page: Page, locale: 'zh-CN' | 'en-US' = 'en-US') {
  await login(page)
  await page.addInitScript(locale => {
    localStorage.setItem('lingshu-gate-console-locale', locale)
    localStorage.setItem('lingshu-gate-console-theme', locale === 'zh-CN' ? 'dark' : 'light')
  }, locale)
  await page.setViewportSize({ width: 1600, height: 900 })
  const writes: Array<{ method: string; path: string; body: unknown }> = []
  await page.route('**/v1/mcp/**', route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (method !== 'GET') {
      writes.push({ method, path, body: route.request().postDataJSON() })
      if (path.endsWith('/validate')) return route.fulfill({ json: { ok: true, can_apply: true, manifest_id: id, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] } })
      return route.fulfill({ status: 500, json: { detail: 'Unexpected synthetic mutation' } })
    }
    if (path === '/v1/mcp/servers') return route.fulfill({ json: { servers: [server], load_errors: [] } })
    if (path === '/v1/mcp/configs') return route.fulfill({ json: { configs: [config], errors: [] } })
    if (path.endsWith('/detail')) return route.fulfill({ json: { server, manifest, config_digest: config.digest, tools: [] } })
    return route.fallback()
  })
  await page.route('**/v1/tools', route => route.fulfill({ json: [] }))
  return writes
}

for (const locale of ['en-US', 'zh-CN'] as const) {
  const zh = locale === 'zh-CN'
  for (const entry of ['servers', 'configs', 'command'] as const) {
    test(`new MCP defaults to save and connect while preserving explicit opt-outs, ${entry} entry ${locale}`, async ({ page }, testInfo) => {
      const writes = await mock(page, locale)
      await page.goto('/console/#/' + (entry === 'command' ? 'servers' : entry))
      if (entry === 'servers') await page.locator('.service-directory-create-actions').getByRole('button').filter({ hasText: zh ? '接入远程 MCP' : 'Connect remote MCP' }).click()
      if (entry === 'configs') await page.getByRole('button', { name: zh ? '新建配置' : 'New Config', exact: true }).click()
      if (entry === 'command') {
        await expect(page.getByRole('heading', { name: manifest.name, exact: true })).toBeVisible()
        await page.keyboard.press('Control+k')
        await page.getByRole('option').filter({ hasText: zh ? '通用模板' : 'Generic Template' }).click()
      }
      const dialog = page.getByRole('dialog', { name: zh ? '新建 MCP 配置' : 'New MCP config', exact: true })
      await expect(dialog).toHaveCSS('opacity', '1')
      await expect(dialog.getByRole('switch', { name: zh ? '启用服务' : 'Enable service', exact: true })).toBeChecked()
      await expect(dialog.getByRole('switch', { name: zh ? 'Gate 启动时自动启动' : 'Start automatically when Gate starts', exact: true })).toBeChecked()
      await expect(dialog.getByRole('radio', { name: zh ? '保存并连接' : 'Save and connect', exact: true })).toBeChecked()
      if (entry === 'servers') await page.screenshot({ path: testInfo.outputPath('new-mcp-enabled-form.png'), animations: 'disabled' })
      await dialog.getByRole('button', { name: 'JSON', exact: true }).click()
      const json = dialog.locator('[data-manifest-json]')
      const draft = JSON.parse(await json.inputValue())
      expect(draft).toMatchObject({ enabled: true, auto_start: true, startup_policy: 'gate_start_v1' })
      // Explicit opt-out must survive every runtime mode change.
      await json.fill(JSON.stringify({ ...draft, enabled: false, auto_start: false }))
      await dialog.getByRole('button', { name: zh ? '表单' : 'Form', exact: true }).click()
      for (const mode of zh ? ['受管 Stdio', '受管 HTTP', '外部 HTTP'] : ['Managed Stdio', 'Managed HTTP', 'External HTTP']) {
        await dialog.getByRole('radio', { name: mode, exact: true }).check()
        await expect(dialog.getByRole('switch', { name: zh ? '启用服务' : 'Enable service', exact: true })).not.toBeChecked()
        await expect(dialog.getByRole('switch', { name: zh ? 'Gate 启动时自动启动' : 'Start automatically when Gate starts', exact: true })).not.toBeChecked()
        await expect(dialog.getByRole('radio', { name: zh ? '仅保存' : 'Save only', exact: true })).toBeChecked()
        await expect(dialog.getByRole('radio', { name: zh ? /^保存并(连接|启动)$/ : /^Save and (connect|start)$/ })).toBeDisabled()
      }
      expect(writes).toEqual([])
    })
  }

  test(`editing a disabled service saves its draft without enabling or starting it ${locale}`, async ({ page }, testInfo) => {
    const writes = await mock(page, locale)
    const saves: Record<string, unknown>[] = []
    await page.route(`**/v1/mcp/configs/${id}`, route => {
      if (route.request().method() !== 'PUT') return route.fallback()
      const body = route.request().postDataJSON()
      saves.push(body)
      return route.fulfill({ json: { config: { ...config, manifest: body.manifest }, server: null, message: 'Saved only' } })
    })
    await page.goto('/console/#/servers')
    const action = page.getByRole('button', { name: zh ? '编辑并启用' : 'Edit and enable', exact: true })
    await expect(action).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('disabled-edit-entry.png'), animations: 'disabled' })
    await action.click()
    const dialog = page.getByRole('dialog', { name: `${zh ? '修改配置' : 'Edit configuration'} · ${id}`, exact: true })
    await expect(dialog).toHaveCSS('opacity', '1')
    await expect(dialog.getByRole('switch', { name: zh ? '启用服务' : 'Enable service', exact: true })).not.toBeChecked()
    await expect(dialog.getByRole('switch', { name: zh ? 'Gate 启动时自动启动' : 'Start automatically when Gate starts', exact: true })).not.toBeChecked()
    await expect(dialog.getByRole('radio', { name: zh ? '仅保存（未生效）' : 'Save only (not applied)', exact: true })).toBeChecked()
    await expect(dialog.getByRole('radio', { name: zh ? '保存后启动' : 'Start after saving', exact: true })).toBeDisabled()
    await dialog.getByRole('button', { name: 'JSON', exact: true }).click()
    await dialog.locator('[data-manifest-json]').fill(JSON.stringify({ ...manifest, name: 'Saved disabled draft' }))
    await page.screenshot({ path: testInfo.outputPath('disabled-save-only.png'), animations: 'disabled' })
    await dialog.getByRole('button', { name: zh ? '仅保存（未生效）' : 'Save only (not applied)', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    expect(saves).toHaveLength(1)
    expect(saves[0]).toMatchObject({ apply: false, start: false, expected_config_digest: config.digest,
      manifest: { id, name: 'Saved disabled draft', enabled: false, auto_start: false } })
    expect(writes.filter(w => w.path.endsWith('/validate'))).toHaveLength(1)
    expect(writes.filter(w => !w.path.endsWith('/validate'))).toEqual([])
  })
}

for (const activate of [true, false]) {
  test(`new enabled MCP ${activate ? 'saves and connects by default' : 'respects explicit save only'} with one save request`, async ({ page }) => {
    const writes = await mock(page)
    const saves: Record<string, unknown>[] = []
    await page.route('**/v1/mcp/configs', route => {
      if (route.request().method() !== 'POST') return route.fallback()
      const body = route.request().postDataJSON()
      saves.push(body)
      return route.fulfill({ json: { config: { ...config, id: body.manifest.id, manifest: body.manifest },
        server: activate ? { ...server, id: body.manifest.id, enabled: true, status: 'running', desired_state: 'running', effective_should_run: true, restore_blocked_reason: null } : null,
        message: activate ? 'Saved and connected' : 'Saved only' } })
    })
    await page.goto('/console/#/configs')
    await page.getByRole('button', { name: 'New Config', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'New MCP config', exact: true })
    await dialog.getByLabel('MCP Endpoint', { exact: true }).fill('https://synthetic.example.test/mcp')
    if (!activate) await dialog.getByRole('radio', { name: 'Save only', exact: true }).check()
    await dialog.getByRole('button', { name: activate ? 'Save and connect' : 'Save Config', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    expect(saves).toHaveLength(1)
    expect(saves[0]).toMatchObject({ apply: activate, start: activate, manifest: { enabled: true, auto_start: true, startup_policy: 'gate_start_v1' } })
    expect(writes.filter(w => w.path.endsWith('/validate'))).toHaveLength(1)
    // Activation is part of the configuration write; no extra apply/start/trust request is needed.
    expect(writes.filter(w => !w.path.endsWith('/validate'))).toEqual([])
  })
}

for (const [status, launch, enabled] of [['external', 'external', true], ['loaded', 'managed_process', true], ['external', 'external', false], ['stopped', 'managed_process', false]] as const) {
  test(`apply and start respects the returned service state ${status}/${launch}/enabled=${enabled}`, async ({ page }) => {
    const writes = await mock(page)
    const appliedConfig = { ...config, manifest: { ...manifest, enabled } }
    let calls = 0, starts = 0
    await page.route(`**/v1/mcp/configs/${id}/apply`, route => {
      calls++
      return route.fulfill({ json: { config: appliedConfig, server: { ...server, status, launch_type: launch, enabled }, message: 'applied' } })
    })
    await page.route(`**/v1/mcp/servers/${id}/start`, route => {
      starts++
      return route.fulfill({ json: { ...server, status: 'running', launch_type: launch, enabled, desired_state: 'running', effective_should_run: true } })
    })
    await page.goto('/console/#/configs')
    await page.getByRole('button', { name: 'Apply and start', exact: true }).click()
    await expect(page.getByText(`${enabled ? 'Applied and started' : 'Applied; service remains disabled'}: ${id}`, { exact: true })).toBeVisible()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    await expect(page.getByText('Configuration application state is unknown. Inspect the service.', { exact: true })).toHaveCount(0)
    expect(calls).toBe(1)
    expect(starts).toBe(enabled ? 1 : 0)
    expect(writes).toEqual([])
  })
}

test('unknown apply response stays an error and does not auto-retry', async ({ page }) => {
  const writes = await mock(page)
  let calls = 0
  await page.route(`**/v1/mcp/configs/${id}/apply`, route => { calls++; return route.fulfill({ json: { config, server: null, message: 'unknown' } }) })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'Apply and start', exact: true }).click()
  await expect(page.getByText('Configuration application state is unknown. Inspect the service.', { exact: true })).toBeVisible()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  expect(calls).toBe(1)
  expect(writes).toEqual([])
})

for (const entry of ['apply', 'save'] as const) {
  test(`direct configuration entry checks the running service before ${entry} interrupts it`, async ({ page }) => {
    const writes = await mock(page)
    const enabledManifest = { ...manifest, enabled: true }
    const running = { ...server, enabled: true, status: 'running', desired_state: 'running', effective_should_run: true, restore_blocked_reason: null }
    const activeConfig = { ...config, manifest: enabledManifest }
    let stateReads = 0
    await page.route('**/v1/mcp/servers', route => { stateReads++; return route.fulfill({ json: { servers: [running], load_errors: [] } }) })
    await page.route('**/v1/mcp/servers/*/detail**', route => route.fulfill({ json: { server: running, manifest: enabledManifest, config_digest: config.digest, tools: [] } }))
    await page.route('**/v1/mcp/configs', route => route.request().method() === 'GET'
      ? route.fulfill({ json: { configs: [activeConfig], errors: [] } }) : route.fallback())
    let applications = 0, starts = 0, saves = 0
    await page.route(`**/v1/mcp/configs/${id}/apply`, route => {
      applications++
      return route.fulfill({ json: { config: activeConfig, server: { ...running, status: 'external', desired_state: 'stopped', effective_should_run: false }, message: 'Applied' } })
    })
    await page.route(`**/v1/mcp/servers/${id}/start`, route => {
      starts++
      return route.fulfill({ json: running })
    })
    await page.route(`**/v1/mcp/configs/${id}`, route => {
      if (route.request().method() !== 'PUT') return route.fallback()
      saves++
      const body = route.request().postDataJSON()
      expect(body).toMatchObject({ apply: true, start: true, expected_config_digest: config.digest })
      return route.fulfill({ json: { config: { ...activeConfig, manifest: body.manifest }, server: running, message: 'Saved and activated' } })
    })
    // No visit to the service page may be required to discover this running instance.
    await page.goto('/console/#/configs')
    if (entry === 'save') await page.getByRole('row').filter({ hasText: id }).getByRole('button', { name: 'Edit', exact: true }).click()
    const action = entry === 'save' ? page.getByRole('dialog').getByRole('button', { name: 'Save and connect', exact: true })
      : page.getByRole('button', { name: 'Apply and start', exact: true })
    await action.click()
    const confirmation = page.getByRole('alertdialog')
    await expect(confirmation).toBeVisible()
    await expect(confirmation).toContainText(id)
    expect({ applications, starts, saves }).toEqual({ applications: 0, starts: 0, saves: 0 })
    expect(stateReads).toBe(1)
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(confirmation).toHaveCount(0)
    await action.click()
    await confirmation.getByRole('button', { name: entry === 'save' ? 'Save and activate' : 'Apply and restart', exact: true }).click()
    await expect(page.getByText(`${entry === 'save' ? 'Saved and activated' : 'Applied and started'}: ${id}`, { exact: true })).toBeVisible()
    await expect(confirmation).toHaveCount(0)
    expect({ applications, starts, saves }).toEqual(entry === 'save'
      ? { applications: 0, starts: 0, saves: 1 } : { applications: 1, starts: 1, saves: 0 })
    // Each attempt reads current state; only the completed write refreshes the workspace.
    await expect.poll(() => stateReads).toBe(3)
    expect(writes.filter(write => !write.path.endsWith('/validate'))).toEqual([])
  })

  test(`unavailable current service state blocks ${entry} without submitting a write`, async ({ page }) => {
    const writes = await mock(page)
    const activeConfig = { ...config, manifest: { ...manifest, enabled: true } }
    let stateReads = 0
    await page.route('**/v1/mcp/servers', route => { stateReads++; return route.fulfill({ status: 503, json: { detail: 'Runtime temporarily unavailable' } }) })
    await page.route('**/v1/mcp/configs', route => route.request().method() === 'GET'
      ? route.fulfill({ json: { configs: [activeConfig], errors: [] } }) : route.fallback())
    await page.goto('/console/#/configs')
    if (entry === 'save') await page.getByRole('row').filter({ hasText: id }).getByRole('button', { name: 'Edit', exact: true }).click()
    const action = entry === 'save' ? page.getByRole('dialog').getByRole('button', { name: 'Save and connect', exact: true })
      : page.getByRole('button', { name: 'Apply and start', exact: true })
    await action.click()
    await expect(page.getByText(`Could not verify the current service state for ${id}. Try again when it is available. No configuration changes were submitted.`, { exact: true })).toBeVisible()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    await expect(action).toBeEnabled()
    expect(stateReads).toBe(1)
    expect(writes.filter(write => !write.path.endsWith('/validate'))).toEqual([])
  })
}

test('an applied configuration with a failed start keeps its partial-result error and never reapplies automatically', async ({ page }) => {
  const writes = await mock(page)
  let applications = 0, starts = 0
  await page.route(`**/v1/mcp/configs/${id}/apply`, route => {
    applications++
    return route.fulfill({ json: { config, server: { ...server, enabled: true }, message: 'Applied' } })
  })
  await page.route(`**/v1/mcp/servers/${id}/start`, route => {
    starts++
    return route.fulfill({ status: 503, json: { detail: 'Synthetic start result unavailable' } })
  })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'Apply and start', exact: true }).click()
  await expect(page.getByText('Configuration applied, but startup was not confirmed. Inspect the service before retrying: Synthetic start result unavailable', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Apply and start', exact: true })).toBeEnabled()
  expect({ applications, starts }).toEqual({ applications: 1, starts: 1 })
  expect(writes).toEqual([])
})

test('a saved configuration with an unconfirmed connection remains open without resubmitting the save', async ({ page }) => {
  const writes = await mock(page)
  let saves = 0
  await page.route('**/v1/mcp/configs', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    saves++
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { config: { ...config, id: body.manifest.id, manifest: body.manifest },
      server: { ...server, id: body.manifest.id, enabled: true, status: 'failed' }, message: 'Saved; connection unavailable' } })
  })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'New Config', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'New MCP config', exact: true })
  await dialog.getByLabel('MCP Endpoint', { exact: true }).fill('https://synthetic.example.test/mcp')
  await dialog.getByRole('button', { name: 'Save and connect', exact: true }).click()
  await expect(dialog.getByText('Configuration saved, but runtime activation is not confirmed (failed). Inspect the service before retrying.', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Save and connect', exact: true })).toBeEnabled()
  await expect(dialog.getByLabel('MCP Endpoint', { exact: true })).toHaveValue('https://synthetic.example.test/mcp')
  expect(saves).toBe(1)
  expect(writes.filter(write => !write.path.endsWith('/validate'))).toEqual([])
})

for (const latestState of ['running', 'stopped', 'unavailable'] as const) {
  test(`service configuration checks ${latestState} runtime evidence again when saving an open draft`, async ({ page }) => {
    const writes = await mock(page)
    const enabledManifest = { ...manifest, enabled: true }
    const idle = { ...server, enabled: true, restore_blocked_reason: null }
    const running = { ...idle, status: 'running', desired_state: 'running', effective_should_run: true }
    const openedServer = latestState === 'stopped' ? running : idle
    let savingPhase = false, stateReads = 0
    await page.route('**/v1/mcp/servers', route => {
      stateReads++
      if (savingPhase && latestState === 'unavailable') return route.fulfill({ status: 503, json: { detail: 'Runtime temporarily unavailable' } })
      return route.fulfill({ json: { servers: [savingPhase ? latestState === 'running' ? running : idle : openedServer], load_errors: [] } })
    })
    await page.route('**/v1/mcp/servers/*/detail**', route => route.fulfill({ json: { server: openedServer, manifest: enabledManifest, config_digest: config.digest, tools: [] } }))
    const saves: Record<string, unknown>[] = []
    await page.route(`**/v1/mcp/configs/${id}`, route => {
      if (route.request().method() !== 'PUT') return route.fallback()
      const body = route.request().postDataJSON()
      saves.push(body)
      return route.fulfill({ json: { config: { ...config, manifest: body.manifest }, server: running, message: 'Saved and connected' } })
    })
    await page.goto('/console/#/servers')
    await page.getByRole('tab', { name: 'Configuration', exact: true }).click()
    await page.getByRole('button', { name: 'Edit configuration', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: `Edit configuration · ${id}`, exact: true })
    await dialog.getByRole('button', { name: 'JSON', exact: true }).click()
    const draft = { ...enabledManifest, name: 'Pending runtime update' }
    const json = dialog.locator('[data-manifest-json]')
    await json.fill(JSON.stringify(draft))
    const initialReads = stateReads
    savingPhase = true
    const save = dialog.getByRole('button', { name: 'Save and reconnect', exact: true })
    await save.click()
    if (latestState === 'unavailable') {
      await expect(dialog.getByText(`Could not verify the current service state for ${id}. Try again when it is available. No configuration changes were submitted.`, { exact: true })).toBeVisible()
      await expect(save).toBeEnabled()
      expect(JSON.parse(await json.inputValue())).toEqual(draft)
      expect(saves).toHaveLength(0)
      expect(stateReads).toBe(initialReads + 1)
    } else {
      if (latestState === 'running') {
        const confirmation = page.getByRole('alertdialog', { name: `Save and reconnect · ${id}`, exact: true })
        await expect(confirmation).toBeVisible()
        expect(saves).toHaveLength(0)
        expect(stateReads).toBe(initialReads + 1)
        await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
        await expect(confirmation).toHaveCount(0)
        expect(JSON.parse(await json.inputValue())).toEqual(draft)
        await save.click()
        await expect(confirmation).toBeVisible()
        expect(stateReads).toBe(initialReads + 2)
        await confirmation.getByRole('button', { name: 'Save and reconnect', exact: true }).click()
      }
      await expect(dialog).toHaveCount(0)
      expect(saves).toHaveLength(1)
      expect(saves[0]).toMatchObject({ apply: true, start: true, expected_config_digest: config.digest, manifest: draft })
    }
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    expect(writes.filter(write => !write.path.endsWith('/validate'))).toEqual([])
  })
}

test('late disabled-editor response cannot open over a different tab', async ({ page }) => {
  await mock(page)
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/mcp/servers/*/detail?*', async route => {
    if (new URL(route.request().url()).searchParams.get('section') === 'configuration') await gate
    await route.fulfill({ json: { server, manifest, config_digest: config.digest, tools: [] } })
  })
  await page.goto('/console/#/servers')
  await page.getByRole('button', { name: 'Edit and enable', exact: true }).click()
  await page.getByRole('tab', { name: 'Overview', exact: true }).click()
  release!()
  await expect(page.getByRole('tab', { name: 'Overview', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

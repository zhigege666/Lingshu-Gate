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
    test(`new MCP is enabled without starting, ${entry} entry ${locale}`, async ({ page }, testInfo) => {
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
      await expect(dialog.getByRole('switch', { name: zh ? 'Gate 启动时自动启动' : 'Start automatically when Gate starts', exact: true })).not.toBeChecked()
      if (entry === 'servers') await page.screenshot({ path: testInfo.outputPath('new-mcp-enabled-form.png'), animations: 'disabled' })
      await dialog.getByRole('button', { name: 'JSON', exact: true }).click()
      const json = dialog.locator('[data-manifest-json]')
      const draft = JSON.parse(await json.inputValue())
      expect(draft).toMatchObject({ enabled: true, auto_start: false, startup_policy: 'gate_start_v1' })
      await json.fill(JSON.stringify({ ...draft, enabled: false }))
      await dialog.getByRole('button', { name: zh ? '表单' : 'Form', exact: true }).click()
      for (const mode of zh ? ['受管 Stdio', '受管 HTTP', '外部 HTTP'] : ['Managed Stdio', 'Managed HTTP', 'External HTTP']) {
        await dialog.getByRole('radio', { name: mode, exact: true }).check()
        await expect(dialog.getByRole('switch', { name: zh ? '启用服务' : 'Enable service', exact: true })).not.toBeChecked()
        await expect(dialog.getByRole('switch', { name: zh ? 'Gate 启动时自动启动' : 'Start automatically when Gate starts', exact: true })).not.toBeChecked()
      }
      expect(writes).toEqual([])
    })
  }

  test(`disabled hint opens the saved draft without enabling or mutating ${locale}`, async ({ page }, testInfo) => {
    const writes = await mock(page, locale)
    await page.goto('/console/#/servers')
    const action = page.getByRole('button', { name: zh ? '编辑并启用' : 'Edit and enable', exact: true })
    await expect(action).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('disabled-edit-entry.png'), animations: 'disabled' })
    await action.click()
    const dialog = page.getByRole('dialog', { name: `${zh ? '修改配置' : 'Edit configuration'} · ${id}`, exact: true })
    await expect(dialog).toHaveCSS('opacity', '1')
    await expect(dialog.getByRole('switch', { name: zh ? '启用服务' : 'Enable service', exact: true })).not.toBeChecked()
    await expect(dialog.getByRole('radio', { name: zh ? '仅保存（未生效）' : 'Save only (not applied)', exact: true })).toBeChecked()
    await dialog.getByRole('switch', { name: zh ? '启用服务' : 'Enable service', exact: true }).click()
    await dialog.getByRole('button', { name: zh ? '保存配置' : 'Save configuration', exact: true }).click()
    const confirmation = page.getByRole('alertdialog')
    await expect(confirmation).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('enable-save-confirmation.png'), animations: 'disabled' })
    await confirmation.getByRole('button', { name: zh ? '取消' : 'Cancel', exact: true }).click()
    expect(writes.filter(w => !w.path.endsWith('/validate'))).toEqual([])
    await expect(dialog).toBeVisible()
  })
}

test('new enabled MCP save is disk-only and never sends apply/start or trust writes', async ({ page }) => {
  const writes = await mock(page)
  let saved: Record<string, unknown> | undefined
  await page.route('**/v1/mcp/configs', route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON()
    expect(body).toMatchObject({ apply: false, start: false, manifest: { enabled: true, auto_start: false, startup_policy: 'gate_start_v1' } })
    saved = body.manifest
    return route.fulfill({ json: { config: { ...config, id: body.manifest.id, manifest: saved }, server: null, message: 'Saved only' } })
  })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'New Config', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'New MCP config', exact: true })
  await dialog.getByLabel('MCP Endpoint', { exact: true }).fill('https://synthetic.example.test/mcp')
  await dialog.getByRole('button', { name: 'Save Config', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(saved?.enabled).toBe(true)
  expect(writes.filter(w => !w.path.endsWith('/validate'))).toEqual([])
})

for (const [status, launch, enabled] of [['external', 'external', true], ['loaded', 'managed_process', true], ['external', 'external', false], ['stopped', 'managed_process', false]] as const) {
  test(`apply without start recognizes ${status}/${launch}/enabled=${enabled}`, async ({ page }) => {
    await mock(page)
    let calls = 0
    await page.route(`**/v1/mcp/configs/${id}/apply`, route => {
      calls++
      return route.fulfill({ json: { config, server: { ...server, status, launch_type: launch, enabled }, message: 'applied' } })
    })
    await page.goto('/console/#/configs')
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(page.getByText(`Applied; ${enabled ? 'not started' : 'service remains disabled'}: ${id}`, { exact: true })).toBeVisible()
    await expect(page.getByText('Configuration application state is unknown. Inspect the service.', { exact: true })).toHaveCount(0)
    expect(calls).toBe(1)
  })
}

test('unknown apply response stays an error and does not auto-retry', async ({ page }) => {
  await mock(page)
  let calls = 0
  await page.route(`**/v1/mcp/configs/${id}/apply`, route => { calls++; return route.fulfill({ json: { config, server: null, message: 'unknown' } }) })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByText('Configuration application state is unknown. Inspect the service.', { exact: true })).toBeVisible()
  expect(calls).toBe(1)
})

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

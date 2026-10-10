import { test, expect, type Locator, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

// Actual Console renderer with isolated synthetic API data; no remote service is changed.
const phase = process.env.GATE_UI_LAYOUT_PHASE || 'after'
const external = {
  id: 'synthetic-playwright-mcp', name: 'Synthetic Playwright MCP', enabled: true,
  launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: '[REDACTED]' },
  timeout_seconds: 120, auto_start: false,
}
const viewports = [[2560, 1080], [1920, 1080], [2560, 1440], [1600, 900]]

async function openEditor(page: Page, locale = 'zh-CN', value: Record<string, unknown> = external) {
  await login(page)
  await page.addInitScript(locale => {
    localStorage.setItem('lingshu-gate-console-locale', locale)
    localStorage.setItem('lingshu-gate-console-theme', 'light')
  }, locale)
  await page.route('**/v1/mcp/configs', route => route.fulfill({ json: {
    configs: [{ id: external.id, path: '/synthetic/mcp.d/playwright.json', manifest: value, config_digest: 'a'.repeat(64) }], errors: [],
  } }))
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: {
    ok: true, can_apply: true, manifest_id: external.id,
    summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [],
  } }))
  await page.goto('/console/#/configs')
  const trigger = page.getByRole('button', { name: locale === 'zh-CN' ? '编辑' : 'Edit', exact: true })
  await trigger.click()
  return page.getByRole('dialog', { name: `${locale === 'zh-CN' ? '编辑' : 'Edit'} · ${external.id}`, exact: true })
}

async function geometry(dialog: Locator) {
  return dialog.evaluate(element => {
    const bounds = (e: Element) => {
      const r = e.getBoundingClientRect()
      return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
    }
    const fields = Array.from(element.querySelectorAll('.manifest-field')).filter(e => e.getBoundingClientRect().height > 0 && !e.closest('details:not([open])'))
    const rows = fields.map(field => {
      const label = field.querySelector(':scope > label') as HTMLElement
      const control = field.querySelector(':scope > .manifest-field-control') as HTMLElement
      const pair = field.parentElement?.classList.contains('manifest-form-pair')
      const index = pair ? Array.from(field.parentElement!.children).indexOf(field) : 0
      const columns = pair ? getComputedStyle(field.parentElement!).gridTemplateColumns.trim().split(/\s+/).length : 1
      const switchControl = control.querySelector('.manifest-switch')
      const switchHelp = control.querySelector('[id$="-help"]')
      return {
        label: label.textContent, label_bounds: bounds(label), control_bounds: bounds(control),
        label_overflow: label.scrollWidth > label.clientWidth + 1,
        first_column: !pair || index % columns === 0,
        in_section: Boolean(field.closest('.manifest-section')),
        grid_columns: getComputedStyle(field).gridTemplateColumns,
        switch_bounds: switchControl ? bounds(switchControl) : null,
        switch_help_bounds: switchHelp ? bounds(switchHelp) : null,
      }
    })
    return { dialog: bounds(element), viewport: { width: innerWidth, height: innerHeight }, rows,
      horizontal_overflow: element.scrollWidth > element.clientWidth + 1 }
  })
}

async function capture(page: Page, dialog: Locator, name: string, testInfo: { outputPath: (name: string) => string }) {
  const directory = process.env.GATE_UI_LAYOUT_EVIDENCE_ROOT
  const png = directory ? join(directory, `${phase}-${name}.png`) : testInfo.outputPath(`${name}.png`)
  if (directory) mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: png, animations: 'disabled' })
  const metrics = await geometry(dialog)
  writeFileSync(png.replace(/\.png$/, '.json'), JSON.stringify({ phase, synthetic_data: true, ...metrics }, null, 2) + '\n')
  expect(metrics.horizontal_overflow).toBe(false)
  if (phase === 'after') {
    const first = metrics.rows.filter(r => r.first_column && !r.in_section)
    expect(Math.max(...first.map(r => r.control_bounds.x)) - Math.min(...first.map(r => r.control_bounds.x))).toBeLessThanOrEqual(1.25)
    expect(metrics.rows.filter(r => r.label_overflow)).toEqual([])
    for (const row of metrics.rows) {
      if (row.switch_bounds && row.switch_help_bounds) {
        expect(row.switch_help_bounds.y - row.switch_bounds.bottom).toBeGreaterThanOrEqual(4)
        expect(Math.abs(row.switch_help_bounds.x - row.switch_bounds.x)).toBeLessThanOrEqual(1.25)
        expect(row.switch_help_bounds.width).toBeGreaterThanOrEqual(200)
      }
    }
  }
}

for (const [width, height] of viewports) {
  test(`service edit external HTTP layout ${width}x${height} @full @visual`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    const editor = await openEditor(page)
    await expectInViewportAndUnobscured(editor.getByRole('button', { name: '保存配置', exact: true }))
    await capture(page, editor, `external-zh-${width}x${height}`, testInfo)
  })
}

test('service edit modes, long help/errors and keyboard at 1600x900 @full @visual', async ({ page }, testInfo) => {
  test.skip(phase === 'before', 'Baseline captures the original external HTTP state at the four desktop sizes.')
  await page.setViewportSize({ width: 1600, height: 900 })
  const editor = await openEditor(page)
  await editor.getByRole('radio', { name: '受管 Stdio', exact: true }).check()
  await capture(page, editor, 'managed-stdio-zh-1600x900', testInfo)
  await editor.getByRole('radio', { name: '受管 HTTP', exact: true }).check()
  await capture(page, editor, 'managed-http-zh-1600x900', testInfo)
  await editor.getByRole('radio', { name: '外部 HTTP', exact: true }).check()
  await editor.getByRole('button', { name: '替换地址', exact: true }).click()
  const endpoint = editor.getByLabel('MCP 地址', { exact: true })
  const longUrl = 'https://synthetic.example.test/mcp?description=' + 'synthetic-long-value-'.repeat(30)
  await endpoint.fill(longUrl)
  await editor.getByText('高级配置', { exact: true }).click()
  await expect(editor.getByText('权限声明', { exact: true })).toBeVisible()
  await expectInViewportAndUnobscured(editor.getByRole('button', { name: '保存配置', exact: true }))
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: {
    ok: false, can_apply: false, manifest_id: external.id,
    summary: { errors: 1, warnings: 0, info: 0, ok: 0 },
    checks: [{ name: 'transport.endpoint', severity: 'error',
      message: '合成错误：服务地址策略不允许此目标，请检查完整 URL 和协议。'.repeat(8), metadata: {} }],
  } }))
  await editor.getByRole('button', { name: '校验配置', exact: true }).click()
  await editor.locator('.manifest-validation button').first().click()
  await expect(endpoint).toBeFocused()
  await capture(page, editor, 'long-error-advanced-focused-zh-1600x900', testInfo)
  await endpoint.fill('https://synthetic.example.test/recovered/mcp')
  const enabled = editor.getByRole('switch', { name: '启用服务', exact: true })
  await enabled.focus()
  await page.keyboard.press('Space')
  await expect(enabled).not.toBeChecked()
  await editor.getByRole('radio', { name: '外部 HTTP', exact: true }).focus()
  await page.keyboard.press('ArrowRight')
  await expect(editor.getByRole('radio', { name: '受管 HTTP', exact: true })).toBeChecked()
  await editor.getByRole('radio', { name: '外部 HTTP', exact: true }).check()
  const cancel = editor.getByRole('button', { name: '取消', exact: true })
  await cancel.focus()
  await page.keyboard.press('Tab')
  await expect(editor.getByRole('button', { name: '保存配置', exact: true })).toBeFocused()
  await expectInViewportAndUnobscured(cancel)
  await cancel.click()
  const confirmation = page.getByRole('alertdialog', { name: '放弃未保存的配置？', exact: true })
  await confirmation.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(page.getByRole('button', { name: '编辑', exact: true })).toBeFocused()
})

for (const [width, height] of viewports) {
  test(`service edit English startup labels and help ${width}x${height} @full @visual`, async ({ page }, testInfo) => {
    test.skip(phase === 'before', 'Additional language coverage follows the layout change.')
    await page.setViewportSize({ width, height })
    const editor = await openEditor(page, 'en-US')
    await capture(page, editor, `external-en-${width}x${height}`, testInfo)
    await expectInViewportAndUnobscured(editor.getByRole('button', { name: 'Save Config', exact: true }))
  })
}

test('service config dirty discard returns keyboard focus to its edit trigger @full', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const editor = await openEditor(page)
  await editor.getByLabel('名称', { exact: true }).fill('Synthetic edited name')
  await editor.getByRole('button', { name: '取消', exact: true }).click()
  const confirmation = page.getByRole('alertdialog', { name: '放弃未保存的配置？', exact: true })
  await confirmation.getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(editor).not.toBeVisible()
  await expect(page.getByRole('button', { name: '编辑', exact: true })).toBeFocused()
})

test('new service config discard returns focus to New Config @full', async ({ page }) => {
  const initial = await openEditor(page)
  await initial.getByRole('button', { name: '取消', exact: true }).click()
  const trigger = page.getByRole('button', { name: '新建配置', exact: true })
  await trigger.click()
  const editor = page.getByRole('dialog', { name: '新建 MCP 配置', exact: true })
  await editor.getByLabel('名称', { exact: true }).fill('Synthetic new draft')
  await editor.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('alertdialog', { name: '放弃未保存的配置？', exact: true }).getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(editor).not.toBeVisible()
  await expect(trigger).toBeFocused()
})

test('service config Keep editing preserves its draft and editor focus @full', async ({ page }) => {
  const editor = await openEditor(page)
  const name = editor.getByLabel('名称', { exact: true })
  await name.fill('Synthetic retained draft')
  const cancel = editor.getByRole('button', { name: '取消', exact: true })
  await cancel.click()
  await page.getByRole('alertdialog', { name: '放弃未保存的配置？', exact: true }).getByRole('button', { name: '继续编辑', exact: true }).click()
  await expect(editor).toBeVisible()
  await expect(name).toHaveValue('Synthetic retained draft')
  await expect(cancel).toBeFocused()
})

for (const invalid of ['removed', 'disabled'] as const) {
  test(`service config trigger ${invalid} returns focus to the available New Config action @full`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const editor = await openEditor(page)
    await page.getByRole('button', { name: '编辑', exact: true, includeHidden: true }).evaluate((element, kind) => {
      if (kind === 'removed') element.remove()
      else (element as HTMLButtonElement).disabled = true
    }, invalid)
    await editor.getByRole('button', { name: '取消', exact: true }).click()
    await expect(editor).not.toBeVisible()
    await expect(page.getByRole('button', { name: '新建配置', exact: true })).toBeFocused()
    expect(errors).toEqual([])
  })
}

async function openDeliveryEditor(page: Page, locale: 'zh-CN' | 'en-US') {
  await login(page)
  await page.addInitScript(locale => {
    localStorage.setItem('lingshu-gate-console-locale', locale)
    localStorage.setItem('lingshu-gate-console-theme', 'light')
  }, locale)
  const time = '2026-01-01T00:00:00Z'
  const upload = { id: 'synthetic-layout-upload', filename: 'synthetic-layout.zip', status: 'uploaded', detected_runtime: 'python', root_dir: '/synthetic/layout', analysis: {}, created_at: time, updated_at: time }
  const build = { id: 'synthetic-layout-build', upload_id: upload.id, status: 'success', runtime: 'python', source_dir: '/synthetic/layout', artifact_dir: '/synthetic/layout-artifact', commands: [], logs: [], manifest: { ...external, name: 'Synthetic delivery', enabled: false, transport: { type: 'streamable_http', endpoint: 'https://synthetic.example.test/delivery/mcp' } }, created_at: time, updated_at: time }
  let draft = { upload_id: upload.id, revision: 1, manifest_patch: {}, server_id: null, build_id: build.id, deployment_id: null, start: false, overwrite: false, project_root: '.', runtime_override: null }
  const writes: Array<{ path: string; method: string; body: Record<string, unknown> }> = []
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    if (method !== 'GET') {
      writes.push({ path, method, body: request.postDataJSON() })
      if (method === 'PUT' && path === `/v1/delivery-drafts/${upload.id}`) {
        draft = { ...draft, ...request.postDataJSON(), revision: draft.revision + 1 }
        return route.fulfill({ json: draft })
      }
      return route.fulfill({ status: 400, json: { detail: 'Unexpected synthetic layout fixture write' } })
    }
    if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads: [upload] } })
    if (path === '/v1/builds') return route.fulfill({ json: { builds: [build] } })
    if (path === '/v1/deployments') return route.fulfill({ json: { deployments: [] } })
    if (path === `/v1/builds/${build.id}/logs`) return route.fulfill({ json: { logs: [] } })
    if (path === `/v1/delivery-drafts/${upload.id}`) return route.fulfill({ json: draft })
    return route.continue()
  })
  await page.goto(`/console/#/builds/${build.id}`)
  await page.getByRole('button', { name: locale === 'zh-CN' ? '编辑 · Manifest' : 'Edit · Manifest', exact: true }).click()
  return { editor: page.getByRole('dialog', { name: locale === 'zh-CN' ? '交付运行配置' : 'Delivery runtime configuration', exact: true }), writes, upload }
}

for (const [width, height] of viewports) for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`delivery configuration shared layout ${width}x${height} ${locale} @full @visual`, async ({ page }, testInfo) => {
    test.skip(phase === 'before', 'Additional consumer coverage follows independent review.')
    await page.setViewportSize({ width, height })
    const { editor, writes, upload } = await openDeliveryEditor(page, locale)
    const zh = locale === 'zh-CN'
    const save = editor.getByRole('button', { name: zh ? '保存交付草稿' : 'Save delivery draft', exact: true })
    await expectInViewportAndUnobscured(save)
    await capture(page, editor, `delivery-external-${zh ? 'zh' : 'en'}-${width}x${height}`, testInfo)
    if (width === 1600) {
      for (const mode of ['stdio', 'http'] as const) {
        await editor.getByRole('radio', { name: zh ? (mode === 'stdio' ? '受管 Stdio' : '受管 HTTP') : (mode === 'stdio' ? 'Managed Stdio' : 'Managed HTTP'), exact: true }).check()
        await expectInViewportAndUnobscured(save)
        await capture(page, editor, `delivery-managed-${mode}-${zh ? 'zh' : 'en'}-${width}x${height}`, testInfo)
      }
      await editor.getByRole('radio', { name: zh ? '外部 HTTP' : 'External HTTP', exact: true }).check()
    }
    await editor.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Synthetic edited delivery')
    await editor.getByRole('button', { name: zh ? '取消' : 'Cancel', exact: true }).click()
    await page.getByRole('alertdialog', { name: zh ? '放弃尚未保存的修改？' : 'Discard unsaved changes?', exact: true }).getByRole('button', { name: zh ? '继续编辑' : 'Continue editing', exact: true }).click()
    await expect(editor.getByLabel(zh ? '名称' : 'Name', { exact: true })).toHaveValue('Synthetic edited delivery')
    expect(writes).toEqual([])
    await expectInViewportAndUnobscured(save)
    await save.click()
    await expect(editor).not.toBeVisible()
    expect(writes).toHaveLength(1)
    expect(writes[0]).toMatchObject({ path: `/v1/delivery-drafts/${upload.id}`, method: 'PUT', body: { expected_revision: 1, start: false, overwrite: false, manifest_patch: { name: 'Synthetic edited delivery' } } })
  })
}

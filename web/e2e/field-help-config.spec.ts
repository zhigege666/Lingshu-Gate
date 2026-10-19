import { expect, test, type Locator, type Page } from '@playwright/test'
import { expectInViewportAndUnobscured, login } from './helpers'
import { servers } from './synthetic-data'

// The same four desktop sizes used by config-interaction and ui-standards.
const viewports = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
const locales = ['zh-CN', 'en-US'] as const
type Locale = typeof locales[number]
const serverId = 'synthetic-field-help-container'
const digest = 'd'.repeat(64)

const copy = {
  'zh-CN': {
    configuration: '配置', edit: '修改配置', name: '名称', form: '表单', editorMode: '编辑模式',
    runtime: '运行方式', container: '容器 Stdio', image: '容器镜像', args: '启动参数', env: '环境变量',
    command: '启动命令', cwd: '工作目录', enabled: '启用服务', startup: 'Gate 启动时自动启动',
    legacy: '旧策略 · 恢复上次状态', save: '保存配置', cancel: '取消', saveOnly: '仅保存（未生效）',
    allowlist: '退出码允许列表', blocklist: '退出码阻止列表', remove: '移除', validate: '校验配置',
    passed: '检查通过', jsonCorrection: 'JSON 需要修正', timeout: '超时秒数', initialDelay: '初始延迟 (s)',
  },
  'en-US': {
    configuration: 'Configuration', edit: 'Edit configuration', name: 'Name', form: 'Form', editorMode: 'Editor mode',
    runtime: 'Runtime Mode', container: 'Container Stdio', image: 'Container image', args: 'Arguments', env: 'Environment Variables',
    command: 'Command', cwd: 'Working Directory', enabled: 'Enable service', startup: 'Start automatically when Gate starts',
    legacy: 'Legacy policy · Restore last state', save: 'Save configuration', cancel: 'Cancel', saveOnly: 'Save only (not applied)',
    allowlist: 'Exit Code Allowlist', blocklist: 'Exit Code Blocklist', remove: 'Remove', validate: 'Validate configuration',
    passed: 'Check passed', jsonCorrection: 'JSON needs correction', timeout: 'Timeout Seconds', initialDelay: 'Initial Delay (s)',
  },
} as const

function containerManifest() {
  return {
    id: serverId, name: 'Synthetic container Stdio', enabled: true, auto_start: false, timeout_seconds: 30,
    launch: {
      type: 'managed_container', image: `registry.example.test/fixtures/synthetic-mcp@sha256:${'a'.repeat(64)}`,
      args: ['--label', ' original value ', '', '--stdio'],
      command: null, cwd: null, package: null,
      environment: { SYNTHETIC_EMPTY: '', SYNTHETIC_PADDED: ' value ', SYNTHETIC_FLAG: 'false' },
      mounts: [{ source: '/srv/synthetic-field-help/input', target: '/workspace/input', read_only: true }],
      resources: { memory: '256m', cpus: 0.5, pids_limit: 64 },
    },
    transport: { type: 'stdio' },
    restart_policy: {
      enabled: false, max_attempts: 0, delay_seconds: 0, backoff_multiplier: 1, max_delay_seconds: 0,
      restart_on_exit: false, reset_after_seconds: 0, exit_code_allowlist: [0], exit_code_blocklist: [],
      health_check: { enabled: false, method: 'tools_list', interval_seconds: 30, timeout_seconds: 10, failure_threshold: 3 },
    },
    permissions: { default: 'read', metadata: { review_only: true, empty: '' } },
    analysis: { metadata: { enabled: false, count: 0, value: null, empty: '', nested: [false, 0, null, ''] } },
    roots: [], manifest_path: null,
  }
}

function processManifest() {
  const original = containerManifest()
  return {
    ...original,
    name: 'Synthetic exit-code draft',
    launch: { type: 'managed_process', command: 'synthetic-mcp-server', args: ['--stdio'], env: { SYNTHETIC_EMPTY: '' } },
    restart_policy: { ...original.restart_policy, enabled: true, restart_on_exit: true, exit_code_allowlist: [17, 23], exit_code_blocklist: [1, 7] },
  }
}

type ConfigWrite = { manifest: Record<string, unknown>; apply: boolean; start: boolean; expected_config_digest: string; user_credential_values: Record<string, string> }
type ValidationRequest = { manifest: Record<string, unknown>; apply: boolean; start: boolean }

async function openEditor(page: Page, locale: Locale, manifest: Record<string, unknown>, viewport = viewports[0], credentials: { id: string }[] = []) {
  await login(page)
  await page.setViewportSize(viewport)
  await page.addInitScript(value => {
    localStorage.setItem('lingshu-gate-console-locale', value)
    localStorage.setItem('lingshu-gate-console-theme', 'light')
  }, locale)
  let saved = structuredClone(manifest)
  const writes: ConfigWrite[] = [], validations: ValidationRequest[] = [], unexpected: string[] = []
  const fixtureServer = () => ({ ...servers[0], id: serverId, name: String(saved.name), enabled: saved.enabled,
    launch_type: (saved.launch as { type: string }).type, transport_type: (saved.transport as { type: string }).type, status: 'stopped', tool_count: 0 })

  // Every mutation after login is intercepted. Only synthetic validation and
  // save-only responses are fulfilled; no apply/start/container call reaches the fixture backend.
  await page.route('**/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    if (method === 'POST' && path === `/v1/mcp/configs/${serverId}/validate`) {
      validations.push(request.postDataJSON() as ValidationRequest)
      return route.fulfill({ json: { ok: true, can_apply: true, manifest_id: serverId, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] } })
    }
    if (method === 'PUT' && path === `/v1/mcp/configs/${serverId}`) {
      const body = request.postDataJSON() as ConfigWrite
      if (body.apply !== false || body.start !== false) {
        unexpected.push(`${method} ${path} apply/start`)
        return route.fulfill({ status: 400, json: { detail: 'This synthetic fixture accepts save-only drafts.' } })
      }
      writes.push(body)
      saved = structuredClone(body.manifest)
      return route.fulfill({ json: { config: { id: serverId, path: '/synthetic/mcp.d/field-help.json', format: 'json', manifest: saved }, server: null, message: 'Synthetic draft saved without applying' } })
    }
    if (method !== 'GET') {
      unexpected.push(`${method} ${path}`)
      return route.fulfill({ status: 400, json: { detail: 'Unexpected synthetic field-help mutation' } })
    }
    if (path === '/v1/mcp/servers') return route.fulfill({ json: { servers: [fixtureServer()], load_errors: [] } })
    if (path === `/v1/mcp/servers/${serverId}/detail`) return route.fulfill({ json: { server: fixtureServer(), manifest: saved, config_digest: digest, tools: [] } })
    if (path === '/v1/mcp/configs') return route.fulfill({ json: { configs: [{ id: serverId, manifest: saved, config_digest: digest }], errors: [] } })
    if (path === '/v1/credentials') return route.fulfill({ json: credentials })
    return route.continue()
  })
  await page.goto('/console/#/servers')
  const c = copy[locale]
  await page.getByRole('tab', { name: c.configuration, exact: true }).click()
  await page.getByRole('button', { name: c.edit, exact: true }).click()
  const editor = page.getByRole('dialog', { name: `${c.edit} · ${serverId}`, exact: true })
  await expect(editor).toBeVisible()
  return { editor, writes, validations, unexpected }
}

function help(editor: Locator, locale: Locale, label: string) {
  return editor.getByRole('button', { name: locale === 'zh-CN' ? `${label}说明` : `${label} help`, exact: true })
}

async function readJson(editor: Locator, locale: Locale): Promise<Record<string, unknown>> {
  await editor.getByRole('group', { name: copy[locale].editorMode, exact: true }).getByRole('button', { name: 'JSON', exact: true }).click()
  return JSON.parse(await editor.locator('[data-manifest-json]').inputValue())
}

async function showForm(editor: Locator, locale: Locale) {
  await editor.getByRole('group', { name: copy[locale].editorMode, exact: true }).getByRole('button', { name: copy[locale].form, exact: true }).click()
}

async function expectContainerFields(editor: Locator, locale: Locale, original: ReturnType<typeof containerManifest>) {
  const c = copy[locale]
  await expect(editor.getByRole('radio', { name: c.container, exact: true })).toBeChecked()
  await expect(editor.locator('[data-manifest-path="/launch/type"]').getByRole('radio')).toHaveCount(4)
  await expect(editor.getByLabel(c.image, { exact: true })).toHaveValue(original.launch.image)
  await expect(editor.getByLabel(c.command, { exact: true })).toHaveCount(0)
  await expect(editor.getByLabel(c.cwd, { exact: true })).toHaveCount(0)
  await expect(editor.getByRole('textbox', { name: `${c.args} 3`, exact: true })).toHaveValue('')
  const environment = editor.getByRole('group', { name: c.env, exact: true })
  await expect(environment.getByLabel('SYNTHETIC_EMPTY', { exact: true })).toHaveValue('')
  await expect(environment.getByLabel('SYNTHETIC_PADDED', { exact: true })).toHaveValue(' value ')
  await expect(environment.getByLabel('SYNTHETIC_FLAG', { exact: true })).toHaveValue('false')
}

async function saveOnly(page: Page, fixture: Awaited<ReturnType<typeof openEditor>>, locale: Locale, expectedManifest: Record<string, unknown>) {
  const c = copy[locale]
  await fixture.editor.getByRole('radio', { name: c.saveOnly, exact: true }).check()
  const save = fixture.editor.getByRole('button', { name: c.save, exact: true })
  await expect(save).toBeEnabled()
  await expectInViewportAndUnobscured(save)
  await save.click()
  await page.getByRole('alertdialog').getByRole('button', { name: c.saveOnly, exact: true }).click()
  await expect(fixture.editor).toHaveCount(0)
  expect(fixture.validations).toEqual([{ manifest: expectedManifest, apply: false, start: false }])
  expect(fixture.writes).toEqual([{ manifest: expectedManifest, apply: false, start: false, expected_config_digest: digest, user_credential_values: {} }])
  expect(fixture.unexpected).toEqual([])
}

for (const locale of locales) {
  test(`HTTP credential references require an explicit header key and retain reserved-header diagnostics ${locale} @full`, async ({ page }) => {
    const c = copy[locale], zh = locale === 'zh-CN', label = zh ? 'HTTP 请求头' : 'HTTP headers'
    const original = {
      id: serverId, name: 'Synthetic HTTP header references', enabled: true, auto_start: false, timeout_seconds: 30,
      launch: { type: 'external' },
      transport: { type: 'streamable_http', endpoint: 'https://synthetic.example.test/mcp', headers: { Accept: 'application/x-synthetic', 'X-Synthetic-Empty': '' } },
      analysis: { nested: [false, 0, null, ''] },
    }
    const fixture = await openEditor(page, locale, original, viewports[0], [{ id: 'synthetic-header-token' }])
    const { editor } = fixture
    const field = editor.locator('.manifest-field').filter({ has: page.getByRole('group', { name: label, exact: true }) })
    const map = field.getByRole('group', { name: label, exact: true })
    const warning = field.getByRole('status')
    await expect(warning).toContainText('Accept')
    await expect(warning).toContainText(zh ? '配置值不会生效' : 'configured values are not used')
    expect(await warning.evaluate(element => element.closest('[data-field-help-content]') === null)).toBe(true)
    await help(editor, locale, label).click()
    await expect(editor.locator('[data-field-help-content]')).toContainText('Authorization')
    await expect(editor.locator('[data-field-help-content]')).toContainText('***')
    await page.keyboard.press('Escape')
    await map.getByRole('button', { name: 'synthetic-header-token', exact: true }).click()
    const key = map.getByRole('textbox', { name: `${label} ${zh ? '新键名' : 'new key'}`, exact: true })
    const value = map.getByRole('textbox', { name: `${label} ${zh ? '新值' : 'new value'}`, exact: true })
    await expect(key).toHaveValue('')
    await expect(value).toHaveValue('${credential:synthetic-header-token}')
    await expect(editor.getByRole('button', { name: c.save, exact: true })).toBeDisabled()
    const add = map.getByRole('button', { name: `${zh ? '添加' : 'Add'} ${label}`, exact: true })
    await add.click()
    await expect(map.getByRole('alert')).toBeVisible()
    await key.fill('Authorization')
    await add.click()
    await expect(map.getByLabel('Authorization', { exact: true })).toHaveValue('${credential:synthetic-header-token}')
    await expect(key).toHaveValue('')
    await expect(value).toHaveValue('')
    const expected = { ...original, transport: { ...original.transport, headers: { ...original.transport.headers, Authorization: '${credential:synthetic-header-token}' } } }
    expect(await readJson(editor, locale)).toEqual(expected)
    await showForm(editor, locale)
    await expect(warning).toBeVisible()
    await saveOnly(page, fixture, locale, expected)
  })

  test(`container form and field help preserve the exact legacy Manifest ${locale} @full`, async ({ page }) => {
    const original = containerManifest(), c = copy[locale]
    const fixture = await openEditor(page, locale, original)
    const { editor } = fixture
    await expectContainerFields(editor, locale, original)
    const legacy = editor.getByText(c.legacy, { exact: true })
    await expect(legacy).toBeVisible()
    expect(await legacy.evaluate(element => element.closest('[data-field-help-content]') === null)).toBe(true)

    const nextName = `Synthetic renamed container ${locale}`, nextArgument = ' updated value with spaces '
    await editor.getByLabel(c.name, { exact: true }).fill(nextName)
    await editor.getByRole('textbox', { name: `${c.args} 2`, exact: true }).fill(nextArgument)
    const startup = editor.getByRole('switch', { name: c.startup, exact: true })
    const startupHelp = help(editor, locale, c.startup), content = editor.locator('[data-field-help-content]')
    await expect(startup).not.toBeChecked()
    await startupHelp.hover()
    // Exceed the underlying popover's delayed hover interval: help is click-only.
    await page.waitForTimeout(350)
    await expect(startupHelp).toHaveAttribute('aria-expanded', 'false')
    await expect(content).toHaveCount(0)
    await startupHelp.click()
    await expect(content).toBeVisible()
    await expect(content).not.toHaveText('')
    await expect(legacy).toBeVisible()
    await expect(startup).not.toBeChecked()
    await page.keyboard.press('Escape')
    await expect(content).toHaveCount(0)
    await expect(editor).toBeVisible()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    await expect(startupHelp).toBeFocused()
    const renamed = { ...original, name: nextName, launch: { ...original.launch, args: ['--label', nextArgument, '', '--stdio'] } }
    const renamedJson = await readJson(editor, locale)
    expect(renamedJson).toEqual(renamed)
    expect(renamedJson).not.toHaveProperty('startup_policy')

    await showForm(editor, locale)
    await editor.getByRole('group', { name: c.env, exact: true }).getByLabel('SYNTHETIC_FLAG', { exact: true }).fill('0')
    const expected = { ...renamed, launch: { ...renamed.launch, environment: { ...renamed.launch.environment, SYNTHETIC_FLAG: '0' } } }
    const finalJson = await readJson(editor, locale)
    expect(finalJson).toEqual(expected)
    expect(finalJson.launch).not.toHaveProperty('env')
    expect(finalJson).not.toHaveProperty('startup_policy')
    await showForm(editor, locale)
    await expect(legacy).toBeVisible()
    await saveOnly(page, fixture, locale, expected)
  })

  for (const recovery of ['zero', 'remove'] as const) {
    test(`cleared numeric exit code stays blank until ${recovery === 'zero' ? 'explicit zero' : 'row removal'} ${locale} @full`, async ({ page }) => {
      const original = processManifest(), c = copy[locale]
      const fixture = await openEditor(page, locale, original)
      const { editor } = fixture
      const key = recovery === 'zero' ? 'exit_code_allowlist' : 'exit_code_blocklist'
      const label = recovery === 'zero' ? c.allowlist : c.blocklist
      const field = editor.locator('.manifest-field').filter({ has: page.locator(`[data-manifest-path="/restart_policy/${key}"]`) })
      const code = field.getByLabel(`${label} 1`, { exact: true })
      const save = editor.getByRole('button', { name: c.save, exact: true })
      await expect(code).toHaveValue(String(original.restart_policy[key][0]))
      await code.fill('')
      await code.press('Tab')
      await expect(code).toHaveValue('')
      await expect(code).toHaveAttribute('aria-invalid', 'true')
      await expect(field.getByRole('alert')).toBeVisible()
      await expect(field.getByRole('alert')).not.toHaveText('')
      await expect(code).toHaveAccessibleDescription(await field.getByRole('alert').innerText())
      await expect(save).toBeDisabled()
      expect(fixture.validations).toEqual([])
      expect(fixture.writes).toEqual([])
      expect(fixture.unexpected).toEqual([])

      const nextCodes = recovery === 'zero' ? [0, ...original.restart_policy[key].slice(1)] : original.restart_policy[key].slice(1)
      if (recovery === 'zero') {
        await code.fill('0')
        await code.press('Tab')
        await expect(code).toHaveValue('0')
      } else {
        await field.getByRole('button', { name: `${c.remove} ${label} 1`, exact: true }).click()
        await expect(field.locator('input')).toHaveCount(nextCodes.length)
        await expect(field.getByLabel(`${label} 1`, { exact: true })).toHaveValue(String(nextCodes[0]))
      }
      await expect(field.getByRole('alert')).toHaveCount(0)
      await expect(save).toBeEnabled()
      const expected = { ...original, restart_policy: { ...original.restart_policy, [key]: nextCodes } }
      expect(await readJson(editor, locale)).toEqual(expected)
      await showForm(editor, locale)
      await saveOnly(page, fixture, locale, expected)
    })
  }

  test(`pending exit codes invalidate prior checks and follow their row after deletion ${locale} @full`, async ({ page }) => {
    const base = processManifest(), c = copy[locale]
    const original = { ...base, restart_policy: { ...base.restart_policy, exit_code_allowlist: [17, 23, 31] } }
    const fixture = await openEditor(page, locale, original)
    const { editor } = fixture
    const field = editor.locator('.manifest-field').filter({ has: page.locator('[data-manifest-path="/restart_policy/exit_code_allowlist"]') })
    await editor.getByRole('button', { name: c.validate, exact: true }).click()
    await expect(editor.getByText(c.passed, { exact: true })).toBeVisible()
    const second = field.getByLabel(`${c.allowlist} 2`, { exact: true })
    await second.fill('')
    await second.press('Tab')
    await expect(second).toHaveValue('')
    await expect(editor.getByText(c.passed, { exact: true })).toHaveCount(0)
    await expect(field.getByRole('alert')).toBeVisible()
    await expect(editor.getByRole('button', { name: c.save, exact: true })).toBeDisabled()
    expect(fixture.validations).toEqual([{ manifest: original, apply: false, start: false }])

    await field.getByRole('button', { name: `${c.remove} ${c.allowlist} 1`, exact: true }).click()
    await expect(field.locator('input')).toHaveCount(2)
    const first = field.getByLabel(`${c.allowlist} 1`, { exact: true })
    await expect(first).toHaveValue('')
    await expect(first).toHaveAttribute('aria-invalid', 'true')
    await expect(field.getByLabel(`${c.allowlist} 2`, { exact: true })).toHaveValue('31')
    await expect(field.getByRole('alert')).toBeVisible()
    await expect(editor.getByRole('button', { name: c.save, exact: true })).toBeDisabled()
    await expect(editor.getByText(c.passed, { exact: true })).toHaveCount(0)

    await first.fill('23')
    await expect(field.getByRole('alert')).toHaveCount(0)
    await expect(editor.getByRole('button', { name: c.save, exact: true })).toBeEnabled()
    const expected = { ...original, restart_policy: { ...original.restart_policy, exit_code_allowlist: [23, 31] } }
    expect(await readJson(editor, locale)).toEqual(expected)
    await showForm(editor, locale)
    await expect(editor.getByText(c.passed, { exact: true })).toHaveCount(0)
    await editor.getByRole('button', { name: c.validate, exact: true }).click()
    await expect(editor.getByText(c.passed, { exact: true })).toBeVisible()
    expect(fixture.validations).toEqual([
      { manifest: original, apply: false, start: false },
      { manifest: expected, apply: false, start: false },
    ])
    expect(fixture.writes).toEqual([])
    expect(fixture.unexpected).toEqual([])
  })

  test(`ordinary numeric fields retain incomplete source and distinguish clearing from values ${locale} @full`, async ({ page }) => {
    const original = processManifest(), c = copy[locale]
    const fixture = await openEditor(page, locale, original)
    const { editor } = fixture
    const mode = editor.getByRole('group', { name: c.editorMode, exact: true })
    const form = mode.getByRole('button', { name: c.form, exact: true })
    const json = mode.getByRole('button', { name: 'JSON', exact: true })
    const save = editor.getByRole('button', { name: c.save, exact: true })
    const timeout = editor.getByLabel(c.timeout, { exact: true })
    const timeoutField = editor.locator('.manifest-field').filter({ has: page.locator('[data-manifest-path="/timeout_seconds"]') })
    const delay = editor.getByLabel(c.initialDelay, { exact: true })
    const delayField = editor.locator('.manifest-field').filter({ has: page.locator('[data-manifest-path="/restart_policy/delay_seconds"]') })

    async function expectIncomplete(control: Locator, field: Locator, raw: string) {
      await control.fill(raw)
      await control.press('Tab')
      await expect(control).toHaveValue(raw)
      await expect(control).toHaveAttribute('aria-invalid', 'true')
      await expect(field.getByRole('alert')).toBeVisible()
      await expect(field.getByRole('alert')).not.toHaveText('')
      await expect(save).toBeDisabled()
      await json.click()
      await expect(form).toHaveAttribute('aria-pressed', 'true')
      await expect(json).toHaveAttribute('aria-pressed', 'false')
      await expect(editor.locator('[data-manifest-json]')).toHaveCount(0)
      await expect(control).toHaveValue(raw)
      await expect(save).toBeDisabled()
      expect(fixture.validations).toEqual([])
      expect(fixture.writes).toEqual([])
      expect(fixture.unexpected).toEqual([])
    }

    await expect(timeout).toHaveValue('30')
    for (const raw of ['1e', '9007199254740993']) {
      await test.step(`retain incomplete timeout ${raw}`, async () => {
        await expectIncomplete(timeout, timeoutField, raw)
      })
    }
    await timeout.fill('120')
    await timeout.press('Tab')
    await expect(timeout).toHaveValue('120')
    await expect(timeout).toHaveAttribute('aria-invalid', 'false')
    await expect(timeoutField.getByRole('alert')).toHaveCount(0)
    await expect(save).toBeEnabled()
    const withTimeout = { ...original, timeout_seconds: 120 }
    const timeoutJson = await readJson(editor, locale)
    expect(timeoutJson.timeout_seconds).toBe(120)
    expect(timeoutJson).toEqual(withTimeout)

    await showForm(editor, locale)
    await timeout.fill('')
    await timeout.press('Tab')
    await expect(timeout).toHaveValue('')
    await expect(timeout).toHaveAttribute('aria-invalid', 'false')
    await expect(timeoutField.getByRole('alert')).toHaveCount(0)
    await expect(save).toBeEnabled()
    const omitted: Record<string, unknown> = { ...withTimeout }
    delete omitted.timeout_seconds
    const omittedJson = await readJson(editor, locale)
    expect(omittedJson).not.toHaveProperty('timeout_seconds')
    expect(omittedJson).toEqual(omitted)

    await showForm(editor, locale)
    await expect(delay).toHaveValue('0')
    await expectIncomplete(delay, delayField, '1.')
    await delay.fill('1.5')
    await delay.press('Tab')
    await expect(delay).toHaveValue('1.5')
    await expect(delay).toHaveAttribute('aria-invalid', 'false')
    await expect(delayField.getByRole('alert')).toHaveCount(0)
    await expect(save).toBeEnabled()
    const expected = { ...omitted, restart_policy: { ...original.restart_policy, delay_seconds: 1.5 } }
    const finalJson = await readJson(editor, locale)
    expect((finalJson.restart_policy as Record<string, unknown>).delay_seconds).toBe(1.5)
    expect(finalJson).not.toHaveProperty('timeout_seconds')
    expect(finalJson).toEqual(expected)
    await showForm(editor, locale)
    await saveOnly(page, fixture, locale, expected)
  })

  test(`JSON source guards retain duplicate keys and unrepresentable numbers with precise ranges ${locale} @full`, async ({ page }) => {
    const base = containerManifest(), c = copy[locale], zh = locale === 'zh-CN'
    const original = { ...base, analysis: { ...base.analysis, source_guard_value: 0 } }
    const fixture = await openEditor(page, locale, original)
    const { editor } = fixture
    await readJson(editor, locale)
    const json = editor.locator('[data-manifest-json]')
    const form = editor.getByRole('group', { name: c.editorMode, exact: true }).getByRole('button', { name: c.form, exact: true })
    const save = editor.getByRole('button', { name: c.save, exact: true })
    const validSource = `\n${JSON.stringify(original, null, 2)}\n`
    const cases = [
      { name: 'duplicate key', replacement: '"source_guard_value": 0,\n    "source_guard_value": 1', token: '"source_guard_value"', message: zh ? /重复字段/ : /duplicate JSON keys/ },
      { name: 'unsafe integer', replacement: '"source_guard_value": 9007199254740993', token: '9007199254740993', message: zh ? /整数超出可安全编辑的范围/ : /integer is outside the safe editing range/ },
      { name: 'nonfinite number', replacement: '"source_guard_value": 1e400', token: '1e400', message: zh ? /数值超出可表示范围/ : /number is outside the representable range/ },
    ]
    for (const item of cases) {
      await test.step(item.name, async () => {
        const source = validSource.replace('"source_guard_value": 0', item.replacement)
        await json.fill(source)
        await expect(json).toHaveValue(source)
        await expect(form).toBeDisabled()
        await expect(save).toBeDisabled()
        const issue = editor.getByRole('button', { name: /^\/analysis\/source_guard_value:/ })
        await expect(editor.getByRole('alert')).toContainText(c.jsonCorrection)
        await expect(issue).toContainText(item.message)
        await expectInViewportAndUnobscured(issue)
        expect(fixture.validations).toEqual([])
        expect(fixture.writes).toEqual([])
        await issue.click()
        await expect(json).toBeFocused()
        const start = source.lastIndexOf(item.token)
        expect(start).toBeGreaterThanOrEqual(0)
        await expect.poll(() => json.evaluate(element => {
          const input = element as HTMLTextAreaElement
          return { start: input.selectionStart, end: input.selectionEnd, text: input.value.slice(input.selectionStart, input.selectionEnd) }
        })).toEqual({ start, end: start + item.token.length, text: item.token })
        await expect(json).toHaveValue(source)

        await json.fill(validSource)
        await expect(editor.getByRole('alert')).toHaveCount(0)
        await expect(form).toBeEnabled()
        await expect(save).toBeEnabled()
        await showForm(editor, locale)
        await expectContainerFields(editor, locale, original)
        expect(await readJson(editor, locale)).toEqual(original)
      })
    }
    await showForm(editor, locale)
    await saveOnly(page, fixture, locale, original)
  })
}

async function expectLabelsFit(editor: Locator) {
  const geometry = await editor.evaluate(element => {
    const rows = Array.from(element.querySelectorAll<HTMLElement>('.manifest-field')).filter(field => field.getBoundingClientRect().height > 0 && !field.closest('details:not([open])'))
    return {
      horizontalOverflow: element.scrollWidth > element.clientWidth + 1,
      rows: rows.flatMap(field => {
        const label = field.querySelector<HTMLElement>(':scope > .field-label, :scope > label')
        const control = field.querySelector<HTMLElement>(':scope > .manifest-field-control')
        if (!label || !control) return [{ text: field.innerText.slice(0, 80), missing: true }]
        const a = label.getBoundingClientRect(), b = control.getBoundingClientRect()
        const icon = label.querySelector<HTMLElement>('[data-field-help-trigger]')?.getBoundingClientRect()
        const text = label.querySelector<HTMLElement>('.field-label-text')?.getBoundingClientRect()
        return label.scrollWidth > label.clientWidth + 1 || a.right > b.left + 1
          || (icon && (icon.right > b.left + 1 || (text && text.right > icon.left + 1)))
          ? [{ text: label.innerText, missing: false }] : []
      }),
    }
  })
  expect(geometry.horizontalOverflow).toBe(false)
  expect(geometry.rows, 'Visible labels and help icons fit beside their controls').toEqual([])
}

async function expectReadableHelp(page: Page, editor: Locator, locale: Locale) {
  const content = editor.locator('[data-field-help-content]')
  await expect(content).toBeVisible()
  await expect(content).not.toHaveText('')
  await expectInViewportAndUnobscured(content)
  await expect.poll(() => content.evaluate(element => {
    const popup = element.closest('.ant-popover')!, rect = popup.getBoundingClientRect(), body = element.getBoundingClientRect()
    const readable = [.05, .5, .95].every(x => [.05, .5, .95].every(y => {
      const hit = document.elementFromPoint(body.left + body.width * x, body.top + body.height * y)
      return hit !== null && (hit === element || element.contains(hit))
    }))
    return rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1
      && element.scrollWidth <= element.clientWidth + 1 && readable
  })).toBe(true)
  await expectInViewportAndUnobscured(editor.getByRole('button', { name: copy[locale].save, exact: true }))
  await expectInViewportAndUnobscured(editor.getByRole('button', { name: copy[locale].cancel, exact: true }))
  await expect(editor.getByRole('button', { name: copy[locale].save, exact: true })).toBeEnabled()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
}

async function clickExposedInput(control: Locator) {
  const position = await control.evaluate(element => {
    const rect = element.getBoundingClientRect()
    for (const x of [.95, .85, .5, .15, .05]) {
      const hit = document.elementFromPoint(rect.left + rect.width * x, rect.top + rect.height / 2)
      if (hit && (hit === element || element.contains(hit))) return { x: rect.width * x, y: rect.height / 2 }
    }
    return null
  })
  expect(position, 'The text input retains a real clickable area beside the open help').not.toBeNull()
  await control.click({ position: position! })
}

for (const viewport of viewports) for (const locale of locales) {
  test(`container field help layout ${viewport.width}x${viewport.height} ${locale} @full @visual`, async ({ page }, testInfo) => {
    test.setTimeout(60_000)
    const original = { ...containerManifest(), startup_policy: 'legacy_restore' }, c = copy[locale]
    const fixture = await openEditor(page, locale, original, viewport)
    const { editor } = fixture
    await page.evaluate(() => document.fonts.ready)
    await expectContainerFields(editor, locale, original)
    await expectLabelsFit(editor)
    const targets = [
      { label: c.runtime, control: editor.locator('[data-manifest-path="/launch/type"]') },
      { label: c.enabled, control: editor.getByRole('switch', { name: c.enabled, exact: true }) },
      { label: c.startup, control: editor.getByRole('switch', { name: c.startup, exact: true }) },
      { label: c.image, control: editor.getByLabel(c.image, { exact: true }), value: original.launch.image },
      { label: c.args, control: editor.getByRole('textbox', { name: `${c.args} 2`, exact: true }), value: original.launch.args[1] },
      { label: c.env, control: editor.getByRole('group', { name: c.env, exact: true }).getByLabel('SYNTHETIC_PADDED', { exact: true }), value: original.launch.environment.SYNTHETIC_PADDED },
    ]
    for (const [index, target] of targets.entries()) {
      await test.step(target.label, async () => {
        await target.control.evaluate(element => element.scrollIntoView({ block: 'center' }))
        await expectInViewportAndUnobscured(target.control)
        const trigger = help(editor, locale, target.label), content = editor.locator('[data-field-help-content]')
        await expectInViewportAndUnobscured(trigger)
        await expect(content).toHaveCount(0)
        await trigger.click()
        await expectReadableHelp(page, editor, locale)
        await page.screenshot({ path: testInfo.outputPath(`container-help-${index}.png`), animations: 'disabled' })
        if (target.value !== undefined) {
          await clickExposedInput(target.control)
          await expect(content).toHaveCount(0)
          await expect(target.control).toBeFocused()
          const edited = target.label === c.image ? original.launch.image.replace(/a{64}$/, 'b'.repeat(64)) : 'Synthetic editable draft'
          await target.control.fill(edited)
          await expect(target.control).toHaveValue(edited)
          await target.control.fill(target.value)
        } else {
          await page.keyboard.press('Escape')
          await expect(content).toHaveCount(0)
          await expect(trigger).toBeFocused()
        }
        await expectInViewportAndUnobscured(target.control)
        await expectLabelsFit(editor)
      })
    }
    await expect(editor.getByRole('radio', { name: c.container, exact: true })).toBeChecked()
    await expect(editor.getByRole('switch', { name: c.enabled, exact: true })).toBeChecked()
    await expect(editor.getByRole('switch', { name: c.startup, exact: true })).not.toBeChecked()
    await expect(editor.getByText(c.legacy, { exact: true })).toBeVisible()
    expect(await readJson(editor, locale)).toEqual(original)
    expect(fixture.validations).toEqual([])
    expect(fixture.writes).toEqual([])
    expect(fixture.unexpected).toEqual([])
  })
}

import { expect, test, type Page, type Locator } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

const secret = 'Synthetic-auth-preset-value'
const peerEndpoint = () => JSON.parse(readFileSync(join(process.env.GATE_E2E_TEMP_ROOT!, 'http-peer.json'), 'utf8')).endpoint as string
const peerState = () => JSON.parse(readFileSync(join(process.env.GATE_E2E_TEMP_ROOT!, 'http-peer-state.json'), 'utf8'))

async function open(page: Page, id: string, endpoint = peerEndpoint(), zh = false, width = 1600, height = 900, dark = false) {
  await login(page)
  await page.goto('/console/#/configs')
  await page.evaluate(({ zh, dark }) => {
    localStorage.setItem('lingshu-gate-console-locale', zh ? 'zh-CN' : 'en-US')
    localStorage.setItem('lingshu-gate-console-theme', dark ? 'dark' : 'light')
  }, { zh, dark })
  // Change locale through a single initialization script on the next document.
  await page.addInitScript(({ zh, dark }) => {
    localStorage.setItem('lingshu-gate-console-locale', zh ? 'zh-CN' : 'en-US')
    localStorage.setItem('lingshu-gate-console-theme', dark ? 'dark' : 'light')
  }, { zh, dark })
  await page.setViewportSize({ width, height })
  await page.reload()
  await page.getByRole('button', { name: zh ? '新建配置' : 'New Config', exact: true }).click()
  const editor = page.getByRole('dialog', { name: zh ? '新建 MCP 配置' : 'New MCP config', exact: true })
  await editor.getByLabel(zh ? '服务 ID' : 'Server ID', { exact: true }).fill(id)
  await editor.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Synthetic HTTP authentication')
  await editor.getByLabel(zh ? 'MCP 地址' : 'MCP Endpoint', { exact: true }).fill(endpoint)
  return editor
}

async function manifest(editor: Locator, zh = false) {
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const data = JSON.parse(await editor.locator('textarea[data-manifest-json]').inputValue())
  await editor.getByRole('button', { name: zh ? '表单' : 'Form', exact: true }).click()
  return data
}

for (const [index, [width, height]] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]].entries()) {
  test(`guided Home bearer workflow ${width}x${height} @full`, async ({ page }, testInfo) => {
    test.setTimeout(60_000)
    const zh = index % 2 === 0
    const endpoint = peerEndpoint()
    const id = `synthetic-guided-home-${width}-${height}`
    const editor = await open(page, id, new URL(endpoint).origin, zh, width, height, index % 2 === 1)
    await editor.getByRole('button', { name: 'Home', exact: true }).click()
    await expect(editor.getByRole('radio', { name: 'Bearer Token', exact: true })).toBeChecked()
    await expect(editor.getByLabel(zh ? 'MCP 地址' : 'MCP Endpoint', { exact: true })).toHaveValue(endpoint)
    await editor.getByRole('radio', { name: zh ? '新增凭据' : 'New credential', exact: true }).check()
    const form = editor.getByRole('region', { name: zh ? '新增服务凭据' : 'New service credential', exact: true })
    await expect(form.getByLabel(zh ? '凭据 ID' : 'Credential ID', { exact: true })).not.toBeVisible()
    if (width === 2560 && height === 1440) {
      await form.getByRole('button', { name: zh ? '保存凭据并使用' : 'Save and use credential', exact: true }).scrollIntoViewIfNeeded()
      await page.screenshot({ path: testInfo.outputPath('auth-home-new-credential-2560x1440.png'), animations: 'disabled' })
    }
    await form.getByLabel('Token', { exact: true }).fill(`Bearer ${secret}`)
    await expect(editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true })).toBeDisabled()
    await expect(editor.getByText(zh ? '请先保存或取消正在编辑的凭据，再测试连接或保存配置。' : 'Save or cancel the credential being edited before testing or saving the configuration.', { exact: true })).toBeVisible()
    const credentialWrite = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/v1/credentials')
    await form.getByRole('button', { name: zh ? '保存凭据并使用' : 'Save and use credential', exact: true }).click()
    const savedSecret = (await credentialWrite).postDataJSON()
    expect(savedSecret.value).toBe(secret)
    expect(savedSecret.http_scopes[0].server_id).toBe(id)
    await expect(form).toHaveCount(0)
    await expect(editor.getByRole('combobox', { name: zh ? '选择服务凭据' : 'Select service credential', exact: true })).toBeFocused()
    const draft = await manifest(editor, zh)
    expect(draft.transport.headers).toEqual({ Authorization: 'Bearer ${credential:' + savedSecret.credential_id + '}' })
    expect(JSON.stringify(draft)).not.toContain(secret)
    await expect(editor.getByRole('radio', { name: 'Bearer Token', exact: true })).toBeChecked()
    await editor.getByRole('button', { name: zh ? '测试连接' : 'Test connection', exact: true }).click()
    const result = editor.getByRole('region', { name: zh ? '联通测试结果' : 'Connection test result', exact: true })
    await expect(result).toContainText(zh ? '连接成功' : 'Connection successful')
    await expect(result.getByRole('listitem')).toHaveCount(5)
    await expect(editor.locator('.manifest-editor-footer').getByRole('button')).toHaveCount(3)
    await expectInViewportAndUnobscured(editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true }))
    await expectInViewportAndUnobscured(editor.getByRole('button', { name: zh ? '测试连接' : 'Test connection', exact: true }))
    const geometry = await editor.evaluate(element => ({ width: element.getBoundingClientRect().width, overflow: element.scrollWidth > element.clientWidth + 1,
      labels: Array.from(element.querySelectorAll('.manifest-field > :is(label, .field-label)')).filter(label => label.getClientRects().length > 0).map(label => ({ text: label.textContent, overflow: label.scrollWidth > label.clientWidth + 1 })) }))
    expect(geometry.width).toBeCloseTo(1200, 0)
    expect(geometry.overflow).toBe(false)
    expect(geometry.labels.filter(item => item.overflow)).toEqual([])
    await page.screenshot({ path: testInfo.outputPath(`auth-home-${width}x${height}.png`), animations: 'disabled' })
    expect((await page.request.get(`/v1/mcp/configs/${id}`)).status()).toBe(404)
    // Saving does not require a fresh successful test and must still remain save-only.
    await editor.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Synthetic revised name')
    await expect(editor.getByText(zh ? '配置草稿已变化，上次联通测试结果已过期，请重新测试。' : 'The draft changed. The previous connection test is stale; test again.', { exact: true })).toBeVisible()
    await editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true }).click()
    await expect(editor).toHaveCount(0)
    expect((await page.request.get(`/v1/mcp/configs/${id}`)).status()).toBe(200)
  })
}

for (const kind of ['Basic', 'API Key'] as const) {
  test(`${kind} is encoded/generated without manual headers and accepted by a real synthetic peer @full`, async ({ page }) => {
    const basic = kind === 'Basic'
    const endpoint = peerEndpoint().replace('/mcp', basic ? '/auth-basic' : '/auth-api-key')
    const editor = await open(page, basic ? 'synthetic-basic-preset' : 'synthetic-api-preset', endpoint)
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    const area = editor.locator('textarea[data-manifest-json]')
    const original = JSON.parse(await area.inputValue())
    original.transport.headers = { 'X-Tenant': 'keep-me', 'X-Empty': '' }
    await area.fill(JSON.stringify(original))
    await editor.getByRole('button', { name: 'Form', exact: true }).click()
    await editor.getByRole('radio', { name: kind, exact: true }).check()
    if (!basic) {
      await editor.getByRole('radio', { name: 'Custom name', exact: true }).check()
      await editor.getByLabel('API key header', { exact: true }).fill('X-Service-Key')
    }
    await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
    const form = editor.getByRole('region', { name: 'New service credential', exact: true })
    if (basic) await form.getByLabel('Username', { exact: true }).fill('synthetic-user')
    await form.getByLabel(basic ? 'Password' : 'API Key', { exact: true }).fill(basic ? 'synthetic-pass' : secret)
    await form.getByRole('button', { name: 'Save and use credential', exact: true }).click()
    await expect(form).toHaveCount(0)
    const draft = await manifest(editor)
    expect(draft.transport.headers['X-Tenant']).toBe('keep-me')
    expect(draft.transport.headers['X-Empty']).toBe('')
    expect(draft.transport.headers[basic ? 'Authorization' : 'X-Service-Key']).toMatch(basic ? /^Basic \$\{credential:/ : /^\$\{credential:/)
    expect(JSON.stringify(draft)).not.toContain(basic ? 'synthetic-pass' : secret)
    await editor.getByRole('button', { name: 'Test connection', exact: true }).click()
    await expect(editor.getByRole('region', { name: 'Connection test result', exact: true })).toContainText('Connection successful')
    expect(peerState().last_authenticated_path).toBe(basic ? '/auth-basic' : '/auth-api-key')
    await editor.getByRole('radio', { name: 'None', exact: true }).check()
    expect((await manifest(editor)).transport.headers).toEqual({ 'X-Tenant': 'keep-me', 'X-Empty': '' })
  })
}

test('unfinished secrets cannot disappear on mode switch; failed save retains inputs and explicit cancel clears them @full', async ({ page }) => {
  const editor = await open(page, 'synthetic-auth-recovery')
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
  const form = editor.getByRole('region', { name: 'New service credential', exact: true })
  await form.getByLabel('Token', { exact: true }).fill(secret)
  // A second header editor cannot replace the authentication context and
  // unmount a secret draft. It is available again after explicit cancellation.
  await editor.locator('summary').filter({ hasText: 'Advanced headers' }).click()
  await expect(editor.getByLabel('HTTP headers new key', { exact: true })).toBeDisabled()
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  await expect(form.getByLabel('Token', { exact: true })).toHaveValue(secret)
  await expect(editor.getByRole('radio', { name: 'Basic', exact: true })).toBeDisabled()
  await expect(editor.getByRole('button', { name: 'Test connection', exact: true })).toBeDisabled()
  await page.route('**/v1/credentials', route => route.request().method() === 'POST' ? route.fulfill({ status: 503, json: { detail: 'Synthetic credential write failure' } }) : route.continue())
  await form.getByRole('button', { name: 'Save and use credential', exact: true }).click()
  await expect(form.getByRole('alert')).toContainText('Inputs are retained')
  await expect(form.getByLabel('Token', { exact: true })).toHaveValue(secret)
  await form.getByRole('button', { name: 'Cancel and clear input', exact: true }).click()
  await expect(form).toHaveCount(0)
  await expect(editor.getByRole('combobox', { name: 'Select service credential', exact: true })).toBeFocused()
  await editor.getByRole('radio', { name: 'None', exact: true }).check()
  await expect(editor.getByLabel('HTTP headers new key', { exact: true })).toBeEnabled()
  expect(JSON.stringify(await manifest(editor))).not.toContain(secret)
  await expect(editor.getByRole('button', { name: 'Test connection', exact: true })).toBeEnabled()
})

test('credential list failure is recoverable; complex headers stay custom and survive form/JSON @full', async ({ page }) => {
  await page.route('**/v1/credentials', route => route.fulfill({ status: 503, json: { detail: 'Synthetic list unavailable' } }))
  const editor = await open(page, 'synthetic-auth-custom')
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await expect(editor.getByRole('alert')).toContainText('credential list could not be loaded')
  await page.unroute('**/v1/credentials')
  await editor.getByRole('button', { name: 'Reload', exact: true }).click()
  await expect(editor.getByText('The credential list could not be loaded; this is not an empty list.', { exact: false })).toHaveCount(0)
  await editor.getByRole('radio', { name: 'None', exact: true }).check()
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const area = editor.locator('textarea[data-manifest-json]')
  const data = JSON.parse(await area.inputValue())
  data.transport.headers = { Authorization: 'Bearer ${credential:one}', 'X-API-Key': '${credential:two}', 'X-Tenant': 'preserve' }
  await area.fill(JSON.stringify(data))
  await editor.getByRole('button', { name: 'Form', exact: true }).click()
  await expect(editor.getByRole('radio', { name: 'Custom', exact: true })).toBeChecked()
  await editor.getByRole('radio', { name: 'None', exact: true }).click()
  await expect(editor.getByRole('radio', { name: 'Custom', exact: true })).toBeChecked()
  await expect(editor.getByRole('alert')).toContainText('has been retained')
  expect((await manifest(editor)).transport.headers).toEqual(data.transport.headers)
})

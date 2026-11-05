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

async function reopen(page: Page, id: string, zh = false) {
  await page.getByRole('row').filter({ hasText: id }).getByRole('button', { name: zh ? '编辑' : 'Edit', exact: true }).click()
  return page.getByRole('dialog', { name: `${zh ? '编辑' : 'Edit'} · ${id}`, exact: true })
}

for (const [index, [width, height]] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]].entries()) {
  test(`guided Home bearer workflow ${width}x${height} @full`, async ({ page }, testInfo) => {
    test.setTimeout(60_000)
    const zh = index % 2 === 0, endpoint = peerEndpoint(), id = `synthetic-guided-home-${width}-${height}`
    let editor = await open(page, id, new URL(endpoint).origin, zh, width, height, index % 2 === 1)
    const independentWrites: string[] = []
    page.on('request', request => { if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/v1/credentials')) independentWrites.push(request.url()) })
    await editor.getByRole('button', { name: 'Home', exact: true }).click()
    await expect(editor.getByRole('radio', { name: 'Bearer Token', exact: true })).toBeChecked()
    await expect(editor.getByLabel(zh ? 'MCP 地址' : 'MCP Endpoint', { exact: true })).toHaveValue(endpoint)
    await editor.getByRole('radio', { name: zh ? '新增凭据' : 'New credential', exact: true }).check()
    const form = editor.getByRole('region', { name: zh ? '新增服务凭据' : 'New service credential', exact: true })
    await expect(form.getByLabel(zh ? '凭据 ID' : 'Credential ID', { exact: true })).not.toBeVisible()
    await form.getByLabel('Token', { exact: true }).fill(`Bearer ${secret}`)
    const save = editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true })
    await expect(save).toBeEnabled()
    await expect(editor.getByRole('button', { name: zh ? '测试连接' : 'Test connection', exact: true })).toBeDisabled()
    expect(independentWrites).toEqual([])
    expect((await page.request.get(`/v1/mcp/configs/${id}`)).status()).toBe(404)
    await expectInViewportAndUnobscured(save)
    await page.screenshot({ path: testInfo.outputPath(`auth-credential-draft-${width}x${height}.png`), animations: 'disabled' })
    const finalWrite = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/v1/mcp/configs/with-credential')
    await save.click()
    const body = (await finalWrite).postDataJSON()
    expect(body.credential_write.value).toBe(secret)
    expect(body.credential_write.target.server_id).toBe(id)
    expect(body.manifest.transport.headers).toEqual({ Authorization: 'Bearer ${credential:' + body.credential_write.credential_id + '}' })
    expect(JSON.stringify(body.manifest)).not.toContain(secret)
    expect(body).toMatchObject({ apply: false, start: false })
    await expect(editor).toHaveCount(0)
    expect(independentWrites).toEqual([])
    editor = await reopen(page, id, zh)
    // A recent save notification must never sit above the next editor's actions.
    expect(await editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true }).evaluate(element => {
      const box = element.getBoundingClientRect()
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
      return hit === element || element.contains(hit)
    })).toBe(true)
    await editor.getByRole('button', { name: zh ? '测试连接' : 'Test connection', exact: true }).click()
    const result = editor.getByRole('region', { name: zh ? '联通测试结果' : 'Connection test result', exact: true })
    await expect(result).toContainText(zh ? '连接成功' : 'Connection successful')
    await expect(result.getByRole('listitem')).toHaveCount(5)
    const geometry = await editor.evaluate(element => ({ width: element.getBoundingClientRect().width, overflow: element.scrollWidth > element.clientWidth + 1,
      labels: Array.from(element.querySelectorAll('.manifest-field > :is(label, .field-label)')).filter(label => label.getClientRects().length > 0).map(label => ({ text: label.textContent, overflow: label.scrollWidth > label.clientWidth + 1 })) }))
    expect(geometry.width).toBeCloseTo(1200, 0)
    expect(geometry.overflow).toBe(false)
    expect(geometry.labels.filter(item => item.overflow)).toEqual([])
    await page.screenshot({ path: testInfo.outputPath(`auth-home-${width}x${height}.png`), animations: 'disabled' })
    await editor.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Synthetic revised name')
    await expect(editor.getByText(zh ? '配置草稿已变化，上次联通测试结果已过期，请重新测试。' : 'The draft changed. The previous connection test is stale; test again.', { exact: true })).toBeVisible()
    await editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true }).click()
    await expect(editor).toHaveCount(0)
  })
}

for (const kind of ['Basic', 'API Key'] as const) {
  test(`${kind} is encoded/generated without manual headers and accepted by a real synthetic peer @full`, async ({ page }) => {
    const basic = kind === 'Basic', id = basic ? 'synthetic-basic-preset' : 'synthetic-api-preset'
    const endpoint = peerEndpoint().replace('/mcp', basic ? '/auth-basic' : '/auth-api-key')
    let editor = await open(page, id, endpoint)
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    const area = editor.locator('textarea[data-manifest-json]'), original = JSON.parse(await area.inputValue())
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
    const saving = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname === '/v1/mcp/configs/with-credential')
    await editor.getByRole('button', { name: 'Save Config', exact: true }).click()
    const submitted = (await saving).postDataJSON()
    expect(submitted.manifest.transport.headers).toMatchObject({ 'X-Tenant': 'keep-me', 'X-Empty': '' })
    expect(submitted.manifest.transport.headers[basic ? 'Authorization' : 'X-Service-Key']).toMatch(basic ? /^Basic \$\{credential:/ : /^\$\{credential:/)
    expect(JSON.stringify(submitted.manifest)).not.toContain(basic ? 'synthetic-pass' : secret)
    await expect(editor).toHaveCount(0)
    editor = await reopen(page, id)
    const draft = await manifest(editor)
    expect(draft.transport.headers['X-Tenant']).toBe('***')
    expect(draft.transport.headers['X-Empty']).toBe('***')
    expect(draft.transport.headers[basic ? 'Authorization' : 'X-Service-Key']).toBe('***')
    expect(JSON.stringify(draft)).not.toContain(basic ? 'synthetic-pass' : secret)
    await editor.getByRole('button', { name: 'Test connection', exact: true }).click()
    await expect(editor.getByRole('region', { name: 'Connection test result', exact: true })).toContainText('Connection successful')
    expect(peerState().last_authenticated_path).toBe(basic ? '/auth-basic' : '/auth-api-key')
    expect(peerState().unrelated_headers_preserved).toBe(true)
  })
}

test('save and connect confirms once, retains cancelled input and activates the combined save @full', async ({ page }, testInfo) => {
  const id = 'synthetic-save-and-connect'
  const editor = await open(page, id)
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
  const form = editor.getByRole('region', { name: 'New service credential', exact: true })
  await form.getByLabel('Token', { exact: true }).fill(secret)
  const writes: Record<string, unknown>[] = []
  page.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/v1/mcp/configs/with-credential') writes.push(request.postDataJSON())
  })
  await editor.getByRole('radio', { name: 'Save and connect', exact: true }).check()
  await editor.getByRole('button', { name: 'Save and connect', exact: true }).click()
  const confirmation = page.getByRole('alertdialog')
  await expect(confirmation).toContainText(id)
  expect(writes).toHaveLength(0)
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(form.getByLabel('Token', { exact: true })).toHaveValue(secret)
  await editor.getByRole('button', { name: 'Save and connect', exact: true }).click()
  const responsePromise = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/v1/mcp/configs/with-credential')
  await confirmation.getByRole('button', { name: 'Save and activate', exact: true }).click()
  const response = await responsePromise
  const result = await response.json()
  await testInfo.attach('activation-result', { body: JSON.stringify(result), contentType: 'application/json' })
  expect(response.status()).toBe(200)
  expect(result.server).toMatchObject({ id, status: 'running' })
  await expect(editor).toHaveCount(0)
  expect(writes).toHaveLength(1)
  expect(writes[0]).toMatchObject({ apply: true, start: true, credential_write: { kind: 'create' } })
  const status = await page.request.get(`/v1/mcp/servers/${id}`)
  const current = await status.json()
  await testInfo.attach('activation-readback', { body: JSON.stringify(current), contentType: 'application/json' })
  expect(status.status()).toBe(200)
  expect(current).toMatchObject({ id, status: 'running' })
  const inventory = await page.request.get('/v1/mcp/servers')
  const listed = await inventory.json()
  await testInfo.attach('activation-inventory', { body: JSON.stringify(listed), contentType: 'application/json' })
  expect(inventory.status()).toBe(200)
  expect(listed.servers).toContainEqual(expect.objectContaining({ id, status: 'running' }))
})

test('unfinished secrets survive editing and failed final save; cancellation performs no credential write @full', async ({ page }) => {
  const editor = await open(page, 'synthetic-auth-recovery')
  const before = await (await page.request.get('/v1/credentials')).json()
  await editor.getByRole('radio', { name: 'Bearer Token', exact: true }).check()
  await editor.getByRole('radio', { name: 'New credential', exact: true }).check()
  const form = editor.getByRole('region', { name: 'New service credential', exact: true })
  await form.getByLabel('Token', { exact: true }).fill(secret)
  await editor.locator('summary').filter({ hasText: 'Advanced headers' }).click()
  await expect(editor.getByLabel('HTTP headers key 1', { exact: true })).toBeDisabled()
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  await expect(form.getByLabel('Token', { exact: true })).toHaveValue(secret)
  await expect(editor.getByRole('radio', { name: 'Basic', exact: true })).toBeDisabled()
  await page.route('**/v1/mcp/configs/with-credential', route => route.fulfill({ status: 503, json: { detail: 'Synthetic final save failure' } }))
  await editor.getByRole('button', { name: 'Save Config', exact: true }).click()
  await expect(editor.getByRole('alert')).toContainText('Synthetic final save failure')
  await expect(form.getByLabel('Token', { exact: true })).toHaveValue(secret)
  await form.getByRole('button', { name: 'Cancel new credential', exact: true }).click()
  await expect(form).toHaveCount(0)
  await editor.getByRole('radio', { name: 'None', exact: true }).check()
  expect(JSON.stringify(await manifest(editor))).not.toContain(secret)
  expect(await (await page.request.get('/v1/credentials')).json()).toEqual(before)
  expect((await page.request.get('/v1/mcp/configs/synthetic-auth-recovery')).status()).toBe(404)
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

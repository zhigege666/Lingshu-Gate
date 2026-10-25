import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

// Built Console + real REST + real isolated MCP peer. No production data or services.
const sizes = [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]]
for (const [index, [width, height]] of sizes.entries()) {
  test(`HTTP connection test keeps draft and runtime separate ${width}x${height} @full`, async ({ page }, testInfo) => {
    const zh = index % 2 === 0
    const root = process.env.GATE_E2E_TEMP_ROOT!
    const endpoint = JSON.parse(readFileSync(join(root, 'http-peer.json'), 'utf8')).endpoint
    const peer = () => JSON.parse(readFileSync(join(root, 'http-peer-state.json'), 'utf8'))
    const before = peer()
    const serverId = `synthetic-connection-${width}-${height}`
    await login(page)
    await page.addInitScript(({ locale, theme }) => {
      localStorage.setItem('lingshu-gate-console-locale', locale)
      localStorage.setItem('lingshu-gate-console-theme', theme)
    }, { locale: zh ? 'zh-CN' : 'en-US', theme: index % 2 === 0 ? 'light' : 'dark' })
    await page.setViewportSize({ width, height })
    await page.goto('/console/#/configs')
    await page.getByRole('button', { name: zh ? '新建配置' : 'New Config', exact: true }).click()
    const editor = page.getByRole('dialog', { name: zh ? '新建 MCP 配置' : 'New MCP config', exact: true })
    await editor.getByRole('button', { name: 'JSON', exact: true }).click()
    await editor.locator('textarea[data-manifest-json]').fill(JSON.stringify({
      id: serverId, name: 'Synthetic isolated probe', enabled: true, auto_start: false, startup_policy: 'gate_start_v1',
      launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint }, timeout_seconds: 3,
    }, null, 2))
    await editor.getByRole('button', { name: zh ? '表单' : 'Form', exact: true }).click()
    const trigger = editor.getByRole('button', { name: zh ? '测试连接' : 'Test connection', exact: true })
    await expectInViewportAndUnobscured(trigger)
    await trigger.click()
    const result = editor.getByRole('region', { name: zh ? '联通测试结果' : 'Connection test result', exact: true })
    await expect(result).toContainText(zh ? '连接成功' : 'Connection successful')
    await expect(result.getByRole('listitem')).toHaveCount(5)
    await expect(result).toContainText(zh ? '实际业务权限尚未验证' : 'Business permissions remain unverified')
    await expectInViewportAndUnobscured(editor.getByRole('button', { name: zh ? '保存配置' : 'Save Config', exact: true }))
    await expectInViewportAndUnobscured(trigger)
    expect(await editor.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`connection-result-${width}x${height}.png`), animations: 'disabled' })
    expect(peer().discoveries).toBe(before.discoveries + 1)
    expect(peer().lists).toBe(before.lists + 1)
    expect(peer().calls).toBe(before.calls)
    expect((await page.request.get(`/v1/mcp/configs/${serverId}`)).status()).toBe(404)
    await editor.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Changed draft must expire previous result')
    await expect(result).toHaveCount(0)
    await expect(editor.getByText(zh ? '配置草稿已变化，上次联通测试结果已过期，请重新测试。' : 'The draft changed. The previous connection test is stale; test again.', { exact: true })).toBeVisible()
    await expect(trigger).toBeEnabled()
  })
}

test('pending test blocks duplicate actions and surfaces explicit authentication failure @full', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/console/#/configs')
  await page.getByRole('button', { name: 'New Config', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'New MCP config', exact: true })
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  await editor.locator('textarea[data-manifest-json]').fill(JSON.stringify({ id: 'synthetic-delayed-probe', enabled: true,
    launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'https://mcp.example.test/mcp' }, timeout_seconds: 3 }))
  await editor.getByRole('button', { name: 'Form', exact: true }).click()
  // Only this race/error-state case mocks diagnostic output; the four cases above use real HTTP.
  let release!: () => void
  const barrier = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/mcp/external-configs/test', async route => {
    await barrier
    await route.fulfill({ json: { ok: false, status: 'failed', elapsed_ms: 123, code: 'authentication_required', http_status: 401,
      auth_scheme: 'bearer', oauth_advertised: false, network_attempted: true,
      config_saved: false, trust_changed: false, registry_changed: false, business_permissions_verified: false,
      stages: [{ id: 'configuration', status: 'passed' }, { id: 'http', status: 'passed' }, { id: 'authentication', status: 'failed' }, { id: 'handshake', status: 'skipped' }, { id: 'tools', status: 'skipped' }] } })
  })
  await editor.getByRole('button', { name: 'Test connection', exact: true }).click()
  await expect(editor.getByRole('button', { name: 'Testing…', exact: true })).toBeDisabled()
  await expect(editor.getByRole('button', { name: 'Save Config', exact: true })).toBeDisabled()
  await expect(editor.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled()
  release()
  const result = editor.getByRole('region', { name: 'Connection test result', exact: true })
  await expect(result).toContainText('Check its issuer')
  await expect(result).toContainText('Not verified')
  await expect(editor.getByRole('button', { name: 'Test connection', exact: true })).toBeEnabled()
})

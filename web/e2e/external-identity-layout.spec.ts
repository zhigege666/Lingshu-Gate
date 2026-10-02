import { test, expect } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

// Synthetic presentation fixtures only. No OAuth provider, tunnel or external network is used.
const output = process.env.GATE_IDENTITY_EVIDENCE_DIR
const issuer = 'https://synthetic-identity.invalid'
const canonical = 'https://synthetic-gate.invalid/mcp'
const connection = {
  revision: 7, enabled: false, mode: 'direct', endpoint: canonical,
  canonical_resource_url: canonical, tunnel_reference: null, runtime_secret_reference: null,
  trusted_issuers: [issuer], client_allowlist: ['synthetic-client'],
  issuer_jwks: [[issuer, `${issuer}/fixed-jwks`]],
  resource_mappings: [['https://synthetic-audience.invalid/mcp', canonical]],
  validation_errors: [], connected: false, provider_verified: false, oauth_verifier_ready: false,
}

for (const [index, [width, height]] of Array.from([[2048, 1119], [1366, 768], [390, 844]].entries())) {
  test(`E2E-${560 + index} @external-identity-layout configuration modal columns, final field and dirty cancellation ${width}`, async ({ page }) => {
    test.skip(!output, 'Opt-in external identity UI evidence')
    await login(page)
    await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width, height })
    const writes: string[] = []
    await page.route('**/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() !== 'GET') {
        writes.push(path)
        return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in presentation scenario' } })
      }
      if (path === '/v1/auth/external-connection/config') return route.fulfill({ json: connection })
      if (path === '/v1/auth/external-subject-links') return route.fulfill({ json: { links: [], total: 0, offset: 0, limit: 50 } })
      return route.continue()
    })
    await page.goto('/console/#/connectionInfrastructure')
    await page.getByRole('button', { name: '编辑验证配置', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '外部接入验证配置', exact: true })
    const title = dialog.getByRole('heading', { name: '外部接入验证配置', exact: true })
    const save = dialog.getByRole('button', { name: '保存配置', exact: true })
    const cancel = dialog.getByRole('button', { name: '取消', exact: true })
    await expectInViewportAndUnobscured(title)
    await expectInViewportAndUnobscured(save)
    await expectInViewportAndUnobscured(cancel)
    const form = dialog.locator('#connection-draft')
    const columns = await form.locator(':scope > fieldset').evaluateAll(nodes => nodes.slice(0, 2).map(el => el.getBoundingClientRect().toJSON()))
    if (width >= 1024) {
      expect(Math.abs(columns[0].top - columns[1].top)).toBeLessThan(2)
      expect(columns[1].left).toBeGreaterThanOrEqual(columns[0].right)
    } else {
      expect(columns[1].top).toBeGreaterThanOrEqual(columns[0].bottom)
      expect(Math.abs(columns[1].left - columns[0].left)).toBeLessThan(2)
    }
    const body = form.locator('..')
    await expect.poll(() => body.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    mkdirSync(output!, { recursive: true })
    await page.screenshot({ path: join(output!, `external-modal-initial-${width}x${height}.png`) })
    const footerBefore = await save.boundingBox()
    const titleBefore = await title.boundingBox()
    await body.evaluate(el => { el.scrollTop = el.scrollHeight })
    expect(await dialog.evaluate(el => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
    expect(Math.abs((await save.boundingBox())!.y - footerBefore!.y)).toBeLessThan(2)
    expect(Math.abs((await title.boundingBox())!.y - titleBefore!.y)).toBeLessThan(2)
    await expectInViewportAndUnobscured(dialog.getByLabel('Canonical resource 1', { exact: true }))
    await expectInViewportAndUnobscured(dialog.getByRole('button', { name: '添加映射', exact: true }))
    await expectInViewportAndUnobscured(title)
    await expectInViewportAndUnobscured(save)
    await expectInViewportAndUnobscured(cancel)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: join(output!, `external-modal-bottom-${width}x${height}.png`) })
    const lastField = dialog.getByLabel('Canonical resource 1', { exact: true })
    await lastField.fill(`${canonical}/unsaved`)
    await cancel.click()
    const confirm = page.getByRole('alertdialog', { name: '放弃尚未保存的修改？', exact: true })
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: '继续编辑', exact: true }).click()
    await expect(confirm).toHaveCount(0)
    await expect(lastField).toHaveValue(`${canonical}/unsaved`)
    expect(writes).toEqual([])
    await cancel.click()
    await page.getByRole('alertdialog').getByRole('button', { name: '放弃修改', exact: true }).click()
    await expect(page.locator('#connection-draft')).toHaveCount(0)
    expect(writes).toEqual([])
    writeFileSync(join(output!, `external-modal-${width}x${height}.json`), JSON.stringify({ viewport: { width, height }, columns, writes, synthetic: true }, null, 2))
  })
}

const longUser = { id: 'synthetic-user-0042', username: 'synthetic.authorization.reviewer', display_name: '合成研发平台集成与权限审核负责人——长名称展示验证', status: 'active' }
for (const [index, width] of Array.from([1366, 390].entries())) {
  test(`E2E-${563 + index} @external-identity-layout names, copied ID and authorized searchable picker ${width}`, async ({ page, context }) => {
    test.skip(!output, 'Opt-in synthetic identity interaction')
    await login(page)
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width, height: width === 390 ? 844 : 768 })
    const requests: string[] = [], writes: string[] = []
    const users = Array.from({ length: 81 }, (_, i) => i === 42 ? longUser : ({ id: `synthetic-user-${i}`, username: `synthetic.${i}`, display_name: `合成用户 ${i}`, status: 'active' }))
    const links = Array.from({ length: 51 }, (_, i) => ({ id: `synthetic-link-${i}`, issuer, subject: `synthetic-subject-${i}`, user_id: i === 0 ? longUser.id : users[i].id, user: i === 0 ? longUser : i === 1 ? null : users[i], enabled: false, revision: 1 }))
    await page.route('**/v1/**', async route => {
      const url = new URL(route.request().url()), path = url.pathname
      requests.push(`${route.request().method()} ${path}${url.search}`)
      if (route.request().method() !== 'GET') { writes.push(path); return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } }) }
      if (path === '/v1/auth/me') return route.fulfill({ json: { id: 'synthetic-manager', username: 'synthetic-manager', display_name: '合成身份管理员', role: 'custom', roles: ['custom'], permissions: ['console.view', 'external_connections.manage'], status: 'active', must_change_password: false, auth_type: 'session', scopes: [] } })
      if (path === '/v1/auth/external-connection/config') return route.fulfill({ json: connection })
      if (path === '/v1/auth/external-subject-links' || path.endsWith('/user-options')) {
        const isUsers = path.endsWith('/user-options'), offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 50), q = (url.searchParams.get('q') || '').toLowerCase()
        const items = (isUsers ? users : links).filter(item => JSON.stringify(item).toLowerCase().includes(q))
        return route.fulfill({ json: { [isUsers ? 'users' : 'links']: items.slice(offset, offset + limit), total: items.length, offset, limit } })
      }
      return route.continue()
    })
    await page.goto('/console/#/connectionInfrastructure')
    const section = page.getByRole('region', { name: 'OAuth 身份绑定', exact: true })
    const targetRow = section.locator('tbody tr').filter({ has: page.getByText('synthetic-subject-0', { exact: true }) })
    await expect(targetRow).toContainText(longUser.display_name)
    await expect(section.getByText('用户不可用', { exact: true })).toBeVisible()
    expect(requests.some(path => path.includes('/user-options'))).toBe(false)
    const search = section.getByRole('textbox', { name: '搜索签发方、subject、用户名称或 ID', exact: true })
    await search.fill(longUser.display_name)
    const rows = section.locator('tbody tr')
    await expect(rows).toHaveCount(2)
    await expect(targetRow).toContainText(`@${longUser.username}`)
    await targetRow.locator('.ant-typography-copy').click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(longUser.id)
    await search.fill(longUser.id)
    await expect(rows).toHaveCount(2)
    await expect(targetRow).toContainText(longUser.display_name)
    await search.fill('')
    await section.getByRole('button', { name: '下一页', exact: true }).click()
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText('synthetic-subject-50')
    await section.getByRole('button', { name: '添加身份绑定', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '添加外部身份绑定', exact: true })
    const picker = dialog.getByRole('combobox', { name: 'Gate 用户', exact: true })
    await picker.click()
    const popup = page.locator('.ant-select-dropdown:visible:not(.ant-slide-up-leave)')
    await expect(popup.getByRole('status')).toHaveText('1–40 / 81')
    await popup.getByRole('button', { name: '下一页', exact: true }).click()
    await expect(popup.getByRole('status')).toHaveText('41–80 / 81')
    await picker.fill(longUser.display_name)
    await expect(popup.getByRole('status')).toHaveText('1–1 / 1')
    await picker.fill(longUser.id)
    await expect.poll(() => requests.some(path => path.includes('/user-options?') && new URL(path.slice(4), 'http://synthetic.invalid').searchParams.get('q') === longUser.id)).toBe(true)
    await expect(popup.locator('.ant-select-item-option').filter({ hasText: longUser.id })).toHaveCount(1)
    await expectInViewportAndUnobscured(popup.getByRole('button', { name: '下一页', exact: true }))
    mkdirSync(output!, { recursive: true })
    await page.screenshot({ path: join(output!, `identity-user-picker-${width}.png`) })
    await popup.locator('.ant-select-item-option').filter({ hasText: longUser.id }).click()
    await expect(picker.locator('..')).toContainText(longUser.id)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: '继续编辑', exact: true }).click()
    await expect(picker.locator('..')).toContainText(longUser.id)
    expect(writes).toEqual([])
    expect(requests.some(path => /\/v1\/access\/(users|subjects)/.test(path))).toBe(false)
    writeFileSync(join(output!, `identity-user-picker-${width}.json`), JSON.stringify({ requests, writes, synthetic: true }, null, 2))
  })
}

test('E2E-565 @external-identity-layout no external management UI or directory request without capability', async ({ page }) => {
  test.skip(!output, 'Opt-in UI capability boundary; API authorization is tested separately')
  await login(page, 'viewer')
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  const requests: string[] = []
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/v1/auth/external-subject-links')) requests.push(request.url()) })
  await page.goto('/console/#/connectionInfrastructure')
  await expect(page.getByText('当前账号无权访问此页面', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'OAuth 身份绑定', exact: true })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Gate 用户', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '添加身份绑定', exact: true })).toHaveCount(0)
  expect(requests).toEqual([])
})

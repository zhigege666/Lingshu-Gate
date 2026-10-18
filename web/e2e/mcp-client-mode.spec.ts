import { test, expect, type Page } from '@playwright/test'
import { expectInViewportAndUnobscured } from './helpers'

const storageKey = 'lingshu-gate-mcp-client-settings'

async function loginWithLocale(page: Page, locale: string, legacyPreference = false) {
  const response = await page.request.post('/v1/auth/login', { data: {
    username: 'admin', password: 'Synthetic-admin-123!',
  } })
  expect(response.status()).toBe(200)
  await page.addInitScript(({ locale, legacyPreference, storageKey }) => {
    localStorage.setItem('lingshu-gate-console-locale', locale)
    if (legacyPreference) localStorage.setItem(storageKey, JSON.stringify({
      name: 'synthetic-client', endpoint: `${location.origin}/mcp?tool_mode=on_demand`, mode: 'on_demand',
    }))
  }, { locale, legacyPreference, storageKey })
}

for (const locale of ['en-US', 'zh-CN']) {
  test(`MCP client settings omit obsolete discovery preferences ${locale} @smoke`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginWithLocale(page, locale, true)
    await page.goto('/console/#/personalTokens')
    const zh = locale === 'zh-CN'
    const trigger = page.getByRole('button', { name: zh ? '客户端设置' : 'Client settings', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: zh ? 'MCP 客户端设置' : 'MCP client settings', exact: true })
    await expect(dialog).toBeVisible()
    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(Math.abs(box!.x + box!.width / 2 - 960)).toBeLessThan(5)
    await expect(dialog.getByRole('radio')).toHaveCount(0)
    await expect(dialog.locator('#mcp-client-url')).toHaveValue('http://127.0.0.1:18763/mcp')
    await expect(dialog.locator('#mcp-client-configuration')).toHaveValue(/\/mcp"/)
    await expect(dialog.locator('#mcp-client-configuration')).not.toHaveValue(/tool_mode/)
    const save = dialog.getByRole('button', { name: zh ? '保存设置' : 'Save settings', exact: true })
    await expectInViewportAndUnobscured(save)
    await save.click()
    await expect(dialog.getByRole('status')).toContainText(zh ? '此浏览器' : 'this browser')
    expect(await page.evaluate(storageKey => JSON.parse(localStorage.getItem(storageKey)!), storageKey)).toEqual({
      name: 'synthetic-client', endpoint: 'http://127.0.0.1:18763/mcp',
    })
    await page.screenshot({ path: testInfo.outputPath(`mcp-client-${locale}.png`) })
    await dialog.getByRole('button', { name: zh ? '关闭' : 'Close', exact: true }).last().click()
    await expect(trigger).toBeFocused()
    await trigger.click()
    await expect(dialog.locator('#mcp-client-name')).toHaveValue('synthetic-client')
    await expect(dialog.getByRole('radio')).toHaveCount(0)
    for (const viewport of [{ width: 1600, height: 900 }, { width: 2560, height: 1440 }, { width: 2560, height: 1080 }]) {
      await page.setViewportSize(viewport)
      const name = dialog.locator('#mcp-client-name')
      const label = dialog.locator('label[for="mcp-client-name"]')
      const bounds = await Promise.all([name.boundingBox(), label.boundingBox()])
      expect(bounds[0]!.x).toBeGreaterThan(bounds[1]!.x)
      expect(Math.abs(bounds[0]!.y - bounds[1]!.y)).toBeLessThan(15)
      await expectInViewportAndUnobscured(save)
    }
  })

  test(`MCP discovery belongs to each authorization ${locale} @smoke`, async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginWithLocale(page, locale)
    const zh = locale === 'zh-CN'
    const names = [`Synthetic discovery selected ${locale}`, `Synthetic discovery unchanged ${locale}`]
    const ids: string[] = []
    for (const name of names) {
      const created = await page.request.post('/v1/auth/tokens', { data: { name, scopes: ['tools.read', 'tools.invoke'] } })
      expect(created.status()).toBe(200)
      ids.push(String((await created.json()).id))
    }
    const path = `/v1/auth/authorizations/api/${ids[0]}/discovery`
    await page.goto('/console/#/personalTokens')
    await page.getByLabel(zh ? '搜索授权' : 'Search authorizations', { exact: true }).fill(names[0])
    const row = page.getByRole('row').filter({ hasText: names[0] })
    await row.getByRole('button', { name: zh ? '按需发现' : 'On demand', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: zh ? '工具发现与结果' : 'Tool discovery and results', exact: true })
    await expect(dialog.getByRole('radio', { name: zh ? '按需发现' : 'On demand', exact: true })).toBeChecked()
    await dialog.getByRole('radio', { name: zh ? '完整工具列表' : 'Full tool list', exact: true }).check()
    await dialog.getByRole('button', { name: zh ? '保存' : 'Save', exact: true }).click()
    const confirmation = page.getByRole('alertdialog', { name: zh ? '确认调整工具发现与结果？' : 'Confirm discovery and result settings?', exact: true })
    await expect(confirmation).toBeVisible()
    expect((await (await page.request.get(path)).json()).tool_discovery_mode).toBe('on_demand')
    const persisted = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === path)
    await confirmation.getByRole('button', { name: zh ? '确认' : 'Confirm', exact: true }).click()
    expect((await persisted).status()).toBe(200)
    await expect(dialog).toHaveCount(0)
    await expect(row.getByRole('button', { name: zh ? '完整工具列表' : 'Full tool list', exact: true })).toBeVisible()
    expect((await (await page.request.get(path)).json()).tool_discovery_mode).toBe('direct')
    expect((await (await page.request.get(`/v1/auth/authorizations/api/${ids[1]}/discovery`)).json()).tool_discovery_mode).toBe('on_demand')
    const tokens = (await (await page.request.get('/v1/auth/tokens')).json()).tokens
    for (const id of ids) expect(tokens.find((token: { id: string }) => token.id === id).scopes.sort()).toEqual(['tools.invoke', 'tools.read'])
    await row.getByRole('button', { name: zh ? '完整工具列表' : 'Full tool list', exact: true }).click()
    await expect(dialog.getByRole('radio', { name: zh ? '完整工具列表' : 'Full tool list', exact: true })).toBeChecked()
  })
}

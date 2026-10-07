import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'

for (const locale of ['en-US', 'zh-CN']) {
  test(`MCP client on-demand mode ${locale} @smoke`, async ({ page }, testInfo) => {
    await login(page)
    await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
    await page.goto('/console/#/personalTokens')
    const zh = locale === 'zh-CN'
    const trigger = page.getByRole('button', { name: zh ? '客户端设置' : 'Client settings', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: zh ? 'MCP 客户端设置' : 'MCP client settings', exact: true })
    await expect(dialog).toBeVisible()
    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(Math.abs(box!.x + box!.width / 2 - 640)).toBeLessThan(5)
    await dialog.getByRole('radio', { name: zh ? '按需发现' : 'On demand', exact: true }).check()
    await expect(dialog.locator('#mcp-client-configuration')).toHaveValue(/tool_mode=on_demand/)
    await expectInViewportAndUnobscured(dialog.getByRole('button', { name: zh ? '保存设置' : 'Save settings', exact: true }))
    await dialog.getByRole('button', { name: zh ? '保存设置' : 'Save settings', exact: true }).click()
    await expect(dialog.getByRole('status')).toContainText(zh ? '此浏览器' : 'this browser')
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('lingshu-gate-mcp-client-settings')!).mode)).toBe('on_demand')
    await page.screenshot({ path: testInfo.outputPath(`mcp-client-${locale}.png`) })
    await dialog.getByRole('button', { name: zh ? '关闭' : 'Close', exact: true }).last().click()
    await expect(trigger).toBeFocused()
    await trigger.click()
    await expect(dialog.getByRole('radio', { name: zh ? '按需发现' : 'On demand', exact: true })).toBeChecked()
    await page.setViewportSize({ width: 390, height: 844 })
    const name = dialog.locator('#mcp-client-name')
    const label = dialog.locator('label[for="mcp-client-name"]')
    const bounds = await Promise.all([name.boundingBox(), label.boundingBox()])
    expect(bounds[0]!.x).toBeGreaterThan(bounds[1]!.x)
    expect(Math.abs(bounds[0]!.y - bounds[1]!.y)).toBeLessThan(15)
    await expectInViewportAndUnobscured(dialog.getByRole('button', { name: zh ? '保存设置' : 'Save settings', exact: true }))
  })
}

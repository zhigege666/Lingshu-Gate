import { test, expect } from '@playwright/test'
import { expectInViewportAndUnobscured, login } from './helpers'

const sizes = [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]] as const

for (const locale of ['zh-CN', 'en-US'] as const) {
  for (const theme of ['light', 'dark'] as const) {
    test(`@full account menu has one copy of each action: ${locale} ${theme}`, async ({ page }, testInfo) => {
      await login(page)
      await page.addInitScript(({ locale, theme }) => {
        localStorage.setItem('lingshu-gate-console-locale', locale)
        localStorage.setItem('lingshu-gate-console-theme', theme)
      }, { locale, theme })
      await page.route('**/v1/auth/me', route => route.fulfill({ json: {
        id: 'synthetic-header-user', username: 'synthetic-account', display_name: 'Synthetic account',
        role: 'admin', roles: ['admin', 'synthetic-auditor'], permissions: ['*'],
        status: 'active', must_change_password: false, auth_type: 'session', scopes: [],
      } }))
      await page.goto('/console/#/servers')
      const account = page.getByRole('button', { name: locale === 'zh-CN' ? '账号菜单' : 'Account menu', exact: true })
      const signOut = locale === 'zh-CN' ? '退出登录' : 'Sign out'
      for (const [width, height] of sizes) {
        await page.setViewportSize({ width, height })
        await expectInViewportAndUnobscured(page.getByRole('button', { name: 'OpenAPI', exact: true }))
        await account.focus()
        await page.keyboard.press('Enter')
        const menu = page.locator('.console-account-menu')
        await expectInViewportAndUnobscured(menu)
        await expect(account).toHaveAttribute('aria-expanded', 'true')
        await expect(page.getByRole('button', { name: 'OpenAPI', exact: true })).toHaveCount(1)
        await expect(menu.getByText('OpenAPI', { exact: true })).toHaveCount(0)
        await expect(page.locator('.console-version')).toHaveCount(1)
        await expect(menu.getByText('0.4.3', { exact: true })).toHaveCount(0)
        await expect(page.getByText('Synthetic account', { exact: true })).toHaveCount(1)
        await expect(menu.getByText(locale === 'zh-CN' ? '管理员' : 'Administrator', { exact: true })).toBeVisible()
        await expect(menu.getByText('synthetic-auditor', { exact: true })).toBeVisible()
        await expect(menu.getByRole('menuitem', { name: signOut, exact: true })).toHaveCount(1)
        await expect(page.getByText(signOut, { exact: true })).toHaveCount(1)
        await expect(page.locator('header').getByText(signOut, { exact: true })).toHaveCount(0)
        await page.screenshot({ path: testInfo.outputPath(`header-${locale}-${theme}-${width}x${height}.png`) })
        await page.keyboard.press('Escape')
        await expect(menu).toHaveCount(0)
        await expect(account).toBeFocused()
        await expect(account).toHaveAttribute('aria-expanded', 'false')
      }
    })
  }
}

test('@full disabled authentication does not offer sign out in the open account menu', async ({ page }) => {
  await login(page)
  await page.route('**/v1/auth/me', route => route.fulfill({ json: {
    id: 'synthetic-disabled', username: 'synthetic-disabled', display_name: 'Synthetic disabled',
    role: 'viewer', roles: [], permissions: ['*'], status: 'active',
    must_change_password: false, auth_type: 'disabled', scopes: [],
  } }))
  await page.goto('/console/#/servers')
  await page.getByRole('button', { name: 'Account menu', exact: true }).click()
  await expect(page.locator('.console-account-menu')).toBeVisible()
  await expect(page.getByText('Sign out', { exact: true })).toHaveCount(0)
  await expect(page.locator('.console-account-menu').getByText('Viewer', { exact: true })).toBeVisible()
})

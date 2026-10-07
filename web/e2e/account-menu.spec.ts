import { test, expect } from '@playwright/test'
import { expectInViewportAndUnobscured, login } from './helpers'

const sizes = [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]] as const

// Actual isolated sign-in; synthetic identity presentation does not grant access.
for (const locale of ['zh-CN', 'en-US'] as const) {
  for (const theme of ['light', 'dark'] as const) {
    test(`@smoke @full @account-menu controlled close and keyboard focus: ${locale} ${theme}`, async ({ page }, testInfo) => {
      test.setTimeout(60_000)
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
      await page.goto('/#/servers')
      const account = page.getByRole('button', { name: locale === 'zh-CN' ? '账号菜单' : 'Account menu', exact: true })
      const menu = page.locator('.console-account-menu')
      for (const [width, height] of sizes) {
        await page.setViewportSize({ width, height })
        await expect(account).toHaveAttribute('aria-haspopup', 'menu')
        await expect(account).toHaveAttribute('aria-expanded', 'false')
        await account.focus()
        await page.keyboard.press('Enter')
        await expectInViewportAndUnobscured(menu)
        await expect(account).toHaveAttribute('aria-expanded', 'true')
        await expect(menu).toContainText('synthetic-auditor')
        await page.screenshot({ path: testInfo.outputPath(`account-${locale}-${theme}-${width}x${height}.png`) })
        await page.keyboard.press('Escape')
        await expect(menu).toHaveCount(0)
        await expect(account).toBeFocused()
        await expect(account).toHaveAttribute('aria-expanded', 'false')
        await account.click()
        await expect(menu).toBeVisible()
        await account.click()
        await expect(menu).toHaveCount(0)
        await account.click()
        await expect(menu).toBeVisible()
        await page.locator('.console-context').click()
        await expect(menu).toHaveCount(0)
      }
      await account.click()
      await expect(menu).toBeVisible()
      await page.locator('[data-console-nav="desktop"] a[href="#/tools"]').click()
      await expect(page).toHaveURL(/\/#\/tools$/)
      await expect(menu).toHaveCount(0)
      await expect(account).toHaveAttribute('aria-expanded', 'false')
    })
  }
}

test('@smoke @full @account-menu an account action closes the menu and restores its trigger', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 640, height: 900 })
  await page.goto('/#/servers')
  const account = page.getByRole('button', { name: 'Account menu', exact: true })
  const menu = page.locator('.console-account-menu')
  await account.click()
  await expect(menu).toBeVisible()
  const popup = page.waitForEvent('popup')
  await menu.getByRole('menuitem', { name: 'OpenAPI', exact: true }).click()
  const docs = await popup
  await expect(docs).toHaveURL(/\/docs$/)
  await docs.close()
  await expect(menu).toHaveCount(0)
  await expect(account).toBeFocused()
  await expect(account).toHaveAttribute('aria-expanded', 'false')
})

test('@smoke @full @account-menu disabled authentication does not offer sign out', async ({ page }) => {
  await login(page)
  await page.route('**/v1/auth/me', route => route.fulfill({ json: {
    id: 'synthetic-disabled', username: 'synthetic-disabled', display_name: 'Synthetic disabled',
    role: 'viewer', roles: [], permissions: ['*'], status: 'active',
    must_change_password: false, auth_type: 'disabled', scopes: [],
  } }))
  await page.goto('/#/servers')
  await page.getByRole('button', { name: 'Account menu', exact: true }).click()
  await expect(page.locator('.console-account-menu')).toBeVisible()
  await expect(page.getByText('Sign out', { exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Account menu', exact: true })).toBeFocused()
})

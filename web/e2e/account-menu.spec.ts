import { test, expect } from '@playwright/test'
import { expectInViewportAndUnobscured, login } from './helpers'

for (const locale of ['zh-CN', 'en-US'] as const) for (const theme of ['light', 'dark'] as const) {
  test(`@smoke @account-menu keyboard, outside click and direct navigation ${locale} ${theme}`, async ({ page }) => {
    await login(page)
    await page.addInitScript(({ locale, theme }) => {
      localStorage.setItem('lingshu-gate-console-locale', locale)
      localStorage.setItem('lingshu-gate-console-theme', theme)
    }, { locale, theme })
    await page.goto('/#/tools')
    const account = page.getByRole('button', { name: locale === 'zh-CN' ? '账号菜单' : 'Account menu', exact: true })
    const menu = page.locator('.console-account-menu')
    for (const [width, height] of [[1600,900], [1920,1080], [2560,1080], [2560,1440]]) {
      await page.setViewportSize({ width, height })
      await account.focus(); await page.keyboard.press('Enter')
      await expectInViewportAndUnobscured(menu)
      await expect(menu.getByRole('menuitemradio')).toHaveCount(2)
      await expect(menu.locator('.console-account-identity')).toContainText('admin')
      await page.keyboard.press('Escape')
      await expect(menu).toHaveCount(0); await expect(account).toBeFocused()
      await account.click()
      await page.locator('main h1').click()
      await expect(menu).toHaveCount(0)
    }
    await account.click()
    await page.locator('[data-console-nav="desktop"] a[href="#/myServers"]').click()
    await expect(page).toHaveURL(/#\/myServers$/)
    await expect(menu).toHaveCount(0)
  })
}
test('@smoke @account-menu infrequent actions remain accessible on mobile', async ({ page }) => {
  await login(page); await page.setViewportSize({ width:640,height:900 }); await page.goto('/#/tools')
  const account = page.getByRole('button', {name:'Account menu',exact:true})
  await account.click()
  const menu = page.locator('.console-account-menu')
  const [docs] = await Promise.all([page.waitForEvent('popup'), menu.getByRole('menuitem',{name:'OpenAPI',exact:true}).click()])
  await expect(docs).toHaveURL(/\/docs$/); await docs.close()
  await expect(menu).toHaveCount(0); await expect(account).toBeFocused()
})

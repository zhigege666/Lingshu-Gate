import { test, expect, type Page } from '@playwright/test'
import { expectInViewportAndUnobscured, login } from './helpers'

const sizes = [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]] as const

type AccountFrameQueue = { hold: () => void; advance: () => void }
declare global {
  interface Window { gateAccountFrameQueue: AccountFrameQueue }
}

// Hold and advance the browser frame queue to exercise close before deferred
// autofocus. This controls ordering without sleeping or changing dependencies.
async function controlAccountFrames(page: Page) {
  await page.addInitScript(() => {
    const requestFrame = window.requestAnimationFrame.bind(window)
    const cancelFrame = window.cancelAnimationFrame.bind(window)
    const pending = new Map<number, FrameRequestCallback>()
    let held = false
    let nextId = 0
    window.requestAnimationFrame = callback => {
      if (!held) return requestFrame(callback)
      const id = --nextId
      pending.set(id, callback)
      return id
    }
    window.cancelAnimationFrame = id => {
      if (id < 0) pending.delete(id)
      else cancelFrame(id)
    }
    window.gateAccountFrameQueue = {
      hold: () => { held = true },
      advance: () => {
        const callbacks = [...pending.values()]
        pending.clear()
        callbacks.forEach(callback => callback(performance.now()))
      },
    }
  })
}

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
        role: 'admin', roles: ['admin', 'operator', 'viewer', 'admin', '', 'synthetic-auditor', 'synthetic-auditor'], permissions: ['*'],
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
        const roles = locale === 'zh-CN' ? '管理员, 运维人员, 只读观察者, synthetic-auditor' : 'Administrator, Operator, Viewer, synthetic-auditor'
        await expect(menu.getByRole('menuitem', { name: `Synthetic account · ${roles}`, exact: true })).toHaveCount(1)
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
  // Existing decorative icons contribute an "api" prefix to this menu item's name.
  const action = menu.getByRole('menuitem', { name: /(?:^| )OpenAPI$/ })
  const [docs] = await Promise.all([page.waitForEvent('popup'), action.click()])
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
  await expect(page.locator('.console-account-menu').getByRole('menuitem', { name: 'Synthetic disabled · Viewer', exact: true })).toHaveCount(1)
  await expect(page.getByText('Sign out', { exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Account menu', exact: true })).toBeFocused()
})

for (const locale of ['en-US', 'zh-CN'] as const) {
  test(`@smoke @full @account-menu blank role lists use the localized primary role: ${locale}`, async ({ page }) => {
    await login(page)
    await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
    await page.route('**/v1/auth/me', route => route.fulfill({ json: {
      id: 'synthetic-empty-roles', username: 'synthetic-empty-roles', display_name: 'Synthetic roles',
      role: 'operator', roles: ['', '', ''], permissions: ['*'], status: 'active',
      must_change_password: false, auth_type: 'session', scopes: [],
    } }))
    await page.goto('/#/servers')
    const account = page.getByRole('button', { name: locale === 'zh-CN' ? '账号菜单' : 'Account menu', exact: true })
    await account.click()
    await expect(page.locator('.console-account-menu').getByRole('menuitem', { name: `Synthetic roles · ${locale === 'zh-CN' ? '运维人员' : 'Operator'}`, exact: true })).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(account).toBeFocused()
  })
}

for (const locale of ['en-US', 'zh-CN'] as const) {
  for (const width of [1280, 640]) {
    for (const openFrames of [0, 1, 2]) {
      test(`@smoke @full @account-menu close before autofocus preserves focus: ${locale} ${width}px frame ${openFrames}`, async ({ page }) => {
        await login(page)
        await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
        await controlAccountFrames(page)
        await page.setViewportSize({ width, height: 720 })
        await page.goto('/#/servers')
        const account = page.getByRole('button', { name: locale === 'zh-CN' ? '账号菜单' : 'Account menu', exact: true })
        const menu = page.locator('.console-account-menu')
        await expect(account).toHaveAttribute('aria-expanded', 'false')
        await page.evaluate(() => window.gateAccountFrameQueue.hold())
        await account.focus()
        await page.keyboard.press('Enter')
        await expect(menu.getByRole('menuitem', { name: /(?:^| )OpenAPI$/ })).toHaveCount(1)
        await expect(account).toHaveAttribute('aria-expanded', 'true')
        for (let frame = 0; frame < openFrames; frame++) {
          await page.evaluate(() => window.gateAccountFrameQueue.advance())
        }
        await page.keyboard.press('Escape')
        await expect(account).toHaveAttribute('aria-expanded', 'false')
        await expect(account).toBeFocused()
        for (let frame = 0; frame < 6; frame++) {
          await page.evaluate(() => window.gateAccountFrameQueue.advance())
        }
        await expect(account).toBeFocused()
        // Normal open autofocus still works once its scheduled frames run.
        await page.keyboard.press('Enter')
        await expect(account).toHaveAttribute('aria-expanded', 'true')
        for (let frame = 0; frame < 3; frame++) {
          await page.evaluate(() => window.gateAccountFrameQueue.advance())
        }
        await expect(menu.getByRole('menuitem', { name: /(?:^| )OpenAPI$/ })).toBeFocused()
        await page.keyboard.press('Escape')
        await expect(account).toBeFocused()
      })
    }
  }
}

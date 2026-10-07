import { test, expect, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expectInViewportAndUnobscured } from './helpers'

const sizes = [{ width: 1600, height: 900 }, { width: 1920, height: 1080 }, { width: 2560, height: 1080 }, { width: 2560, height: 1440 }]
type Locale = 'en-US' | 'zh-CN'
type Theme = 'light' | 'dark'

async function initialize(page: Page, locale: Locale, theme: Theme) {
  await page.addInitScript(({ locale, theme }) => {
    localStorage.setItem('lingshu-gate-console-locale', locale)
    localStorage.setItem('lingshu-gate-console-theme', theme)
  }, { locale, theme })
}

function versionBadge(page: Page) { return page.locator('[data-gate-version]:visible') }

async function geometry(page: Page) {
  await expectInViewportAndUnobscured(versionBadge(page))
  expect(await page.evaluate(() => ({
    width: document.documentElement.scrollWidth <= innerWidth,
    height: document.documentElement.scrollHeight <= innerHeight,
  }))).toEqual({ width: true, height: true })
  expect(await versionBadge(page).evaluate(element => {
    const style = getComputedStyle(element)
    const rgb = (value: string) => value.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => {
      const channel = value / 255
      return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
    })
    const luminance = (value: string) => { const [r, g, b] = rgb(value); return .2126 * r + .7152 * g + .0722 * b }
    const foreground = luminance(style.color), background = luminance(style.backgroundColor)
    return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05)
  })).toBeGreaterThanOrEqual(4.5)
}

async function capture(page: Page, name: string, state: string, metadataMocked = false) {
  const directory = process.env.GATE_LOGIN_SCREENSHOT_DIR
  if (!directory) return
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: join(directory, `${name}.png`), animations: 'disabled' })
  writeFileSync(join(directory, `${name}.json`), JSON.stringify({ viewport: page.viewportSize(), state, metadataMocked, observedVersion: await versionBadge(page).textContent() }, null, 2))
}

for (const size of sizes) for (const locale of ['en-US', 'zh-CN'] as const) for (const theme of ['light', 'dark'] as const) {
  const suffix = `${locale}-${theme}-${size.width}x${size.height}`
  test(`runtime login/register version ${suffix}`, async ({ page }) => {
    await page.setViewportSize(size)
    await initialize(page, locale, theme)
    const backend = await (await page.request.get('/healthz')).json()
    let reads = 0
    page.on('request', request => { if (new URL(request.url()).pathname === '/healthz') reads++ })
    await page.goto('/console/')
    const text = `${locale === 'zh-CN' ? '版本' : 'Version'} v${backend.version}`
    await expect(versionBadge(page)).toHaveText(text)
    await geometry(page)
    await capture(page, `login-${suffix}`, 'actual anonymous login; no API mocks')
    await page.getByRole('button', { name: locale === 'zh-CN' ? '还没有账号？注册' : 'Need an account? Register', exact: true }).click()
    await expect(versionBadge(page)).toHaveText(text)
    await geometry(page)
    await expectInViewportAndUnobscured(page.getByLabel(locale === 'zh-CN' ? '确认密码' : 'Confirm password', { exact: true }))
    await capture(page, `register-${suffix}`, 'actual registration form; no submission or API mocks')
    await page.getByRole('button', { name: locale === 'zh-CN' ? '已有账号？返回登录' : 'Already registered? Sign in', exact: true }).click()
    expect(reads).toBe(1)
    await page.getByLabel(locale === 'zh-CN' ? '用户名' : 'Username', { exact: true }).fill('admin')
    await page.getByLabel(locale === 'zh-CN' ? '密码' : 'Password', { exact: true }).fill('Synthetic-admin-123!')
    await page.getByRole('button', { name: locale === 'zh-CN' ? '登录' : 'Sign in', exact: true }).click()
    await expect(page.locator('main')).toBeVisible()
    await expect(page.locator('.console-version')).toHaveText(`v${backend.version}`)
  })

  test(`metadata failure keeps login/register usable ${suffix}`, async ({ page }) => {
    await page.setViewportSize(size)
    await initialize(page, locale, theme)
    let reads = 0
    await page.route('**/healthz', route => {
      reads++
      return route.fulfill({ status: 503, json: { version: '9.8.7', detail: 'SYNTHETIC_DIAGNOSTIC_NOT_FOR_VERSION' } })
    })
    await page.goto('/console/')
    const text = locale === 'zh-CN' ? '版本不可用' : 'Version unavailable'
    await expect(versionBadge(page)).toHaveText(text)
    await geometry(page)
    await capture(page, `unavailable-${suffix}`, 'synthetic metadata HTTP 503; actual anonymous session and login controls', true)
    await page.getByRole('button', { name: locale === 'zh-CN' ? '还没有账号？注册' : 'Need an account? Register', exact: true }).click()
    await expect(versionBadge(page)).toHaveText(text)
    await geometry(page)
    await page.getByRole('button', { name: locale === 'zh-CN' ? '已有账号？返回登录' : 'Already registered? Sign in', exact: true }).click()
    await page.getByLabel(locale === 'zh-CN' ? '用户名' : 'Username', { exact: true }).fill('admin')
    await page.getByLabel(locale === 'zh-CN' ? '密码' : 'Password', { exact: true }).fill('Synthetic-admin-123!')
    await expectInViewportAndUnobscured(page.getByRole('button', { name: locale === 'zh-CN' ? '登录' : 'Sign in', exact: true }))
    await expect(page.getByRole('button', { name: locale === 'zh-CN' ? '登录' : 'Sign in', exact: true })).toBeEnabled()
    await expect(page.locator('body')).not.toContainText('SYNTHETIC_DIAGNOSTIC_NOT_FOR_VERSION')
    expect(reads).toBe(1)
  })
}

for (const locale of ['en-US', 'zh-CN'] as const) for (const theme of ['light', 'dark'] as const) {
  test(`pending version does not block real login and times out ${locale} ${theme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    await initialize(page, locale, theme)
    let reads = 0
    let release = async () => {}
    await page.route('**/healthz', route => {
      if (++reads > 1) return route.continue()
      return new Promise<void>(resolve => {
        release = async () => { await route.fulfill({ json: { version: '9.8.7' } }).catch(() => {}); resolve() }
      })
    })
    try {
      await page.goto('/console/')
      await expect(versionBadge(page)).toHaveText(locale === 'zh-CN' ? '正在读取版本…' : 'Reading version…')
      await capture(page, `loading-${locale}-${theme}-1920x1080`, 'held synthetic metadata; actual anonymous session and login controls', true)
      await page.getByLabel(locale === 'zh-CN' ? '用户名' : 'Username', { exact: true }).fill('admin')
      await page.getByLabel(locale === 'zh-CN' ? '密码' : 'Password', { exact: true }).fill('Synthetic-admin-123!')
      await page.getByRole('button', { name: locale === 'zh-CN' ? '登录' : 'Sign in', exact: true }).click()
      await expect(page.locator('main')).toBeVisible()
      await expect(page.locator('.console-version')).toHaveText(locale === 'zh-CN' ? '版本不可用' : 'Version unavailable')
      await release()
      await expect(page.locator('.console-version')).not.toContainText('9.8.7')
      expect(reads).toBe(2) // One version read; one existing authenticated dashboard health read.
    } finally { await release() }
  })
}

test('backend version wins over the Console build version and long prereleases remain visible', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await initialize(page, 'en-US', 'dark')
  const version = `9.8.7-${'a'.repeat(90)}`
  await page.route('**/healthz', route => route.fulfill({ json: { version } }))
  await page.goto('/console/')
  await expect(versionBadge(page)).toHaveText(`Version v${version}`)
  await geometry(page)
  await page.getByLabel('Username', { exact: true }).fill('admin')
  await page.getByLabel('Password', { exact: true }).fill('Synthetic-admin-123!')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.locator('.console-version')).toHaveText(`v${version}`)
})

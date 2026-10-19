import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'

// Synthetic presentation fixtures only; never contact a Git host/proxy or install tools.
const profile = { id: 'synthetic-network', name: 'Synthetic network', version: 3, enabled: true, scheme: 'https', endpoint_masked: '***', credential_ref: null, credential_configured: false }
const settings = { revision: 5, profiles: [profile], defaults: { git: { mode: 'direct' }, install: { mode: 'direct' }, npm_registry: 'https://registry.npmjs.org/', python_index: 'https://pypi.org/simple/', npm_credential_ref: null, python_credential_ref: null, git_hosts: [{ host: 'github.com', port: 443, private_cidrs: [] }] }, executor: { available: false, code: 'safe_executor_unavailable' } }

for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) {
  for (const locale of ['en-US', 'zh-CN']) {
    test(`system settings and lossless Git network selection ${locale} ${width}x${height}`, async ({ page }) => {
      await login(page)
      await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
      await page.setViewportSize({ width, height })
      const writes: string[] = []
      await page.route('**/v1/**', async route => {
        const path = new URL(route.request().url()).pathname
        if (route.request().method() !== 'GET') {
          writes.push(path)
          return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in layout/selection scenario' } })
        }
        if (path === '/v1/system-settings/network' || path === '/v1/network/options') return route.fulfill({ json: settings })
        if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads: [] } })
        if (path === '/v1/builds') return route.fulfill({ json: { builds: [] } })
        if (path === '/v1/deployments') return route.fulfill({ json: { deployments: [] } })
        return route.continue()
      })
      const zh = locale === 'zh-CN'
      await page.goto('/console/#/systemSettings')
      await expect(page.getByRole('tab', { name: zh ? '网络与依赖' : 'Network and dependencies' })).toHaveAttribute('aria-selected', 'true')
      await expectInViewportAndUnobscured(page.getByRole('button', { name: zh ? '新增配置' : 'New profile', exact: true }))
      await expect(page.getByText('Synthetic network', { exact: true })).toBeVisible()
      await expect(page.getByText(/safe_executor_unavailable/)).toHaveCount(0) // Friendly explanation precedes transport details.
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
      await page.goto('/console/#/uploads')
      await page.getByText(zh ? 'Git 仓库' : 'Git repository', { exact: true }).click()
      const repository = page.getByLabel(zh ? '仓库 URL（HTTPS）' : 'Repository URL (HTTPS)', { exact: true })
      await repository.fill('https://github.com/synthetic/example')
      await page.getByLabel(zh ? '项目子目录' : 'Project subdirectory', { exact: true }).fill('packages/server')
      await page.getByRole('button', { name: zh ? '网络设置' : 'Network settings', exact: true }).click()
      const drawer = page.getByRole('dialog', { name: zh ? '系统设置 · 网络与依赖' : 'System settings · Network and dependencies', exact: true })
      await expect(drawer.getByText('Synthetic network', { exact: true })).toBeVisible()
      await drawer.getByRole('button', { name: zh ? '关闭' : 'Close', exact: true }).click()
      await expect(repository).toHaveValue('https://github.com/synthetic/example')
      await expect(page.getByLabel(zh ? '项目子目录' : 'Project subdirectory', { exact: true })).toHaveValue('packages/server')
      await expectInViewportAndUnobscured(page.getByRole('button', { name: zh ? '检查并生成计划' : 'Inspect and plan', exact: true }))
      expect(writes).toEqual([])
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    })
  }
}

test('Git execution blocker keeps source inputs and dispatches no import/build/start', async ({ page }) => {
  await login(page)
  const mutations: string[] = []
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') {
      mutations.push(path)
      if (path === '/v1/projects/git/plan') return route.fulfill({ json: { status: 'blocked', commit_sha: null, validation: { ok: false }, error: { code: 'safe_executor_unavailable', message: 'Reviewed executor unavailable', next_action: 'Install and validate a dedicated executor' } } })
      return route.fulfill({ status: 500, json: { detail: 'Unexpected execution mutation' } })
    }
    if (path === '/v1/network/options') return route.fulfill({ json: settings })
    if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads: [] } })
    if (path === '/v1/builds') return route.fulfill({ json: { builds: [] } })
    if (path === '/v1/deployments') return route.fulfill({ json: { deployments: [] } })
    return route.continue()
  })
  await page.goto('/console/#/uploads')
  await page.getByText('Git repository', { exact: true }).click()
  const repository = page.getByLabel('Repository URL (HTTPS)', { exact: true })
  await repository.fill('https://github.com/synthetic/example')
  await page.getByRole('button', { name: 'Inspect and plan', exact: true }).click()
  await expect(page.getByText(/safe_executor_unavailable/)).toBeVisible()
  await expect(repository).toHaveValue('https://github.com/synthetic/example')
  expect(mutations).toEqual(['/v1/projects/git/plan'])
  await expect(page.getByRole('button', { name: 'Confirm and acquire snapshot', exact: true })).toHaveCount(0)
})

test('nested network profile dialog preserves a rejected close and restores focus through the settings dialog', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  const mutations: string[] = []
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') {
      mutations.push(path)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    }
    if (path === '/v1/system-settings/network' || path === '/v1/network/options') return route.fulfill({ json: settings })
    if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads: [] } })
    if (path === '/v1/builds') return route.fulfill({ json: { builds: [] } })
    if (path === '/v1/deployments') return route.fulfill({ json: { deployments: [] } })
    return route.continue()
  })
  await page.goto('/console/#/uploads')
  await page.getByText('Git repository', { exact: true }).click()
  const openSettings = page.getByRole('button', { name: 'Network settings', exact: true })
  await openSettings.click()
  const settingsDialog = page.getByRole('dialog', { name: 'System settings · Network and dependencies', exact: true })
  const newProfile = settingsDialog.getByRole('button', { name: 'New profile', exact: true })
  await newProfile.click()
  const profileDialog = page.getByRole('dialog', { name: 'New proxy profile', exact: true })
  await profileDialog.getByRole('textbox', { name: 'Profile name', exact: true }).fill('Synthetic unsaved profile')
  await profileDialog.press('Escape')
  const discard = page.getByRole('alertdialog', { name: 'Discard unsaved network configuration?', exact: true })
  await expect(discard).toBeVisible()
  await discard.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(profileDialog.getByRole('textbox', { name: 'Profile name', exact: true })).toHaveValue('Synthetic unsaved profile')
  await expect(profileDialog.getByRole('button', { name: 'Save', exact: true })).toBeVisible()
  // Restoring the baseline closes without a destructive confirmation or write.
  await profileDialog.getByRole('textbox', { name: 'Profile name', exact: true }).fill('')
  await profileDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(profileDialog).toHaveCount(0)
  await expect(newProfile).toBeFocused()
  await settingsDialog.getByRole('button', { name: 'Back to import', exact: true }).click()
  await expect(settingsDialog).toHaveCount(0)
  await expect(openSettings).toBeFocused()
  expect(mutations).toEqual([])
})

test('network profile save stays pending through a slow refresh and returns focus to the enabled trigger', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  const savedProfile = { ...profile, id: 'synthetic-saved-network', name: 'Synthetic saved profile', version: 1 }
  const refreshedSettings = { ...settings, revision: 6, profiles: [...settings.profiles, savedProfile] }
  const mutations: string[] = []
  let saved = false
  let refreshStarted = false
  let releaseRefresh: () => void = () => {}
  const refresh = new Promise<void>(resolve => { releaseRefresh = resolve })
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (method !== 'GET') {
      mutations.push(path)
      if (method === 'POST' && path === '/v1/system-settings/network/profiles') {
        saved = true
        return route.fulfill({ json: savedProfile })
      }
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    }
    if (path === '/v1/system-settings/network') {
      if (saved) { refreshStarted = true; await refresh }
      return route.fulfill({ json: saved ? refreshedSettings : settings })
    }
    if (path === '/v1/network/options') return route.fulfill({ json: saved ? refreshedSettings : settings })
    if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads: [] } })
    if (path === '/v1/builds') return route.fulfill({ json: { builds: [] } })
    if (path === '/v1/deployments') return route.fulfill({ json: { deployments: [] } })
    return route.continue()
  })
  try {
    await page.goto('/console/#/uploads')
    await page.getByText('Git repository', { exact: true }).click()
    await page.getByRole('button', { name: 'Network settings', exact: true }).click()
    const settingsDialog = page.getByRole('dialog', { name: 'System settings · Network and dependencies', exact: true })
    const newProfile = settingsDialog.getByRole('button', { name: 'New profile', exact: true })
    await newProfile.click()
    const profileDialog = page.getByRole('dialog', { name: 'New proxy profile', exact: true })
    await profileDialog.getByRole('textbox', { name: 'Profile name', exact: true }).fill(savedProfile.name)
    await profileDialog.getByPlaceholder('http://proxy.example.invalid:8080', { exact: true }).fill('https://proxy.example.invalid:8443')
    await profileDialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => refreshStarted).toBe(true)
    await expect(profileDialog).toHaveAttribute('aria-busy', 'true')
    await expect(profileDialog.getByRole('button', { name: 'Close', exact: true })).toBeDisabled()
    await expect(profileDialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled()
    await profileDialog.press('Escape')
    await expect(profileDialog).toBeVisible()
    releaseRefresh()
    await expect(profileDialog).toHaveCount(0)
    await expect(newProfile).toBeEnabled()
    await expect(newProfile).toBeFocused()
    await expect(settingsDialog.getByText(savedProfile.name, { exact: true })).toBeVisible()
    expect(mutations).toEqual(['/v1/system-settings/network/profiles'])
  } finally {
    releaseRefresh()
  }
})

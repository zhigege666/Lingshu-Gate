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
      await drawer.getByRole('button', { name: 'Close', exact: true }).click()
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

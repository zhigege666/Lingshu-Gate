import { test, expect } from '@playwright/test'
import { login } from './helpers'
import { grants, roles, tools, users } from './synthetic-data'

const groups = ['builtin', 'gate-control', 'gate-delivery', 'gate-tool-files']
const definitions = groups.map((serverId, i) => ({
  ...tools[i], id: `synthetic-builtin-${i}`, name: `Synthetic built-in ${i}`,
  source: 'builtin', metadata: { ...tools[i].metadata, server_id: serverId },
}))
const spoof = { ...tools[4], id: 'gate_synthetic_spoof', name: 'Synthetic third-party', metadata: { ...tools[4].metadata, server_id: 'gate-control' } }
const resources = [...definitions, spoof].map(tool => ({
  server_id: tool.metadata.server_id, tool_id: tool.id, tool_name: tool.name,
  registry_source: tool.source, classification: 'read', classification_status: 'published',
}))
const syntheticGrants = resources.map((resource, i) => ({
  ...grants[i], id: `synthetic-origin-grant-${i}`, server_id: resource.server_id, tool_id: resource.tool_id,
}))

for (const locale of ['en-US', 'zh-CN'] as const) {
  test(`E2E-218 @full ${locale} origin labels distinguish registry-builtins from an ID lookalike without mutations`, async ({ page }, testInfo) => {
    await login(page)
    await page.addInitScript(locale => {
      localStorage.setItem('lingshu-gate-console-locale', locale)
      localStorage.setItem('lingshu-gate-console-theme', locale === 'zh-CN' ? 'dark' : 'light')
    }, locale)
    let writes = 0
    const fixture: Record<string, unknown> = {
      '/v1/tools': [...definitions, spoof],
      '/v1/access/resources': { resources },
      '/v1/access/subjects': { users, roles },
      '/v1/access/grants': { grants: syntheticGrants },
    }
    await page.route('**/v1/**', route => {
      if (route.request().method() !== 'GET') {
        writes++
        return route.fulfill({ status: 500, json: { detail: 'Unexpected origin-label write' } })
      }
      const data = fixture[new URL(route.request().url()).pathname]
      return data === undefined ? route.fallback() : route.fulfill({ json: data })
    })
    const zh = locale === 'zh-CN'
    const names = zh ? ['Gate 基础能力', '工具审核管理', '项目交付与服务管理', '工具文件传输']
      : ['Gate core capabilities', 'Tool review management', 'Project delivery and service management', 'Tool file transfer']
    const badge = zh ? '系统内置' : 'Built in'
    await page.setViewportSize({ width: 1600, height: 900 })
    await page.goto('/console/#/tools')
    for (const name of names) await expect(page.locator('main').getByText(name, { exact: true })).toBeVisible()
    await expect(page.locator('main').getByText(badge, { exact: true })).toHaveCount(4)
    const thirdParty = page.locator('.tool-card').filter({ hasText: 'Synthetic third-party' })
    await expect(thirdParty.getByText(badge, { exact: true })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('tool-origin-labels.png') })
    await page.goto('/console/#/accessGrants')
    for (const name of names) await expect(page.locator('main').getByText(name, { exact: true })).toBeVisible()
    await expect(page.locator('main').getByText(badge, { exact: true })).toHaveCount(4)
    const thirdPartyGrant = page.getByRole('row').filter({ hasText: spoof.id })
    await expect(thirdPartyGrant.getByText('gate-control', { exact: true })).toBeVisible()
    await expect(thirdPartyGrant.getByText(badge, { exact: true })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('grant-origin-labels.png') })
    expect(writes).toBe(0)
  })
}

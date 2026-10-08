import { test, expect } from '@playwright/test'
import { login } from './helpers'
import { classifications, listFixtures } from './synthetic-data'

for (const locale of ['en-US', 'zh-CN']) {
  test(`@smoke @full @classification-change field and legacy drift reasons: ${locale}`, async ({ page }) => {
    await login(page)
    await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
    const items = [
      { ...classifications[0], tool_name: 'Synthetic contract drift', status: 'stale', effective_access: 'unknown', evidence: { invalidation: { reason: 'tool_definition_changed', changed_fields: ['input_schema', 'output_schema'] } } },
      { ...classifications[1], tool_name: 'Synthetic legacy drift', status: 'stale', effective_access: 'unknown', evidence: { invalidation: { reason: 'tool_definition_changed', previous_definition_unrecorded: true, output_schema_recorded: true } } },
      { ...classifications[2], tool_name: 'Synthetic catalog removal', status: 'stale', effective_access: 'unknown', evidence: { lifecycle: { reason: 'missing_from_latest_tools_list' } } },
    ]
    const mutations: string[] = []
    await page.route('**/v1/**', route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (request.method() !== 'GET') {
        mutations.push(`${request.method()} ${path}`)
        return route.fulfill({ status: 500, json: { detail: 'Unexpected classification mutation' } })
      }
      if (path === '/v1/access/tool-classifications') return route.fulfill({ json: { classifications: items } })
      if (path in listFixtures) return route.fulfill({ json: listFixtures[path] })
      return route.continue()
    })
    await page.goto('/#/toolClassifications')
    const row = (name: string) => page.locator('tbody tr').filter({ hasText: name })
    await expect(row('Synthetic contract drift')).toContainText(locale === 'zh-CN' ? '输入契约、输出契约已变更，需重新审核并发布。' : 'input contract, output contract changed; review and publish again.')
    await expect(row('Synthetic legacy drift')).toContainText(locale === 'zh-CN' ? '现已记录输出契约' : 'the output contract is now recorded')
    await expect(row('Synthetic legacy drift')).toContainText(locale === 'zh-CN' ? '无法还原逐字段差异' : 'field differences are unavailable')
    await expect(row('Synthetic catalog removal')).toContainText(locale === 'zh-CN' ? '最新目录中已移除' : 'Removed from latest catalog')
    expect(mutations).toEqual([])
  })
}

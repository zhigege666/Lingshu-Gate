import { test, expect, type Locator } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { classifications, listFixtures } from './synthetic-data'

async function expectActionFitsRows(action: Locator) {
  await expectInViewportAndUnobscured(action)
  await expect.poll(() => action.evaluate(button => {
    const viewport = button.closest('.bounded-list-scroll')!
    const cell = button.closest('td')!
    const bounds = button.getBoundingClientRect(), rows = viewport.getBoundingClientRect(), column = cell.getBoundingClientRect()
    return bounds.left >= rows.left && bounds.right <= rows.right + .5
      && bounds.left >= column.left && bounds.right <= column.right + .5
  })).toBe(true)
}

for (const locale of ['en-US', 'zh-CN']) {
  test(`output contract drift and legacy comparison limits are visible ${locale}`, async ({ page }, info) => {
    await login(page)
    await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
    await page.setViewportSize({ width: 1600, height: 900 })
    const rows = classifications.slice(0, 2).map((item, index) => ({ ...item, status: 'stale', effective_access: 'unknown',
      evidence: { invalidation: { reason: 'tool_definition_changed', changed_fields: index === 0 ? ['output_schema'] : [], previous_definition_unrecorded: index === 1, output_schema_recorded: true } } }))
    const writes: string[] = []
    await page.route('**/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (request.method() !== 'GET') { writes.push(path); return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in contract explanation' } }) }
      if (path === '/v1/access/tool-classifications') return route.fulfill({ json: { classifications: rows } })
      if (path in listFixtures) return route.fulfill({ json: listFixtures[path] })
      return route.continue()
    })
    await page.goto('/console/#/toolClassifications')
    const changed = page.getByText(locale === 'zh-CN' ? '输出契约已变更，需重新审核并发布。' : 'output contract changed; review and publish again.', { exact: true })
    const legacy = page.getByText(locale === 'zh-CN' ? '定义已变更；现已记录输出契约。旧版未记录字段摘要，无法还原逐字段差异；需重新审核并发布。' : 'Definition changed; the output contract is now recorded. Previous field digests were not recorded; field differences are unavailable. Review and publish again.', { exact: true })
    await expectInViewportAndUnobscured(changed)
    await expectInViewportAndUnobscured(legacy)
    for (const reason of [changed, legacy]) {
      await expect.poll(() => reason.evaluate(element => {
        const style = getComputedStyle(element)
        return style.whiteSpace === 'normal' && element.scrollWidth <= element.clientWidth + 1
          && element.scrollHeight <= element.clientHeight + 1
      })).toBe(true)
    }
    await page.screenshot({ path: info.outputPath(`output-contract-drift-${locale}.png`) })
    expect(writes).toHaveLength(0)
  })
}

// Synthetic presentation data over actual isolated sign-in; no review is submitted.
for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) {
  for (const locale of ['en-US', 'zh-CN']) {
    test(`classification review actions fit and remain reachable ${locale} ${width}x${height}`, async ({ page }) => {
      await login(page)
      await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
      await page.setViewportSize({ width, height })
      const mutations: string[] = []
      await page.route('**/v1/**', async route => {
        const request = route.request(), path = new URL(request.url()).pathname
        if (request.method() !== 'GET') {
          mutations.push(`${request.method()} ${path}`)
          return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in action-layout regression' } })
        }
        if (path === '/v1/access/tool-classifications') return route.fulfill({ json: { classifications: classifications.slice(0, 51) } })
        if (path in listFixtures) return route.fulfill({ json: listFixtures[path] })
        return route.continue()
      })
      await page.goto('/console/#/toolClassifications')
      const rows = page.locator('.tool-review-content .bounded-list-scroll')
      const action = rows.getByRole('button', { name: locale === 'zh-CN' ? '人工确认' : 'Human review', exact: true }).first()
      await expectActionFitsRows(action)
      await rows.evaluate(element => { element.scrollLeft = element.scrollWidth })
      await expectActionFitsRows(action)
      await action.click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await dialog.getByRole('button', { name: locale === 'zh-CN' ? '取消' : 'Cancel', exact: true }).last().click()
      await expect(dialog).toHaveCount(0)
      expect(mutations).toEqual([])
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    })
  }
}

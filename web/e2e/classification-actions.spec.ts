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

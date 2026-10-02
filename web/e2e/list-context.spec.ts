import { test, expect } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers, tools, classifications, credentials, listFixtures } from './synthetic-data'

const matrix = process.env.GATE_LIST_LAYOUT_MATRIX === '1'
const sizes = matrix ? [[2048, 1119], [1366, 768], [390, 844]] : [[1280, 600]]
for (const [width, height] of sizes) {
const cases = [
  ['configs', 'synthetic-config-99'], ['credentials', 'Synthetic credential 199'],
  ['runtimeCache', 'synthetic-cache-99'], ['accessUsers', 'synthetic-user-199'],
  ['accessRoles', 'Synthetic role 59'], ['accessGrants', 'synthetic-service-099'],
  ['toolClassifications', 'Synthetic tool 4999'], ['invocationAudit', 'synthetic-correlation-199'],
  ['personalTokens', 'Synthetic token 99'],
] as const
for (let index = 0; index < cases.length; index++) {
  const [view, query] = cases[index]
  test(`E2E-${401 + index} ${view} preserves context through middle/end/filter/page ${width}x${height} @list-context`, async ({ page }, testInfo) => {
    await login(page)
    if (matrix) await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width, height })
    const configs = Array.from({ length: 100 }, (_, i) => ({ id: `synthetic-config-${i}`, path: `/synthetic/config-${i}.json`, format: 'json', manifest: { id: `synthetic-config-${i}`, name: `Synthetic config ${i}`, enabled: false, launch: { type: 'remote' }, transport: { type: 'streamable_http', url: 'http://127.0.0.1:1/mcp' } } }))
    const fixtures: Record<string, unknown> = { ...listFixtures, '/v1/mcp/servers': { servers, load_errors: [] }, '/v1/tools': tools, '/v1/credentials': credentials, '/v1/access/tool-classifications': { classifications }, '/v1/mcp/configs': { configs, errors: [] } }
    await page.route('**/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() === 'GET' && path in fixtures) await route.fulfill({ json: fixtures[path] })
      else await route.continue()
    })
    await page.goto(`/console/#/${view}`)
    const viewport = page.locator('.bounded-list-scroll:visible').first()
    const rows = viewport.locator('tbody tr')
    await expect(rows.first()).toContainText(/synthetic/i)
    const search = page.locator('main input[type="search"], main input[placeholder]').first()
    const next = page.getByRole('button', { name: matrix ? '下一页' : 'Next page', exact: true })
    const previous = page.getByRole('button', { name: matrix ? '上一页' : 'Previous page', exact: true })
    const header = width === 390 ? viewport.locator('thead th').first() : viewport.locator('thead')
    if (matrix) {
      await expect.poll(() => viewport.evaluate(el => {
        const owner = el.closest('.remaining-list-group, .maintenance-list-page, .tool-review-workspace')!
        const budget = Number.parseFloat(getComputedStyle(owner).maxHeight)
        const reserved = owner.getBoundingClientRect().height - el.getBoundingClientRect().height
        return Number.isFinite(budget) && el.clientHeight >= Math.min(el.scrollHeight, budget - reserved) - 2
      })).toBe(true)
    }
    await expectInViewportAndUnobscured(search)
    await expectInViewportAndUnobscured(next)
    if (matrix) {
      const action = rows.first().locator('td').last().getByRole('button').first()
      if (await action.count()) await expectInViewportAndUnobscured(action)
    }
    await page.screenshot({ path: testInfo.outputPath(`list-${view}-${width}x${height}.png`) })
    for (const fraction of [0, 0.5, 1]) {
      await viewport.evaluate((el, part) => { el.scrollTop = (el.scrollHeight - el.clientHeight) * part }, fraction)
      await expectInViewportAndUnobscured(header)
      await expectInViewportAndUnobscured(search)
      await expectInViewportAndUnobscured(next)
      if (matrix && fraction === 1) {
        const action = rows.last().locator('td').last().getByRole('button').first()
        if (await action.count()) await expectInViewportAndUnobscured(action)
      }
    }
    await page.screenshot({ path: testInfo.outputPath(`list-${view}-${width}x${height}-bottom.png`) })
    await next.click()
    await expect(previous).toBeEnabled()
    await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBe(0)
    await search.fill(query)
    await expect(previous).toHaveCount(0)
    await expect(rows.first()).toContainText(/synthetic/i)
    await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBe(0)
    await expectInViewportAndUnobscured(header)
    await search.fill('')
    // Clearing a filter may intentionally restore the prior page.
    await expect.poll(async () => (await next.isEnabled()) || (await previous.isEnabled())).toBe(true)
    expect(await rows.count()).toBeLessThanOrEqual(50)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

for (const [tab, query] of [['Build history', 'build-999'], ['Deployment history', 'deployment-499']]) {
  test(`E2E-${tab === 'Build history' ? 410 : 411} ${tab} exposes actions and keeps search/pager through scroll ${width}x${height} @list-context`, async ({ page }, testInfo) => {
    await login(page)
    if (matrix) await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width: matrix ? width : 1366, height: matrix ? height : 768 })
    await page.route('**/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() === 'GET' && path in listFixtures) await route.fulfill({ json: listFixtures[path] })
      else await route.continue()
    })
    await page.goto('/console/#/builds')
    await page.getByRole('tab', { name: new RegExp(matrix ? (tab === 'Build history' ? '构建记录' : '部署记录') : tab, 'i') }).click()
    const region = page.locator('.delivery-records-table')
    const rows = region.locator('tbody tr')
    await expect(rows.first()).toContainText(tab === 'Build history' ? 'build-' : 'synthetic-service')
    const search = page.locator('main input[placeholder]').first()
    const next = page.getByRole('button', { name: 'Next', exact: true })
    await expectInViewportAndUnobscured(next)
    await expectInViewportAndUnobscured(rows.first().getByRole('button', { name: matrix ? '查看' : 'View', exact: true }))
    if (matrix && width === 390) {
      await expectInViewportAndUnobscured(rows.first().locator('code').first())
      for (const action of await rows.first().locator('td').last().getByRole('button').all()) await expectInViewportAndUnobscured(action)
    }
    await page.screenshot({ path: testInfo.outputPath(`list-${tab.replace(' ', '-')}-${matrix ? width : 1366}x${matrix ? height : 768}.png`) })
    for (const fraction of [0.5, 1]) {
      await region.evaluate((el, part) => { el.scrollTop = (el.scrollHeight - el.clientHeight) * part }, fraction)
      if (matrix && width === 390) writeFileSync(testInfo.outputPath('delivery-column-geometry.json'), JSON.stringify(await region.evaluate(root => [root, root.querySelector('table')!, ...Array.from(root.querySelectorAll('thead th, tbody tr:first-child td'))].map(el => {
        const r = el.getBoundingClientRect(), css = getComputedStyle(el)
        const hits = [.15, .5, .85].map(x => document.elementFromPoint(r.left + r.width * x, r.top + r.height / 2)?.outerHTML.slice(0, 220))
        return { tag: el.tagName, text: el.textContent?.slice(0,100), rect: r.toJSON(), client: el.clientHeight, content: el.scrollHeight, overflow: css.overflow, position: css.position, hits }
      })), null, 2))
      await expectInViewportAndUnobscured(region.locator('thead th').first())
      await expectInViewportAndUnobscured(search)
      await expectInViewportAndUnobscured(next)
    }
    await next.click()
    await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeEnabled()
    await search.fill(query)
    await expect(rows).toHaveCount(1)
    await expect(rows.first().locator('code').first()).toHaveAttribute('title', query)
    await expectInViewportAndUnobscured(rows.first().getByRole('button', { name: matrix ? '查看' : 'View', exact: true }))
  })
}

}

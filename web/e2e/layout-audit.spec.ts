import { test, expect } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers, tools, credentials, listFixtures } from './synthetic-data'

// Explicit evidence collection, not a pass claim about layout or authorization.
const destination = process.env.GATE_LAYOUT_EVIDENCE_DIR
const verifyLayout = process.env.GATE_LAYOUT_ASSERT === '1'
for (const [width, height] of [[2048, 1222], [1366, 768], [390, 844], [1280, 600]]) {
  test(`Layout evidence ${width}x${height} @layout-evidence`, async ({ page }) => {
    test.skip(!destination, 'Set GATE_LAYOUT_EVIDENCE_DIR to collect synthetic presentation evidence')
    test.setTimeout(90_000)
    await login(page)
    await page.setViewportSize({ width, height })
    const manifest = { id: servers[0].id, name: servers[0].name, enabled: false, launch: { type: 'remote' }, transport: { type: 'streamable_http', url: 'http://127.0.0.1:1/mcp', headers: Object.fromEntries(Array.from({ length: 80 }, (_, i) => [`X-Synthetic-${i}`, `nonsecret-${i}`])) } }
    const configs = Array.from({ length: 100 }, (_, i) => ({ id: `synthetic-config-${i}`, path: `/synthetic/config-${i}.json`, format: 'json', manifest: { ...manifest, id: `synthetic-config-${i}`, name: `Synthetic config ${i}` } }))
    const statistics = { period_start: '2026-09-23T00:00:00Z', period_end: '2026-09-30T00:00:00Z', bucket_hours: 6, totals: { requests: 2800, calls: 2500, mcp_calls: 2300, success: 2400, errors: 100, not_invoked: 300 }, series: Array.from({ length: 28 }, (_, i) => ({ start: new Date(Date.UTC(2026, 8, 23, i * 6)).toISOString(), requests: 100 + i, calls: 90 + i, mcp_calls: 80 + i })), top_tools: tools.slice(0, 10).map((tool, i) => ({ tool_id: tool.id, server_id: tool.metadata.server_id, calls: 500 - i * 30, errors: i })) }
    const fixtures: Record<string, unknown> = { ...listFixtures, '/v1/access/invocation-statistics': statistics, '/v1/mcp/servers': { servers, load_errors: [] }, '/v1/tools': tools, '/v1/credentials': credentials, '/v1/mcp/configs': { configs, errors: [] } }
    await page.route('**/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() === 'GET' && path in fixtures) await route.fulfill({ json: fixtures[path] })
      else if (path.match(/\/v1\/mcp\/servers\/[^/]+\/detail$/)) await route.fulfill({ json: { server: servers[0], manifest, tools: tools.filter(t => t.metadata.server_id === servers[0].id), logs: [], events: [] } })
      else await route.continue()
    })
    mkdirSync(destination!, { recursive: true })
    for (const view of ['dashboard', 'configs', 'credentials', 'runtimeCache', 'servers', 'logs']) {
      await page.goto(`/console/#/${view}`)
      await expect(page.locator('main')).toBeVisible()
      if (['configs', 'credentials', 'runtimeCache', 'logs'].includes(view)) await expect(page.locator('tbody tr').first()).toContainText(/synthetic/i)
      if (view === 'servers') await page.getByRole('button').filter({ has: page.getByText(servers[0].name, { exact: true }) }).first().click()
      if (view === 'dashboard') {
        await expect(page.locator('main')).toContainText('100')
        await page.getByRole('button', { name: 'Last 7 days', exact: true }).click()
        await expect(page.getByRole('button', { name: 'Last 7 days', exact: true })).toHaveAttribute('aria-pressed', 'true')
        await expect(page.getByRole('group', { name: 'Trend chart. Use left and right arrows to inspect points', exact: true })).toBeVisible()
      }
      const basename = `${view}-${width}x${height}`
      if (verifyLayout && view === 'dashboard') {
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        const trend = page.locator('[data-dashboard-trend]')
        const ranking = page.locator('[data-dashboard-ranking] ol')
        await expect(ranking.locator('li')).toHaveCount(10)
        expect(await ranking.evaluate(el => el.clientHeight)).toBeLessThanOrEqual(256)
        expect(await trend.evaluate(el => el.getBoundingClientRect().height)).toBeLessThan(480)
        const ticks = await page.locator('[data-trend-axis] > span:visible').evaluateAll(elements => elements.map(el => ({ text: el.textContent, x: el.getBoundingClientRect().x, right: el.getBoundingClientRect().right })))
        expect(ticks.length).toBeLessThanOrEqual(width === 390 ? 4 : 7)
        expect(new Set(ticks.map(t => t.text)).size).toBe(ticks.length)
        for (let i = 1; i < ticks.length; i++) expect(ticks[i].x).toBeGreaterThanOrEqual(ticks[i - 1].right)
        await trend.evaluate(el => { const top = el.getBoundingClientRect().top + window.scrollY; window.scrollTo(0, top - (document.querySelector('header')?.getBoundingClientRect().height || 108) - 12) })
        await page.screenshot({ path: join(destination!, `dashboard-${width}x${height}-trend.png`) })
        await ranking.scrollIntoViewIfNeeded()
        await ranking.evaluate(el => { el.scrollTop = el.scrollHeight })
        writeFileSync(join(destination!, `dashboard-${width}x${height}-rank.json`), JSON.stringify(await ranking.locator('li').last().evaluate(el => { const nodes = []; for (let node: Element | null = el; node; node = node.parentElement) { const r = node.getBoundingClientRect(); nodes.push({ tag: node.tagName, class: node.className, x: r.x, y: r.y, width: r.width, height: r.height, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, overflowX: getComputedStyle(node).overflowX, minWidth: getComputedStyle(node).minWidth }) } return { scrollX, scrollY, nodes } }), null, 2))
        await expectInViewportAndUnobscured(ranking.locator('li').last())
        await page.screenshot({ path: join(destination!, `dashboard-${width}x${height}-ranking-bottom.png`) })
        await ranking.evaluate(el => { el.scrollTop = 0 })
        await page.evaluate(() => window.scrollTo(0, 0))
      }
      if (verifyLayout && ['configs', 'credentials', 'runtimeCache', 'servers'].includes(view)) {
        expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(height + 1)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        if (view !== 'servers') {
          await expectInViewportAndUnobscured(page.getByRole('button', { name: 'Next page', exact: true }))
          const viewport = page.locator('.bounded-list-scroll')
          if (width === 2048) expect(await viewport.evaluate(el => el.clientHeight)).toBeGreaterThan(height * .42)
        }
      }
      const measure = () => page.evaluate(() => {
        const elements = Array.from(document.querySelectorAll('html, body, main, main *, header')).filter(el => {
          const r = el.getBoundingClientRect(); const css = getComputedStyle(el)
          return r.width > 0 && r.height > 0 && (['HTML', 'BODY', 'MAIN', 'HEADER', 'THEAD'].includes(el.tagName) || el.matches('button, input, [role="tablist"]') || (el.scrollHeight > el.clientHeight + 2 && /(auto|scroll)/.test(css.overflowY)))
        })
        return elements.map(el => { const r = el.getBoundingClientRect(); const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return { tag: el.tagName, class: el.className, text: el.textContent?.trim().slice(0, 90), scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, scrollTop: el.scrollTop, overflowY: getComputedStyle(el).overflowY, box: { x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right }, inViewport: r.top>=0 && r.left>=0 && r.bottom<=innerHeight && r.right<=innerWidth, centerUnobscured: !!hit && (hit===el || el.contains(hit)) } })
      })
      writeFileSync(join(destination!, `${basename}.json`), JSON.stringify({ viewport: { width, height }, data: 'mock presentation fixtures over isolated real login/backend; not authorization proof', elements: await measure() }, null, 2))
      await page.screenshot({ path: join(destination!, `${basename}.png`) })
      if (verifyLayout && width === 390 && ['configs', 'credentials', 'runtimeCache'].includes(view)) {
        const viewport = page.locator('.bounded-list-scroll')
        const firstRow = viewport.locator('tbody tr').first()
        expect(await firstRow.locator('td').first().evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThanOrEqual(180)
        await expectInViewportAndUnobscured(firstRow.locator('td').first())
        if (view === 'runtimeCache') {
          await expect(firstRow.locator('.maintenance-row-summary')).toContainText('Writable')
          await expect(firstRow.locator('.maintenance-row-summary')).toContainText('10 B · 1 files')
          await expectInViewportAndUnobscured(firstRow.locator('.maintenance-row-summary'))
        }
        expect(await viewport.evaluate(el => el.scrollWidth - el.clientWidth)).toBeGreaterThan(1)
        const action = firstRow.locator('td').last().getByRole('button').first()
        await expectInViewportAndUnobscured(action)
        if (view !== 'credentials') {
          const pathIndex = view === 'configs' ? 3 : 1
          const pathCell = firstRow.locator('td').nth(pathIndex)
          expect(await pathCell.evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThanOrEqual(180)
          await viewport.evaluate((el, index) => { const cell = el.querySelectorAll('tbody tr:first-child td')[index]; el.scrollLeft += cell.getBoundingClientRect().left - el.getBoundingClientRect().left }, pathIndex)
          await expectInViewportAndUnobscured(pathCell)
        } else await viewport.evaluate(el => { el.scrollLeft = el.scrollWidth })
        await expectInViewportAndUnobscured(action)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        await page.screenshot({ path: join(destination!, `${basename}-horizontal-details.png`) })
        if (view === 'runtimeCache') {
          await viewport.evaluate(el => { const cell = el.querySelectorAll('tbody tr:first-child td')[4]; el.scrollLeft += cell.getBoundingClientRect().left - el.getBoundingClientRect().left })
          await expectInViewportAndUnobscured(firstRow.locator('td').nth(4))
          await expectInViewportAndUnobscured(action)
          await page.screenshot({ path: join(destination!, `${basename}-horizontal-access.png`) })
        }
        await viewport.evaluate(el => { el.scrollLeft = 0 })
      }
      if (view === 'servers') {
        await page.getByRole('tab', { name: 'Configuration', exact: true }).click()
        await expect(page.getByRole('button', { name: 'Edit configuration', exact: true })).toBeVisible()
        if (verifyLayout) {
          const body = page.locator('.service-detail-tabs > .ant-tabs-body-holder')
          expect(await body.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(1)
          await body.evaluate(el => { el.scrollTop = el.scrollHeight })
          await expect.poll(() => body.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
          await expect.poll(() => body.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThanOrEqual(1)
          await expectInViewportAndUnobscured(page.locator('.service-detail').getByRole('button', { name: /View tools$/ }))
          await expectInViewportAndUnobscured(page.getByRole('tab', { name: 'Configuration', exact: true }))
          await expectInViewportAndUnobscured(page.locator('.service-detail').getByRole('button', { name: 'Start', exact: true }))
          expect(await page.locator('.service-detail').evaluate(el => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
          await body.evaluate(el => { el.scrollTop = 0 })
        }
        await page.screenshot({ path: join(destination!, `${basename}-configuration.png`) })
        writeFileSync(join(destination!, `${basename}-configuration.json`), JSON.stringify(await measure(), null, 2))
        if (width === 390) {
          await page.locator('.service-detail-back').click()
          if (verifyLayout) {
            const directory = page.locator('.service-directory-list')
            expect(await directory.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(1)
            await directory.evaluate(el => { el.scrollTop = el.scrollHeight })
            await expect.poll(() => directory.evaluate(el => el.scrollTop)).toBeGreaterThan(0)
            await expectInViewportAndUnobscured(page.locator('.service-directory-footer').getByRole('button', { name: /From project$/ }))
            expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(height + 1)
          }
          await page.screenshot({ path: join(destination!, `${basename}-directory.png`) })
          writeFileSync(join(destination!, `${basename}-directory.json`), JSON.stringify(await measure(), null, 2))
        }
      }
      await page.locator('main').evaluate(main => { for (const el of [document.scrollingElement!, main, ...Array.from(main.querySelectorAll('*'))]) { if (el.scrollHeight>el.clientHeight+2 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) el.scrollTop=el.scrollHeight } })
      await page.screenshot({ path: join(destination!, `${basename}-scrolled.png`) })
      writeFileSync(join(destination!, `${basename}-scrolled.json`), JSON.stringify(await measure(), null, 2))
    }
  })
}

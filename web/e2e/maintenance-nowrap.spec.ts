import { test, expect } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { cache, credentials, listFixtures } from './synthetic-data'

const destination = process.env.GATE_MAINTENANCE_EVIDENCE_DIR
const verify = process.env.GATE_MAINTENANCE_ASSERT === '1'
for (const [width, height] of [[1188, 768], [1366, 768], [390, 844]]) {
  test(`E2E-52${width === 1188 ? 0 : width === 1366 ? 1 : 2} @maintenance-nowrap Chinese short labels ${width}x${height}`, async ({ page }) => {
    test.skip(!destination, 'Opt-in maintenance short-label evidence')
    await login(page)
    await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width, height })
    const configs = Array.from({ length: 100 }, (_, i) => ({ id: `synthetic-service-configuration-${String(i).padStart(6, "0")}`, path: `/synthetic/projects/delivery-output/configurations/config-${i}.json`, format: 'json', manifest: { id: `synthetic-service-configuration-${String(i).padStart(6, "0")}`, name: `合成配置 ${i}`, enabled: true, auto_start: i % 2 === 0, launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'http://127.0.0.1:1/mcp' } } }))
    const fixtures: Record<string, unknown> = { ...listFixtures, '/v1/mcp/configs': { configs, errors: [] }, '/v1/credentials': credentials, '/v1/runtime/cache': { ...cache, caches: cache.caches.map((item, i) => ({ ...item, path: `/synthetic/projects/delivery-output/runtime-cache/${item.name}`, writable: i % 2 !== 0 })) } }
    await page.route('**/v1/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (route.request().method() === 'GET' && path in fixtures) return route.fulfill({ json: fixtures[path] })
      return route.continue()
    })
    mkdirSync(destination!, { recursive: true })
    for (const view of ['configs', 'runtimeCache', 'credentials']) {
      await page.goto(`/console/#/${view}`)
      const table = page.locator('.maintenance-table')
      const viewport = page.locator('.bounded-list-scroll')
      await expect(table.locator('tbody tr').first()).toContainText('synthetic')
      const heightControl = await page.evaluate(() => {
        const selectors = [
          '.maintenance-list-page,.maintenance-list-card,.maintenance-list-content', '.maintenance-table th',
          '.maintenance-config-table :is(th,td):nth-child(2)', '.maintenance-config-table :is(th,td):nth-child(3)',
          '.maintenance-cache-table :is(th,td):nth-child(3),.maintenance-cache-table :is(th,td):nth-child(4)',
          '.maintenance-cache-table :is(th,td):nth-child(5)', '.maintenance-table :is(th,td):last-child', '.maintenance-table td:last-child button', '.maintenance-table :is(th,td):first-child',
        ].map(value => value.replace(/\s/g, ''))
        const changed: Array<{ sheet: CSSStyleSheet; index: number; text: string }> = []
        const afterHeight = document.documentElement.scrollHeight
        for (const sheet of Array.from(document.styleSheets)) {
          for (let index = sheet.cssRules.length - 1; index >= 0; index--) {
            const rule = sheet.cssRules[index]
            if (rule instanceof CSSStyleRule && selectors.includes(rule.selectorText.replace(/\s/g, ''))) {
              changed.push({ sheet, index, text: rule.cssText }); sheet.deleteRule(index)
            }
          }
        }
        const oldHeight = document.documentElement.scrollHeight
        const oldHeader = document.querySelector('header')!.getBoundingClientRect().height
        for (const record of changed.reverse()) record.sheet.insertRule(record.text, record.index)
        return { afterHeight, oldHeight, oldHeader, removedRules: changed.length, restoredHeight: document.documentElement.scrollHeight }
      })
      if (verify) {
        expect(heightControl.removedRules).toBe(9)
        expect(heightControl.restoredHeight).toBe(heightControl.afterHeight)
      }
      const stem = `${view}-zh-${width}x${height}`
      const violations: string[] = []
      const samples: unknown[] = []
      for (const phase of ['initial', 'status', 'end']) {
        await viewport.evaluate((el, data) => {
          const table = el.querySelector('table')!
          const cell = table.querySelectorAll('thead th')[data.index] as HTMLElement
          el.scrollLeft = data.phase === 'initial' ? 0 : data.phase === 'end' ? el.scrollWidth : cell.offsetLeft - 10
        }, { phase, index: view === 'configs' ? 2 : view === 'runtimeCache' ? 4 : 3 })
        const geometry = await table.evaluate(table => {
          const elements = Array.from(table.querySelectorAll('.maintenance-cache-table tbody tr:first-child td:first-child code, thead th, tbody tr:first-child td:last-child button, tbody tr:first-child td:nth-child(2) .rounded-full, tbody tr:first-child td:nth-child(5) .rounded-full'))
          return elements.map(el => {
            const rect = el.getBoundingClientRect(), ys = new Set<number>()
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
            for (let node = walker.nextNode(); node; node = walker.nextNode()) if (node.textContent?.trim()) {
              const range = document.createRange(); range.selectNodeContents(node)
              Array.from(range.getClientRects()).forEach(r => { if (r.width > 0) ys.add(Math.round(r.y)) })
            }
            return { text: el.textContent?.trim(), lines: ys.size, x: rect.x, y: rect.y, width: rect.width, height: rect.height, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }
          })
        })
        samples.push({ phase, geometry, outer: await page.evaluate(() => ({ docHeight: document.documentElement.scrollHeight, docWidth: document.documentElement.scrollWidth, elements: Array.from(document.querySelectorAll('header, main, .maintenance-list-page, .bounded-list-scroll, .list-pagination')).map(el => ({ class: el.className, height: el.getBoundingClientRect().height, top: el.getBoundingClientRect().top, bottom: el.getBoundingClientRect().bottom, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight })) })), scrollLeft: await viewport.evaluate(el => el.scrollLeft) })
        geometry.filter(item => item.lines > 1).forEach(item => violations.push(`${phase}: ${item.text} wraps into ${item.lines} lines`))
        await page.screenshot({ path: join(destination!, `${stem}-${phase}.png`) })
        if (verify) {
          expect.soft(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
          expect.soft(await page.evaluate(() => document.documentElement.scrollHeight), `${view}:${phase} does not increase existing vertical overflow`).toBeLessThanOrEqual(Math.max(height, heightControl.oldHeight) + 1)
          expect(await table.locator('tbody tr').first().locator('td').first().evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThanOrEqual(200)
          const action = table.locator('tbody tr').first().locator('td').last().getByRole('button').first()
          await expectInViewportAndUnobscured(action)
          if (phase === 'status') {
            const column = view === 'configs' ? 2 : view === 'runtimeCache' ? 4 : 3
            await expectInViewportAndUnobscured(table.locator('thead th').nth(column))
            if (view === 'runtimeCache') {
              const badge = table.locator('tbody tr').first().locator('td').nth(column).locator('.rounded-full')
              await expect(badge).toHaveText('不可写')
              await expectInViewportAndUnobscured(badge)
            }
          }
        }
      }
      writeFileSync(join(destination!, `${stem}.json`), JSON.stringify({ viewport: { width, height }, data: 'synthetic configs100/cache100/credentials200; real login only', heightControl, samples, violations }, null, 2))
      if (verify) expect.soft(violations).toEqual([])
    }
  })
}

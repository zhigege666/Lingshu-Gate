import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'
import { CONSOLE_VIEW_IDS } from '../src/routing/console-routes'
import { login } from './helpers'

// Real built console, isolated synthetic backend. This matrix checks every
// route after rendering; interaction-specific suites exercise mutations.
for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) {
  for (const locale of ['zh-CN', 'en-US']) {
    test('shared UI geometry ' + width + 'x' + height + ' ' + locale + ' @visual', async ({ page }, testInfo) => {
      test.setTimeout(180_000)
      await page.setViewportSize({ width, height })
      await login(page)
      await page.addInitScript(value => {
        localStorage.setItem('lingshu-gate-console-locale', value)
        localStorage.setItem('lingshu-gate-console-theme', 'light')
      }, locale)
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      const directory = process.env.GATE_UI_SCREENSHOT_DIR
        ? join(process.env.GATE_UI_SCREENSHOT_DIR, width + 'x' + height, locale)
        : testInfo.outputPath('routes')
      await mkdir(directory, { recursive: true })
      for (const route of CONSOLE_VIEW_IDS) {
        await test.step(route, async () => {
          await page.goto('/?ui-standard=' + route + '#/' + route)
          await page.locator('main .page-header, main .dashboard-page, main .server-workspace').first().waitFor({ state: 'attached' })
          await page.waitForLoadState('networkidle')
          await page.evaluate(() => document.fonts.ready)
          const geometry = await page.evaluate(() => {
            const styles = getComputedStyle(document.documentElement)
            const fields = [...document.querySelectorAll<HTMLElement>('main .gate-form-row')].map(row => {
              const label = row.querySelector<HTMLElement>(':scope > .gate-form-label')
              const control = row.querySelector<HTMLElement>(':scope > .gate-form-control')
              if (!label || !control || !row.getClientRects().length || row.dataset.compound === 'true') return null
              const l = label.getBoundingClientRect(), c = control.getBoundingClientRect()
              return { text: label.innerText, width: c.width, gap: c.left - l.right, right: c.right }
            }).filter(Boolean)
            return {
              viewport: innerWidth,
              scrollWidth: document.documentElement.scrollWidth,
              controlHeight: styles.getPropertyValue('--control-height').trim(),
              smallHeight: styles.getPropertyValue('--control-height-sm').trim(),
              sectionGap: styles.getPropertyValue('--section-gap').trim(),
              headerHeight: document.querySelector('.console-header')!.getBoundingClientRect().height,
              fields,
            }
          })
          expect(geometry.scrollWidth, route + ' must not scroll the whole page sideways').toBeLessThanOrEqual(width + 1)
          expect(geometry.headerHeight).toBe(64)
          expect(geometry.controlHeight).toBe('36px')
          expect(geometry.smallHeight).toBe('32px')
          expect(geometry.sectionGap).toBe('24px')
          for (const field of geometry.fields) {
            expect(field!.width, route + ': usable input width for ' + field!.text).toBeGreaterThanOrEqual(72)
            expect(field!.gap, route + ': label and control share a row').toBeGreaterThanOrEqual(11)
            expect(field!.right, route + ': field stays inside viewport').toBeLessThanOrEqual(width + 1)
          }
          await page.screenshot({ path: join(directory, route + '.png'), fullPage: false })
        })
      }
      expect(errors).toEqual([])
    })
  }
}

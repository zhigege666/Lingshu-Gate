import { test, expect, type Locator } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { listFixtures } from './synthetic-data'

const output = process.env.GATE_REMAINING_PANELS_DIR
async function trailingSpace(viewport: Locator) {
  return viewport.evaluate(element => {
    const number = (value: string) => Number.parseFloat(value) || 0
    let reserved = 0
    for (let node: Element | null = element; node; node = node.parentElement) {
      const style = getComputedStyle(node)
      reserved += number(style.paddingBottom) + number(style.borderBottomWidth) + number(style.marginBottom)
      for (let sibling = node.nextElementSibling; sibling; sibling = sibling.nextElementSibling) {
        const siblingStyle = getComputedStyle(sibling)
        // A side-by-side grid panel does not consume height below this list.
        if (siblingStyle.display === 'none' || sibling.getBoundingClientRect().top < node.getBoundingClientRect().bottom - 2) continue
        reserved += sibling.getBoundingClientRect().height + number(siblingStyle.marginTop) + number(siblingStyle.marginBottom)
        reserved += number(getComputedStyle(node.parentElement!).rowGap)
      }
      if (node.classList.contains('console-content')) break
    }
    return reserved
  })
}
async function expectUsesSpace(viewport: Locator, reserve = 100) {
  try {
    await expect.poll(() => viewport.evaluate((el, reserved) => {
      const rect = el.getBoundingClientRect()
      return el.clientHeight >= Math.min(el.scrollHeight, innerHeight - rect.top - reserved) - 2
    }, reserve)).toBe(true)
  } catch (cause) {
    console.log('Synthetic remaining-space failure', await viewport.evaluate((el, reserved) => ({
      viewport: innerHeight, reserve: reserved, top: el.getBoundingClientRect().top,
      client: el.clientHeight, content: el.scrollHeight,
      ancestors: Array.from((function* () { for (let node: Element | null = el; node; node = node.parentElement) yield node })()).slice(0, 8).map(node => ({
        class: node.className, height: node.getBoundingClientRect().height,
        maxHeight: getComputedStyle(node).maxHeight, flex: getComputedStyle(node).flex,
        bottomPadding: getComputedStyle(node).paddingBottom,
        remaining: getComputedStyle(node).getPropertyValue('--remaining-list-height'),
        pageRemaining: getComputedStyle(node).getPropertyValue('--remaining-viewport-height'),
        top: node.getBoundingClientRect().top, bottom: node.getBoundingClientRect().bottom,
      })),
    }), reserve))
    throw cause
  }
  return viewport.evaluate(el => ({ top: el.getBoundingClientRect().top, bottom: el.getBoundingClientRect().bottom, client: el.clientHeight, content: el.scrollHeight }))
}
for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440], [2048, 1119], [1188, 761], [1366, 768], [390, 844]]) test(`E2E-${width === 2048 ? 550 : width === 1366 ? 551 : width === 390 ? 552 : 553} @remaining-panels below-fold identities, uploads and build logs ${width}x${height}`, async ({ page }) => {
  test.skip(!output, 'Opt-in affected remaining-height panels')
  test.setTimeout(60_000)
  await login(page)
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  await page.setViewportSize({ width, height })
  const mutations: string[] = [], measures: unknown[] = []
  const links = Array.from({ length: 200 }, (_, i) => ({ id: `synthetic-link-${i}`, issuer: 'https://synthetic.invalid', subject: `synthetic-subject-${i}`, user_id: `synthetic-user-${i}`, enabled: false, revision: 1 }))
  const logs = Array.from({ length: 200 }, (_, i) => ({ id: `synthetic-build-log-${i}`, build_id: 'build-0', sequence: i, phase: 'prepare', level: 'info', message: `Synthetic build log ${i}`, command: [], stdout: '', stderr: '', duration_ms: 0, created_at: '2026-01-01T00:00:00Z' }))
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') { mutations.push(path); return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } }) }
    if (path === '/v1/auth/external-subject-links') {
      const url = new URL(request.url()), offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 50)
      return route.fulfill({ json: { links: links.slice(offset, offset + limit), total: links.length, offset, limit } })
    }
    if (/^\/v1\/builds\/[^/]+\/logs$/.test(path)) return route.fulfill({ json: { logs } })
    if (path.startsWith('/v1/delivery-drafts/')) return route.fulfill({ json: { upload_id: path.split('/').at(-1), revision: 0, manifest_patch: {}, server_id: null, build_id: null, deployment_id: null, start: false, overwrite: false, project_root: '.', runtime_override: null } })
    if (path === '/v1/auth/downstream-credentials') {
      const source = listFixtures[path] as { credentials: Array<Record<string, unknown>> }
      return route.fulfill({ json: { credentials: source.credentials.map((item, index) => ({ ...item, injection: { type: 'http_header', name: index === 0 ? 'Authorization' : 'X-Synthetic', template: '{value}' }, required: index < 2, configured: index === 0 })) } })
    }
    if (path in listFixtures) return route.fulfill({ json: listFixtures[path] })
    return route.continue()
  })
  mkdirSync(output!, { recursive: true })
  for (const view of ['downstreamCredentials', 'myConnections']) {
    await page.goto(`/console/#/${view}`)
    if (view === 'myConnections') await page.getByRole('tab', { name: '外部身份提供方', exact: true }).click()
    const viewport = page.locator('.bounded-list-scroll')
    await expect(viewport.locator('tbody tr').first()).toContainText('synthetic')
    measures.push({ view, geometry: await expectUsesSpace(viewport) })
    if (view === 'downstreamCredentials') {
      const wrapping = await viewport.locator('thead th, tbody tr:first-child .rounded-full, tbody tr:first-child td:last-child button').evaluateAll(elements => elements.map(el => {
        const ys = new Set<number>(), walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
        for (let node = walker.nextNode(); node; node = walker.nextNode()) if (node.textContent?.trim()) {
          const range = document.createRange(); range.selectNodeContents(node)
          Array.from(range.getClientRects()).forEach(rect => { if (rect.width) ys.add(Math.round(rect.y)) })
        }
        return { text: el.textContent?.trim(), lines: ys.size }
      }).filter(item => item.lines > 1))
      expect(wrapping).toEqual([])
      await expect(viewport.locator('tbody tr').first()).toContainText('Authorization · HTTP Header')
      await expect(viewport.locator('tbody tr').first()).toContainText('必填')
      await expect(viewport.locator('tbody tr').first()).toContainText('已配置')
      // The compact table combines configured/required state in one column.
      for (const column of [2]) {
        await viewport.evaluate((el, index) => { el.scrollLeft = (el.querySelectorAll('thead th')[index] as HTMLElement).offsetLeft }, column)
        await expectInViewportAndUnobscured(viewport.locator('tbody tr').first().locator('td').nth(column).locator('.rounded-full'))
        await page.screenshot({ path: join(output!, `downstream-short-column-${column}-${width}x${height}.png`) })
      }
      await expectInViewportAndUnobscured(viewport.locator('tbody tr').first().locator('td').last().getByRole('button').first())
      await viewport.evaluate(el => { el.scrollLeft = 0 })
    }
    const next = page.getByRole('button', { name: '下一页', exact: true })
    await expectInViewportAndUnobscured(next)
    await viewport.evaluate(el => { el.scrollTop = el.scrollHeight })
    await expectInViewportAndUnobscured(next)
    await page.screenshot({ path: join(output!, `${view}-${width}x${height}.png`) })
    await next.click()
    await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBe(0)
  }
  await page.goto('/console/#/connectionInfrastructure')
  await page.getByRole('tab', { name: '外部身份提供方', exact: true }).click()
  const section = page.getByRole('region', { name: 'OAuth 身份绑定', exact: true })
  const identityViewport = section.locator('.bounded-list-scroll')
  await expect(identityViewport.locator('tbody tr').first()).toContainText('synthetic-subject-0')
  const beforeTop = await section.evaluate(el => el.getBoundingClientRect().top)
  await section.evaluate(el => { window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - (document.querySelector('header')?.getBoundingClientRect().height || 0) - 12) })
  const geometry = await expectUsesSpace(identityViewport)
  expect(geometry.client).toBeGreaterThan(180)
  measures.push({ view: 'subjectLinks', beforeTop, geometry })
  await expectInViewportAndUnobscured(section.getByRole('button', { name: '下一页', exact: true }))
  await identityViewport.evaluate(el => { el.scrollLeft = el.scrollWidth })
  await expectInViewportAndUnobscured(identityViewport.locator('tbody tr').first().getByRole('button', { name: '启用', exact: true }))
  await identityViewport.evaluate(el => { el.scrollTop = el.scrollHeight })
  await expectInViewportAndUnobscured(section.getByRole('button', { name: '下一页', exact: true }))
  await page.screenshot({ path: join(output!, `subject-links-below-fold-${width}x${height}.png`) })
  await page.goto('/console/#/uploads')
  await page.getByRole('button', { name: '查看上传记录', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '上传记录', exact: true })
  const uploadViewport = drawer.locator('.bounded-list-scroll')
  await expect(uploadViewport).toContainText('synthetic-project-0.zip')
  measures.push({ view: 'uploadHistory', geometry: await expectUsesSpace(uploadViewport, 64) })
  await expectInViewportAndUnobscured(drawer.getByRole('button', { name: '下一页', exact: true }))
  await uploadViewport.evaluate(el => { el.scrollTop = el.scrollHeight })
  await expectInViewportAndUnobscured(uploadViewport.getByRole('button', { name: '删除', exact: true }).last())
  await page.screenshot({ path: join(output!, `upload-history-bottom-${width}x${height}.png`) })
  await drawer.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(uploadViewport).toContainText('synthetic-project-20.zip')
  await drawer.getByRole('button', { name: /Close|关闭/, exact: true }).click()
  await page.goto('/console/#/builds/build-0')
  await page.getByRole('tab', { name: /日志与输出/ }).click()
  // Log workspaces initially follow the latest page of the bounded window.
  const logViewport = page.locator('.bounded-list-scroll').filter({ has: page.getByText('Synthetic build log 199', { exact: true }) })
  await expect(logViewport).toBeVisible()
  expect(await logViewport.locator('tbody tr').count()).toBeLessThanOrEqual(50)
  await logViewport.evaluate(el => { window.scrollBy(0, el.getBoundingClientRect().top - (document.querySelector('header')?.getBoundingClientRect().height || 0) - 100) })
  // Reserve actual pagination, card padding and page padding. A fixed 44px
  // budget omitted the 56px pager alone and rejected a fully occupied panel.
  const logReserve = await trailingSpace(logViewport)
  measures.push({ view: 'buildLogs', reserve: logReserve, geometry: await expectUsesSpace(logViewport, logReserve) })
  const logPager = logViewport.locator('..').locator('.list-pagination')
  await expectInViewportAndUnobscured(logPager)
  await logViewport.evaluate(el => { el.scrollTop = el.scrollHeight })
  await expectInViewportAndUnobscured(logViewport.getByText('Synthetic build log 199', { exact: true }))
  await expectInViewportAndUnobscured(logViewport.locator('thead th').first())
  await page.screenshot({ path: join(output!, `build-logs-bottom-${width}x${height}.png`) })
  expect(mutations).toEqual([])
  writeFileSync(join(output!, `remaining-panels-${width}x${height}.json`), JSON.stringify({ synthetic: true, measures, mutations }, null, 2))
})

for (const width of [1366, 390]) test(`Subject below-fold diagnostic ${width} @layout-diagnostic`, async ({ page }) => {
  test.skip(!process.env.GATE_LAYOUT_DIAGNOSTIC, 'Geometry capture only')
  await login(page)
  await page.setViewportSize({ width, height: width === 390 ? 844 : 768 })
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  const links = Array.from({ length: 200 }, (_, i) => ({ id: `synthetic-link-${i}`, issuer: 'https://synthetic.invalid', subject: `synthetic-subject-${i}`, user_id: `synthetic-user-${i}`, enabled: false, revision: 1 }))
  await page.route('**/v1/auth/external-subject-links*', route => {
    const query = new URL(route.request().url()).searchParams
    const offset = Number(query.get('offset') || 0), limit = Number(query.get('limit') || 50)
    return route.fulfill({ json: { links: links.slice(offset, offset + limit), total: links.length, offset, limit } })
  })
  await page.goto('/console/#/connectionInfrastructure')
  await page.getByRole('tab', { name: '外部身份提供方', exact: true }).click()
  const section = page.getByRole('region', { name: 'OAuth 身份绑定', exact: true })
  await expect(section.locator('tbody tr').first()).toContainText('synthetic-subject-0')
  const data = await section.evaluate(async section => {
    const measure = () => ({ scrollY, docHeight: document.documentElement.scrollHeight, docClient: document.documentElement.clientHeight, sectionTop: section.getBoundingClientRect().top, groupTop: section.querySelector('.remaining-list-group')!.getBoundingClientRect().top, groupHeight: section.querySelector('.remaining-list-group')!.clientHeight, listTop: section.querySelector('.bounded-list-scroll')!.getBoundingClientRect().top, listHeight: section.querySelector('.bounded-list-scroll')!.clientHeight })
    const before = measure(), requestedY = window.scrollY + section.getBoundingClientRect().top - (document.querySelector('header')?.getBoundingClientRect().height || 0) - 12
    window.scrollTo(0, requestedY)
    const frames = []
    for (let i = 0; i < 8; i++) { await new Promise<void>(resolve => requestAnimationFrame(() => resolve())); frames.push(measure()) }
    return { before, requestedY, frames }
  })
  mkdirSync(process.env.GATE_LAYOUT_DIAGNOSTIC!, { recursive: true })
  writeFileSync(join(process.env.GATE_LAYOUT_DIAGNOSTIC!, `subject-scroll-${width}.json`), JSON.stringify(data, null, 2))
})

import { test, expect, type Locator } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers, tools, classifications, listFixtures } from './synthetic-data'

async function expectDrawerSettled(drawer: Locator) {
  await expect.poll(() => drawer.evaluate(async el => {
    const wrapper = el.closest('.ant-drawer-content-wrapper') || el
    if (wrapper.getAnimations().some(animation => animation.playState === 'running')) return false
    const samples: number[][] = []
    for (let i = 0; i < 3; i++) {
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
      const r = wrapper.getBoundingClientRect()
      samples.push([r.x, r.y, r.width, r.height])
    }
    const r = wrapper.getBoundingClientRect()
    return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight
      && samples.every(sample => sample.every((value, i) => Math.abs(value - samples[0][i]) < .1))
  })).toBe(true)
}

const output = process.env.GATE_PERSONAL_LAYOUT_DIR
for (const [width, height] of [[1188, 761], [2048, 1119], [1366, 768], [390, 844]]) {
  test(`E2E-53${width === 1188 ? 0 : width === 2048 ? 1 : width === 1366 ? 2 : 3} @personal-layout personal lists, tool drawer and service entry actions ${width}`, async ({ page }) => {
    test.skip(!output, 'Opt-in personal workspace and service-entry layout regression')
    test.setTimeout(45_000)
    await login(page)
    await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
    await page.setViewportSize({ width, height })
    let count = 0, toolCount = 41
    const writes: string[] = [], offsets: number[] = []
    const summaries = Array.from({ length: 41 }, (_, index) => ({ id: `synthetic-personal-${index}`, name: `合成服务 ${index}`, tool_count: 41, read_tool_count: 41, write_tool_count: 0 }))
    const fixtures: Record<string, unknown> = { ...listFixtures, '/v1/mcp/servers': { servers, load_errors: [] }, '/v1/tools': tools, '/v1/mcp/configs': { configs: [], errors: [] }, '/v1/access/tool-classifications': { classifications } }
    await page.route('**/v1/**', async route => {
      const request = route.request(), url = new URL(request.url())
      if (request.method() !== 'GET') { writes.push(`${request.method()} ${url.pathname}`); return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in read-only UI journey' } }) }
      if (url.pathname === '/v1/me/mcp-servers') {
        const offset = Number(url.searchParams.get('offset') || 0); offsets.push(offset)
        return route.fulfill({ json: { servers: summaries.slice(0, count).slice(offset, offset + 20), total: count } })
      }
      if (url.pathname.startsWith('/v1/me/mcp-servers/')) return route.fulfill({ json: { ...summaries[0], tools: Array.from({ length: toolCount }, (_, i) => ({ id: `synthetic-tool-${String(i).padStart(4, '0')}`, name: `合成只读工具 ${i}`, description: '', required_access: 'read' })) } })
      if (url.pathname in fixtures) return route.fulfill({ json: fixtures[url.pathname] })
      return route.continue()
    })
    mkdirSync(output!, { recursive: true })
    const measures: unknown[] = []
    for (const amount of [0, 1, 41]) {
      count = amount
      await page.goto('/console/#/myServers')
      await page.reload()
      await expect(page.locator('main .ant-spin-spinning')).toHaveCount(0)
      const table = page.locator('main .ant-table-wrapper')
      await expect(table).toBeVisible()
      if (amount === 0) await expect(table.getByRole('cell', { name: '暂无数据', exact: true })).toBeVisible()
      else await expect(table.getByRole('button', { name: '合成服务 0', exact: true })).toBeVisible()
      const body = table.locator('.ant-table-body')
      const bounds = await table.evaluate(el => ({ height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width }))
      if (amount <= 1) {
        await expect(table.locator('.ant-pagination')).toHaveCount(0)
        expect(bounds.height).toBeLessThanOrEqual(amount === 0 ? 290 : 160)
        const overflow = await body.evaluate(el => ({ mode: getComputedStyle(el).overflowY, client: el.clientHeight, content: el.scrollHeight }))
        expect(overflow.mode).toBe('auto')
        expect(overflow.content).toBeLessThanOrEqual(overflow.client + 1)
      } else {
        await expect(table.locator('.ant-pagination')).toBeVisible()
        await expectInViewportAndUnobscured(table.locator('.ant-pagination-next button'))
        await table.locator('.ant-pagination-next button').click()
        await expect(table.getByRole('button', { name: '合成服务 20', exact: true })).toBeVisible()
        expect(offsets).toContain(20)
        await table.locator('.ant-pagination-prev button').click()
        await expect(table.getByRole('button', { name: '合成服务 0', exact: true })).toBeVisible()
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
      measures.push({ amount, bounds, body: await body.evaluateAll(nodes => nodes.map(el => ({ client: el.clientHeight, scroll: el.scrollHeight }))) })
      await page.screenshot({ path: join(output!, `my-mcp-${amount}-${width}x${height}.png`) })
    }
    for (const amount of [0, 1]) {
      toolCount = amount
      await page.getByRole('button', { name: '合成服务 0', exact: true }).click()
      const smallDrawer = page.getByRole('dialog')
      const smallTable = smallDrawer.locator('.ant-table-wrapper')
      if (amount === 0) await expect(smallTable.locator('.ant-empty')).toBeVisible()
      else await expect(smallDrawer.getByText('合成只读工具 0', { exact: true })).toBeVisible()
      await expect(smallDrawer.locator('.ant-spin-spinning')).toHaveCount(0)
      await expectDrawerSettled(smallDrawer)
      await expectInViewportAndUnobscured(smallDrawer.getByRole('button', { name: /Close|关闭/ }).first())
      await expectInViewportAndUnobscured(smallTable.locator('thead th').last())
      if (amount === 1) await expectInViewportAndUnobscured(smallDrawer.getByRole('button', { name: '测试工具', exact: true }))
      await expect(smallTable.locator('.ant-pagination')).toHaveCount(0)
      const geometry = await smallTable.locator('.ant-table-body').evaluate(el => ({ mode: getComputedStyle(el).overflowY, client: el.clientHeight, content: el.scrollHeight }))
      expect(geometry.mode).toBe('auto')
      expect(geometry.content).toBeLessThanOrEqual(geometry.client + 1)
      expect(geometry.client).toBeLessThanOrEqual(amount === 0 ? 220 : 100)
      measures.push({ smallDrawerTools: amount, geometry })
      await page.screenshot({ path: join(output!, `my-mcp-tools-${amount}-${width}x${height}.png`) })
      await smallDrawer.getByRole('button', { name: /Close|关闭/ }).first().click()
      await expect(smallDrawer).toHaveCount(0)
    }
    toolCount = 41
    await page.getByRole('button', { name: '合成服务 0', exact: true }).click()
    const drawer = page.getByRole('dialog')
    await expect(drawer.getByText('合成只读工具 0', { exact: true })).toBeVisible()
    await expectDrawerSettled(drawer)
    const drawerBody = drawer.locator('.ant-drawer-body')
    const toolBody = drawer.locator('.ant-table-body')
    const pager = drawer.locator('.ant-pagination')
    const geometry = await toolBody.evaluate(el => {
      const container = el.closest('.ant-drawer-body')!, pagination = container.querySelector('.ant-pagination')!
      const bodyStyle = getComputedStyle(container), pagerStyle = getComputedStyle(pagination)
      const reserve = Number.parseFloat(bodyStyle.paddingBottom) + pagination.getBoundingClientRect().height + Number.parseFloat(pagerStyle.marginTop) + Number.parseFloat(pagerStyle.marginBottom)
      return { clientHeight: el.clientHeight, scrollHeight: el.scrollHeight, reserve, paddingBottom: bodyStyle.paddingBottom, pagerMargins: [pagerStyle.marginTop, pagerStyle.marginBottom], available: container.getBoundingClientRect().bottom - el.getBoundingClientRect().top - reserve }
    })
    writeFileSync(join(output!, `drawer-geometry-${width}x${height}.json`), JSON.stringify(geometry, null, 2))
    expect(geometry.clientHeight).toBeGreaterThanOrEqual(Math.min(geometry.scrollHeight, geometry.available) - 2)
    await expectInViewportAndUnobscured(pager.locator('.ant-pagination-next button'))
    await toolBody.evaluate(el => { el.scrollTop = el.scrollHeight; el.scrollLeft = el.scrollWidth })
    await expectInViewportAndUnobscured(drawer.getByRole('button', { name: '测试工具', exact: true }).last())
    measures.push({ drawer: geometry, drawerHeight: await drawerBody.evaluate(el => el.clientHeight) })
    await page.screenshot({ path: join(output!, `my-mcp-tools-bottom-${width}x${height}.png`) })
    await pager.locator('.ant-pagination-next button').click()
    await expect(drawer.getByText('合成只读工具 20', { exact: true })).toBeVisible()
    await drawer.getByRole('button', { name: '测试工具', exact: true }).first().click()
    await expect(page).toHaveURL(/#\/invoke$/)
    await page.goto('/console/#/servers')
    const header = page.locator('.service-directory-header')
    const remote = header.getByRole('button', { name: /接入远程 MCP$/ })
    const project = header.getByRole('button', { name: '从项目创建', exact: true })
    await expectInViewportAndUnobscured(remote)
    await expectInViewportAndUnobscured(project)
    const search = header.getByRole('textbox', { name: '搜索服务名称或 ID', exact: true })
    expect((await project.boundingBox())!.y + (await project.boundingBox())!.height).toBeLessThanOrEqual((await search.boundingBox())!.y)
    await page.screenshot({ path: join(output!, `service-header-actions-${width}x${height}.png`) })
    await remote.click()
    await expect(page).toHaveURL(/#\/configs$/)
    await expect(page.getByRole('dialog', { name: '新建 MCP 配置', exact: true })).toBeVisible()
    await page.getByRole('dialog').getByRole('button', { name: /Close|关闭/ }).first().click()
    await page.goto('/console/#/servers')
    await page.locator('.service-directory-header').getByRole('button', { name: '从项目创建', exact: true }).click()
    await expect(page).toHaveURL(/#\/uploads$/)
    await expect(page.locator('input[type=file]')).toHaveCount(1)
    for (const view of ['tools', 'toolClassifications']) {
      await page.goto(`/console/#/${view}`)
      const viewport = page.locator(view === 'tools' ? '.tool-catalog-scroll' : '.bounded-list-scroll')
      const pagination = page.locator(view === 'tools' ? '.tool-catalog-pagination' : '.list-pagination')
      await expect(viewport).toContainText('Synthetic tool')
      if (view === 'tools') {
        await expect(viewport.locator('.tool-catalog-card')).toHaveCount(48)
        await expect(pagination.locator('.tool-page-number')).toHaveText('1 / 105')
      }
      const size = await viewport.evaluate(el => {
        const owner = el.closest('.tool-catalog, .tool-review-workspace')!
        const budget = Number.parseFloat(getComputedStyle(owner).maxHeight)
        const reserve = owner.getBoundingClientRect().height - el.getBoundingClientRect().height
        return { client: el.clientHeight, content: el.scrollHeight, top: el.getBoundingClientRect().top, budget, reserve, available: budget - reserve }
      })
      expect(size.client).toBeGreaterThanOrEqual(Math.min(size.content, size.available) - 2)
      await expectInViewportAndUnobscured(pagination.getByRole('button', { name: '下一页', exact: true }))
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
      // A bounded list must not leave a second document scrollbar because the
      // shell's bottom padding was omitted from its available-height budget.
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollHeight - innerHeight)).toBeLessThanOrEqual(1)
      if (view === 'toolClassifications') {
        const state = viewport.locator('tbody tr').first().locator('td').nth(6).locator('.inline-flex')
        await expect(state).toBeVisible()
        expect(await state.evaluate(el => getComputedStyle(el).whiteSpace)).toBe('nowrap')
        const geometry = await state.evaluate(el => {
          const rect = el.getBoundingClientRect(), css = getComputedStyle(el)
          return { height: rect.height, maxHeight: parseFloat(css.lineHeight) + parseFloat(css.paddingTop) + parseFloat(css.paddingBottom) + 2 }
        })
        expect(geometry.height).toBeLessThanOrEqual(geometry.maxHeight + 1)
        await viewport.evaluate(el => { el.scrollLeft = el.scrollWidth })
        await expectInViewportAndUnobscured(state)
        await expectInViewportAndUnobscured(viewport.locator('tbody tr').first().getByRole('button'))
      }
      await viewport.evaluate(el => { el.scrollTop = el.scrollHeight })
      await expectInViewportAndUnobscured(pagination.getByRole('button', { name: '下一页', exact: true }))
      await page.screenshot({ path: join(output!, `${view}-remaining-height-${width}x${height}.png`) })
      await pagination.getByRole('button', { name: '下一页', exact: true }).click()
      await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBe(0)
      measures.push({ view, size })
    }
    expect(writes).toEqual([])
    writeFileSync(join(output!, `geometry-${width}x${height}.json`), JSON.stringify({ viewport: { width, height }, synthetic: true, measures, writes }, null, 2))
  })
}

test('Personal table flex-chain diagnostic @layout-diagnostic', async ({ page }) => {
  test.skip(!process.env.GATE_LAYOUT_DIAGNOSTIC, 'Capture only, not layout acceptance')
  await login(page)
  await page.setViewportSize({ width: 2048, height: 1119 })
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'zh-CN'))
  const services = Array.from({ length: 20 }, (_, i) => ({ id: `synthetic-${i}`, name: `合成服务 ${i}`, tool_count: 41, read_tool_count: 41, write_tool_count: 0 }))
  await page.route('**/v1/me/mcp-servers?*', route => route.fulfill({ json: { servers: services, total: 41 } }))
  await page.goto('/console/#/myServers')
  await expect(page.getByRole('button', { name: '合成服务 0', exact: true })).toBeVisible()
  const data = await page.locator('.personal-workspace-page').evaluate(root => [root, ...Array.from(root.querySelectorAll('*'))].filter(el => el === root || /ant-(?:table|spin)|pagination/.test(el.className)).map(el => {
    const css = getComputedStyle(el), rect = el.getBoundingClientRect()
    return { tag: el.tagName, class: el.className, children: Array.from(el.children).map(child => ({ tag: child.tagName, class: child.className })), top: rect.top, bottom: rect.bottom, height: rect.height, client: el.clientHeight, content: el.scrollHeight, css: { height: css.height, maxHeight: css.maxHeight, minHeight: css.minHeight, flex: css.flex, display: css.display, overflowY: css.overflowY, variable: css.getPropertyValue('--remaining-viewport-height') } }
  }))
  mkdirSync(process.env.GATE_LAYOUT_DIAGNOSTIC!, { recursive: true })
  writeFileSync(join(process.env.GATE_LAYOUT_DIAGNOSTIC!, 'personal-flex-chain-2048.json'), JSON.stringify(data, null, 2))
})

import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { listFixtures, credentials, classifications, servers, tools } from './synthetic-data'

test.beforeEach(async ({ page }) => {
  await login(page)
  const fixtures: Record<string, unknown> = { ...listFixtures, '/v1/credentials': credentials, '/v1/access/tool-classifications': {classifications}, '/v1/mcp/servers': {servers,load_errors:[]}, '/v1/tools':tools }
  await page.route('**/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() === 'GET' && path in fixtures) await route.fulfill({json:fixtures[path]})
    else await route.continue()
  })
})

for (const view of ['accessUsers','accessRoles','accessGrants','credentials','personalTokens','downstreamCredentials','runtimeCache','toolClassifications']) {
  test(`E2E-590-${view} @large-data clearing search never resurrects the old page`, async ({page}) => {
    await page.goto(`/console/#/${view}`)
    const pager=page.locator('.list-pagination')
    await pager.getByRole('button',{name:'Next page',exact:true}).click()
    await expect(pager).toContainText('51–')
    const search=page.locator('.page-toolbar-search input')
    await search.fill('zz-no-match-20261001')
    await expect(pager).toContainText('0–0 / 0')
    await page.getByRole('button',{name:'Clear Search',exact:true}).click()
    await expect(pager).toContainText('1–50')
    await expect(pager.getByRole('button',{name:'Previous page',exact:true})).toBeDisabled()
  })
}

const toolbarCases = [
  ...[390, 1366, 2048].map(width => ({ width, height: 900, locale: 'en-US', theme: 'light', name: String(width) })),
  ...[[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]].flatMap(([width, height]) =>
    ['en-US', 'zh-CN'].flatMap(locale => ['light', 'dark'].map(theme => ({ width, height, locale, theme, name: `${width}x${height}-${locale}-${theme}` })))),
]
for (const { width, height, locale, theme, name } of toolbarCases) {
  test(`E2E-591-${name} @visual reset is compact and does not shift the list`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height })
    await page.addInitScript(({ locale, theme }) => {
      localStorage.setItem('lingshu-gate-console-locale', locale)
      localStorage.setItem('lingshu-gate-console-theme', theme)
    }, { locale, theme })
    await page.goto('/console/#/downstreamCredentials')
    const reset=page.getByRole('button',{name:locale === 'zh-CN' ? '重置筛选' : 'Reset Filters',exact:true})
    await expect(reset).toBeDisabled()
    await expect(page.locator('html')).toHaveAttribute('lang', locale)
    await expect.poll(() => page.locator('html').evaluate(el => el.classList.contains('dark'))).toBe(theme === 'dark')
    const before=await page.locator('.downstream-credentials-table').boundingBox()
    const input = page.locator('.page-toolbar-search > .ant-input-affix-wrapper')
    const inputBefore = (await input.boundingBox())!
    await page.screenshot({ path: testInfo.outputPath('toolbar-empty.png') })
    await page.locator('.page-toolbar-search input').fill('Synthetic')
    await expect(reset).toBeEnabled()
    const clear = page.getByRole('button', { name: locale === 'zh-CN' ? '清除搜索' : 'Clear Search', exact: true })
    expect((await input.boundingBox())!.height).toBe(inputBefore.height)
    expect((await clear.boundingBox())!.height).toBe(inputBefore.height)
    await expectInViewportAndUnobscured(clear)
    const after=await page.locator('.downstream-credentials-table').boundingBox()
    expect(Math.abs(after!.y-before!.y)).toBeLessThan(2)
    expect((await reset.boundingBox())!.width).toBeLessThan(180)
    await expectInViewportAndUnobscured(reset)
    await page.screenshot({ path: testInfo.outputPath('toolbar-search.png') })
    // Keyboard clearing exercises the same-sized action without scrolling it.
    await clear.focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('.page-toolbar-search input')).toHaveValue('')
    await expect(clear).toHaveCount(0)
    expect((await input.boundingBox())!.height).toBe(inputBefore.height)
    expect(Math.abs((await page.locator('.downstream-credentials-table').boundingBox())!.y-before!.y)).toBeLessThan(2)
    await page.locator('.page-toolbar-search input').fill('Synthetic')
    await reset.click()
    await expect(page.locator('.page-toolbar-search input')).toHaveValue('')
    await expect(reset).toBeDisabled()
    expect(Math.abs((await page.locator('.downstream-credentials-table').boundingBox())!.y-before!.y)).toBeLessThan(2)
    await page.screenshot({ path: testInfo.outputPath('toolbar-reset.png') })
  })
}

test('E2E-592 @smoke audit reset clears search and immediately requests defaults',async({page})=>{
  const requests: string[]=[]
  await page.route('**/v1/access/invocation-audits*',async route=>{
    requests.push(route.request().url())
    await route.fulfill({json:listFixtures['/v1/access/invocation-audits']})
  })
  await page.goto('/console/#/invocationAudit')
  await page.getByRole('radio',{name:'Deny',exact:true}).check()
  await expect.poll(()=>new URL(requests.at(-1)!).searchParams.get('decision')).toBe('deny')
  await page.locator('.page-toolbar-search input').fill('zz-no-match')
  await page.getByRole('button',{name:'Reset conditions',exact:true}).click()
  await expect.poll(()=>new URL(requests.at(-1)!).searchParams.has('decision')).toBe(false)
  await expect(page.locator('.page-toolbar-search input')).toHaveValue('')
  await expect(page.locator('.list-pagination')).toContainText('1–50')
})

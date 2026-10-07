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

for(const width of [390,1366,2048]) {
  test(`E2E-591-${width} @visual reset is compact and does not shift the list`,async({page})=>{
    await page.setViewportSize({width,height:900})
    await page.goto('/console/#/downstreamCredentials')
    const reset=page.getByRole('button',{name:'Reset Filters',exact:true})
    await expect(reset).toBeDisabled()
    const before=await page.locator('.downstream-credentials-table').boundingBox()
    await page.locator('.page-toolbar-search input').fill('Synthetic')
    await expect(reset).toBeEnabled()
    const after=await page.locator('.downstream-credentials-table').boundingBox()
    expect(Math.abs(after!.y-before!.y)).toBeLessThan(2)
    expect((await reset.boundingBox())!.width).toBeLessThan(180)
    await expectInViewportAndUnobscured(reset)
    await reset.click()
    await expect(page.locator('.page-toolbar-search input')).toHaveValue('')
    await expect(reset).toBeDisabled()
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

import { test, expect } from '@playwright/test'
import { readFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

const routes = ['dashboard','servers','myServers','configs','builds','tools','invoke','toolClassifications','logs','invocationAudit','diagnostics','accessUsers','accessRoles','accessGrants','credentials','runtimeCache','systemSettings','connectionInfrastructure','myConnections','myInvocations','downstreamCredentials']

for (const [width, height] of [[2560,1440],[1920,1080],[1600,900],[2560,1080]]) {
  test(`@refactor all primary pages use the shared shell without overflow ${width}x${height}`, async ({ page }) => {
    test.setTimeout(180_000)
    await login(page)
    await page.addInitScript(() => {
      localStorage.setItem('lingshu-gate-console-locale','en-US')
      localStorage.setItem('lingshu-gate-console-theme','light')
    })
    await page.setViewportSize({width,height})
    const errors: string[]=[]
    page.on('pageerror',error=>errors.push(error.message))
    for (const route of routes) {
      await page.goto('/#/'+route)
      await expect(page.locator('.console-main > .console-content')).toBeVisible()
      await expect(page.getByText('Loading page…',{exact:true})).toHaveCount(0)
      await expect(page.locator('[data-console-nav="desktop"] a[aria-current="page"]')).toHaveAttribute('href','#/'+route)
      await expect(page.locator('main')).not.toBeEmpty()
      await expectInViewportAndUnobscured(page.getByRole('button',{name:'Search',exact:true}))
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),route).toBe(true)
      if (width===2560 && height===1440 && process.env.GATE_REFACTOR_SCREENSHOT_DIR && ['dashboard','servers','tools','builds','myConnections','toolClassifications'].includes(route)) {
        await expect(page.locator('main').getByRole('heading').first()).toBeVisible()
        const directory=process.env.GATE_REFACTOR_SCREENSHOT_DIR
        mkdirSync(directory,{recursive:true})
        await page.screenshot({path:join(directory,route+'.png'),animations:'disabled'})
      }
    }
    expect(errors).toEqual([])
    for(const route of ['uploads','personalTokens']) {
      await page.goto('/#/'+route)
      await expect(page.locator('main').getByRole('heading').first()).toBeVisible()
    }
  })
}

test('@refactor a newly connected MCP tool is discovered and invoked without publication',async({page})=>{
  await login(page)
  const {endpoint}=JSON.parse(readFileSync(join(process.env.GATE_E2E_TEMP_ROOT!,'http-peer.json'),'utf8'))
  const id='synthetic-automatic-discovery'
  const response=await page.request.post('/v1/mcp/configs',{data:{manifest:{id,name:'Synthetic automatic discovery',enabled:true,auto_start:false,startup_policy:'gate_start_v1',launch:{type:'external'},transport:{type:'streamable_http',endpoint},timeout_seconds:10},apply:true,start:true,http_trust_action:'auto',expected_http_trust_revision:0}})
  expect(response.ok(),await response.text()).toBe(true)
  await expect.poll(async()=>((await (await page.request.get('/v1/tools')).json()) as Array<{id:string}>).some(tool=>tool.id===`mcp.${id}.echo`)).toBe(true)
  const mutations:string[]=[]
  page.on('request',request=>{if(['POST','PUT','DELETE'].includes(request.method())) mutations.push(new URL(request.url()).pathname)})
  await page.goto('/#/tools')
  await page.getByRole('textbox',{name:'Search tool name, ID or description'}).fill('mcp.'+id+'.echo')
  const card=page.getByRole('article',{name:'echo',exact:true})
  await expect(card).toContainText('Write')
  await card.getByRole('button',{name:'Invoke Tool · echo',exact:true}).click()
  await expect(page).toHaveURL(/#\/invoke$/)
  const run=page.getByRole('button',{name:'Run tool',exact:true})
  await expect(run).toBeEnabled();await run.click()
  await expect(page.locator('.invoke-result')).toContainText('synthetic-loopback-ok')
  expect(mutations.filter(path=>path.includes('tool-classifications'))).toEqual([])
})

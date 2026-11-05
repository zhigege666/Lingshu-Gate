import { test, expect } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { classifications } from './synthetic-data'

test('@refactor dedicated control permissions cannot enter a generic tool-policy edit', async ({ page }) => {
  await login(page)
  const item = { ...classifications[0], tool_name: 'Synthetic control tool', required_access: 'write',
    policy_source: 'builtin_contract', policy_editable: false, policy_constraint: 'control_permission' }
  await page.route('**/v1/access/tool-classifications', route => route.fulfill({json: {classifications: [item]}}))
  await page.goto('/#/toolClassifications')
  const row = page.getByRole('row').filter({hasText: 'Synthetic control tool'})
  await expect(row).toContainText('Control permission')
  await expect(row).toContainText('Role managed')
  await expect(row.getByRole('button')).toHaveCount(0)
  await expect(row.getByRole('checkbox')).toHaveCount(0)
  await expect(page.getByRole('checkbox', {name: 'Select tools on this page', exact: true})).toBeDisabled()
})

test('@refactor policy override saves once, disables, and restores the automatic default', async ({ page }) => {
  await login(page)
  let current = { ...classifications[0], required_access:'write', policy_source:'default_write', status:'pending', effective_access:'unknown', tool_name:'Synthetic policy tool' }
  const writes: {method:string;path:string;body:Record<string,unknown>}[] = []
  await page.route('**/v1/access/tool-classifications**', route => {
    const request=route.request(), path=new URL(request.url()).pathname
    if (request.method()==='GET') return route.fulfill({json:{classifications:[current]}})
    const body=request.postDataJSON(); writes.push({method:request.method(),path,body})
    if (request.method()!=='PUT') return route.fulfill({status:500,json:{detail:'Unexpected review or publish step'}})
    current={...current, required_access:body.access==='unknown'?'none':body.access==='automatic'?'write':body.access, policy_source:body.access==='automatic'?'default_write':'local_override'}
    return route.fulfill({json:current})
  })
  await page.goto('/#/toolClassifications')
  const row=page.getByRole('row').filter({hasText:'Synthetic policy tool'})
  await expect(row).toContainText('Automatic')
  await expect(page.getByRole('button',{name:/publish|review|analysis/i})).toHaveCount(0)
  for (const [option,expected] of [['Disabled','Disabled'],['Automatic default','Automatic']]) {
    await row.getByRole('button',{name:'Set access · Synthetic policy tool',exact:true}).click()
    const dialog=page.getByRole('dialog')
    await dialog.getByRole('radio',{name:option,exact:true}).check()
    await dialog.getByRole('button',{name:'Save and apply',exact:true}).click()
    await expect(dialog).toHaveCount(0); await expect(row).toContainText(expected)
  }
  expect(writes).toHaveLength(2)
  expect(writes.map(w=>w.body.access)).toEqual(['unknown','automatic'])
  expect(writes.every(w=>w.body.expected_fingerprint===current.fingerprint)).toBe(true)
})

test('@refactor partial policy conflict retains failed selection and saved result', async ({page})=>{
  await login(page)
  const items=classifications.slice(0,2).map((item,i)=>({...item,tool_name:`Synthetic policy ${i}`,required_access:'write',policy_source:'default_write',status:'pending'}))
  await page.route('**/v1/access/tool-classifications**', route=>{
    if(route.request().method()==='GET') return route.fulfill({json:{classifications:items}})
    const id=decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!)
    if(id===items[1].tool_id) return route.fulfill({status:409,json:{detail:'Catalog changed; refresh this tool'}})
    return route.fulfill({json:{...items[0],required_access:'write',policy_source:'local_override'}})
  })
  await page.goto('/#/toolClassifications')
  await page.getByRole('checkbox',{name:'Select tools on this page',exact:true}).check()
  await page.getByRole('button',{name:'Set access',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByRole('button',{name:'Save and apply',exact:true}).click()
  await expect(dialog).toContainText('Saved 1'); await expect(dialog).toContainText('Unfinished 1')
  await expect(dialog).toContainText('Catalog changed')
  await dialog.getByRole('button',{name:'Cancel',exact:true}).click()
  await expect(page.getByRole('checkbox',{name:'Select tool Synthetic policy 0',exact:true})).not.toBeChecked()
  await expect(page.getByRole('checkbox',{name:'Select tool Synthetic policy 1',exact:true})).toBeChecked()
})

for (const [width,height] of [[1600,900],[1920,1080],[2560,1080],[2560,1440]]) {
  test(`@refactor policy controls and footer remain reachable ${width}x${height}`,async({page})=>{
    await login(page);await page.setViewportSize({width,height})
    await page.route('**/v1/access/tool-classifications',route=>route.fulfill({json:{classifications:classifications.slice(0,120).map(item=>({...item,required_access:'write',policy_source:'default_write'}))}}))
    await page.goto('/#/toolClassifications')
    const action=page.locator('.tool-review-table tbody tr').first().getByRole('button')
    await expectInViewportAndUnobscured(action)
    await expectInViewportAndUnobscured(page.locator('.list-pagination'))
    await action.click();const dialog=page.getByRole('dialog')
    await expectInViewportAndUnobscured(dialog.getByRole('button',{name:'Save and apply',exact:true}))
    await dialog.getByRole('button',{name:'Cancel',exact:true}).click();await expect(action).toBeFocused()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  })
}

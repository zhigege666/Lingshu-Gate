import {test,expect} from '@playwright/test'
import {login,expectInViewportAndUnobscured} from './helpers'

for(const [width,height] of [[1600,900],[1920,1080],[2560,1080],[2560,1440]]) {
 test(`desktop acceptance ${width}x${height}: focused dashboard fits viewport`,async({page})=>{
  await login(page)
  await page.setViewportSize({width,height})
  await page.goto('/console/#/dashboard')
  await expect(page.locator('[data-dashboard-trend]')).toBeVisible()
  await expectInViewportAndUnobscured(page.locator('[data-dashboard-trend]'))
  await expectInViewportAndUnobscured(page.locator('[data-dashboard-ranking]'))
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  expect(await page.evaluate(()=>document.documentElement.scrollHeight)).toBeLessThanOrEqual(height+2)
  await page.getByRole('button',{name:'How statistics are counted',exact:true}).click()
  await expect(page.getByText(/Only audited, recognized tool requests/)).toBeVisible()
 })
}

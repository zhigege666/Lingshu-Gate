import { test, expect } from '@playwright/test'
import { initialize, expectInViewportAndUnobscured } from './helpers'

for (const viewport of [{ width: 1280, height: 600 }, { width: 390, height: 844 }]) {
  test(`E2E-301 @visual login ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await initialize(page)
    await page.goto('/console/')
    await expectInViewportAndUnobscured(page.getByRole('heading', { name: 'Sign in to Lingshu Gate', exact: true }))
    await expect(page).toHaveScreenshot(`login-${viewport.width}x${viewport.height}.png`, { animations: 'disabled', maxDiffPixelRatio: 0.01 })
  })
}

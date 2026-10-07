import { expect, type Locator, type Page } from '@playwright/test'

/** Does not scroll the target into view: bounding-box + hit testing is stronger than visible. */
export async function expectInViewportAndUnobscured(locator: Locator) {
  await expect(locator).toBeVisible()
  await expect.poll(() => locator.evaluate(element => {
    const r = element.getBoundingClientRect()
    if (r.width <= 0 || r.height <= 0 || r.top < 0 || r.left < 0 || r.bottom > innerHeight || r.right > innerWidth) return false
    return [[.5, .5], [.15, .5], [.85, .5]].every(([x, y]) => {
      const hit = document.elementFromPoint(r.left + r.width * x, r.top + r.height * y)
      return hit !== null && (hit === element || element.contains(hit))
    })
  })).toBe(true)
}

export async function initialize(page: Page) {
  await page.addInitScript(() => localStorage.setItem('lingshu-gate-console-locale', 'en-US'))
}

export async function login(page: Page, identity: 'admin' | 'viewer' = 'admin') {
  const response = await page.request.post('/v1/auth/login', { data: {
    username: identity === 'admin' ? 'admin' : 'synthetic-viewer',
    password: `Synthetic-${identity}-123!`,
  } })
  expect(response.status()).toBe(200)
  await initialize(page)
}

import { expect, test } from '@playwright/test'
import { initialize, login } from './helpers'

for (const locale of ['en-US', 'zh-CN'] as const) {
  for (const entry of ['/', '/console', '/console/', '/console/index.html']) {
    test(`@smoke root entry ${locale} ${entry} preserves bookmark through login and reload`, async ({ page }) => {
      await page.addInitScript(value => localStorage.setItem('lingshu-gate-console-locale', value), locale)
      const query = '?bookmark=one&bookmark=two&return=%2F%23%2FmyServers&label=a+b'
      const response = await page.goto(entry + query + '#/myServers')
      expect(response?.status()).toBe(200)
      expect(response?.headers()['content-type']).toContain('text/html')
      expect(response?.headers()['vary']).toBe('Accept')
      expect(response?.headers()['cache-control']).toContain('no-store')
      if (entry !== '/') {
        const redirect = response?.request().redirectedFrom()
        expect((await redirect?.response())?.status()).toBe(307)
      }
      const expectedUrl = 'http://127.0.0.1:18763/' + query + '#/myServers'
      await expect(page).toHaveURL(expectedUrl)
      await page.getByLabel(locale === 'zh-CN' ? '用户名' : 'Username', { exact: true }).fill('synthetic-viewer')
      await page.getByLabel(locale === 'zh-CN' ? '密码' : 'Password', { exact: true }).fill('Synthetic-viewer-123!')
      await page.getByRole('button', { name: locale === 'zh-CN' ? '登录' : 'Sign in', exact: true }).click()
      await expect(page.locator('main')).toBeVisible()
      await expect(page.locator('a[href="#/myServers"][aria-current="page"]')).toBeVisible()
      await expect(page).toHaveURL(expectedUrl)
      expect((await page.request.get('/v1/auth/me')).status()).toBe(200)
      expect((await page.request.get('/v1/mcp/configs')).status()).toBe(403)
      const session = (await page.context().cookies()).find(cookie => cookie.name === 'lingshu_gate_session')
      expect(session).toMatchObject({ path: '/', httpOnly: true, sameSite: 'Lax' })
      await page.reload()
      await expect(page.locator('a[href="#/myServers"][aria-current="page"]')).toBeVisible()
      await expect(page).toHaveURL(expectedUrl)
    })
  }
}

test('@smoke root hash navigation preserves native back, forward and query', async ({ page }) => {
  await login(page, 'viewer')
  const query = '?source=root-navigation&return=%2F%23%2FmyServers'
  await page.goto('/' + query + '#/myServers')
  await expect(page.locator('a[href="#/myServers"][aria-current="page"]')).toBeVisible()
  await page.locator('a[href="#/tools"]').first().click()
  await expect(page.locator('a[href="#/tools"][aria-current="page"]')).toBeVisible()
  await page.locator('a[href="#/personalTokens"]').first().click()
  await expect(page.locator('a[href="#/personalTokens"][aria-current="page"]')).toBeVisible()
  await page.goBack()
  await expect(page.locator('a[href="#/tools"][aria-current="page"]')).toBeVisible()
  await page.goBack()
  await expect(page.locator('a[href="#/myServers"][aria-current="page"]')).toBeVisible()
  await page.goForward()
  await expect(page.locator('a[href="#/tools"][aria-current="page"]')).toBeVisible()
  await page.reload()
  await expect(page.locator('a[href="#/tools"][aria-current="page"]')).toBeVisible()
  await page.goForward()
  await expect(page.locator('a[href="#/personalTokens"][aria-current="page"]')).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/')
  expect(new URL(page.url()).search).toBe(query)
})

test('@smoke browser root uses new assets while programmatic discovery stays JSON', async ({ page }) => {
  await initialize(page)
  const failedAssets: string[] = []
  page.on('response', response => {
    if ((new URL(response.url()).pathname.startsWith('/assets/') || response.request().resourceType() === 'image') && !response.ok()) failedAssets.push(response.url())
  })
  const html = await page.goto('/')
  expect(html?.status()).toBe(200)
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible()
  const scriptPaths = await page.locator('script[src]').evaluateAll(elements => elements.map(element => new URL((element as HTMLScriptElement).src).pathname))
  expect(scriptPaths.length).toBeGreaterThan(0)
  expect(scriptPaths.every(path => path.startsWith('/assets/'))).toBe(true)
  for (const path of scriptPaths) {
    const fresh = await page.request.get(path)
    const legacy = await page.request.get('/console' + path)
    expect(fresh.status()).toBe(200)
    expect(legacy.status()).toBe(200)
    expect(await fresh.body()).toEqual(await legacy.body())
    expect(fresh.headers()['cache-control']).toContain('immutable')
  }
  expect(failedAssets).toEqual([])
  const json = await page.request.get('/')
  const explicit = await page.request.get('/', { headers: { Accept: 'application/json;q=0.5,text/html;q=1' } })
  const stable = await page.request.get('/v1/meta', { headers: { Accept: 'text/html' } })
  expect(json.headers()['content-type']).toBe('application/json')
  expect(explicit.headers()['content-type']).toBe('application/json')
  expect(await stable.json()).toEqual(await json.json())
  expect(await explicit.json()).toEqual(await json.json())
  for (const response of [json, explicit]) {
    expect(response.headers()['vary']).toBe('Accept')
    expect(response.headers()['cache-control']).toContain('no-store')
  }
})

import { expect, test } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'

test('@smoke check for updates through the selected proxy after saving its revision', async ({ page }) => {
  await login(page)
  const profile = { id: 'release-proxy', version: 4, name: 'Release proxy', enabled: true, scheme: 'https' }
  let saved = false
  const checks: string[] = []
  await page.route('**/v1/system-settings/network', route => route.fulfill({ json: {
    profiles: [profile], revision: 1, defaults: { git: { mode: 'direct' }, install: { mode: 'direct' }, git_hosts: [] },
    executor: { available: false },
  } }))
  await page.route('**/v1/system-settings/updates', route => {
    if (route.request().method() === 'PUT') {
      expect(route.request().postDataJSON()).toEqual({ expected_revision: 0, proxy_profile_id: profile.id, proxy_profile_version: 4 })
      saved = true
    }
    return route.fulfill({ json: { current_version: '0.5.11', revision: saved ? 1 : 0, proxy_profile: saved ? profile : null } })
  })
  await page.route('**/v1/system-settings/updates/check', route => {
    const proxy = saved ? 'configured' : 'direct'
    checks.push(proxy)
    return route.fulfill({ json: { current_version: '0.5.11', latest_version: '0.5.12', update_available: true,
      release_name: 'Gate v0.5.12', release_notes: 'Synthetic release notes', published_at: '2026-11-04T00:00:00Z', proxy } })
  })
  await page.goto('/console/#/systemSettings')
  await page.getByRole('tab', { name: 'Updates', exact: true }).click()
  await expect(page.getByText('Checked via · Direct')).toBeVisible()
  await page.getByLabel('Check proxy', { exact: true }).click()
  await page.getByText('Release proxy · v4', { exact: true }).click()
  await page.getByRole('button', { name: 'Save and check' }).click()
  await expect(page.getByText('Checked via · Proxy')).toBeVisible()
  expect(checks).toEqual(['direct', 'configured'])
  for (const [width, height] of [[2560, 1440], [1920, 1080], [1600, 900], [2560, 1080]]) {
    await page.setViewportSize({ width, height })
    await expectInViewportAndUnobscured(page.getByRole('button', { name: 'Check for updates' }))
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  }
})

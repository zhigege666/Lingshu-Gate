import { test, expect, type Page } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { servers } from './synthetic-data'

const server = { ...servers[0], launch_type: 'external', status: 'running', enabled: true }
const manifest = { id: server.id, name: server.name, enabled: true, launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint: 'http://127.0.0.1:1/mcp' }, timeout_seconds: 30 }
async function openEditor(page: Page, historyForward = false) {
  await login(page)
  await page.route('**/v1/mcp/servers', route => route.fulfill({ json: { servers: [server], load_errors: [] } }))
  await page.route('**/v1/mcp/servers/*/detail?*', route => route.fulfill({ json: { server, manifest, tools: [] } }))
  await page.route('**/v1/mcp/configs/*/validate', route => route.fulfill({ json: { ok: true, can_apply: true, manifest_id: server.id, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] } }))
  await page.setViewportSize({ width: 1280, height: 600 })
  if (historyForward) {
    await page.goto('/console/#/dashboard')
    await page.locator('.console-rail-item[href="#/servers"]').click()
    await page.locator('.console-rail-item[href="#/tools"]').click()
    await page.goBack()
  } else await page.goto('/console/#/servers')
  await page.getByRole('tab', { name: 'Configuration', exact: true }).click()
  await page.getByRole('button', { name: 'Edit configuration', exact: true }).click()
  return page.getByRole('dialog', { name: `Edit configuration · ${server.id}`, exact: true })
}

test('E2E-201 @full cancelling save-only confirmation sends no mutation', async ({ page }, testInfo) => {
  const editor = await openEditor(page)
  const writes: string[] = []
  await page.route('**/v1/mcp/configs/*', async route => {
    if (route.request().method() === 'PUT') { writes.push(route.request().url()); await route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } }) }
    else await route.fallback()
  })
  await editor.getByRole('radio', { name: 'Save only (not applied)', exact: true }).check()
  const save = editor.getByRole('button', { name: 'Save only (not applied)', exact: true })
  await expectInViewportAndUnobscured(save)
  await page.screenshot({ path: testInfo.outputPath('mock-service-config-short.png') })
  await save.click()
  const confirm = page.getByRole('alertdialog')
  await expect(confirm).toBeVisible()
  await expectInViewportAndUnobscured(confirm.getByRole('button', { name: 'Cancel', exact: true }))
  await confirm.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  await expect(save).toBeEnabled()
  expect(writes).toEqual([])
})

test('E2E-202 @full HTTP200 failed activation retains editor and blocks duplicate save', async ({ page }) => {
  const editor = await openEditor(page)
  let writes = 0
  let release: (() => void) | undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/v1/mcp/configs/*', async route => {
    if (route.request().method() !== 'PUT') return route.fallback()
    writes++
    await gate
    await route.fulfill({ json: { config: { id: server.id, path: '/synthetic/config.json', format: 'json', manifest }, server: { ...server, status: 'failed', last_error: 'Synthetic activation failed' }, message: 'Synthetic failure' } })
  })
  await editor.getByRole('button', { name: 'Save and reconnect', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Save and reconnect', exact: true }).click()
  await expect.poll(() => writes).toBe(1)
  await expect(editor.getByRole('button', { name: 'Saving…', exact: true })).toBeDisabled()
  await page.keyboard.press('Enter')
  expect(writes).toBe(1)
  release!()
  await expect(editor.getByText('Synthetic activation failed', { exact: true })).toBeVisible()
  await expect(editor).toBeVisible()
  await expect(editor.getByRole('button', { name: 'Save and reconnect', exact: true })).toBeEnabled()
})


test('E2E-204 @full cancelled Back and Forward preserve dirty service configuration', async ({ page }) => {
  const editor = await openEditor(page, true)
  const name = editor.getByLabel('Name', { exact: true })
  await name.fill('Synthetic unsaved draft')
  for (const direction of ['forward', 'back'] as const) {
    await page.evaluate(direction => history[direction](), direction)
    const dialog = page.getByRole('alertdialog', { name: 'Discard changes and leave?', exact: true })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Keep editing', exact: true }).click()
    await expect(page).toHaveURL(/#\/servers$/)
    await expect(name).toHaveValue('Synthetic unsaved draft')
  }
})

import { expect, test, type Page } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { login } from './helpers'
import { builds, deployments, tokens, uploads } from './synthetic-data'

/**
 * Opt-in README layout screenshots, not authorization or deployment evidence.
 * MCP connections and echo calls use the isolated E2E backend/loopback peer.
 * Project history and token metadata are synthetic GET responses only: no
 * project is built/deployed and no real token is created or exposed here.
 *
 * GATE_REFACTOR_SCREENSHOT_DIR=../docs/images/console-refactor \
 *   npm exec playwright test -- e2e/console-screenshots.spec.ts
 */
const output = process.env.GATE_REFACTOR_SCREENSHOT_DIR
const demos = [
  { id: 'console-demo-development', name: 'Demo · Development' },
  { id: 'console-demo-staging', name: 'Demo · Staging' },
  { id: 'console-demo-automation', name: 'Demo · Automation' },
]

test.use({ viewport: { width: 2560, height: 1440 }, locale: 'en-US', colorScheme: 'light', timezoneId: 'UTC' })

test('@readme populated Console layout screenshots with isolated demo data', async ({ page }) => {
  test.skip(!output, 'Set GATE_REFACTOR_SCREENSHOT_DIR to generate the README PNG files')
  test.setTimeout(120_000)
  await login(page)
  await page.addInitScript(() => {
    localStorage.setItem('lingshu-gate-console-locale', 'en-US')
    localStorage.setItem('lingshu-gate-console-theme', 'light')
  })

  const { endpoint } = JSON.parse(readFileSync(join(process.env.GATE_E2E_TEMP_ROOT!, 'http-peer.json'), 'utf8'))
  for (const demo of demos) {
    const created = await page.request.post('/v1/mcp/configs', { data: {
      manifest: { ...demo, enabled: true, auto_start: false, startup_policy: 'gate_start_v1', launch: { type: 'external' }, transport: { type: 'streamable_http', endpoint }, timeout_seconds: 10 },
      apply: true, start: true, http_trust_action: 'auto', expected_http_trust_revision: 0,
    } })
    expect(created.ok(), await created.text()).toBe(true)
  }
  let runningCount = 0, mcpToolCount = 0
  await expect.poll(async () => {
    const response = await page.request.get('/v1/mcp/servers')
    expect(response.ok()).toBe(true)
    const { servers } = await response.json() as { servers: { id: string; status: string }[] }
    runningCount = servers.filter(server => server.status === 'running').length
    return demos.every(demo => servers.some(server => server.id === demo.id && server.status === 'running'))
  }).toBe(true)
  await expect.poll(async () => {
    const response = await page.request.get('/v1/tools')
    expect(response.ok()).toBe(true)
    const available = await response.json() as { id: string; source: string }[]
    mcpToolCount = available.filter(tool => tool.source === 'mcp').length
    return demos.every(demo => available.some(tool => tool.id === `mcp.${demo.id}.echo`))
  }).toBe(true)
  // Populate the overview with real successful calls against the loopback fixture.
  // New tools are used immediately; no classification publication is performed.
  for (const demo of demos) {
    const invoked = await page.request.post(`/v1/tools/mcp.${demo.id}.echo/invoke`, { data: { arguments: {} } })
    expect(invoked.ok(), await invoked.text()).toBe(true)
  }

  const projects = uploads.slice(0, 3).map((item, index) => ({ ...item, id: `demo-project-${index + 1}`, filename: `demo-${['development', 'staging', 'automation'][index]}-mcp.zip` }))
  const history = builds.slice(0, 6).map((item, index) => ({
    ...item, id: `demo-build-${String(index + 1).padStart(2, '0')}`, upload_id: projects[index % projects.length].id,
    runtime: index % 2 ? 'node' : 'python', status: ['success', 'success', 'failed', 'cancelled', 'success', 'success'][index],
    manifest: { id: demos[index % demos.length].id },
    created_at: `2026-11-03T0${9 - index}:00:00Z`, updated_at: `2026-11-03T0${9 - index}:02:18Z`,
  }))
  const deploymentHistory = deployments.slice(0, 2).map((item, index) => ({ ...item, id: `demo-deployment-${index + 1}`, build_id: history[index].id, server_id: demos[index].id, status: 'success', started: true }))
  const tokenMetadata = tokens.slice(0, 4).map((item, index) => ({
    ...item, id: `demo-display-token-${index + 1}`, name: ['Demo · Desktop assistant', 'Demo · Build automation', 'Demo · Research notebook', 'Demo · QA workspace'][index],
    token_prefix: `demo-display-only-${index + 1}`, authorization_mode: index === 0 ? 'account' : 'independent',
    tool_discovery_mode: index === 2 ? 'direct' : 'on_demand', scopes: ['tools.read', 'tools.invoke'],
    server_policies: index === 1 ? [{ server_id: demos[2].id, mode: 'continuous', access: 'write' }] : [],
    tool_ids: index > 1 ? demos.slice(0, index - 1).map(demo => `mcp.${demo.id}.echo`) : [],
    rate_per_minute: [6000, 1200, 600, 300][index], concurrency: [100, 20, 10, 5][index],
    expires_at: index === 0 ? null : '2099-01-01T00:00:00Z',
  }))
  const fixtures: Record<string, unknown> = {
    '/v1/projects/uploads': { uploads: projects }, '/v1/builds': { builds: history }, '/v1/deployments': { deployments: deploymentHistory },
    '/v1/auth/tokens': { tokens: tokenMetadata }, '/v1/auth/oauth/grants': { grants: [] },
    '/v1/auth/external-grants': { grants: [], connection_ready: false, activation_errors: [] },
  }
  const unexpectedWrites: string[] = [], apiErrors: string[] = [], runtimeErrors: string[] = []
  page.on('pageerror', error => runtimeErrors.push(error.message))
  page.on('response', response => {
    const path = new URL(response.url()).pathname
    if (path.startsWith('/v1/') && response.status() >= 400) apiErrors.push(`${response.status()} ${path}`)
  })
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    // After setup the screenshot journey is read-only, including token actions.
    if (request.method() !== 'GET') {
      unexpectedWrites.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 409, json: { detail: 'Layout screenshot data is read-only' } })
    }
    if (path in fixtures) return route.fulfill({ json: fixtures[path] })
    if (path.startsWith('/v1/delivery-drafts/')) return route.fulfill({ json: {
      upload_id: path.split('/').at(-1), revision: 0, manifest_patch: {}, server_id: null, build_id: null, deployment_id: null,
      start: false, overwrite: false, project_root: '.', runtime_override: null, package_manager_override: null,
    } })
    if (/^\/v1\/builds\/[^/]+\/logs$/.test(path)) return route.fulfill({ json: { logs: [], has_earlier: false, has_later: false } })
    return route.continue()
  })
  mkdirSync(output!, { recursive: true })
  async function open(view: string) {
    await page.goto(`/console/#/${view}`)
    await expect(page.locator('main').getByRole('heading').first()).toBeVisible()
    await expect(page.getByText('Loading page…', { exact: true })).toHaveCount(0)
  }
  async function capture(name: string) {
    await expect(page.locator('main [data-slot="skeleton"], main .ant-skeleton, main .ant-spin-spinning')).toHaveCount(0)
    await expect(page.locator('main').getByRole('alert')).toHaveCount(0)
    await settleLayout(page)
    expect(apiErrors).toEqual([])
    expect(runtimeErrors).toEqual([])
    await page.screenshot({ path: join(output!, `${name}.png`), animations: 'disabled' })
  }

  await open('dashboard')
  await expect(page.locator('[data-resource="servers"]')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('[data-resource="servers"]')).toContainText(`${runningCount} running`)
  await expect(page.locator('[data-resource="tools"]')).toContainText(`${mcpToolCount} MCP`)
  await expect(page.locator('.dashboard-metric-grid [data-slot="skeleton"]')).toHaveCount(0)
  await capture('dashboard')

  await open('servers')
  for (const demo of demos) await expect(page.locator('.service-entry').filter({ hasText: demo.id })).toContainText(/Running/i)
  await capture('servers')

  await open('tools')
  await page.getByRole('textbox', { name: 'Search tool name, ID or description', exact: true }).fill('console-demo')
  for (const demo of demos) await expect(page.getByRole('article', { name: 'echo', exact: true }).filter({ hasText: `mcp.${demo.id}.echo` })).toBeVisible()
  await capture('tools')

  await open('toolClassifications')
  await page.getByRole('textbox', { name: 'Search tools or services', exact: true }).fill('console-demo')
  for (const demo of demos) await expect(page.getByRole('row').filter({ hasText: `mcp.${demo.id}.echo` })).toContainText('Automatic')
  await capture('toolClassifications')
  await page.getByRole('row').filter({ hasText: `mcp.${demos[0].id}.echo` }).getByRole('button', { name: 'Set access · echo', exact: true }).click()
  const policyDialog = page.getByRole('dialog', { name: 'Tool access · echo', exact: true })
  await expect(policyDialog.getByRole('button', { name: 'Save and apply', exact: true })).toBeVisible()
  await settleLayout(page)
  await page.screenshot({ path: join(output!, 'toolAccessDialog.png'), animations: 'disabled' })
  await policyDialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(policyDialog).toHaveCount(0)

  await open('builds')
  await page.getByRole('tab', { name: /^Build history/ }).click()
  await expect(page.locator('.build-records-table tbody tr')).toHaveCount(history.length)
  for (const build of history) await expect(page.locator('.build-records-table').locator(`code[title="${build.id}"]`)).toBeVisible()
  await capture('builds')

  await open('myConnections')
  for (const token of tokenMetadata) await expect(page.getByRole('row').filter({ hasText: token.name })).toContainText('Active')
  await expect(page.getByRole('button', { name: 'Create API token', exact: true })).toBeEnabled()
  await capture('myConnections')
  expect(unexpectedWrites).toEqual([])
})

async function settleLayout(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
  })
}

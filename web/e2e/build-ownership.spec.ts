import { test, expect, type Page } from '@playwright/test'
import { login } from './helpers'

function deferred() { let release!: () => void; const wait = new Promise<void>(resolve => { release = resolve }); return { wait, release } }
async function fixture(page: Page, withHistory = false, createMode: 'off' | 'success' | 'conflict' | 'retry' | 'post-conflict' = 'off') {
  await login(page)
  const time = '2026-01-01T00:00:00Z'
  const uploads = ['a', 'b', 'c'].map(id => ({ id: `upload-${id}`, filename: `project-${id}.zip`, status: 'uploaded', detected_runtime: 'python', root_dir: `/synthetic/${id}`, analysis: {}, created_at: time, updated_at: time }))
  let builds = ['a', 'b'].map(id => ({ id: `build-${id}`, upload_id: `upload-${id}`, status: 'success', runtime: 'python', source_dir: `/synthetic/${id}`, artifact_dir: `/synthetic/artifact-${id}`, commands: [], logs: [], manifest: { id: `service-${id}`, name: `Service ${id}`, enabled: false, launch: { type: 'external' }, transport: { type: 'streamable_http', url: 'http://127.0.0.1:1/mcp' } }, created_at: time, updated_at: time }))
  if (createMode === 'retry') builds[1].status = 'failed'
  const deployments = ['a', 'b'].map(id => ({ id: `deployment-${id}`, build_id: `build-${id}`, server_id: `service-${id}`, status: 'success', manifest: {}, previous_manifest: { id: `service-${id}` }, rollback_available: true, started: false, created_at: time, updated_at: time }))
  deployments.push({ ...deployments[1], id: 'deployment-b-old' })
  const drafts = Object.fromEntries(['a', 'b', 'c'].map(id => [`upload-${id}`, { upload_id: `upload-${id}`, revision: 1, manifest_patch: {}, server_id: `saved-${id}`, build_id: id === 'c' ? null : `build-${id}`, deployment_id: null, start: false, overwrite: false, project_root: '.', runtime_override: null }]))
  const state = { draftReads: 0, staleDraftStarted: false, staleDraft: deferred(), holdRefresh: false, refreshStarted: false, refresh: deferred(), deleteStarted: false, deletion: deferred(), preflightStarted: false, preflight: deferred(), operations: [] as Array<{ path: string; body: Record<string, unknown> }>, rollbacks: [] as unknown[], writes: [] as string[] }
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
    if (method !== 'GET') state.writes.push(`${method} ${path}`)
    if (createMode !== 'off' && method === 'POST' && path === '/v1/builds/preflight') return route.fulfill({ json: { status: 'ok', runtime: 'python', checks: [], recommendations: [], tools: {}, metadata: {} } })
    if (createMode !== 'off' && method === 'PUT' && path.startsWith('/v1/delivery-drafts/')) {
      const body = request.postDataJSON(); const uploadId = path.split('/').at(-1)!; state.operations.push({ path, body })
      if (createMode === 'conflict' || createMode === 'post-conflict' && body.expected_revision === 2) return route.fulfill({ status: 409, json: { detail: { code: 'draft_revision_conflict', message: 'Synthetic draft conflict' } } })
      expect(body.expected_revision).toBe(drafts[uploadId].revision)
      drafts[uploadId] = { ...drafts[uploadId], ...body, revision: drafts[uploadId].revision + 1 }
      return route.fulfill({ json: drafts[uploadId] })
    }
    if (createMode !== 'off' && method === 'POST' && path === '/v1/builds') {
      state.operations.push({ path, body: request.postDataJSON() }); const build = { ...builds.find(item => item.upload_id === request.postDataJSON().upload_id)!, id: 'build-new', status: 'success' }; builds.unshift(build); return route.fulfill({ json: build })
    }
    if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads } })
    if (path === '/v1/builds' && method === 'GET') { if (state.holdRefresh) { state.holdRefresh = false; state.refreshStarted = true; await state.refresh.wait } return route.fulfill({ json: { builds } }) }
    if (path === '/v1/deployments') return route.fulfill({ json: { deployments } })
    if (/^\/v1\/builds\/[^/]+\/logs$/.test(path)) return route.fulfill({ json: { logs: [] } })
    if (createMode === 'retry' && path === '/v1/delivery-drafts/upload-b' && method === 'GET') {
      state.draftReads++; const snapshot = structuredClone(drafts['upload-b'])
      if (state.draftReads === 1) { state.staleDraftStarted = true; await state.staleDraft.wait }
      return route.fulfill({ json: snapshot })
    }
    if (path.startsWith('/v1/delivery-drafts/')) return route.fulfill({ json: drafts[path.split('/').at(-1)!] })
    if (path === '/v1/builds/build-a' && method === 'DELETE') { state.deleteStarted = true; await state.deletion.wait; builds = builds.filter(build => build.id !== 'build-a'); return route.fulfill({ json: { id: 'build-a' } }) }
    if (path === '/v1/builds/preflight') { state.preflightStarted = true; await state.preflight.wait; return route.fulfill({ json: { upload_id: 'upload-a', status: 'ok', runtime: 'STALE_RUNTIME', detected_runtime: 'python', platform: 'linux', project_root_dir: '/synthetic/a', checks: [], recommendations: [], tools: {}, metadata: {} } }) }
    if (/\/rollback$/.test(path)) { const body = request.postDataJSON(); const deployment = deployments.find(item => item.id === path.split('/')[3])!; state.rollbacks.push({ path, body }); return route.fulfill({ json: { deployment, server: { id: deployment.server_id, status: body.start ? 'running' : 'stopped' }, message: 'Synthetic rollback' } }) }
    return route.continue()
  })
  await page.goto('/console/#/builds/build-a')
  await expect(page.getByRole('combobox', { name: 'Select upload', exact: true })).toBeEnabled()
  if (withHistory) {
    await page.locator('.console-rail-item[href="#/dashboard"]').click()
    await expect(page).toHaveURL(/dashboard$/)
    await page.goBack()
    await expect(page).toHaveURL(/build-a$/)
  }
  await page.getByText('Advanced settings (runtime, root, server ID)', { exact: true }).click()
  await expect(page.getByLabel('Optional: override server_id on deploy', { exact: true })).toHaveValue('saved-a')
  return state
}
async function choose(page: Page, id: string) {
  const combo = page.getByRole('combobox', { name: 'Select upload', exact: true })
  await combo.click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: `project-${id}.zip` }).click()
}
const target = (page: Page) => page.getByLabel('Optional: override server_id on deploy', { exact: true })

test('E2E-501 @build-ownership delayed refresh preserves a newly selected upload without a build', async ({ page }) => {
  const state = await fixture(page)
  state.holdRefresh = true
  await page.getByRole('button', { name: 'Refresh current page', exact: true }).click()
  await expect.poll(() => state.refreshStarted).toBe(true)
  await choose(page, 'c')
  await expect(target(page)).toHaveValue('saved-c')
  state.refresh.release()
  await expect(page.getByRole('button', { name: 'Refresh current page', exact: true })).toBeEnabled()
  await expect(target(page)).toHaveValue('saved-c')
  await expect(page).not.toHaveURL(/build-a$/)
})

test('E2E-502 @build-ownership deleting a noncurrent build does not select its upload', async ({ page }) => {
  const state = await fixture(page)
  await choose(page, 'b')
  await expect(target(page)).toHaveValue('saved-b')
  await page.getByRole('tab', { name: /Build history/ }).click()
  await page.locator('tbody tr').filter({ hasText: 'build-a' }).getByRole('button', { name: 'Delete record', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(() => state.deleteStarted).toBe(true)
  state.deletion.release()
  await expect(page.locator('tbody tr').filter({ hasText: 'build-a' })).toHaveCount(0)
  await expect(page).toHaveURL(/build-b$/)
  await page.getByRole('tab', { name: 'Workspace', exact: true }).click()
  await expect(target(page)).toHaveValue('saved-b')
})

test('E2E-503 @build-ownership cross-upload target switch respects dirty cancel then saved draft', async ({ page }) => {
  const state = await fixture(page)
  await target(page).fill('unsaved-a')
  await choose(page, 'b')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(target(page)).toHaveValue('unsaved-a')
  await expect(page).toHaveURL(/build-a$/)
  expect(state.writes).toEqual([])
  await choose(page, 'b')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(target(page)).toHaveValue('saved-b')
  await expect(page).toHaveURL(/build-b$/)
  expect(state.writes).toEqual([])
})

test('E2E-504 @build-ownership pending preflight blocks real navigation and does not leak after switching', async ({ page }) => {
  const state = await fixture(page, true)
  await page.getByRole('button', { name: 'Run Preflight', exact: true }).click()
  await expect.poll(() => state.preflightStarted).toBe(true)
  await expect(page.getByRole('combobox', { name: 'Select upload', exact: true })).toBeDisabled()
  await page.goForward()
  await expect(page.getByRole('alertdialog')).toContainText('Submission in progress')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Return to editor', exact: true }).click()
  await expect(page).toHaveURL(/build-a$/)
  state.preflight.release()
  await expect(page.getByRole('button', { name: 'Run Preflight', exact: true })).toBeEnabled()
  await expect(page.locator('main')).toContainText('STALE_RUNTIME')
  await choose(page, 'b')
  await expect(target(page)).toHaveValue('saved-b')
  await expect(page.locator('main')).not.toContainText('STALE_RUNTIME')
})

test('E2E-505 @build-ownership rollback on another deployment does not inherit start', async ({ page }) => {
  const state = await fixture(page)
  await page.getByRole('tab', { name: /Deployment history/ }).click()
  await page.getByRole('checkbox', { name: /^Start after rollback/ }).check()
  await page.locator('tbody tr').filter({ has: page.locator('code[title="deployment-b"]') }).getByRole('button', { name: 'Rollback', exact: true }).click()
  const confirmation = page.getByRole('alertdialog')
  const summary = await confirmation.textContent()
  await confirmation.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(() => state.rollbacks.length).toBe(1)
  expect(state.rollbacks[0]).toEqual({ path: '/v1/deployments/deployment-b/rollback', body: { start: false } })
  expect(summary).toContain('Start after rollback: No')
})


test('E2E-506 @build-ownership rollback option belongs to the selected deployment even within one build', async ({ page }) => {
  const state = await fixture(page)
  await page.getByRole('tab', { name: /Deployment history/ }).click()
  const old = page.locator('tbody tr').filter({ has: page.locator('code[title="deployment-b-old"]') })
  await old.locator('code[title="deployment-b-old"]').click()
  await expect(old).toHaveAttribute('data-state', 'selected')
  const start = page.getByRole('checkbox', { name: /^Start after rollback/ })
  await expect(start).not.toBeChecked()
  await start.check()
  await old.getByRole('button', { name: 'Rollback', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('Start after rollback: Yes')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(() => state.rollbacks.length).toBe(1)
  expect(state.rollbacks[0]).toEqual({ path: '/v1/deployments/deployment-b-old/rollback', body: { start: true } })
  const other = page.locator('tbody tr').filter({ has: page.locator('code[title="deployment-b"]') })
  await expect(other.getByRole('button', { name: 'Rollback', exact: true })).toBeEnabled()
  await other.getByRole('button', { name: 'Rollback', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('Start after rollback: No')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect.poll(() => state.rollbacks.length).toBe(2)
  expect(state.rollbacks[1]).toEqual({ path: '/v1/deployments/deployment-b/rollback', body: { start: false } })
})


async function editBuildOptions(page: Page) {
  await target(page).fill('fresh-target')
  await page.getByLabel('Project root', { exact: true }).fill('synthetic-subdir')
  await page.getByRole('checkbox', { name: /^Start after deploy/ }).check()
  await page.getByRole('checkbox', { name: /^Overwrite existing/ }).check()
}

test('E2E-508 @build-ownership create persists fresh options before build and links with next revision', async ({ page }) => {
  const state = await fixture(page, false, 'success')
  await editBuildOptions(page)
  const create = page.getByRole('button', { name: 'Create Build', exact: true })
  await create.click()
  await expect.poll(() => state.operations.map(item => item.path)).toEqual(['/v1/delivery-drafts/upload-a', '/v1/builds', '/v1/delivery-drafts/upload-a'])
  await expect(create).toBeEnabled()
  const options = { server_id: 'fresh-target', start: true, overwrite: true, project_root: 'synthetic-subdir', runtime_override: null }
  expect(state.operations[0].body).toMatchObject({ ...options, expected_revision: 1, build_id: 'build-a' })
  expect(state.operations[1].body).toMatchObject({ upload_id: 'upload-a', project_root: 'synthetic-subdir', runtime_override: null })
  expect(state.operations[2].body).toMatchObject({ ...options, expected_revision: 2, build_id: 'build-new', deployment_id: null })
  await expect(target(page)).toHaveValue('fresh-target')
  await expect(page.getByRole('checkbox', { name: /^Start after deploy/ })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: /^Overwrite existing/ })).toBeChecked()
})

test('E2E-509 @build-ownership conflicting option save preserves input and creates no build', async ({ page }) => {
  const state = await fixture(page, false, 'conflict')
  await editBuildOptions(page)
  const create = page.getByRole('button', { name: 'Create Build', exact: true })
  await create.click()
  await expect.poll(() => state.operations.some(item => item.path === '/v1/delivery-drafts/upload-a')).toBe(true)
  await expect(create).toBeEnabled()
  expect(state.operations.map(item => item.path)).toEqual(['/v1/delivery-drafts/upload-a'])
  await expect(target(page)).toHaveValue('fresh-target')
  await expect(page.getByLabel('Project root', { exact: true })).toHaveValue('synthetic-subdir')
  await expect(page.getByRole('checkbox', { name: /^Start after deploy/ })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: /^Overwrite existing/ })).toBeChecked()
  await expect(page).toHaveURL(/build-a$/)
})


test('E2E-510 @build-ownership cross-upload retry keeps destination draft despite late older revision', async ({ page }) => {
  const state = await fixture(page, false, 'retry')
  await page.getByRole('tab', { name: /Build history/ }).click()
  await page.locator('tbody tr').filter({ has: page.locator('code[title="build-b"]') }).getByRole('button', { name: 'Rebuild', exact: true }).click()
  await expect.poll(() => state.operations.length).toBe(3)
  await expect.poll(() => state.staleDraftStarted).toBe(true)
  await expect(page.getByRole('button', { name: 'Create Build', exact: true })).toBeEnabled()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  expect(state.operations[0]).toMatchObject({ path: '/v1/delivery-drafts/upload-b', body: { expected_revision: 1, server_id: 'saved-b', start: false, overwrite: false } })
  expect(state.operations[2]).toMatchObject({ path: '/v1/delivery-drafts/upload-b', body: { expected_revision: 2, server_id: 'saved-b', build_id: 'build-new' } })
  const staleReturned = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === '/v1/delivery-drafts/upload-b')
  state.staleDraft.release()
  await (await staleReturned).finished()
  await expect(page).toHaveURL(/build-new$/)
  await expect(target(page)).toHaveValue('saved-b')
  await page.getByText('Advanced settings (runtime, root, server ID)', { exact: true }).click()
  await target(page).fill('saved-b-confirmed')
  await page.getByRole('button', { name: 'Save delivery options', exact: true }).click()
  await expect.poll(() => state.operations.length).toBe(4)
  expect(state.operations[3]).toMatchObject({ path: '/v1/delivery-drafts/upload-b', body: { expected_revision: 3, server_id: 'saved-b-confirmed', build_id: 'build-new' } })
})

test('E2E-511 @build-ownership post-build draft conflict retains created build and fresh options without retry', async ({ page }) => {
  const state = await fixture(page, false, 'post-conflict')
  await editBuildOptions(page)
  const create = page.getByRole('button', { name: 'Create Build', exact: true })
  await create.click()
  await expect.poll(() => state.operations.length).toBe(3)
  await expect(create).toBeEnabled()
  await expect(page).toHaveURL(/build-new$/)
  await expect(target(page)).toHaveValue('fresh-target')
  await expect(page.getByRole('checkbox', { name: /^Start after deploy/ })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: /^Overwrite existing/ })).toBeChecked()
  expect(state.operations.filter(item => item.path === '/v1/builds')).toHaveLength(1)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page.getByText(/Build build-new was created, but its task context could not be saved/)).toBeVisible()
})

test('E2E-512 @build-ownership history deployment opens its owner before requiring a loaded draft', async ({ page }) => {
  const state = await fixture(page)
  await page.goto('/console/#/builds')
  await page.getByRole('tab', { name: /Build history/ }).click()
  const writesBefore = state.writes.length
  await page.locator('tbody tr').filter({ hasText: 'build-a' }).getByRole('button', { name: 'Deploy Build', exact: true }).click()
  await expect(page).toHaveURL(/build-a$/)
  await expect(page.getByRole('tab', { name: 'Workspace', exact: true })).toHaveAttribute('aria-selected', 'true')
  await page.getByText('Advanced settings (runtime, root, server ID)', { exact: true }).click()
  await expect(target(page)).toHaveValue('saved-a')
  expect(state.writes.slice(writesBefore)).toEqual([])
})

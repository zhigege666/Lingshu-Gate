import { expect, test } from '@playwright/test'
import type { DeliveryDraft } from '../src/api/builds'
import type { ToolClassification } from '../src/api/client'
import { expectInViewportAndUnobscured, login } from './helpers'

// These routes exercise client state and keyboard interaction with synthetic
// records. They do not establish backend permission or deployment behavior.
test('saving upload build options preserves deployment defaults and pending install input', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  const upload = {
    id: 'synthetic-upload', filename: 'synthetic-project.zip', status: 'uploaded',
    detected_runtime: 'python', root_dir: '/synthetic/project', analysis: {},
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  }
  let draft: DeliveryDraft = {
    upload_id: upload.id, revision: 1, manifest_patch: { name: 'Saved name' },
    server_id: 'saved-target', build_id: null, deployment_id: null,
    project_root: '.', runtime_override: null, package_manager_override: null,
    start: true, overwrite: true,
  }
  const savedRequests: Record<string, unknown>[] = []
  const unexpectedWrites: string[] = []
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === `/v1/delivery-drafts/${upload.id}`) {
      if (request.method() === 'GET') return route.fulfill({ json: draft })
      if (request.method() === 'PUT') {
        const body = request.postDataJSON()
        savedRequests.push(body)
        draft = { ...draft, ...body, revision: draft.revision + 1 }
        return route.fulfill({ json: draft })
      }
    }
    if (request.method() !== 'GET') {
      unexpectedWrites.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in synthetic delivery journey' } })
    }
    if (path === '/v1/projects/uploads') return route.fulfill({ json: { uploads: [upload] } })
    if (path === '/v1/builds') return route.fulfill({ json: { builds: [] } })
    if (path === '/v1/deployments') return route.fulfill({ json: { deployments: [] } })
    return route.continue()
  })

  await page.goto('/console/#/uploads')
  const historyTrigger = page.getByRole('button', { name: 'Upload history', exact: true })
  await historyTrigger.click()
  const history = page.getByRole('dialog', { name: 'Upload history', exact: true })
  await expect(history.getByRole('button', { name: /synthetic-project\.zip/ })).toBeVisible()
  await expectInViewportAndUnobscured(history.getByRole('button', { name: 'Close', exact: true }))
  await expect.poll(() => history.evaluate(element => {
    const rect = element.getBoundingClientRect()
    return Math.abs((rect.left + rect.right) / 2 - innerWidth / 2)
      + Math.abs((rect.top + rect.bottom) / 2 - innerHeight / 2)
  })).toBeLessThan(2)
  await page.keyboard.press('Escape')
  await expect(history).toHaveCount(0)
  await expect(historyTrigger).toBeFocused()
  await historyTrigger.click()
  await history.getByRole('button', { name: /synthetic-project\.zip/ }).click()
  await expect(history).toHaveCount(0)

  const target = page.getByRole('textbox', { name: 'Target server', exact: true })
  const projectRoot = page.getByRole('textbox', { name: /^Project root/ })
  await expect(target).toHaveCount(0) // Deployment inputs appear after a successful build.
  await projectRoot.fill('subproject')
  await page.getByText('Advanced build options', { exact: true }).click()
  const install = page.getByRole('checkbox', { name: 'Install dependencies using detected settings', exact: true })
  await install.uncheck()
  await page.getByRole('button', { name: 'Save build options', exact: true }).click()
  await expect.poll(() => savedRequests.length).toBe(1)
  await expect(page.getByRole('button', { name: 'Save build options', exact: true })).toHaveCount(0)
  await expect(target).toHaveCount(0)
  await expect(projectRoot).toHaveValue('subproject')
  await expect(install).not.toBeChecked()
  expect(savedRequests[0]).toMatchObject({
    expected_revision: 1, server_id: 'saved-target', project_root: 'subproject',
    start: true, overwrite: true, manifest_patch: { name: 'Saved name' },
  })
  expect(savedRequests[0]).not.toHaveProperty('run_install')

  await page.getByRole('button', { name: 'Change project or source', exact: true }).click()
  const discard = page.getByRole('alertdialog', { name: 'Discard unsaved delivery input?', exact: true })
  await expect(discard).toBeVisible()
  await discard.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(discard).toHaveCount(0)
  await expect(target).toHaveCount(0)
  await expect(install).not.toBeChecked()
  expect(unexpectedWrites).toEqual([])
})

test('one policy save retains successful work and refreshes only unfinished tools for a safe retry', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  let records: ToolClassification[] = ['a', 'b', 'c', 'd'].map(id => ({
    id, server_id: `service-${id}`, tool_id: `tool-${id}`, tool_name: `Synthetic tool ${id}`,
    fingerprint: `fingerprint-${id}`, suggested_access: 'unknown', effective_access: 'unknown', status: 'pending',
    required_access: 'write', policy_source: 'default_write', registry_source: 'mcp',
    confidence: 1, source: 'rule', destructive: id === 'b', idempotent: id !== 'b', open_world: false,
    evidence: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  }))
  type PolicyWrite = { server_id: string; tool_id: string; access: string; destructive: boolean; idempotent: boolean; note: string; expected_fingerprint: string }
  const savedRequests: PolicyWrite[] = []
  const unexpectedWrites: string[] = []
  let refreshes = 0, failSecondService = true
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === '/v1/access/tool-classifications' && request.method() === 'GET') {
      refreshes += 1
      return route.fulfill({ json: { classifications: records } })
    }
    const match = path.match(/^\/v1\/access\/tool-classifications\/([^/]+)\/([^/]+)$/)
    if (match && request.method() === 'PUT') {
      const body = request.postDataJSON() as Omit<PolicyWrite, 'server_id' | 'tool_id'>
      const serverId = decodeURIComponent(match[1]), toolId = decodeURIComponent(match[2])
      savedRequests.push({ server_id: serverId, tool_id: toolId, ...body })
      const current = records.find(item => item.server_id === serverId && item.tool_id === toolId)!
      if (serverId === 'service-b' && failSecondService) {
        failSecondService = false
        records = records.map(item => item.id === 'b' ? { ...item, fingerprint: 'fingerprint-b-current' } : item)
        return route.fulfill({ status: 409, json: { detail: 'Tool definition changed; refresh the current version.' } })
      }
      if (body.expected_fingerprint !== current.fingerprint) return route.fulfill({ status: 409, json: { detail: 'Expected the current tool fingerprint.' } })
      const updated: ToolClassification = { ...current, required_access: 'read', policy_source: 'local_override', effective_access: 'read', status: 'published', source: 'manual' }
      records = records.map(item => item.id === current.id ? updated : item)
      return route.fulfill({ json: updated })
    }
    if (request.method() !== 'GET') {
      unexpectedWrites.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in synthetic classification journey' } })
    }
    return route.continue()
  })

  await page.goto('/console/#/toolClassifications')
  await page.getByRole('checkbox', { name: 'Select tools on this page', exact: true }).check()
  await page.getByRole('region', { name: 'Selected tool actions', exact: true }).getByRole('button', { name: 'Set access', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Set access for 4 tools', exact: true })).toBeVisible()
  await dialog.getByRole('radio', { name: 'Read only', exact: true }).check()
  await dialog.getByRole('textbox', { name: 'Note', exact: true }).fill('Verified read-only synthetic tools')
  await dialog.getByRole('button', { name: 'Save and apply', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Saved 3; Unfinished 1.')
  await expect(dialog.getByRole('alert')).toContainText('Tool definition changed')
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  expect(refreshes).toBe(1)
  expect(savedRequests.map(item => item.server_id).sort()).toEqual(['service-a', 'service-b', 'service-c', 'service-d'])
  // Successful rows remain updated behind the open failed-item editor.
  const checkbox = (id: string) => page.locator(`main input[aria-label="Select tool Synthetic tool ${id}"]`)
  for (const id of ['a', 'c', 'd']) {
    await expect(checkbox(id)).not.toBeChecked()
    await expect(page.locator('main tbody tr').filter({ hasText: `Synthetic tool ${id}` })).toContainText('Read only')
  }
  await expect(checkbox('b')).toBeChecked()
  await expect(dialog.getByText('service-b / tool-b', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Advanced: tool safety information', { exact: true })).toHaveCount(0)

  await dialog.getByRole('button', { name: 'Refresh unfinished tools', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Latest versions loaded.')
  await expect(dialog.getByRole('radio', { name: 'Read only', exact: true })).toBeChecked()
  await expect(dialog.getByRole('textbox', { name: 'Note', exact: true })).toHaveValue('Verified read-only synthetic tools')
  expect(refreshes).toBe(2)
  await dialog.getByRole('button', { name: 'Save and apply', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByText('Saved and active · 1 tools', { exact: true })).toBeVisible()
  for (const id of ['a', 'b', 'c', 'd']) await expect(checkbox(id)).not.toBeChecked()
  expect(savedRequests).toHaveLength(5)
  expect(savedRequests[4]).toMatchObject({ server_id: 'service-b', tool_id: 'tool-b', access: 'read',
    destructive: true, idempotent: false, note: 'Verified read-only synthetic tools', expected_fingerprint: 'fingerprint-b-current' })
  expect(savedRequests.filter(item => item.server_id !== 'service-b').every(item => item.destructive === false && item.idempotent === true)).toBe(true)
  expect(unexpectedWrites).toEqual([])
})

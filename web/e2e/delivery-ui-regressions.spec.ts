import { expect, test } from '@playwright/test'
import type { DeliveryDraft } from '../src/api/builds'
import type { ToolClassification } from '../src/api/client'
import { expectInViewportAndUnobscured, login } from './helpers'

// These routes exercise client state and keyboard interaction with synthetic
// records. They do not establish backend permission or deployment behavior.
test('saving upload build options preserves pending target and install input', async ({ page }) => {
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
  const historyTrigger = page.getByRole('button', { name: 'View upload history', exact: true })
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
  await expect(target).toHaveValue('saved-target')
  await target.fill('pending-target')
  await projectRoot.fill('subproject')
  await page.getByText('Advanced build options', { exact: true }).click()
  const install = page.getByRole('checkbox', { name: 'Install dependencies using detected settings', exact: true })
  await install.uncheck()
  await page.getByRole('button', { name: 'Save build options', exact: true }).click()
  await expect.poll(() => savedRequests.length).toBe(1)
  await expect(page.getByRole('button', { name: 'Save build options', exact: true })).toHaveCount(0)
  await expect(target).toHaveValue('pending-target')
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
  await expect(target).toHaveValue('pending-target')
  await expect(install).not.toBeChecked()
  expect(unexpectedWrites).toEqual([])
})

test('partial classification publication refreshes completed work and retains only unfinished selections', async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  let records: ToolClassification[] = ['a', 'b', 'c', 'unknown'].map(id => ({
    id, server_id: `service-${id}`, tool_id: `tool-${id}`, tool_name: `Synthetic tool ${id}`,
    fingerprint: `fingerprint-${id}`, suggested_access: id === 'unknown' ? 'unknown' : 'read',
    effective_access: id === 'unknown' ? 'unknown' : 'read', status: 'pending',
    confidence: 1, source: 'manual', destructive: false, idempotent: true, open_world: false,
    evidence: {}, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  }))
  const batches: { server_id: string; tool_ids: string[] }[] = []
  const unexpectedWrites: string[] = []
  let refreshes = 0, failSecondService = true
  await page.route('**/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === '/v1/access/tool-classifications' && request.method() === 'GET') {
      refreshes += 1
      return route.fulfill({ json: { classifications: records } })
    }
    if (path === '/v1/access/tool-classifications/publish' && request.method() === 'POST') {
      const body = request.postDataJSON() as { server_id: string; tool_ids: string[] }
      batches.push(body)
      if (body.server_id === 'service-b' && failSecondService) {
        failSecondService = false
        return route.fulfill({ status: 409, json: { detail: 'Synthetic service-b publication failure' } })
      }
      records = records.map(item => item.server_id === body.server_id && body.tool_ids.includes(item.tool_id)
        ? { ...item, status: 'published' } : item)
      return route.fulfill({ json: { classifications: records.filter(item => item.server_id === body.server_id) } })
    }
    if (request.method() !== 'GET') {
      unexpectedWrites.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation in synthetic classification journey' } })
    }
    return route.continue()
  })

  await page.goto('/console/#/toolClassifications')
  await page.getByRole('checkbox', { name: 'Select tools on this page', exact: true }).check()
  await page.getByRole('button', { name: 'Publish selected (3)', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('1 published; 3 items remain selected.')
  await expect(page.getByRole('alert')).toContainText('Latest status was refreshed.')
  expect(refreshes).toBe(2)
  expect(batches.map(batch => batch.server_id)).toEqual(['service-a', 'service-b'])
  const checkbox = (id: string) => page.getByRole('checkbox', { name: `Select tool: Synthetic tool ${id}`, exact: true })
  await expect(checkbox('a')).not.toBeChecked()
  for (const id of ['b', 'c', 'unknown']) await expect(checkbox(id)).toBeChecked()
  await expect(page.getByRole('row').filter({ has: checkbox('a') })).toContainText('Published')

  await page.getByRole('button', { name: 'Publish selected (2)', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByText('2 published; 1 item remains selected.', { exact: true })).toBeVisible()
  await expect(checkbox('unknown')).toBeChecked()
  for (const id of ['a', 'b', 'c']) await expect(checkbox(id)).not.toBeChecked()
  expect(refreshes).toBe(3)
  expect(batches.map(batch => batch.server_id)).toEqual(['service-a', 'service-b', 'service-b', 'service-c'])
  expect(unexpectedWrites).toEqual([])
})

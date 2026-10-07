import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import ts from 'typescript-ast'
import { initialize } from './helpers'

test('E2E-507 @preview-adapter synthetic adapter upload-to-start preserves draft and confirmation context', async ({ page }, testInfo) => {
  test.skip(!process.env.GATE_PREVIEW_ADAPTER_PATH, 'Opt in with the external synthetic adapter source path')
  test.setTimeout(60_000)
  const source = readFileSync(process.env.GATE_PREVIEW_ADAPTER_PATH!, 'utf8')
  const exports: Record<string, unknown> = {}
  new Function('exports', ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText)(exports)
  const create = exports.createSyntheticDeliveryPreview as () => { handle(request: Request): Promise<Response | null>; state: { manifests: Record<string, { launch?: { env?: Record<string, string> } }> } }
  const adapter = create()
  const requests: string[] = [], unhandled: string[] = []
  await initialize(page)
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), method = request.method()
    if (url.origin !== 'http://127.0.0.1:18763') { unhandled.push(request.url()); return route.abort() }
    if (!/^\/(v1|mcp|healthz|readyz)(\/|$)/.test(url.pathname)) return route.continue()
    const key = `${method} ${url.pathname}`
    requests.push(key)
    const bytes = request.postDataBuffer()
    const result = await adapter.handle(new Request(url, { method, headers: request.headers(), body: method === 'GET' || method === 'HEAD' ? undefined : bytes ? new Uint8Array(bytes).buffer : undefined }))
    if (result) {
      const headers: Record<string, string> = {}
      result.headers.forEach((value, name) => { headers[name] = value })
      return route.fulfill({ status: result.status, headers, body: Buffer.from(await result.arrayBuffer()) })
    }
    const fixtures: Record<string, unknown> = {
      'GET /v1/auth/me': { id: 'synthetic-admin', username: 'synthetic-admin', display_name: 'Synthetic admin', role: 'admin', roles: ['admin'], permissions: ['*'], status: 'active', must_change_password: false, auth_type: 'session', scopes: [] },
      'GET /v1/tools': { tools: [] },
      'GET /healthz': { status: 'synthetic', service: 'synthetic-preview', version: 'synthetic-only', checks: {} },
      'GET /v1/diagnostics': { ok: false, checks: [], summary: { synthetic: true, executed: false } },
    }
    if (key in fixtures) return route.fulfill({ json: fixtures[key] })
    unhandled.push(key)
    return route.fulfill({ status: 501, json: { detail: 'PREVIEW_NOT_IMPLEMENTED' } })
  })
  await page.goto('/console/#/uploads')
  await page.locator('input[type=file]').setInputFiles({ name: 'synthetic-adapter.zip', mimeType: 'application/zip', buffer: Buffer.from('Synthetic metadata only; adapter never unpacks bytes') })
  const uploaded = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/v1/projects/upload')
  await page.getByRole('button', { name: 'Upload & Analyze', exact: false }).first().click()
  const upload = await (await uploaded).json()
  await page.getByLabel('Target server', { exact: true }).fill('synthetic-adapter-target')
  const created = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/v1/builds')
  await page.getByRole('button', { name: 'Create Build', exact: true }).last().click()
  const build = await (await created).json()
  await expect(page).toHaveURL(new RegExp(`#/builds/${build.id}$`))
  await page.getByRole('button', { name: 'Edit · Manifest', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Delivery runtime configuration', exact: true })
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const input = editor.locator('textarea[data-manifest-json]')
  const manifest = JSON.parse(await input.inputValue())
  manifest.launch.env = { ...manifest.launch.env, PREVIEW_MARKER: 'synthetic-draft-kept' }
  await input.fill(JSON.stringify(manifest))
  await editor.getByRole('button', { name: 'Save delivery draft', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await page.getByRole('checkbox', { name: /Start after deploy/ }).check()
  const deploy = page.getByRole('button', { name: 'Deploy Build', exact: true })
  await deploy.click()
  const confirm = page.getByRole('alertdialog', { name: 'Confirm build deployment?', exact: true })
  await expect(confirm).toContainText('synthetic-adapter-target')
  await confirm.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(deploy).toBeEnabled()
  expect(requests.filter(key => key === `POST /v1/builds/${build.id}/deploy`)).toEqual([])
  await deploy.click()
  const deployed = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/v1/builds/${build.id}/deploy`)
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && new URL(response.url()).pathname === `/v1/delivery-drafts/${upload.id}` && Boolean(response.request().postDataJSON().deployment_id))
  await confirm.getByRole('button', { name: 'Confirm', exact: true }).click()
  const response = await deployed
  expect(response.status()).toBe(200)
  expect(response.request().postDataJSON()).toMatchObject({ start: true, server_id: 'synthetic-adapter-target' })
  const deployment = await response.json()
  expect(deployment).toMatchObject({ build_id: build.id, server_id: 'synthetic-adapter-target', status: 'success', runtime_started: true, manifest: { launch: { env: { PREVIEW_MARKER: '***' } } } })
  expect(adapter.state.manifests[deployment.server_id].launch?.env?.PREVIEW_MARKER).toBe('synthetic-draft-kept')
  expect(await (await saved).json()).toMatchObject({ upload_id: upload.id, build_id: build.id, deployment_id: deployment.id, server_id: deployment.server_id, start: true })
  await expect(deploy).toBeEnabled()
  const servers = page.waitForResponse(response => new URL(response.url()).pathname === '/v1/mcp/servers')
  await page.locator('.console-rail-item[href="#/servers"]').click()
  expect((await (await servers).json()).servers).toEqual(expect.arrayContaining([expect.objectContaining({ id: deployment.server_id, status: 'running', synthetic: true })]))
  expect(unhandled).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('synthetic-adapter-completed.png') })
})

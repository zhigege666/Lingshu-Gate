import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'

async function selectLocale(page: Page, locale: 'zh-CN' | 'en-US') {
  await page.getByRole('combobox', { name: /^(Language|语言)$/ }).first().click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: locale === 'zh-CN' ? '中文' : 'English' }).click()
}

test('E2E-007 @delivery real upload, build, configure, deploy and start', async ({ page }, testInfo) => {
  test.setTimeout(60_000)
  const archive = join(process.env.GATE_E2E_TEMP_ROOT!, 'synthetic-browser-delivery.zip')
  execFileSync('../.venv/bin/python', ['../scripts/e2e/make_bundle.py', archive], { timeout: 10_000 })
  await login(page)
  await page.goto('/console/#/uploads')
  await page.locator('input[type=file]').setInputFiles(archive)
  const uploaded = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/v1/projects/upload')
  const upload = page.getByRole('button', { name: 'Upload & Analyze', exact: false }).first()
  await expectInViewportAndUnobscured(upload)
  await upload.click()
  const uploadResponse = await uploaded
  expect(uploadResponse.status()).toBe(200)
  const project = await uploadResponse.json()
  await page.getByRole('combobox', { name: 'Runtime Type', exact: true }).selectOption('python')
  await page.getByLabel('Target server', { exact: true }).fill('synthetic-browser-delivery')
  await selectLocale(page, 'zh-CN')
  for (const viewport of [{ width: 1672, height: 941 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await page.evaluate(() => { document.scrollingElement?.scrollTo(0, 0); document.querySelector('main')?.scrollTo(0, 0) })
    await expect(page.getByText('准备创建构建', { exact: true })).toBeVisible()
    if (viewport.width < 768) {
      await expect(page.locator('.delivery-mobile-progress')).toContainText('3/5')
      await expect(page.locator('.delivery-mobile-progress')).toContainText('待创建')
      await expect(page.locator('.workflow-steps-stacked')).toBeHidden()
    } else {
      await expect(page.locator('.workflow-steps-stacked li').nth(2).locator('small')).toHaveText('待创建')
      await expect(page.locator('.workflow-steps-stacked li').nth(3).locator('small')).toHaveText('待部署')
      await expect(page.locator('.workflow-steps-stacked li').nth(4).locator('small')).toHaveText('待启动')
      expect(await page.locator('.workflow-steps-stacked li').evaluateAll(items => items.every(item => {
        const icon = item.querySelector('.workflow-step-symbol')!.getBoundingClientRect()
        const name = item.querySelector('strong')!.getBoundingClientRect()
        const state = item.querySelector('small')!.getBoundingClientRect()
        return name.top >= icon.bottom && state.top >= name.bottom
      }))).toBe(true)
    }
    expect(await page.locator('.delivery-focus-content > .min-w-0').first().evaluate(element => {
      const form = element.getBoundingClientRect(), parent = element.parentElement!.getBoundingClientRect()
      return form.width <= 921 && Math.abs((form.left + form.right) - (parent.left + parent.right)) <= 3
    })).toBe(true)
    await expectInViewportAndUnobscured(page.getByRole('button', { name: '创建构建', exact: true }).last())
    await expectInViewportAndUnobscured(page.getByRole('button', { name: '上一步', exact: true }))
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollHeight - innerHeight)).toBeLessThanOrEqual(1)
    await page.screenshot({ path: testInfo.outputPath(`real-upload-analysis-${viewport.width}x${viewport.height}.png`), animations: 'disabled' })
    if (viewport.width === 390) {
      const advanced = page.locator('details').filter({ has: page.locator('summary', { hasText: '高级构建选项' }) })
      await advanced.locator('summary').click()
      const lastField = advanced.getByRole('checkbox')
      await lastField.scrollIntoViewIfNeeded()
      await expectInViewportAndUnobscured(lastField)
      await expectInViewportAndUnobscured(page.getByRole('button', { name: '创建构建', exact: true }).last())
      await expectInViewportAndUnobscured(page.getByRole('button', { name: '上一步', exact: true }))
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
      await page.screenshot({ path: testInfo.outputPath('real-upload-advanced-bottom-390x844.png'), animations: 'disabled' })
      await advanced.locator('summary').click()
    }
  }
  await page.setViewportSize({ width: 1280, height: 720 })
  await selectLocale(page, 'en-US')
  const planned = await page.request.post('/v1/builds/plan', { data: { upload_id: project.id, run_install: false, run_build: true } })
  expect(planned.status()).toBe(200)
  expect((await planned.json()).plan.steps).toEqual([])
  await page.getByText('Advanced build options', { exact: true }).click()
  await page.getByRole('checkbox', { name: 'Install dependencies using detected settings', exact: true }).uncheck()
  const created = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/v1/builds')
  await page.getByRole('button', { name: 'Create Build', exact: true }).last().click()
  const build = await (await created).json()
  expect(build.id).toBeTruthy()
  await expect.poll(async () => { const draft = await (await page.request.get(`/v1/delivery-drafts/${project.id}`)).json(); return { runtime: draft.runtime_override, target: draft.server_id, build: draft.build_id } }).toEqual({ runtime: 'python', target: 'synthetic-browser-delivery', build: build.id })
  await expect.poll(async () => (await (await page.request.get(`/v1/builds/${build.id}`)).json()).status, { timeout: 20_000 }).toBe('success')
  await expect(page).toHaveURL(new RegExp(`#/builds/${build.id}`))
  // A hash can update before the leave guard accepts it. Assert the mounted
  // workspace actually changed, instead of reloading past a blocked transition.
  await expect(page.locator('.delivery-focus-workspace')).toHaveCount(0)
  await expect(page.getByRole('alertdialog', { name: 'Submission in progress', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit · Manifest', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Edit · Manifest', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Delivery runtime configuration', exact: true })
  await editor.getByRole('button', { name: 'JSON', exact: true }).click()
  const config = editor.locator('textarea[data-manifest-json]')
  const manifest = JSON.parse(await config.inputValue())
  manifest.launch.env = { ...(manifest.launch.env || {}), DELIVERY_MARKER: 'synthetic-browser-v1' }
  manifest.transport.protocol_version = '2026-07-28'
  manifest.restart_policy = { enabled: false }
  manifest.timeout_seconds = 3
  await config.fill(JSON.stringify(manifest, null, 2))
  await editor.getByRole('button', { name: 'Save delivery draft', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await page.getByText('Advanced settings (runtime, root, server ID)', { exact: true }).click()
  const target = page.getByLabel('Optional: override server_id on deploy', { exact: true })
  const savedTarget = await target.inputValue()
  const unsavedWrites: string[] = []
  const recordWrite = (request: import('@playwright/test').Request) => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) unsavedWrites.push(request.url()) }
  page.on('request', recordWrite)
  await target.fill('synthetic-unsaved-target')
  await page.locator('.console-rail-item[href="#/tools"]').click()
  const leave = page.getByRole('alertdialog', { name: 'Discard changes and leave?', exact: true })
  await expect(leave).toBeVisible()
  await leave.getByRole('button', { name: 'Keep editing', exact: true }).click()
  await expect(target).toHaveValue('synthetic-unsaved-target')
  await expect(page).toHaveURL(new RegExp(`#/builds/${build.id}`))
  expect(unsavedWrites).toEqual([])
  page.off('request', recordWrite)
  await target.fill(savedTarget)
  await page.getByText('Advanced settings (runtime, root, server ID)', { exact: true }).click()
  await page.getByRole('checkbox', { name: /Start after deploy/ }).check()
  const deploy = page.getByRole('button', { name: 'Deploy Build', exact: true })
  await expectInViewportAndUnobscured(deploy)
  await deploy.click()
  const confirmation = page.getByRole('alertdialog', { name: 'Confirm build deployment?', exact: true })
  await expect(confirmation).toContainText(manifest.id)
  await expectInViewportAndUnobscured(confirmation.getByRole('button', { name: 'Confirm', exact: true }))
  expect(await confirmation.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
  const deployed = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === `/v1/builds/${build.id}/deploy`)
  const savedDeploymentDraft = page.waitForResponse(response => response.request().method() === 'PUT' && new URL(response.url()).pathname === `/v1/delivery-drafts/${project.id}` && Boolean(response.request().postDataJSON()?.deployment_id))
  await confirmation.getByRole('button', { name: 'Confirm', exact: true }).click()
  const result = await deployed
  expect(result.status()).toBe(200)
  const deployment = await result.json()
  expect(deployment.status).toBe('success')
  expect(deployment.server_id).toBe('synthetic-browser-delivery')
  expect(deployment.runtime_started).toBe(true)
  const runtime = await (await page.request.get(`/v1/mcp/servers/${deployment.server_id}`)).json()
  expect(runtime).toMatchObject({ status: 'running', tool_count: 1 })
  const invocation = await page.request.post(`/v1/tools/mcp.${deployment.server_id}.snapshot/invoke`, { data: { arguments: {} } })
  expect(invocation.status()).toBe(200)
  const output = await invocation.json()
  expect(output.ok).toBe(true)
  expect(JSON.parse(output.output.content[0].text).marker).toBe('synthetic-browser-v1')
  const draft = await (await page.request.get(`/v1/delivery-drafts/${project.id}`)).json()
  expect(draft).toMatchObject({ runtime_override: 'python', upload_id: project.id, build_id: build.id, deployment_id: deployment.id, server_id: deployment.server_id })
  expect((await savedDeploymentDraft).status()).toBe(200)
  await expect(confirmation).toHaveCount(0)
  await expect(deploy).toBeEnabled()
  await page.goto(`/console/#/servers/${deployment.server_id}`)
  await expect(page.getByRole('alertdialog', { name: 'Discard changes and leave?', exact: true })).toHaveCount(0)
  await selectLocale(page, 'zh-CN')
  await page.getByRole('tab', { name: '配置', exact: true }).click()
  await page.getByRole('button', { name: '修改配置', exact: true }).click()
  const serviceEditor = page.getByRole('dialog', { name: `修改配置 · ${deployment.server_id}`, exact: true })
  await serviceEditor.getByLabel('名称', { exact: true }).fill('合成项目配置未保存草稿')
  await expect(serviceEditor.getByRole('radio', { name: '仅保存（未生效）', exact: true })).toBeChecked()
  await serviceEditor.getByRole('radio', { name: '保存并应用启动', exact: true }).check()
  await serviceEditor.getByText('崩溃重启策略', { exact: true }).click()
  for (const viewport of [{ width: 1672, height: 941 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const expectedWidth = Math.min(1200, viewport.width - (viewport.width <= 600 ? 32 : 96))
    // The centered dialog keeps a single scrolling editor body and fixed actions.
    await expect.poll(() => serviceEditor.evaluate(element => ({ width: Math.round(element.getBoundingClientRect().width), left: Math.round(element.getBoundingClientRect().left) }))).toEqual({ width: expectedWidth, left: Math.round((viewport.width - expectedWidth) / 2) })
    await expect.poll(async () => (await serviceEditor.boundingBox())!.height).toBeLessThanOrEqual(viewport.height - (viewport.width <= 600 ? 32 : 64))
    await serviceEditor.locator('.manifest-editor-body').evaluate(element => { element.scrollTop = element.scrollHeight })
    await expectInViewportAndUnobscured(serviceEditor.getByLabel('失败阈值', { exact: true }))
    await expectInViewportAndUnobscured(serviceEditor.getByRole('button', { name: '保存配置', exact: true }))
    await expect(serviceEditor.getByRole('radio', { name: '保存并应用启动', exact: true })).toBeChecked()
    await page.screenshot({ path: testInfo.outputPath(`real-service-config-bottom-${viewport.width}x${viewport.height}.png`), animations: 'disabled' })
  }
})

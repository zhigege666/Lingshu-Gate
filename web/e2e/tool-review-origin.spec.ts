import { test, expect, type Page } from '@playwright/test'
import { login, expectInViewportAndUnobscured } from './helpers'
import { classifications, tools } from './synthetic-data'

const groups = ['builtin', 'gate-control', 'gate-delivery', 'gate-tool-files']
const definitions = groups.map((serverId, i) => ({
  ...tools[i], id: `synthetic-review-builtin-${i}`, name: `Synthetic review tool ${i}`,
  source: 'builtin', metadata: { ...tools[i].metadata, server_id: serverId },
}))
const downstream = {
  ...tools[4], id: 'gate_synthetic_review_downstream', name: definitions[0].name,
  metadata: { ...tools[4].metadata, server_id: 'gate-synthetic-third-party' },
}

type ReviewRow = typeof classifications[number] & { registry_source?: string | null }

function reviewRecord(tool: typeof tools[number], i: number): ReviewRow {
  return {
    ...classifications[i], id: `synthetic-review-classification-${i}`,
    server_id: tool.metadata.server_id, tool_id: tool.id, tool_name: tool.name,
    registry_source: tool.source, source: ['rule', 'annotation', 'manual'][i % 3],
    status: 'pending', suggested_access: 'read', effective_access: 'unknown',
    required_access: tool.source === 'builtin' ? 'read' : 'write',
    policy_source: tool.source === 'builtin' ? 'builtin_contract' : 'default_write',
  }
}
const rows = [...definitions, downstream].map(reviewRecord)

async function mockReview(page: Page, records: ReviewRow[]) {
  let writes = 0
  await page.route('**/v1/**', route => {
    if (route.request().method() !== 'GET') {
      writes++
      return route.fulfill({ status: 500, json: { detail: 'Unexpected tool-review origin mutation' } })
    }
    if (new URL(route.request().url()).pathname === '/v1/access/tool-classifications') {
      return route.fulfill({ json: { classifications: records } })
    }
    return route.fallback()
  })
  return () => writes
}

function labels(locale: 'en-US' | 'zh-CN') {
  const zh = locale === 'zh-CN'
  return {
    names: zh ? ['Gate 基础能力', '工具权限管理', '项目交付与服务管理', '工具文件传输']
      : ['Gate core capabilities', 'Tool access management', 'Project delivery and service management', 'Tool file transfer'],
    edit: zh ? '设置权限' : 'Set access',
    builtinPolicy: zh ? '内置策略' : 'Built-in policy', automatic: zh ? '自动默认' : 'Automatic',
    serviceFilter: zh ? '筛选服务' : 'Filter service',
    search: zh ? '搜索工具或服务' : 'Search tools or services',
    note: zh ? '备注' : 'Note', discard: zh ? '放弃尚未保存的修改？' : 'Discard unsaved changes?',
    keep: zh ? '继续编辑' : 'Continue editing',
  }
}

for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) {
  for (const locale of ['en-US', 'zh-CN'] as const) {
    for (const theme of ['light', 'dark'] as const) {
      test(`tool access preserves trusted Registry origins ${locale} ${theme} ${width}x${height}`, async ({ page }, testInfo) => {
        await login(page)
        await page.addInitScript(({ locale, theme }) => {
          localStorage.setItem('lingshu-gate-console-locale', locale)
          localStorage.setItem('lingshu-gate-console-theme', theme)
        }, { locale, theme })
        await page.setViewportSize({ width, height })
        const writes = await mockReview(page, rows)
        const c = labels(locale)
        await page.goto('/console/#/toolClassifications')
        if (theme === 'dark') await expect(page.locator('html')).toHaveClass(/dark/)
        else await expect(page.locator('html')).not.toHaveClass(/dark/)
        const main = page.locator('main')
        for (let i = 0; i < definitions.length; i++) {
          const row = main.getByRole('row').filter({ hasText: definitions[i].id })
          await expect(row.getByText(c.names[i], { exact: true })).toBeVisible()
          await expect(row.getByText(groups[i], { exact: true })).toBeVisible()
          await expect(row.getByText(definitions[i].id, { exact: true })).toHaveAttribute('title', definitions[i].id)
          await expect(row.getByText(c.builtinPolicy, { exact: true })).toBeVisible()
        }
        const thirdParty = main.getByRole('row').filter({ hasText: downstream.id })
        await expect(thirdParty.getByText('gate-synthetic-third-party', { exact: true })).toBeVisible()
        await expect(thirdParty.getByText(c.automatic, { exact: true })).toBeVisible()
        for (const name of c.names) await expect(thirdParty.getByText(name, { exact: true })).toHaveCount(0)
        await page.screenshot({ path: testInfo.outputPath('review-origin-list.png'), animations: 'disabled' })

        const action = main.getByRole('row').filter({ hasText: definitions[1].id }).getByRole('button', { name: `${c.edit} · ${definitions[1].name}`, exact: true })
        await expectInViewportAndUnobscured(action)
        await action.click()
        const dialog = page.getByRole('dialog')
        await expect(dialog).toHaveCSS('opacity', '1')
        await expect(dialog.getByText(c.names[1], { exact: true })).toBeVisible()
        await expect(dialog.getByText(`gate-control / ${definitions[1].id}`, { exact: true })).toBeVisible()
        await page.screenshot({ path: testInfo.outputPath('review-origin-detail.png'), animations: 'disabled' })
        await page.keyboard.press('Escape')
        await expect(dialog).toHaveCount(0)
        await expect(action).toBeFocused()

        await main.getByRole('combobox', { name: c.serviceFilter, exact: true }).click()
        for (const group of groups) await expect(page.getByRole('option', { name: group, exact: true })).toBeVisible()
        await page.screenshot({ path: testInfo.outputPath('review-origin-filter.png'), animations: 'disabled' })
        await page.getByRole('option', { name: 'gate-delivery', exact: true }).click()
        await expect(main.locator('tbody tr')).toHaveCount(1)
        await expect(main.getByRole('row').filter({ hasText: definitions[2].id })).toBeVisible()
        expect(writes()).toBe(0)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
      })
    }
  }
}

for (const locale of ['en-US', 'zh-CN'] as const) {
  test(`tool access rejects spoofed origins and protects unsaved policy input ${locale}`, async ({ page }, testInfo) => {
    await login(page)
    await page.addInitScript(locale => {
      localStorage.setItem('lingshu-gate-console-locale', locale)
      localStorage.setItem('lingshu-gate-console-theme', locale === 'zh-CN' ? 'dark' : 'light')
    }, locale)
    await page.setViewportSize({ width: 1600, height: 900 })
    const spoof = { ...rows[4], server_id: 'gate-control' }
    const missing = { ...rows[4], id: 'synthetic-missing', tool_id: 'gate_synthetic_missing', server_id: 'builtin', registry_source: undefined, source: 'builtin' }
    const mixed = { ...rows[4], id: 'synthetic-mixed', tool_id: 'gate_synthetic_mixed', server_id: 'gate-tool-files', registry_source: null, source: 'manual' }
    const writes = await mockReview(page, [...rows.slice(0, 4), spoof, missing, mixed])
    const c = labels(locale)
    await page.goto('/console/#/toolClassifications')
    const main = page.locator('main')
    for (const item of [spoof, missing, mixed]) {
      const row = main.getByRole('row').filter({ hasText: item.tool_id })
      await expect(row.getByText(item.server_id, { exact: true })).toBeVisible()
      for (const name of c.names) await expect(row.getByText(name, { exact: true })).toHaveCount(0)
      const action = row.getByRole('button', { name: `${c.edit} · ${item.tool_name}`, exact: true })
      await action.click()
      const dialog = page.getByRole('dialog')
      for (const name of c.names) await expect(dialog.getByText(name, { exact: true })).toHaveCount(0)
      await expect(dialog.getByText(item.server_id, { exact: true })).toBeVisible()
      await expect(dialog.getByText(`${item.server_id} / ${item.tool_id}`, { exact: true })).toBeVisible()
      if (item === spoof) {
        const note = dialog.getByRole('textbox', { name: c.note, exact: true })
        await note.fill('Unsaved policy reason')
        await page.keyboard.press('Escape')
        const discard = page.getByRole('alertdialog', { name: c.discard, exact: true })
        await expect(discard).toBeVisible()
        await discard.getByRole('button', { name: c.keep, exact: true }).click()
        await expect(discard).toHaveCount(0)
        await expect(note).toHaveValue('Unsaved policy reason')
        await note.fill('')
      }
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(action).toBeFocused()
    }
    await page.screenshot({ path: testInfo.outputPath('review-untrusted-origins.png'), animations: 'disabled' })
    await main.getByRole('combobox', { name: c.serviceFilter, exact: true }).click()
    for (const serverId of groups) {
      const option = page.getByRole('option', { name: serverId, exact: true })
      await expect(option).toBeVisible()
      for (const name of c.names) await expect(option.getByText(name, { exact: true })).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath('review-untrusted-filter.png'), animations: 'disabled' })
    await page.keyboard.press('Escape')
    // The same localized group name shown in the list is searchable over all loaded records.
    await main.getByPlaceholder(c.search, { exact: true }).fill(c.names[1])
    await expect(main.locator('tbody tr')).toHaveCount(1)
    await expect(main.getByRole('row').filter({ hasText: definitions[1].id })).toBeVisible()
    expect(writes()).toBe(0)
  })
}

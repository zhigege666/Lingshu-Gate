import { expect, test, type Page, type Route } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { listFixtures, servers } from './synthetic-data'

const alpha = 'a'.repeat(32), beta = 'b'.repeat(32)
const instances = Array.from({ length: 1000 }, (_, i) => ({ instance_id: `instance-${String(i).padStart(4, '0')}`, name: `Instance ${String(i).padStart(4, '0')}`, status: 'not_loaded', available: true, contract_revision: (i < 20 ? 'a' : 'b').repeat(64), groups: [{ id: alpha, name: 'Synthetic alpha', status: 'active' }] }))
const stamp = '2026-10-04T00:00:00Z'
const record = (id: string, name: string, members = instances.map(item => item.instance_id)) => ({ id, name, description: 'Synthetic metadata-only collection', status: 'active', revision: 1, created_at: stamp, updated_at: stamp, default_instance_id: null as string | null, members: members.map(instance_id => ({ instance_id, status: 'active', available: true })) })

async function fixture(page: Page, locale = 'en-US', theme = 'dark') {
  await login(page)
  await page.addInitScript(({ locale, theme }) => { localStorage.setItem('lingshu-gate-console-locale', locale); localStorage.setItem('lingshu-gate-console-theme', theme) }, { locale, theme })
  const records = new Map([[alpha, record(alpha, 'Synthetic alpha')], [beta, record(beta, 'Synthetic beta', ['instance-0999'])]])
  const writes: { method: string; path: string; body: Record<string, unknown> }[] = []
  const requests: string[] = []
  const instanceQueries: URLSearchParams[] = []
  const receipts = new Map<string, { body: string; id: string }>()
  let failure = false, loseResponse = false, delay: ((route: Route) => Promise<boolean>) | undefined
  await page.route('**/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname
    requests.push(`${req.method()} ${path}`)
    if (path.startsWith('/v1/mcp/groups')) {
      if (delay && await delay(route)) return
      if (path.endsWith('/csrf')) return route.fulfill({ json: { csrf: 'synthetic-request-ticket', expires_at: 9999999999 } })
      if (req.method() !== 'GET') {
        const body = req.postDataJSON(); writes.push({ method: req.method(), path, body })
        if (failure) return route.fulfill({ status: 409, json: { detail: { code: 'group_revision_conflict', message: 'Synthetic concurrent revision' } } })
        if (req.method() === 'POST' && receipts.has(body.request_key)) {
          const receipt = receipts.get(body.request_key)!
          if (receipt.body !== JSON.stringify(body)) return route.fulfill({ status: 409, json: { detail: { code: 'group_request_conflict' } } })
          return route.fulfill({ json: records.get(receipt.id) })
        }
        const id = req.method() === 'POST' ? 'c'.repeat(32) : path.split('/').at(-1)!
        if (req.method() === 'DELETE') { records.delete(id); return route.fulfill({ json: { id, deleted: true, metadata_only: true } }) }
        const next = { ...record(id, body.name, body.members), description: body.description, status: body.status, default_instance_id: body.default_instance_id ?? null, revision: (records.get(id)?.revision ?? 0) + 1 }
        records.set(id, next)
        if (req.method() === 'POST') receipts.set(body.request_key, { body: JSON.stringify(body), id })
        if (loseResponse) { loseResponse = false; return route.abort('failed') }
        return route.fulfill({ json: next })
      }
      if (path.includes('/requests/')) {
        const receipt = receipts.get(path.split('/').at(-1)!)
        return route.fulfill({ status: receipt ? 200 : 404, json: receipt ? records.get(receipt.id) : { detail: { code: 'group_request_not_found' } } })
      }
      const q = (url.searchParams.get('q') || '').toLowerCase(), offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 20)
      if (path.endsWith('/instances')) {
        instanceQueries.push(url.searchParams)
        const group = records.get(url.searchParams.get('group_id') || '')
        const all = instances.filter(item => (!group || group.members.some(member => member.instance_id === item.instance_id)) && `${item.name} ${item.instance_id}`.toLowerCase().includes(q))
        return route.fulfill({ json: { instances: all.slice(offset, offset + limit), total: all.length, offset, limit } })
      }
      if (path === '/v1/mcp/groups') {
        const status = url.searchParams.get('status') || 'active'
        const all = Array.from(records.values()).filter(item => (status === 'all' || item.status === status) && `${item.name} ${item.id}`.toLowerCase().includes(q))
          .map(({ members, ...item }) => ({ ...item, member_count: members.length, missing_count: 0 }))
        return route.fulfill({ json: { groups: all.slice(offset, offset + limit), total: all.length, offset, limit } })
      }
      const found = records.get(path.split('/').at(-1)!)
      return route.fulfill({ status: found ? 200 : 404, json: found ?? { detail: { code: 'group_not_found' } } })
    }
    if (req.method() !== 'GET') return route.fulfill({ status: 500, json: { detail: 'Unexpected non-group mutation' } })
    if (path === '/v1/mcp/servers') return route.fulfill({ json: { servers, load_errors: [] } })
    if (path in listFixtures) return route.fulfill({ json: listFixtures[path] })
    return route.continue()
  })
  await page.goto('/console/#/servers')
  await page.locator('.mcp-group-view-switch').getByText(locale === 'zh-CN' ? '组' : 'Groups', { exact: true }).click()
  await expect(page.locator('.service-entry').filter({ hasText: 'Synthetic alpha' })).toBeVisible()
  return { records, writes, requests, instanceQueries, setFailure: (value: boolean) => { failure = value }, setLoseResponse: () => { loseResponse = true }, setDelay: (value: typeof delay) => { delay = value } }
}

for (const [width, height] of [[1600, 900], [1920, 1080], [2560, 1080], [2560, 1440]]) for (const locale of ['en-US', 'zh-CN']) for (const theme of ['light', 'dark']) {
  test(`group layout/editor ${locale} ${theme} ${width}x${height}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height })
    const gate = await fixture(page, locale, theme)
    await page.locator('.service-entry').filter({ hasText: 'Synthetic alpha' }).click()
    const edit = page.getByRole('button', { name: locale === 'zh-CN' ? '编辑组' : 'Edit group', exact: true })
    await expectInViewportAndUnobscured(edit)
    const output = process.env.GATE_GROUP_EVIDENCE_DIR || info.outputPath('evidence'); mkdirSync(output, { recursive: true })
    await page.screenshot({ path: join(output, `groups-${locale}-${theme}-${width}x${height}.png`) })
    await edit.click()
    const dialog = page.getByRole('dialog'), save = dialog.getByRole('button', { name: locale === 'zh-CN' ? '保存组' : 'Save group', exact: true })
    await expectInViewportAndUnobscured(save)
    await expect(dialog.getByLabel(locale === 'zh-CN' ? '名称' : 'Name', { exact: true })).toBeFocused()
    await expect.poll(() => dialog.evaluate(element => {
      const r = element.getBoundingClientRect(); return r.width <= 1201 && r.height <= innerHeight - 63 && Math.abs(r.x + r.width / 2 - innerWidth / 2) < 3 && Math.abs(r.y + r.height / 2 - innerHeight / 2) < 3
    })).toBe(true)
    await expect.poll(() => dialog.evaluate(element => {
      const label = element.querySelector('label')!.getBoundingClientRect(), field = element.querySelector('input[id]')!.getBoundingClientRect()
      return label.right <= field.left && Math.abs(label.top + label.height / 2 - field.top - field.height / 2) < 4
    })).toBe(true)
    await expect(dialog.getByRole('status')).toContainText('1000')
    await page.screenshot({ path: join(output, `group-editor-${locale}-${theme}-${width}x${height}.png`) })
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(edit).toBeFocused()
    expect(gate.writes).toHaveLength(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

for (const locale of ['en-US', 'zh-CN']) test(`explicit default radio and incompatible versions ${locale}`, async ({ page }) => {
  const gate = await fixture(page, locale)
  const zh = locale === 'zh-CN'
  await page.getByRole('button', { name: zh ? '创建组' : 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(zh ? '名称' : 'Name', { exact: true }).fill('Synthetic contract group')
  const default0 = dialog.getByRole('radio', { name: `${zh ? '默认实例' : 'Default instance'} · instance-0000`, exact: true })
  await expect(default0).toBeDisabled()
  await dialog.getByRole('checkbox', { name: 'Instance 0000 · instance-0000', exact: true }).check()
  await dialog.getByRole('checkbox', { name: 'Instance 0001 · instance-0001', exact: true }).check()
  await default0.check()
  const default1 = dialog.getByRole('radio', { name: `${zh ? '默认实例' : 'Default instance'} · instance-0001`, exact: true })
  await default1.check()
  await expect(default0).not.toBeChecked()
  await dialog.getByRole('checkbox', { name: 'Instance 0001 · instance-0001', exact: true }).uncheck()
  await expect(dialog.getByRole('group', { name: zh ? '默认实例' : 'Default instance', exact: true })).toContainText(zh ? '未选择' : 'None selected')
  await default0.check()
  await dialog.getByRole('searchbox', { name: zh ? '按名称或 ID 搜索实例' : 'Search instances by name or ID' }).fill('0020')
  await dialog.getByRole('checkbox', { name: 'Instance 0020 · instance-0020', exact: true }).check()
  await expect(dialog.getByText(zh ? '已选择不同合同版本。合同不兼容的工具保持独立分区，不能混用参数。' : 'Different contract versions are selected. Tools with incompatible contracts stay in separate partitions; arguments cannot be shared between them.', { exact: true })).toBeVisible()
  await expect(dialog.getByText('bbbbbbbbbbbb', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: zh ? '保存组' : 'Save group', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes.at(-1)!.body).toMatchObject({ members: ['instance-0000', 'instance-0020'], default_instance_id: 'instance-0000' })
})

test('cross-page selection and complete search survive save failure/retry', async ({ page }) => {
  const gate = await fixture(page)
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Synthetic selected group')
  await dialog.getByRole('checkbox', { name: 'Instance 0000 · instance-0000', exact: true }).check()
  await dialog.locator('.ant-pagination-next').click()
  await dialog.getByRole('checkbox', { name: 'Instance 0020 · instance-0020', exact: true }).check()
  await dialog.getByRole('searchbox', { name: 'Search instances by name or ID' }).fill('0999')
  await dialog.getByRole('checkbox', { name: 'Instance 0999 · instance-0999', exact: true }).check()
  await expect(dialog.getByRole('status')).toContainText('3 selected')
  gate.setFailure(true)
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog.getByRole('alert').filter({ hasText: 'Your draft is intact' })).toBeVisible()
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Synthetic selected group')
  gate.setFailure(false)
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes.map(item => item.body.members)).toEqual([['instance-0000', 'instance-0020', 'instance-0999'], ['instance-0000', 'instance-0020', 'instance-0999']])
  expect(gate.writes.every(item => !('endpoint' in item.body) && !('scopes' in item.body))).toBe(true)
  expect(gate.writes[0].body.request_key).toMatch(/^[a-f0-9]{32}$/)
  expect(gate.writes[1].body.request_key).toBe(gate.writes[0].body.request_key)
})

test('lost create response retries the same bound request instead of another group', async ({ page }, info) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const gate = await fixture(page)
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Synthetic lost creation')
  gate.setLoseResponse()
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Check saved result', exact: true })).toBeVisible()
  await expect(dialog.getByRole('alert')).toContainText('creation result is unconfirmed')
  for (const name of ['Check saved result', 'Retry original creation', 'Save group']) await expectInViewportAndUnobscured(dialog.getByRole('button', { name, exact: true }))
  const output = process.env.GATE_GROUP_EVIDENCE_DIR || info.outputPath('evidence'); mkdirSync(output, { recursive: true })
  await page.screenshot({ path: join(output, 'create-recovery-en-US-dark-1600x900.png') })
  expect(Array.from(gate.records.values()).filter(item => item.name === 'Synthetic lost creation')).toHaveLength(1)
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes).toHaveLength(2)
  expect(gate.writes[0].body).toEqual(gate.writes[1].body)
  expect(Array.from(gate.records.values()).filter(item => item.name === 'Synthetic lost creation')).toHaveLength(1)
})

test('changed unconfirmed creation reconciles the saved group while keeping new edits', async ({ page }, info) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const gate = await fixture(page, 'zh-CN', 'light')
  await page.getByRole('button', { name: '创建组', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('名称', { exact: true }).fill('首次提交')
  gate.setLoseResponse()
  await dialog.getByRole('button', { name: '保存组', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '核对保存结果', exact: true })).toBeVisible()
  await dialog.getByLabel('名称', { exact: true }).fill('保留新的修改')
  await dialog.getByRole('button', { name: '保存组', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('草稿已修改')
  for (const name of ['核对保存结果', '重试原创建', '保存组']) await expectInViewportAndUnobscured(dialog.getByRole('button', { name, exact: true }))
  const output = process.env.GATE_GROUP_EVIDENCE_DIR || info.outputPath('evidence'); mkdirSync(output, { recursive: true })
  await page.screenshot({ path: join(output, 'create-recovery-zh-CN-light-1600x900.png') })
  expect(gate.writes).toHaveLength(1)
  await dialog.getByRole('button', { name: '核对保存结果', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '重新读取已保存组', exact: true })).toBeVisible()
  await expect(dialog.getByLabel('名称', { exact: true })).toHaveValue('保留新的修改')
  await dialog.getByRole('button', { name: '保存组', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes.map(item => item.method)).toEqual(['POST', 'PUT'])
  expect(gate.writes[1].body.expected_revision).toBe(1)
  expect(gate.writes[1].body).not.toHaveProperty('request_key')
  expect(Array.from(gate.records.values()).filter(item => item.name === '保留新的修改')).toHaveLength(1)
})

for (const locale of ['en-US', 'zh-CN']) {
  test(`reload keeps only the unresolved key and reconciles by read only ${locale}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1600, height: 900 })
    const gate = await fixture(page, locale, locale === 'zh-CN' ? 'light' : 'dark')
    const chinese = locale === 'zh-CN', create = chinese ? '创建组' : 'Create group', check = chinese ? '核对保存结果' : 'Check saved result'
    await page.getByRole('button', { name: create, exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel(chinese ? '名称' : 'Name', { exact: true }).fill('Synthetic saved before reload')
    gate.setLoseResponse()
    await dialog.getByRole('button', { name: chinese ? '保存组' : 'Save group', exact: true }).click()
    await expect(dialog.getByRole('button', { name: check, exact: true })).toBeVisible()
    await dialog.getByLabel(chinese ? '名称' : 'Name', { exact: true }).fill('Synthetic unsaved edits must not persist')
    const entries = await page.evaluate(() => Object.entries(sessionStorage).filter(([key]) => key.startsWith('gate-mcp-group-create-pending:')))
    const actor = await (await page.request.get('/v1/auth/me')).json()
    expect(entries).toEqual([[`gate-mcp-group-create-pending:${JSON.stringify([new URL(page.url()).origin, actor.id])}`, gate.writes[0].body.request_key]])
    await page.reload()
    await page.locator('.mcp-group-view-switch').getByText(chinese ? '组' : 'Groups', { exact: true }).click()
    await expect(page.locator('.mcp-group-recovery')).toContainText(chinese ? '无法恢复未保存的编辑内容' : 'Unsaved edits cannot be restored')
    await expect(page.getByRole('button', { name: create, exact: true })).toBeDisabled()
    expect(gate.requests.filter(item => item.includes('/requests/'))).toHaveLength(0)
    expect(gate.writes).toHaveLength(1)
    const output = process.env.GATE_GROUP_EVIDENCE_DIR || info.outputPath('evidence'); mkdirSync(output, { recursive: true })
    await page.screenshot({ path: join(output, `create-reload-${locale}-1600x900.png`) })
    await page.getByRole('button', { name: check, exact: true }).click()
    await expect(page.locator('.mcp-group-recovery')).toHaveCount(0)
    await expect(page.locator('.mcp-group-detail h1')).toHaveText('Synthetic saved before reload')
    await expect(page.getByRole('button', { name: create, exact: true })).toBeEnabled()
    expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('gate-mcp-group-create-pending:')))).toEqual([])
    expect(gate.writes).toHaveLength(1)
    expect(gate.requests.filter(item => item.includes('/requests/'))).toEqual([`GET /v1/mcp/groups/requests/${gate.writes[0].body.request_key}`])
  })

  test(`receipt capacity rejection is definite and preserves the creation draft ${locale}`, async ({ page }) => {
    const gate = await fixture(page, locale), chinese = locale === 'zh-CN'
    let rejectedKey: string | undefined
    gate.setDelay(async route => {
      if (route.request().method() !== 'POST' || new URL(route.request().url()).pathname !== '/v1/mcp/groups') return false
      rejectedKey = route.request().postDataJSON().request_key
      await route.fulfill({ status: 429, json: { detail: { code: 'group_request_capacity' } } })
      gate.setDelay(undefined); return true
    })
    await page.getByRole('button', { name: chinese ? '创建组' : 'Create group', exact: true }).click()
    const dialog = page.getByRole('dialog'), name = dialog.getByLabel(chinese ? '名称' : 'Name', { exact: true })
    await name.fill('Synthetic draft at capacity')
    await dialog.getByRole('button', { name: chinese ? '保存组' : 'Save group', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText(chinese ? '本次请求未新建组' : 'This request did not create a new group')
    await expect(name).toHaveValue('Synthetic draft at capacity')
    await expect(dialog.getByRole('button', { name: chinese ? '核对保存结果' : 'Check saved result', exact: true })).toHaveCount(0)
    expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('gate-mcp-group-create-pending:')))).toEqual([])
    await name.fill('Synthetic corrected draft')
    await dialog.getByRole('button', { name: chinese ? '保存组' : 'Save group', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    expect(gate.writes).toHaveLength(1)
    expect(gate.writes[0].body.request_key).not.toBe(rejectedKey)
    expect(gate.writes[0].body.name).toBe('Synthetic corrected draft')
  })
}

test('reload GET 404 keeps the key until confirmed abandonment and never creates', async ({ page }) => {
  const gate = await fixture(page), actor = await (await page.request.get('/v1/auth/me')).json(), key = 'e'.repeat(32)
  await page.evaluate(({ actorId, key }) => sessionStorage.setItem(`gate-mcp-group-create-pending:${JSON.stringify([location.origin, actorId])}`, key), { actorId: actor.id, key })
  await page.reload()
  await page.locator('.mcp-group-view-switch').getByText('Groups', { exact: true }).click()
  await page.getByRole('button', { name: 'Check saved result', exact: true }).click()
  await expect(page.locator('.mcp-group-recovery').getByRole('alert')).toContainText('does not prove the earlier request failed')
  await expect(page.getByRole('button', { name: 'Create group', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => Object.values(sessionStorage).includes('e'.repeat(32)))).toBe(true)
  expect(gate.writes).toHaveLength(0)
  await page.getByRole('button', { name: 'Abandon recovery record', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('may already have been saved and will not be deleted')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.locator('.mcp-group-recovery')).toBeVisible()
  await page.getByRole('button', { name: 'Abandon recovery record', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Abandon recovery record', exact: true }).click()
  await expect(page.locator('.mcp-group-recovery')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Create group', exact: true })).toBeEnabled()
  expect(await page.evaluate(() => Object.values(sessionStorage).includes('e'.repeat(32)))).toBe(false)
  expect(gate.writes).toHaveLength(0)
})

test('switching authenticated IDs isolates recovery even with the same username', async ({ page }) => {
  const gate = await fixture(page), original = await (await page.request.get('/v1/auth/me')).json(), key = 'f'.repeat(32)
  let actorId = original.id
  await page.route('**/v1/auth/me', route => route.fulfill({ json: { ...original, id: actorId } }))
  await page.evaluate(({ actorId, key }) => sessionStorage.setItem(`gate-mcp-group-create-pending:${JSON.stringify([location.origin, actorId])}`, key), { actorId, key })
  actorId = 'opaque-synthetic-other-user'
  await page.reload()
  await page.locator('.mcp-group-view-switch').getByText('Groups', { exact: true }).click()
  await expect(page.locator('.service-entry').filter({ hasText: 'Synthetic alpha' })).toBeVisible()
  await expect(page.locator('.mcp-group-recovery')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Create group', exact: true })).toBeEnabled()
  expect(await page.evaluate(() => Object.values(sessionStorage).includes('f'.repeat(32)))).toBe(true)
  actorId = original.id
  await page.reload()
  await page.locator('.mcp-group-view-switch').getByText('Groups', { exact: true }).click()
  await expect(page.locator('.mcp-group-recovery')).toBeVisible()
  expect(gate.requests.filter(item => item.includes('/requests/'))).toHaveLength(0)
  expect(gate.writes).toHaveLength(0)
})

test('storage failure keeps in-dialog reconciliation usable and reports reload limitation', async ({ page }) => {
  const gate = await fixture(page)
  await page.evaluate(() => {
    const set = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith('gate-mcp-group-create-pending:')) throw new Error('Synthetic unavailable recovery storage')
      return set.call(this, key, value)
    }
  })
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Synthetic unavailable storage')
  gate.setLoseResponse()
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog).toContainText('Browser recovery storage is unavailable')
  await dialog.getByRole('button', { name: 'Check saved result', exact: true }).click()
  await expect(dialog).toContainText('saved group was recovered')
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Synthetic unavailable storage')
  expect(gate.writes).toHaveLength(1)
})

test('explicit retry of an unconfirmed original creation preserves later edits', async ({ page }) => {
  const gate = await fixture(page)
  let originalKey = '', aborted = false
  gate.setDelay(async route => {
    if (route.request().method() !== 'POST' || new URL(route.request().url()).pathname !== '/v1/mcp/groups' || aborted) return false
    originalKey = route.request().postDataJSON().request_key; aborted = true
    await route.abort('failed'); return true
  })
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Original submitted draft')
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Retry original creation', exact: true })).toBeVisible()
  await dialog.getByLabel('Name', { exact: true }).fill('Edits after failure')
  await dialog.getByRole('button', { name: 'Check saved result', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('No saved result')
  await dialog.getByRole('button', { name: 'Retry original creation', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Reload saved group', exact: true })).toBeVisible()
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Edits after failure')
  expect(gate.writes[0].body.request_key).toBe(originalKey)
  expect(gate.writes[0].body.name).toBe('Original submitted draft')
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes.map(item => item.method)).toEqual(['POST', 'PUT'])
})

test('explicit catalog refresh is separate from normal search and paging', async ({ page }) => {
  const gate = await fixture(page)
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Instance 0000')
  await dialog.locator('.ant-pagination-next').click()
  await expect(dialog).toContainText('Instance 0020')
  expect(gate.instanceQueries.every(query => query.get('refresh') !== 'true')).toBe(true)
  await dialog.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect.poll(() => gate.instanceQueries.at(-1)?.get('refresh')).toBe('true')
  await expect(dialog.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled()
  await dialog.getByRole('searchbox', { name: 'Search instances by name or ID' }).fill('0999')
  await expect(dialog).toContainText('Instance 0999')
  expect(gate.instanceQueries.at(-1)?.get('refresh')).toBe('false')
})

test('readonly management connection can inspect groups without write actions', async ({ page }) => {
  const gate = await fixture(page)
  await page.route('**/v1/auth/me', async route => {
    const response = await route.fetch({ timeout: 10_000, maxRedirects: 0 })
    const user = await response.json()
    user.auth_type = 'token'; user.scopes = ['operations.manage', 'tools.read', 'mcp.read', 'console.view']
    user.permissions = user.permissions.filter((permission: string) => permission !== 'tools.invoke' && permission !== '*')
    await route.fulfill({ response, json: user })
  })
  await page.reload()
  await page.locator('.mcp-group-view-switch').getByText('Groups', { exact: true }).click()
  await expect(page.locator('.service-entry').filter({ hasText: 'Synthetic alpha' })).toBeVisible()
  await page.locator('.service-entry').filter({ hasText: 'Synthetic alpha' }).click()
  await expect(page.locator('.mcp-group-detail h1')).toHaveText('Synthetic alpha')
  await expect(page.getByRole('button', { name: 'Create group', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit group', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Delete group', exact: true })).toHaveCount(0)
  expect(gate.writes).toHaveLength(0)
})

test('keyboard dirty close keeps or discards the exact draft and restores focus', async ({ page }) => {
  await fixture(page, 'zh-CN')
  const create = page.getByRole('button', { name: '创建组', exact: true })
  await create.click()
  const dialog = page.getByRole('dialog').first()
  await dialog.getByLabel('名称', { exact: true }).fill('保留的草稿')
  await page.keyboard.press('Escape')
  await page.getByRole('alertdialog').getByRole('button', { name: '继续编辑', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(dialog.getByLabel('名称', { exact: true })).toBeFocused()
  await expect(dialog.getByLabel('名称', { exact: true })).toHaveValue('保留的草稿')
  await page.keyboard.press('Escape')
  await page.getByRole('alertdialog').getByRole('button', { name: '放弃修改', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(create).toBeFocused()
})

test('group fields, state choices and member selection work by keyboard', async ({ page }) => {
  const gate = await fixture(page)
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill('Synthetic keyboard draft')
  await page.keyboard.press('Tab')
  await expect(dialog.getByLabel('Description', { exact: true })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('radio', { name: 'Active', exact: true })).toBeFocused()
  await page.keyboard.press('ArrowRight')
  await expect(dialog.getByRole('radio', { name: 'Archived', exact: true })).toBeChecked()
  const member = dialog.getByRole('checkbox', { name: 'Instance 0000 · instance-0000', exact: true })
  await member.focus(); await page.keyboard.press('Space')
  await expect(member).toBeChecked()
  await expect(dialog.getByRole('status')).toContainText('1 selected')
  await page.keyboard.press('Escape')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Discard changes', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes).toHaveLength(0)
})

test('late group details cannot replace a newly selected group', async ({ page }) => {
  const gate = await fixture(page)
  let release: (() => void) | undefined
  const held = new Promise<void>(resolve => { release = resolve })
  let entered = false
  gate.setDelay(async route => {
    if (new URL(route.request().url()).pathname !== `/v1/mcp/groups/${alpha}`) return false
    entered = true; await held
    await route.fulfill({ json: gate.records.get(alpha) }).catch(() => {})
    return true
  })
  try {
    await page.locator('.service-entry').filter({ hasText: 'Synthetic alpha' }).click()
    await expect.poll(() => entered).toBe(true)
    await page.locator('.service-entry').filter({ hasText: 'Synthetic beta' }).click()
    await expect(page.locator('.mcp-group-detail h1')).toHaveText('Synthetic beta')
  } finally { release?.() }
  await expect(page.locator('.mcp-group-detail h1')).toHaveText('Synthetic beta')
  await expect(page.locator('.mcp-group-detail')).toContainText('instance-0999')
})

test('closing a loading catalog ignores its late response in the next editor', async ({ page }) => {
  const gate = await fixture(page)
  let release: (() => void) | undefined, entered = false
  const held = new Promise<void>(resolve => { release = resolve })
  gate.setDelay(async route => {
    if (new URL(route.request().url()).pathname !== '/v1/mcp/groups/instances' || entered) return false
    entered = true; await held
    await route.fulfill({ json: { instances: [{ ...instances[0], name: 'Obsolete late row' }], total: 1, offset: 0, limit: 20 } }).catch(() => {})
    return true
  })
  try {
    await page.getByRole('button', { name: 'Create group', exact: true }).click()
    await expect.poll(() => entered).toBe(true)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: 'Create group', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Instance 0000')
  } finally { release?.() }
  await expect(page.getByRole('dialog')).not.toContainText('Obsolete late row')
})

test('pending save blocks duplicate submission and keyboard close', async ({ page }) => {
  const gate = await fixture(page)
  let release: (() => void) | undefined, entered = false
  const held = new Promise<void>(resolve => { release = resolve })
  gate.setDelay(async route => {
    if (route.request().method() !== 'POST' || new URL(route.request().url()).pathname !== '/v1/mcp/groups') return false
    entered = true; await held
    await route.fulfill({ json: record('c'.repeat(32), 'Pending synthetic', []) })
    return true
  })
  try {
    await page.getByRole('button', { name: 'Create group', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Name', { exact: true }).fill('Pending synthetic')
    await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
    await expect.poll(() => entered).toBe(true)
    await expect(dialog.getByRole('button', { name: 'Save group', exact: true })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeVisible()
    expect(gate.requests.filter(path => path === 'POST /v1/mcp/groups')).toHaveLength(1)
  } finally { release?.() }
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('real isolated Console reconciles lost create response then archives/deletes through bound CSRF', async ({ page }) => {
  await login(page)
  const creations: { key: string; id: string }[] = []
  await page.route('**/v1/mcp/groups', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const response = await route.fetch({ timeout: 10_000, maxRedirects: 0 })
    if (response.status() !== 200) return route.fulfill({ response })
    creations.push({ key: route.request().postDataJSON().request_key, id: (await response.json()).id })
    if (creations.length === 1) return route.abort('failed')
    return route.fulfill({ response })
  })
  await page.goto('/console/#/servers')
  await page.locator('.mcp-group-view-switch').getByText('Groups', { exact: true }).click()
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Synthetic ephemeral collection')
  await page.getByRole('dialog').getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Check saved result', exact: true })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(creations).toHaveLength(2)
  expect(creations[0]).toEqual(creations[1])
  const once = await page.request.get('/v1/mcp/groups?status=all&q=Synthetic%20ephemeral%20collection')
  expect((await once.json()).total).toBe(1)
  await expect(page.locator('.mcp-group-detail h1')).toHaveText('Synthetic ephemeral collection')
  await page.getByRole('button', { name: 'Edit group', exact: true }).click()
  await page.getByRole('dialog').getByRole('radio', { name: 'Archived', exact: true }).check()
  await page.getByRole('dialog').getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.mcp-group-detail')).toContainText('Archived')
  await page.getByRole('button', { name: 'Delete group', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete group', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('.mcp-group-detail h1')).toHaveText('Groups')
  const result = await page.request.get('/v1/mcp/groups?status=all&q=Synthetic%20ephemeral%20collection')
  expect(result.status()).toBe(200); expect((await result.json()).total).toBe(0)
})

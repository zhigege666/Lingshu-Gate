import { expect, test, type Page, type Route } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { login, expectInViewportAndUnobscured } from './helpers'
import { listFixtures, servers } from './synthetic-data'

const alpha = 'a'.repeat(32), beta = 'b'.repeat(32)
const instances = Array.from({ length: 1000 }, (_, i) => ({ instance_id: `instance-${String(i).padStart(4, '0')}`, name: `Instance ${String(i).padStart(4, '0')}`, status: 'not_loaded', available: true, groups: [{ id: alpha, name: 'Synthetic alpha', status: 'active' }] }))
const stamp = '2026-10-04T00:00:00Z'
const record = (id: string, name: string, members = instances.map(item => item.instance_id)) => ({ id, name, description: 'Synthetic metadata-only collection', status: 'active', revision: 1, created_at: stamp, updated_at: stamp, members: members.map(instance_id => ({ instance_id, status: 'active', available: true })) })

async function fixture(page: Page, locale = 'en-US', theme = 'dark') {
  await login(page)
  await page.addInitScript(({ locale, theme }) => { localStorage.setItem('lingshu-gate-console-locale', locale); localStorage.setItem('lingshu-gate-console-theme', theme) }, { locale, theme })
  const records = new Map([[alpha, record(alpha, 'Synthetic alpha')], [beta, record(beta, 'Synthetic beta', ['instance-0999'])]])
  const writes: { method: string; path: string; body: Record<string, unknown> }[] = []
  const requests: string[] = []
  let failure = false, delay: ((route: Route) => Promise<boolean>) | undefined
  await page.route('**/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname
    requests.push(`${req.method()} ${path}`)
    if (path.startsWith('/v1/mcp/groups')) {
      if (delay && await delay(route)) return
      if (path.endsWith('/csrf')) return route.fulfill({ json: { csrf: 'synthetic-request-ticket', expires_at: 9999999999 } })
      if (req.method() !== 'GET') {
        const body = req.postDataJSON(); writes.push({ method: req.method(), path, body })
        if (failure) return route.fulfill({ status: 409, json: { detail: { code: 'group_revision_conflict', message: 'Synthetic concurrent revision' } } })
        const id = req.method() === 'POST' ? 'c'.repeat(32) : path.split('/').at(-1)!
        if (req.method() === 'DELETE') { records.delete(id); return route.fulfill({ json: { id, deleted: true, metadata_only: true } }) }
        const next = { ...record(id, body.name, body.members), description: body.description, status: body.status, revision: (records.get(id)?.revision ?? 0) + 1 }
        records.set(id, next); return route.fulfill({ json: next })
      }
      const q = (url.searchParams.get('q') || '').toLowerCase(), offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 20)
      if (path.endsWith('/instances')) {
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
  return { records, writes, requests, setFailure: (value: boolean) => { failure = value }, setDelay: (value: typeof delay) => { delay = value } }
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
  await expect(dialog.getByRole('alert')).toContainText('Your draft is intact')
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('Synthetic selected group')
  gate.setFailure(false)
  await dialog.getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(gate.writes.map(item => item.body.members)).toEqual([['instance-0000', 'instance-0020', 'instance-0999'], ['instance-0000', 'instance-0020', 'instance-0999']])
  expect(gate.writes.every(item => !('endpoint' in item.body) && !('scopes' in item.body))).toBe(true)
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

test('real isolated Console creates/archives/deletes metadata through bound CSRF', async ({ page }) => {
  await login(page)
  await page.goto('/console/#/servers')
  await page.locator('.mcp-group-view-switch').getByText('Groups', { exact: true }).click()
  await page.getByRole('button', { name: 'Create group', exact: true }).click()
  await page.getByRole('dialog').getByLabel('Name', { exact: true }).fill('Synthetic ephemeral collection')
  await page.getByRole('dialog').getByRole('button', { name: 'Save group', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
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

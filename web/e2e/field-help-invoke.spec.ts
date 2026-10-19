import { expect, test, type Page } from '@playwright/test'
import { login } from './helpers'
import { servers, tools } from './synthetic-data'
import { translate } from '../src/i18n'

// Only synthetic form drafts are edited. No invocation or credential write is allowed.
test.beforeEach(async ({ page }) => {
  await login(page)
  await page.setViewportSize({ width: 1600, height: 900 })
})

test('field help opens on click without changing choices or losing Form/JSON arguments', async ({ page }) => {
  const explanation = 'Choose whether to include disabled records.'
  const fixture = { ...tools[0], input_schema: { type: 'object', properties: {
    enabled: { type: 'boolean', description: explanation },
    query: { type: 'string', description: 'The query is retained in this argument draft.' },
  } } }
  const writes: string[] = []
  await page.route('**/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') {
      writes.push(path)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    }
    if (path === '/v1/tools') return route.fulfill({ json: [fixture] })
    if (path === '/v1/mcp/servers') return route.fulfill({ json: { servers: servers.slice(0, 1), load_errors: [] } })
    return route.continue()
  })
  await page.goto('/console/#/invoke')
  const choices = page.getByRole('radiogroup', { name: 'enabled', exact: true })
  const help = page.getByRole('button', { name: 'enabled help', exact: true })
  const content = page.locator('[data-field-help-content]')
  const mode = page.getByRole('radiogroup', { name: 'Argument editor mode', exact: true })
  await expect(choices.getByRole('radio', { checked: true })).toHaveCount(0)
  await expect(choices).toHaveAccessibleDescription(explanation)
  await expect(help).toHaveAttribute('aria-expanded', 'false')
  await help.hover()
  // Pass the delayed hover-open interval used by the underlying popover.
  await page.waitForTimeout(350)
  await expect(help).toHaveAttribute('aria-expanded', 'false')
  await expect(content).toHaveCount(0)
  await help.click()
  await expect(help).toHaveAttribute('aria-expanded', 'true')
  await expect(content).toBeVisible()
  await expect(content).toHaveText(explanation)
  await expect(choices.getByRole('radio', { checked: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(help).toHaveAttribute('aria-expanded', 'false')
  await expect(help).toBeFocused()
  await expect(content).toHaveCount(0)
  await page.locator('.invoke-field-label').getByText('enabled', { exact: true }).click()
  await expect(choices.getByRole('radio', { checked: true })).toHaveCount(0)

  const query = page.getByRole('textbox', { name: 'query', exact: true })
  await page.locator('.invoke-field-label').getByText('query', { exact: true }).click()
  await expect(query).toBeFocused()
  await query.fill('synthetic draft')
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  const editor = page.locator('#invoke-arguments')
  expect(JSON.parse(await editor.inputValue())).toEqual({ query: 'synthetic draft' })
  const argumentsDraft = { enabled: false, query: 'synthetic draft', upstream: { count: 0, value: null, empty: '' } }
  await editor.fill(JSON.stringify(argumentsDraft))
  await mode.getByRole('radio', { name: 'Form', exact: true }).check()
  await expect(choices.getByRole('radio', { name: 'No (false)', exact: true })).toBeChecked()
  await help.click()
  await expect(content).toHaveText(explanation)
  await page.keyboard.press('Escape')
  await expect(query).toHaveValue('synthetic draft')
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await editor.inputValue())).toEqual(argumentsDraft)
  await editor.fill('{"enabled":false,')
  await mode.getByRole('radio', { name: 'Form', exact: true }).click()
  await expect(mode.getByRole('radio', { name: 'JSON', exact: true })).toBeChecked()
  await expect(editor).toHaveValue('{"enabled":false,')
  expect(writes).toEqual([])
})

test('Escape closes field help before its parent dialog and keeps validation visible', async ({ page }) => {
  const writes: string[] = []
  await page.route('**/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') {
      writes.push(path)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    }
    if (path === '/v1/credentials') return route.fulfill({ json: [] })
    return route.continue()
  })
  await page.goto('/console/#/credentials')
  await page.getByRole('button', { name: translate('en-US', 'newCredential'), exact: true }).click()
  const dialog = page.getByRole('dialog', { name: translate('en-US', 'newCredential'), exact: true })
  const name = dialog.locator('#credential-name')
  const value = dialog.locator('#credential-value')
  await name.fill('SYNTHETIC_FIELD_HELP')
  await dialog.getByRole('button', { name: translate('en-US', 'save'), exact: true }).click()
  await expect(value).toHaveAttribute('aria-invalid', 'true')
  await expect(dialog.locator('#credential-value-error')).toBeVisible()
  const help = dialog.getByRole('button', { name: `${translate('en-US', 'credentialValue')} help`, exact: true })
  await help.click()
  await expect(help).toHaveAttribute('aria-expanded', 'true')
  await expect(dialog.locator('[data-field-help-content]')).toContainText('A failed save keeps this attempt')
  await expect(dialog.locator('#credential-value-error')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(help).toHaveAttribute('aria-expanded', 'false')
  await expect(help).toBeFocused()
  await expect(dialog.locator('[data-field-help-content]')).toHaveCount(0)
  await expect(dialog).toBeVisible()
  await expect(name).toHaveValue('SYNTHETIC_FIELD_HELP')
  await expect(value).toHaveValue('')
  await expect(dialog.locator('#credential-value-error')).toBeVisible()
  await expect(value).toHaveAttribute('aria-describedby', 'credential-value-error credential-value-hint')
  expect(writes).toEqual([])
})

async function mockInvokeCatalog(page: Page, catalog: () => unknown[]) {
  const writes: string[] = []
  await page.route('**/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() !== 'GET') {
      writes.push(path)
      return route.fulfill({ status: 500, json: { detail: 'Unexpected mutation' } })
    }
    if (path === '/v1/tools') return route.fulfill({ json: catalog() })
    if (path === '/v1/mcp/servers') return route.fulfill({ json: { servers: servers.slice(0, 1), load_errors: [] } })
    return route.continue()
  })
  return writes
}

test('numeric drafts block stale runs and replacements until an atomic correction or explicit removal', async ({ page }) => {
  const fixture = { ...tools[0], input_schema: { type: 'object', required: ['count'], properties: {
    count: { type: 'integer', default: 7 }, ratio: { type: 'number', default: 0.5 },
  } } }
  const other = tools[100]
  const writes = await mockInvokeCatalog(page, () => [fixture, other])
  await page.goto('/console/#/invoke')
  const mode = page.getByRole('radiogroup', { name: 'Argument editor mode', exact: true })
  const editor = page.locator('#invoke-arguments')
  const count = page.getByRole('textbox', { name: /^count\b/ })
  const ratio = page.getByRole('textbox', { name: 'ratio', exact: true })
  const pending = page.locator('#invoke-pending-entries')
  const original = { count: 7, ratio: 0.5, opaque: { zero: 0, off: false, nil: null, empty: '' } }
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  await editor.fill(JSON.stringify(original))
  await mode.getByRole('radio', { name: 'Form', exact: true }).check()
  for (const raw of ['-', '1e', '9007199254740993', '1e400', '1.5']) {
    await count.fill(raw)
    await ratio.click()
    await expect(count).toHaveValue(raw)
    await expect(count).toHaveAttribute('aria-invalid', 'true')
    await expect(pending).toContainText(raw)
    await page.getByRole('button', { name: 'Run tool', exact: true }).click()
    await expect(count).toHaveValue(raw)
    expect(writes).toEqual([])
  }
  await mode.getByRole('radio', { name: 'JSON', exact: true }).click()
  await expect(mode.getByRole('radio', { name: 'Form', exact: true })).toBeChecked()
  await page.getByRole('button', { name: 'Restore defaults', exact: true }).click()
  await page.getByRole('button', { name: 'Fill example', exact: true }).click()
  await expect(count).toHaveValue('1.5')
  await page.locator('#invoke-tool').click()
  await page.getByTitle(`${other.name} · ${other.id}`, { exact: true }).click()
  await expect(page.locator('.invoke-run-bar')).toContainText(fixture.id)
  await expect(count).toHaveValue('1.5')

  await count.fill('0')
  await expect(pending).toHaveCount(0)
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await editor.inputValue())).toEqual({ ...original, count: 0 })
  await mode.getByRole('radio', { name: 'Form', exact: true }).check()
  await ratio.fill('0.')
  await count.click()
  await expect(ratio).toHaveValue('0.')
  await page.getByRole('button', { name: 'Run tool', exact: true }).click()
  expect(writes).toEqual([])
  await ratio.fill('0.25')
  await expect(pending).toHaveCount(0)
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await editor.inputValue())).toEqual({ ...original, count: 0, ratio: 0.25 })

  await mode.getByRole('radio', { name: 'Form', exact: true }).check()
  await count.fill('-')
  await count.fill('')
  await expect(pending).toHaveCount(0)
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await editor.inputValue())).toEqual({ ratio: 0.25, opaque: original.opaque })
  await page.getByRole('button', { name: 'Run tool', exact: true }).click()
  await expect(page.locator('#invoke-validation-summary')).toContainText('/count')
  expect(writes).toEqual([])
})

test('schema refresh retains each numeric or map draft without reinterpreting its kind', async ({ page }) => {
  let schema: Record<string, unknown> = { type: 'object', properties: { count: { type: 'integer' } } }
  const writes = await mockInvokeCatalog(page, () => [{ ...tools[0], input_schema: schema }])
  await page.goto('/console/#/invoke')
  const pending = page.locator('#invoke-pending-entries')
  const mode = page.getByRole('radiogroup', { name: 'Argument editor mode', exact: true })
  const refresh = page.getByRole('button', { name: 'Refresh current page', exact: true })
  const count = page.getByRole('textbox', { name: 'count', exact: true })
  await count.fill('1e')
  schema = { type: 'object', properties: { count: { type: 'object', additionalProperties: { type: 'string' } } } }
  await refresh.click()
  const mapKey = page.getByPlaceholder('Field name', { exact: true })
  await expect(mapKey).toHaveValue('')
  await expect(mapKey).toHaveAttribute('readonly', '')
  await expect(pending).toContainText('1e')
  await expect(page.getByRole('button', { name: 'Add field', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Run tool', exact: true }).click()
  await mode.getByRole('radio', { name: 'JSON', exact: true }).click()
  await expect(mode.getByRole('radio', { name: 'Form', exact: true })).toBeChecked()
  await pending.getByRole('button', { name: 'Clear numeric draft', exact: true }).click()
  await expect(mapKey).toBeEditable()
  await mapKey.fill('Header-Key')
  await page.getByRole('button', { name: 'Add field', exact: true }).click()
  await expect(pending).toHaveCount(0)
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  const editor = page.locator('#invoke-arguments')
  expect(JSON.parse(await editor.inputValue())).toEqual({ count: { 'Header-Key': '' } })

  await editor.fill('{}')
  await mode.getByRole('radio', { name: 'Form', exact: true }).check()
  await mapKey.fill('1e')
  schema = { type: 'object', properties: { count: { type: 'integer' } } }
  await refresh.click()
  await expect(count).toHaveValue('')
  await expect(count).toHaveAttribute('readonly', '')
  await expect(pending).toContainText('1e')
  await page.getByRole('button', { name: 'Run tool', exact: true }).click()
  await pending.getByRole('button', { name: 'Clear pending entry', exact: true }).click()
  await expect(count).toBeEditable()
  await count.fill('0')
  await mode.getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await editor.inputValue())).toEqual({ count: 0 })
  expect(writes).toEqual([])
})

test('numeric array edits keep unfinished sibling text attached until explicitly cleared', async ({ page }) => {
  const fixture = { ...tools[0], input_schema: { type: 'object', properties: {
    rows: { type: 'array', items: { type: 'integer' }, default: [1, 2] },
  } } }
  const writes = await mockInvokeCatalog(page, () => [fixture])
  await page.goto('/console/#/invoke')
  const first = page.getByRole('textbox', { name: /^Item 1\b/ })
  const second = page.getByRole('textbox', { name: /^Item 2\b/ })
  const pending = page.locator('#invoke-pending-entries')
  await second.fill('1e')
  await page.getByRole('button', { name: 'Remove rows 1', exact: true }).click()
  await expect(first).toHaveValue('1')
  await expect(second).toHaveValue('1e')
  await first.fill('')
  await expect(first).toHaveValue('1')
  await expect(second).toHaveValue('1e')
  await first.fill('-')
  await expect(pending.locator('li')).toHaveCount(2)
  await first.fill('0')
  await expect(first).toHaveValue('0')
  await expect(pending.locator('li')).toHaveCount(1)
  await expect(pending).toContainText('/rows/1')
  await page.getByRole('button', { name: 'Run tool', exact: true }).click()
  expect(writes).toEqual([])
  await pending.getByRole('button', { name: 'Clear numeric draft', exact: true }).click()
  await expect(second).toHaveValue('2')
  await page.getByRole('button', { name: 'Remove rows 1', exact: true }).click()
  await expect(first).toHaveValue('2')
  await expect(second).toHaveCount(0)
  await page.getByRole('radiogroup', { name: 'Argument editor mode', exact: true }).getByRole('radio', { name: 'JSON', exact: true }).check()
  expect(JSON.parse(await page.locator('#invoke-arguments').inputValue())).toEqual({ rows: [2] })
  expect(writes).toEqual([])
})

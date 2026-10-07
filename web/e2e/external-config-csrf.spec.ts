import { test, expect } from '@playwright/test'
import { login } from './helpers'

test('@full same-origin browser POST obtains a request-bound configuration ticket', async ({ page }) => {
  await login(page)
  await page.goto('/console/#/servers')
  const observed = await page.evaluate(async () => {
    const body = {
      manifest: {
        id: 'synthetic-browser-external',
        launch: { type: 'external' },
        transport: { endpoint: 'https://mcp.example.test/mcp', type: 'streamable_http' },
      },
      mode: 'create',
    }
    // These ASCII keys/values already use the service's sorted compact form.
    const encoded = JSON.stringify(body)
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(encoded))
    const digest = Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, '0')).join('')
    const ticket = await fetch(`/v1/mcp/external-configs/csrf?action=plan&request_digest=${digest}`, { method: 'POST' })
    if (!ticket.ok) return { ticket: ticket.status }
    const { csrf } = await ticket.json()
    const headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }
    const changed = await fetch('/v1/mcp/external-configs/plan', {
      method: 'POST', headers, body: JSON.stringify({ ...body, connect: true }),
    })
    const accepted = await fetch('/v1/mcp/external-configs/plan', { method: 'POST', headers, body: encoded })
    const replay = await fetch('/v1/mcp/external-configs/plan', { method: 'POST', headers, body: encoded })
    return { ticket: ticket.status, changed: changed.status, accepted: accepted.status, replay: replay.status }
  })
  // Origin is supplied by Chromium itself; no fabricated Origin header is used.
  expect(observed).toEqual({ ticket: 200, changed: 403, accepted: 200, replay: 403 })
})

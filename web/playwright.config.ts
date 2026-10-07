import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

process.env.GATE_E2E_TEMP_ROOT ||= mkdtempSync(join(tmpdir(), 'gate-e2e-'))

export default defineConfig({
  testDir: './e2e',
  globalTeardown: './e2e/teardown.ts',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:18763',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    viewport: { width: 1280, height: 720 },
    locale: 'en-US',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {},
  },
  webServer: {
    command: 'exec timeout --foreground 1800 ../.venv/bin/python ../scripts/e2e/serve.py',
    url: 'http://127.0.0.1:18763/healthz',
    timeout: 30_000,
    reuseExistingServer: false,
  },
})

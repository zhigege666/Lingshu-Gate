import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, basename } from 'node:path'

export default async function teardown() {
  const root = process.env.GATE_E2E_TEMP_ROOT
  if (root && dirname(root) === tmpdir() && basename(root).startsWith('gate-e2e-')) {
    rmSync(root, { recursive: true, force: true })
  }
}

import { configDefaults, defineConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default defineConfig({
  ...viteConfig,
  test: { exclude: [...configDefaults.exclude, 'e2e/**'] },
})

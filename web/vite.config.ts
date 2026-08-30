import fs from "node:fs"
import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

const versionSource = path.resolve(__dirname, "../src/lingshu_gate/_version.py")
const versionMatch = fs.readFileSync(versionSource, "utf8").match(/__version__\s*=\s*["']([^"']+)["']/)

if (!versionMatch) {
  throw new Error(`Unable to read Lingshu Gate version from ${versionSource}`)
}

export default defineConfig({
  base: "/console/",
  plugins: [react(), tailwindcss()],
  define: {
    __LINGSHU_GATE_VERSION__: JSON.stringify(versionMatch[1]),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "../src/lingshu_gate/static/console",
    emptyOutDir: true,
  },
})

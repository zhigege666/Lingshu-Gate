import fs from "node:fs"
import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

const versionSource = path.resolve(__dirname, "../src/lingshu_gate/_version.py")
const versionMatch = fs.existsSync(versionSource)
  ? fs.readFileSync(versionSource, "utf8").match(/__version__\s*=\s*["']([^"']+)["']/)
  : null
const developmentProxyTarget = process.env.LINGSHU_GATE_DEV_PROXY_TARGET || "http://127.0.0.1:8000"

if (!versionMatch && process.env.NODE_ENV === "production") {
  throw new Error(`Unable to read Lingshu Gate version from ${versionSource}`)
}

export default defineConfig({
  base: "/console/",
  server: {
    host: "0.0.0.0",
    port: 4173,
    strictPort: true,
    allowedHosts: ["terminal.local"],
    proxy: {
      "/v1": developmentProxyTarget,
      "/healthz": developmentProxyTarget,
      "/readyz": developmentProxyTarget,
    },
  },
  plugins: [react(), tailwindcss()],
  define: {
    __LINGSHU_GATE_VERSION__: JSON.stringify(versionMatch?.[1] || "dev"),
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

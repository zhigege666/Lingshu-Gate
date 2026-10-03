import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

// A separate entry publishes only the authorization UI under /oauth/assets/.
export default defineConfig({
  base: "/oauth/", plugins: [react(), tailwindcss()], publicDir: false,
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  esbuild: { minifyIdentifiers: false },
  build: { outDir: "../src/lingshu_gate/static/oauth", emptyOutDir: true,
    rollupOptions: { input: path.resolve(__dirname, "oauth.html") } },
})

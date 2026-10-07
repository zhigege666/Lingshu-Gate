import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

// A separate entry publishes only the authorization UI under /oauth/assets/.
export default defineConfig({
  base: "/oauth/", plugins: [react(), tailwindcss()], publicDir: false,
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  build: { outDir: "../src/lingshu_gate/static/oauth", emptyOutDir: true,
    rolldownOptions: { input: path.resolve(import.meta.dirname, "oauth.html"), output: { minify: { mangle: false } } } },
})

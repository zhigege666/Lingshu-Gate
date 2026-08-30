import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import { AuthGate } from "@/components/auth-gate"
import { applyTheme, getInitialTheme } from "@/theme"
import "./index.css"

// 认证门禁早于 App 渲染，需在首屏挂载前应用主题，避免登录页短暂或持续使用错误配色。
applyTheme(getInitialTheme())

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AuthGate>
      <App />
    </AuthGate>
  </React.StrictMode>,
)

import React from "react"
import ReactDOM from "react-dom/client"
import { ConsoleDesignProvider } from "@/components/console-design-provider"
import { OAuthConsentPage } from "@/pages/oauth-consent-page"
import { applyTheme, getInitialTheme } from "@/theme"
import "./index.css"
import "./features/external-connections/oauth.css"

applyTheme(getInitialTheme())
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><ConsoleDesignProvider><OAuthConsentPage /></ConsoleDesignProvider></React.StrictMode>)

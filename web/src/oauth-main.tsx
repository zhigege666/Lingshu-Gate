import React from "react"
import ReactDOM from "react-dom/client"
import { ConsoleDesignProvider } from "@/components/console-design-provider"
import { OAuthConsentPage } from "@/pages/oauth-consent-page"
import { oauthUiLocale } from "@/features/external-connections/oauth-ui-locale"
import { applyTheme, getInitialTheme } from "@/theme"
import "./index.css"
import "./features/external-connections/oauth.css"

applyTheme(getInitialTheme())
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><ConsoleDesignProvider initialLocale={oauthUiLocale(window.location.hash)}><OAuthConsentPage /></ConsoleDesignProvider></React.StrictMode>)

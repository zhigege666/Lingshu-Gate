import { MyAuthorizationsPage } from "./my-authorizations-page"
import type { Locale, TFunction } from "@/i18n"

// Preserve the legacy entry while using the same scope, secret and recovery behavior.
export function PersonalTokensPage(props: { locale: Locale; t: TFunction }) {
  return <MyAuthorizationsPage {...props} initialKind="api" />
}

export { TokenScopeSelector, TokenScopeSummary } from "@/features/external-connections/token-scope-controls"

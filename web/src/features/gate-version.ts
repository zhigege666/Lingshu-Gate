import { translate, type Locale } from "@/i18n"

export type GateVersionState =
  | { status: "loading" | "unavailable" }
  | { status: "ready"; version: string }

export function gateVersionText(state: GateVersionState, locale: Locale): string {
  return state.status === "ready" ? `v${state.version}`
    : translate(locale, state.status === "loading" ? "versionLoading" : "versionUnavailable")
}

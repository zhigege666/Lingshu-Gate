import type { Locale } from "@/i18n"

export function oauthUiLocale(fragment: string): Locale | undefined {
  const fields = new URLSearchParams(fragment.replace(/^#/, ""))
  const hints = fields.getAll("ui_locales")
  // The server emits only these canonical, non-security hints. Directly editing
  // the fragment changes presentation only, never the request ticket or APIs.
  return hints.length === 1 && (hints[0] === "zh-CN" || hints[0] === "en-US") ? hints[0] : undefined
}

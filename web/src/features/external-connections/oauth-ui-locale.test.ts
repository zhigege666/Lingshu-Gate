import { expect, it } from "vitest"
import { oauthUiLocale } from "./oauth-ui-locale"

it.each(["zh-CN", "en-US"] as const)("adopts the canonical %s presentation hint", locale => {
  expect(oauthUiLocale(`#request=synthetic-ticket&ui_locales=${locale}`)).toBe(locale)
})
it.each(["", "#request=synthetic-ticket", "#ui_locales=fr-CA", "#ui_locales=zh_CN", "#ui_locales=zh-CN&ui_locales=en-US", "#ui_locales=%3Cscript%3E"])("leaves the existing preference for an unsupported hint %s", fragment => {
  expect(oauthUiLocale(fragment)).toBeUndefined()
})

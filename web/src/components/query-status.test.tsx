import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { translate } from "@/i18n"
import { QueryStatus, querySignature } from "./query-status"

describe("remote query status", () => {
  const t = (key: Parameters<typeof translate>[1]) => translate("en-US", key)

  it("does not mark reordered or cleared optional filters as a different query", () => {
    const applied = { level: "error", limit: 80 }
    const next = { keyword: "", limit: 80, source: undefined, level: "error" }
    expect(querySignature(next)).toBe(querySignature(applied))
  })

  it("distinguishes meaningful false, zero, null and omitted filter values", () => {
    const signatures = [{}, { value: false }, { value: 0 }, { value: null }].map(querySignature)
    expect(new Set(signatures).size).toBe(signatures.length)
  })

  it("does not present the next query as a loaded snapshot before the first response", () => {
    const html = renderToStaticMarkup(<QueryStatus t={t} pendingChanges lastLoadedAt="" summary="level: error" />)
    expect(html).toContain('role="status"')
    expect(html).toContain(t("unappliedFilters"))
    expect(html).toContain(t("notLoaded"))
    expect(html).not.toContain("level: error")
    expect(html).not.toContain(t("snapshotAt"))
  })

  it("keeps the applied snapshot visible while new conditions await application", () => {
    const html = renderToStaticMarkup(<QueryStatus t={t} pendingChanges lastLoadedAt="2026-09-26T10:00:00Z" summary="level: info · limit: 80" />)
    expect(html).toContain(t("unappliedFilters"))
    expect(html).toContain("level: info · limit: 80")
    expect(html).toContain(t("snapshotAt"))
  })
})

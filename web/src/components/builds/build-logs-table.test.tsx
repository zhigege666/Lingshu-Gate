import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import type { BuildLog } from "@/api/builds"
import { translate } from "@/i18n"
import { BuildLogsTable } from "./build-logs-table"

describe("build log rendering bounds", () => {
  it.each(["zh-CN", "en-US"] as const)("renders at most 50 data rows and explains remote history in %s", locale => {
    const logs = Array.from({ length: 200 }, (_, index) => ({ id: String(index), build_id: "build", sequence: index, phase: "command", level: "info", message: `log ${index}`, command: [], stdout: "", stderr: "", started_at: "now", created_at: "now" } as BuildLog))
    const html = renderToStaticMarkup(<BuildLogsTable logs={logs} filter="all" onFilterChange={() => {}} selectedBuildLabel="build" t={key => translate(locale, key)} windowNavigation={{ busy: false, following: false, earlier: true, later: false, onEarlier() {}, onLater() {}, onLatest() {}, onPause() {} }} />)
    expect((html.match(/<tr\b/g) || []).length).toBe(51)
    expect(html).toContain(locale === "zh-CN" ? "历史仍保留在服务端" : "history remains on the server")
    expect(html).toContain(locale === "zh-CN" ? "更早记录" : "Earlier records")
  })
})

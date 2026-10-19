import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { BuildPreflightResult } from "@/api/builds"
import { translate, type Locale, type TFunction } from "@/i18n"
import { PreflightCard } from "./builds-page"

const preflight: BuildPreflightResult = {
  status: "error", runtime: "python", detected_runtime: "python", runtime_candidates: ["python"],
  project_root: ".", project_root_dir: "/synthetic/project", upload_root_dir: "/synthetic/project",
  platform: "linux", tools: {}, recommendations: [], metadata: {},
  checks: [
    ...Array.from({ length: 20 }, (_, index) => ({ id: `passed-${index}`, status: "ok", message: `Passed check ${index}` })),
    { id: "late-warning", status: "warning", message: "Optional executable is unavailable" },
    { id: "late-error", status: "error", message: "Required interpreter is unavailable", detail: "Choose an installed interpreter before building." },
    { id: "new-status", status: "unsupported", message: "The runner cannot check this requirement" },
  ],
}

function render(locale: Locale, result = preflight) {
  const t: TFunction = key => translate(locale, key)
  return renderToStaticMarkup(<PreflightCard preflight={result} t={t} />)
}

describe("build preflight details", () => {
  it.each(["en-US", "zh-CN"] as const)("keeps all blocking and non-passing checks visible in %s", locale => {
    const html = render(locale)
    const attention = html.match(/<section\b[^>]*>[\s\S]*?<\/section>/)?.[0] || ""
    const passed = html.match(/<details\b[^>]*>[\s\S]*?<\/details>/)?.[0] || ""

    expect(attention).toContain("Required interpreter is unavailable")
    expect(attention).toContain("Choose an installed interpreter before building.")
    expect(attention).toContain("Optional executable is unavailable")
    expect(attention).toContain("The runner cannot check this requirement")
    expect(attention.indexOf("late-error")).toBeLessThan(attention.indexOf("late-warning"))
    expect(attention).not.toContain("Passed check")
    expect(attention).not.toContain("<details")
    expect(passed).toContain(locale === "zh-CN" ? "已通过的检查" : "Passed checks")
    expect(passed).toContain("(20)")
    expect(passed).toContain("Passed check 0")
    expect(passed).toContain("Passed check 19")
    expect(passed).not.toContain("open=")
  })

  it("does not render empty check groups and explains a missing check list", () => {
    const html = render("en-US", { ...preflight, checks: [] })
    expect(html).toContain("This preflight returned no check details.")
    expect(html).not.toContain("Checks requiring attention")
    expect(html).not.toContain("Passed checks")
  })
})

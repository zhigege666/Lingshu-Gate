import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { UploadsPage } from "@/pages/uploads-page"
import { BuildsPage } from "@/pages/builds-page"
import { translate, type TFunction } from "@/i18n"

const t: TFunction = key => translate("zh-CN", key)

describe("unselected delivery workspaces", () => {
  it("offers uploading without an empty result panel or duplicate list refresh buttons", () => {
    const html = renderToStaticMarkup(<UploadsPage t={t} />)
    expect(html).toContain("上传记录")
    expect(html).toContain(t("uploadAndAnalyze"))
    expect(html).not.toContain("高级数据 / 原始 JSON")
    expect(html).not.toContain(t("refreshList"))
    expect(html).not.toContain("xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]")
  })

  it("shows the next upload action before a project is selected instead of unusable build controls", () => {
    const html = renderToStaticMarkup(<BuildsPage t={t} />)
    expect(html).toContain('href="#/uploads"')
    expect(html).not.toContain(t("noSelectedBuild"))
    expect(html).not.toContain("部署选项")
    expect(html).not.toContain(`>${t("createBuild")}<`)
    expect(html).not.toContain(`>${t("deployBuild")}<`)
  })
})

import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { BuildRecord, DeploymentRecord } from "@/api/builds"
import { translate, type TFunction } from "@/i18n"
import { BuildRecordsTable } from "./build-records-table"
import { DeploymentRecordsTable } from "./deployment-records-table"

const t: TFunction = key => translate("zh-CN", key)
const noop = () => {}
const build: BuildRecord = {
  id: "example-build", upload_id: "example-upload", status: "success", runtime: "python",
  source_dir: "source", artifact_dir: "artifact", commands: [], logs: [], manifest: {},
  created_at: "2026-09-30T00:00:00Z", updated_at: "2026-09-30T00:00:00Z",
}
const deployment: DeploymentRecord = {
  id: "example-deployment", build_id: build.id, server_id: "example-service", status: "success",
  manifest: {}, started: false, created_at: build.created_at, updated_at: build.updated_at,
}

function rowButtons(html: string) {
  const row = html.match(/<tbody[^>]*>([\s\S]*?)<\/tbody>/)?.[1] || ""
  expect(row).toContain('aria-haspopup="menu"')
  return [...row.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => ({
    markup: button, disabled: button.includes('disabled=""'),
  }))
}

function buildButtons(status: string, busy = false) {
  return rowButtons(renderToStaticMarkup(<BuildRecordsTable builds={[{ ...build, status }]} busy={busy}
    selectedBuildId="" canRequestStop={item => item.status === "running"}
    onShowBuild={noop} onLoadLogs={noop} onRequestStop={noop} onDeploy={noop} onRetry={noop} onDelete={noop} t={t} />))
}

describe("构建和部署行主要操作与更多菜单", () => {
  it("成功构建显示日志和配置部署，删除收进菜单", () => {
    expect(buildButtons("success")).toEqual([
      { markup: expect.stringContaining(">查看日志<"), disabled: false }, { markup: expect.stringContaining(">配置部署<"), disabled: false },
      { markup: expect.stringContaining(`>${t("actions")}<`), disabled: false },
    ])
  })
  it("运行中直接显示停止入口，不能部署或重试", () => {
    expect(buildButtons("running")).toEqual([
      { markup: expect.stringContaining(">查看日志<"), disabled: false }, { markup: expect.stringContaining(`>${t("requestStop")}<`), disabled: false },
      { markup: expect.stringContaining(`>${t("actions")}<`), disabled: false },
    ])
  })
  it.each(["failed", "cancelled", "unsupported"])("%s 构建直接显示重试", status => {
    expect(buildButtons(status)).toContainEqual({ markup: expect.stringContaining(">重新构建<"), disabled: false })
    expect(buildButtons(status).map(button => button.markup)).not.toContainEqual(expect.stringContaining(`>${t("deployBuild")}<`))
  })
  it("忙碌时禁用写操作，但仍可查看", () => {
    expect(buildButtons("success", true)).toEqual([
      { markup: expect.stringContaining(">查看日志<"), disabled: false }, { markup: expect.stringContaining(">配置部署<"), disabled: true },
      { markup: expect.stringContaining(`>${t("actions")}<`), disabled: false },
    ])
  })
  it.each([false, true])("部署操作以服务入口和次要菜单呈现：%s", hasPrevious => {
    const buttons = rowButtons(renderToStaticMarkup(<DeploymentRecordsTable
      deployments={[{ ...deployment, previous_manifest: { id: deployment.server_id }, rollback_available: hasPrevious }]}
      busy={false} selectedDeploymentId="" onSelect={noop} onDetail={noop} onRollback={noop} onDelete={noop} t={t} />))
    expect(buttons.map(button => button.markup)).toEqual([expect.stringContaining(`>${t("actions")}<`)])
  })
})

describe("紧凑的构建与部署列表工具栏", () => {
  it.each(["zh-CN", "en-US"] as const)("%s 不重复页签标题，保留有意义的搜索和状态过滤", locale => {
    const tr: TFunction = key => translate(locale, key)
    const html = renderToStaticMarkup(<BuildRecordsTable builds={[build]} busy={false}
      selectedBuildId="" canRequestStop={() => false} onShowBuild={noop} onLoadLogs={noop}
      onRequestStop={noop} onDeploy={noop} onRetry={noop} onDelete={noop} t={tr} />)
    expect(html).not.toContain("<h3")
    expect(html).not.toContain(`${tr("search")} ·`)
    expect(html).toContain(locale === "zh-CN" ? "搜索构建 ID / 上传 ID" : "Search build / upload ID")
    expect(html).toContain(locale === "zh-CN" ? "全部状态" : "All statuses")
    expect(html).toContain('role="region"')
    expect(html).toContain('role="status"')
  })
})

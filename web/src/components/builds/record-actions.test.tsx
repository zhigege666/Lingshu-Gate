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
  expect(row).not.toContain('aria-haspopup="menu"')
  return [...row.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => ({
    label: button.replace(/<[^>]+>/g, ""), disabled: button.includes('disabled=""'),
  }))
}

function buildButtons(status: string, busy = false) {
  return rowButtons(renderToStaticMarkup(<BuildRecordsTable builds={[{ ...build, status }]} busy={busy}
    selectedBuildId="" canRequestStop={item => item.status === "running"}
    onShowBuild={noop} onLoadLogs={noop} onRequestStop={noop} onDeploy={noop} onRetry={noop} onDelete={noop} t={t} />))
}

describe("构建和部署行操作常驻展示", () => {
  it("成功构建直接显示查看、日志、部署和删除，不重复入口", () => {
    expect(buildButtons("success")).toEqual([
      { label: "查看", disabled: false }, { label: "查看日志", disabled: false },
      { label: t("deployBuild"), disabled: false }, { label: "删除记录", disabled: false },
    ])
  })
  it("运行中保留停止入口和删除禁用，不能部署或重试", () => {
    expect(buildButtons("running")).toEqual([
      { label: "查看", disabled: false }, { label: "查看日志", disabled: false },
      { label: t("requestStop"), disabled: false }, { label: "删除记录", disabled: true },
    ])
  })
  it.each(["failed", "cancelled", "unsupported"])("%s 构建直接显示重试", status => {
    expect(buildButtons(status)).toContainEqual({ label: "重新构建", disabled: false })
    expect(buildButtons(status).map(button => button.label)).not.toContain(t("deployBuild"))
  })
  it("忙碌时禁用写操作，但仍可查看", () => {
    expect(buildButtons("success", true)).toEqual([
      { label: "查看", disabled: false }, { label: "查看日志", disabled: false },
      { label: t("deployBuild"), disabled: true }, { label: "删除记录", disabled: true },
    ])
  })
  it.each([false, true])("部署回滚仍由历史配置决定：%s", hasPrevious => {
    const buttons = rowButtons(renderToStaticMarkup(<DeploymentRecordsTable
      deployments={[{ ...deployment, previous_manifest: hasPrevious ? { id: deployment.server_id } : null }]}
      busy={false} selectedDeploymentId="" onSelect={noop} onDetail={noop} onRollback={noop} onDelete={noop} t={t} />))
    expect(buttons.map(button => button.label)).toEqual([
      "查看", t("viewServerDetail"), ...(hasPrevious ? [t("rollback")] : []), "删除记录",
    ])
  })
})

import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ConfigsPage } from "@/pages/configs-page"
import { translate, type TFunction } from "@/i18n"

const t: TFunction = key => translate("zh-CN", key)

function actionButtons(busy: boolean) {
  const html = renderToStaticMarkup(<ConfigsPage
    locale="zh-CN"
    t={t}
    configs={[{ id: "example", path: "/config/example.yaml", format: "yaml", manifest: { id: "example", name: "Example" } }]}
    configErrors={[]}
    selectedConfigId=""
    configText=""
    busy={busy}
    editorOpen={false}
    onCloseEditor={() => {}}
    onNewConfig={() => {}}
    onReloadConfigs={() => {}}
    onEditConfig={() => {}}
    onApplyConfig={() => {}}
    onDeleteConfig={() => {}}
    onConfigTextChange={() => {}}
    onSaveConfig={async () => {}}
  />)
  const row = html.match(/<tbody[^>]*>([\s\S]*?)<\/tbody>/)?.[1] || ""
  return [...row.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => ({
    label: button.replace(/<[^>]+>/g, ""),
    disabled: button.includes('disabled=""'),
  }))
}

describe("MCP 配置行操作", () => {
  it("只显示一次编辑、应用和删除，删除无需打开重复菜单", () => {
    expect(actionButtons(false)).toEqual([
      { label: "编辑", disabled: false },
      { label: "应用", disabled: false },
      { label: "删除", disabled: false },
    ])
  })

  it("操作繁忙时同时禁用三个行按钮", () => {
    expect(actionButtons(true)).toEqual([
      { label: "编辑", disabled: true },
      { label: "应用", disabled: true },
      { label: "删除", disabled: true },
    ])
  })
})

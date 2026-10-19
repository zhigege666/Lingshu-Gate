import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { configStartupDisplay, ConfigsPage } from "@/pages/configs-page"
import { translate, type TFunction } from "@/i18n"

const t: TFunction = key => translate("zh-CN", key)

function actionButtons(busy: boolean, count = 1) {
  const html = renderToStaticMarkup(<ConfigsPage
    locale="zh-CN"
    t={t}
    configs={Array.from({ length: count }, (_, index) => ({ id: `example-${index}`, path: `/config/example-${index}.yaml`, format: "yaml", manifest: { id: `example-${index}`, name: "Example" } }))}
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
  it("200 configurations render only 50 rows without duplicating actions", () => {
    expect(actionButtons(false, 200)).toHaveLength(50 * 3)
  })

})

describe("configuration startup policy labels", () => {
  it("identifies legacy restore regardless of the auto_start fallback value", () => {
    for (const auto_start of [true, false]) {
      expect(configStartupDisplay({ auto_start }, "en-US").label).toBe("Restore last state")
      expect(configStartupDisplay({ auto_start, startup_policy: "legacy_restore" }, "zh-CN").label).toBe("恢复上次状态")
    }
  })

  it("distinguishes the new automatic and manual policy while keeping disabled services inactive", () => {
    expect(configStartupDisplay({ startup_policy: "gate_start_v1", auto_start: true }, "en-US")).toMatchObject({ label: "Automatic on startup", automatic: true })
    expect(configStartupDisplay({ startup_policy: "gate_start_v1", auto_start: false }, "en-US")).toMatchObject({ label: "Manual start", automatic: false })
    expect(configStartupDisplay({ startup_policy: "gate_start_v1", auto_start: true, enabled: false }, "zh-CN")).toMatchObject({ label: "启动时自动", automatic: false })
  })

  it("does not describe an unrecognized policy as manual startup", () => {
    expect(configStartupDisplay({ startup_policy: "unknown_policy" }, "en-US").label).toBe("Unconfirmed policy")
  })
})

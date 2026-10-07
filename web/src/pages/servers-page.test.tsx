import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { McpServer } from "@/api/client"
import { translate, type Locale, type TFunction } from "@/i18n"
import { ServersPage } from "./servers-page"

const fixture = vi.hoisted(() => ({ server: undefined as McpServer | undefined }))
vi.mock("@/features/servers/use-server-details", () => ({
  useServerDetails: () => ({ states: { overview: { loading: false, data: { server: fixture.server } } }, load: vi.fn() }),
}))

function buttons(changes: Partial<McpServer>, busy = false, locale: Locale = "zh-CN") {
  fixture.server = {
    id: "example-service", enabled: true, launch_type: "managed_process", transport_type: "stdio",
    status: "loaded", tool_count: 0, restart_policy: {}, restart_count: 0, restart_attempts: 0,
    consecutive_health_failures: 0, health_status: "unknown", ...changes,
  }
  const t: TFunction = key => translate(locale, key)
  const html = renderToStaticMarkup(<ServersPage locale={locale} t={t} servers={[fixture.server]}
    loadErrors={[]} busy={busy} visibleTools={[]} toolsError={null} canReadTools canManageClassifications={false}
    onServerAction={vi.fn()} onRefresh={vi.fn()} onNewConfig={vi.fn()} onNavigate={vi.fn()} />)
  const header = html.match(/<header\b[\s\S]*?<\/header>/)?.[0] || ""
  expect(header).not.toContain("ant-dropdown")
  return [...header.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => ({
    label: button.replace(/<[^>]+>/g, "").replace(/([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])/g, "$1"), disabled: button.includes('disabled=""'),
  }))
}

describe("服务操作直接展示", () => {
  it("截图中的已加载服务直接显示启动", () => {
    expect(buttons({ allowed_actions: ["start"] })).toEqual([
      { label: "查看工具", disabled: false }, { label: "启动", disabled: false },
    ])
  })
  it("运行中服务直接显示停止和重启", () => {
    expect(buttons({ status: "running", allowed_actions: ["stop", "restart"] })).toEqual([
      { label: "查看工具", disabled: false }, { label: "停止", disabled: false }, { label: "重启", disabled: false },
    ])
  })
  it("空 allowed_actions 不暴露写操作", () => {
    expect(buttons({ allowed_actions: [] })).toEqual([{ label: "查看工具", disabled: false }])
  })
  it("忙碌时保留按钮但禁用服务操作", () => {
    expect(buttons({ allowed_actions: ["start"] }, true)).toContainEqual({ label: "启动", disabled: true })
  })
  it("外部服务保留连接和断开语义", () => {
    expect(buttons({ launch_type: "external", allowed_actions: ["start"] })).toContainEqual({ label: "连接", disabled: false })
    expect(buttons({ launch_type: "external", allowed_actions: ["stop"] })).toContainEqual({ label: "断开", disabled: false })
  })
  it("英文按钮复用原有词条", () => {
    expect(buttons({ allowed_actions: ["start"] }, false, "en-US")).toContainEqual({ label: "Start", disabled: false })
  })
})

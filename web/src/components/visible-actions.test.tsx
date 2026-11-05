import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { AuthUser } from "./auth-gate"
import { ConsoleShell } from "./console-shell"
import { UploadList } from "./uploads/upload-list"
import { useConsoleNavigation } from "@/routing/use-console-navigation"
import { translate, type TFunction } from "@/i18n"

vi.mock("@/components/console-design-provider", () => ({
  useConsoleDesign: () => ({ locale: "zh-CN", theme: "light", setLocale: vi.fn(), setTheme: vi.fn() }),
}))
const t: TFunction = key => translate("zh-CN", key)
const noop = () => {}

function Shell({ authType }: { authType: string }) {
  const { navById, navGroups } = useConsoleNavigation({ locale: "zh-CN", t, can: () => true, authenticated: true })
  const user: AuthUser = {
    id: "example-user", username: "example", display_name: "Example", role: "admin", roles: ["admin"],
    permissions: [], status: "active", must_change_password: false, auth_type: authType, scopes: [],
  }
  return <ConsoleShell view="servers" title="MCP 服务" user={user} version="0.2.2" groups={navGroups} items={navById}
    busy={false} onNavigate={noop} onSearch={noop} onRefresh={noop} onLogout={noop}>内容</ConsoleShell>
}

describe("控制台导航与上传行操作", () => {
  it.each(["session", "disabled"])("%s 账号首屏展示适用操作", authType => {
    const html = renderToStaticMarkup(<Shell authType={authType} />)
    expect(html).toContain('aria-label="账号菜单"')
    expect(html).toContain('class="console-mobile-context">MCP 服务</span>')
    expect(html).not.toContain("OpenAPI")
  })
  it.each([false, true])("上传行操作收纳在菜单中，避免占用首屏：%s", busy => {
    const html = renderToStaticMarkup(<UploadList
      uploads={[{ id: "example-upload", filename: "example.zip", status: "analyzed", detected_runtime: "python", created_at: "", updated_at: "" }]}
      builds={[]} deployments={[]} selectedId="" busy={busy} loading={false} failed={false} filtered={false}
      onSelect={noop} onDraft={noop} onCreateBuild={noop} onDelete={noop} t={t} />)
    const buttons = [...html.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => ({
      label: button.replace(/<[^>]+>/g, "").trim(), disabled: button.includes('disabled=""'),
    }))
    expect(buttons).toContainEqual({ label: "操作", disabled: false })
    expect(html).toContain('aria-haspopup="menu"')
    expect(html).not.toContain(t("draftManifest"))
  })
})

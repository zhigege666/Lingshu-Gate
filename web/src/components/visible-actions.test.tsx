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

describe("账号与上传操作直接展示", () => {
  it.each(["session", "disabled"])("%s 首屏保留 OpenAPI，退出只在账号菜单", authType => {
    const html = renderToStaticMarkup(<Shell authType={authType} />)
    const header = html.match(/<header\b[\s\S]*?<\/header>/)?.[0] || ""
    expect(header).toContain("OpenAPI")
    expect(header).not.toContain("退出登录")
    expect(header.match(/>Example</g)).toHaveLength(1)
  })
  it.each([false, true])("上传行按钮直接展示并保留忙碌禁用：%s", busy => {
    const html = renderToStaticMarkup(<UploadList
      uploads={[{ id: "example-upload", filename: "example.zip", status: "analyzed", detected_runtime: "python", created_at: "", updated_at: "" }]}
      builds={[]} deployments={[]} selectedId="" busy={busy} loading={false} failed={false} filtered={false}
      onSelect={noop} onDraft={noop} onCreateBuild={noop} onDelete={noop} t={t} />)
    const buttons = [...html.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(([button]) => ({
      label: button.replace(/<[^>]+>/g, ""), disabled: button.includes('disabled=""'),
    }))
    for (const key of ["draftManifest", "createBuild", "delete"] as const) {
      expect(buttons).toContainEqual({ label: t(key), disabled: busy })
    }
    expect(html).not.toContain('aria-haspopup="menu"')
  })
})

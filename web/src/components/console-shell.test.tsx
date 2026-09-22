import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { ConsoleShell } from "@/components/console-shell"
import { PageHeader } from "@/components/page-shell"
import type { AuthUser } from "@/components/auth-gate"
import { translate, type TFunction } from "@/i18n"
import { CONSOLE_ROUTES, type ConsoleView } from "@/routing/console-routes"
import { useConsoleNavigation } from "@/routing/use-console-navigation"
import { consoleViewHash, parseConsoleHash } from "@/routing/use-console-route"

vi.mock("@/components/console-design-provider", () => ({
  useConsoleDesign: () => ({ theme: "light", locale: "zh-CN", setTheme: vi.fn(), setLocale: vi.fn() }),
}))

const t: TFunction = key => translate("zh-CN", key)
const user: AuthUser = {
  id: "test-user", username: "test-user", display_name: "Test", role: "user", roles: [],
  permissions: [], status: "active", must_change_password: false, auth_type: "session", scopes: [],
}

function NavigationFixture({ permissions, authenticated = true, view = "tools" }: {
  permissions: string[]; authenticated?: boolean; view?: ConsoleView
}) {
  const { navGroups, navById } = useConsoleNavigation({ locale: "zh-CN", t, can: permission => permissions.includes(permission), authenticated })
  return <ConsoleShell view={view} title={navById[view].label} user={user} version="test" groups={navGroups} items={navById} busy={false}
    onNavigate={() => {}} onRefresh={() => {}} onSearch={() => {}} onLogout={() => {}}>
    <PageHeader title={navById[view].label} />
  </ConsoleShell>
}

function navigationMarkup(props: Parameters<typeof NavigationFixture>[0]) {
  const html = renderToStaticMarkup(<NavigationFixture {...props} />)
  const navigation = html.match(/<nav\b[^>]*>([\s\S]*?)<\/nav>/)?.[1]
  expect(navigation).toBeDefined()
  return navigation!
}

describe("控制台直接导航", () => {
  it("全部已授权页面直接呈现为可访问的路由链接，无需打开二级菜单", () => {
    const html = navigationMarkup({ permissions: [...new Set(CONSOLE_ROUTES.map(route => route.permission))], view: "personalTokens" })
    const links = [...html.matchAll(/<a\b[^>]*href="([^"]+)"[^>]*>/g)]
    expect(links).toHaveLength(CONSOLE_ROUTES.length)
    for (const route of CONSOLE_ROUTES) {
      expect(links.filter(link => link[1] === consoleViewHash(route.id))).toHaveLength(1)
      expect(parseConsoleHash(consoleViewHash(route.id)).view).toBe(route.id)
    }
    expect(html).not.toContain("<button")
    expect(html.match(/aria-current="page"/g)).toHaveLength(1)
    expect(html).toMatch(/<a[^>]*href="#\/personalTokens"[^>]*aria-current="page"/)
  })

  it("受限账号只看到实际授权的页面", () => {
    const html = navigationMarkup({ permissions: ["tools.read", "audit.read"] })
    expect([...html.matchAll(/href="([^"]+)"/g)].map(link => link[1])).toEqual(["#/tools", "#/invoke", "#/invocationAudit"])
    expect(html).not.toContain("用户管理")
    expect(html).not.toContain("资源授权")
    expect(html).not.toContain("配置管理")
  })

  it("未启用登录时不出现必须绑定个人身份的凭据页面", () => {
    const html = navigationMarkup({ permissions: ["console.view", "credentials.manage.self"], authenticated: false, view: "dashboard" })
    expect([...html.matchAll(/href="([^"]+)"/g)].map(link => link[1])).toEqual(["#/dashboard"])
  })

  it("没有可见页面时仍可渲染导航容器", () => {
    const html = navigationMarkup({ permissions: [] })
    expect(html).not.toContain("<a ")
  })
})

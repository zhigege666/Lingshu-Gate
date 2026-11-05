import { useEffect, useRef, useState, type ReactNode } from "react"
import { BookOpen, Check, ChevronDown, Globe, LogOut, Menu, Moon, RefreshCw, Search, Sun, X } from "lucide-react"
import { DropdownMenu } from "radix-ui"
import { Button } from "@/components/ui/button"
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import type { AuthUser } from "@/components/auth-gate"
import { useConsoleDesign } from "@/components/console-design-provider"
import type { ConsoleNavItem } from "@/routing/use-console-navigation"
import type { ConsoleView } from "@/routing/console-routes"
import { consoleViewHash } from "@/routing/use-console-route"

type Props = {
  view: ConsoleView
  title: string
  user: AuthUser
  version: string
  groups: Array<{ title: string; items: ConsoleView[] }>
  items: Record<ConsoleView, ConsoleNavItem>
  busy: boolean
  onNavigate: (view: ConsoleView) => void
  onSearch: () => void
  onRefresh: () => void
  onLogout: () => void
  children: ReactNode
}

export function ConsoleShell({ view, title, user, version, groups, items, busy, onNavigate, onSearch, onRefresh, onLogout, children }: Props) {
  const { theme, setTheme, locale, setLocale } = useConsoleDesign()
  const [mobileOpen, setMobileOpen] = useState(false)
  const activeNavItem = useRef<HTMLAnchorElement>(null)
  useEffect(() => {
    activeNavItem.current?.scrollIntoView({ block: "nearest" })
    if (view !== "tools") window.scrollTo(0, 0)
  }, [view])
  const zh = locale === "zh-CN"
  const roleNames: Record<string, string> = zh
    ? { admin: "管理员", operator: "运维人员", viewer: "只读观察者" }
    : { admin: "Administrator", operator: "Operator", viewer: "Viewer" }
  const roles = [...new Set(user.roles.filter(Boolean))]
  if (!roles.length && user.role) roles.push(user.role)
  const roleLabels = roles.map(role => Object.hasOwn(roleNames, role) ? roleNames[role] : role).join(", ")
  const allowedIds = groups.flatMap(group => group.items)
  function navigate(id: ConsoleView) {
    if (!allowedIds.includes(id)) return
    onNavigate(id)
    setMobileOpen(false)
  }
  function navigation(mobile = false) {
    return <nav className="console-nav" data-console-nav={mobile ? "mobile" : "desktop"} aria-label={zh ? "主导航" : "Main navigation"}>
      {groups.map(group => <div className="console-nav-group" key={items[group.items[0]].section}>
        <div className="console-nav-group-title">{group.title}</div>
        {group.items.map(id => {
          const Icon = items[id].icon
          return <a key={id} ref={!mobile && view === id ? activeNavItem : undefined} href={consoleViewHash(id)}
            className="console-rail-item" data-active={view === id} aria-current={view === id ? "page" : undefined}
            title={items[id].label} onClick={event => {
              if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
              event.preventDefault(); navigate(id)
            }}><Icon size={17} aria-hidden="true" /><span>{items[id].label}</span></a>
        })}
      </div>)}
    </nav>
  }
  return <div className="console-shell">
    <a className="console-skip-link" href="#console-content" onClick={event => { event.preventDefault(); document.getElementById("console-content")?.focus() }}>{zh ? "跳到页面内容" : "Skip to content"}</a>
    <aside className="console-rail">
      <a href={consoleViewHash(allowedIds[0] || view)} className="console-brand" aria-label={`Lingshu Gate ${version}`} onClick={event => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
        event.preventDefault(); navigate(allowedIds[0] || view)
      }}>
        <img src="/lingshu-gate-icon.svg" alt="" />
        <span className="console-brand-label"><strong>Lingshu Gate</strong><span className="console-version" title={version}>{version}</span></span>
      </a>
      {navigation()}
    </aside>
    <header className="console-header">
      <Button className="console-mobile-menu console-icon-button" variant="ghost" onClick={() => setMobileOpen(true)} aria-label={zh ? "打开导航" : "Open navigation"}><Menu /></Button>
      <Button className="console-search-trigger" variant="outline" onClick={onSearch} aria-label={zh ? "搜索" : "Search"}>
        <Search /><span>{zh ? "搜索页面或操作" : "Search pages or actions"}</span><kbd aria-hidden="true">Ctrl K</kbd>
      </Button>
      <span className="console-mobile-context">{title}</span>
      <div className="console-header-actions">
        <Button className="console-icon-button" variant="ghost" disabled={busy} onClick={onRefresh} aria-label={zh ? "刷新当前页面" : "Refresh current page"} title={zh ? "刷新当前页面" : "Refresh current page"}>
          <RefreshCw className={busy ? "animate-spin" : undefined} />
        </Button>
        <Button className="console-icon-button" variant="ghost" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={zh ? "切换主题" : "Toggle theme"} title={theme === "dark" ? (zh ? "切换浅色" : "Light theme") : (zh ? "切换深色" : "Dark theme")}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
        <DropdownMenu.Root modal={false}>
          <DropdownMenu.Trigger asChild>
            <Button variant="ghost" className="console-account" aria-label={zh ? "账号菜单" : "Account menu"}>
              <span className="console-avatar" aria-hidden="true">{(user.display_name || user.username || "U").slice(0, 1).toUpperCase()}</span>
              <span className="console-account-name">{user.display_name || user.username}</span><ChevronDown />
            </Button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="console-account-menu" align="end" sideOffset={8}>
              <DropdownMenu.Label className="console-account-identity"><strong>{user.display_name || user.username}</strong><span>{roleLabels}</span></DropdownMenu.Label>
              <DropdownMenu.Separator className="console-menu-separator" />
              <DropdownMenu.Label className="console-menu-label"><Globe size={14} />{zh ? "语言" : "Language"}</DropdownMenu.Label>
              <DropdownMenu.RadioGroup value={locale} onValueChange={value => setLocale(value as "zh-CN" | "en-US")}>
                {[{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }].map(option => <DropdownMenu.RadioItem className="console-menu-item" key={option.value} value={option.value}>
                  <span>{option.label}</span><DropdownMenu.ItemIndicator><Check size={15} /></DropdownMenu.ItemIndicator>
                </DropdownMenu.RadioItem>)}
              </DropdownMenu.RadioGroup>
              <DropdownMenu.Separator className="console-menu-separator" />
              <DropdownMenu.Item className="console-menu-item" asChild><a href="/docs" target="_blank" rel="noreferrer"><BookOpen size={16} /><span>OpenAPI</span></a></DropdownMenu.Item>
              {user.auth_type !== "disabled" && <DropdownMenu.Item className="console-menu-item" onSelect={onLogout}><LogOut size={16} /><span>{zh ? "退出登录" : "Sign out"}</span></DropdownMenu.Item>}
              <DropdownMenu.Separator className="console-menu-separator" />
              <div className="console-account-version"><span>{zh ? "版本" : "Version"}</span><code>{version}</code></div>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </header>
    <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
      <SheetContent side="left" className="console-mobile-sheet" showCloseButton={false} aria-describedby={undefined}>
        <SheetHeader><SheetTitle>Lingshu Gate</SheetTitle><SheetClose asChild><Button className="console-icon-button" variant="ghost" aria-label={zh ? "关闭导航" : "Close navigation"}><X /></Button></SheetClose></SheetHeader>
        {navigation(true)}
      </SheetContent>
    </Sheet>
    <main id="console-content" className="console-main" tabIndex={-1}>
      <div className={`console-content${view === "servers" ? " console-content-services" : ""}`}>{children}</div>
    </main>
  </div>
}

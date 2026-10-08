import { useEffect, useRef, useState, type ReactNode } from "react"
import {
  ApiOutlined, DownOutlined, GlobalOutlined, LogoutOutlined, MenuOutlined, MoonOutlined,
  ReloadOutlined, SearchOutlined, SunOutlined,
} from "@ant-design/icons"
import { Avatar, Button, Drawer, Dropdown, Menu, Select, Tooltip, type MenuProps } from "antd"
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
  const [accountOpen, setAccountOpen] = useState(false)
  const accountTrigger = useRef<HTMLButtonElement>(null)
  const activeNavItem = useRef<HTMLAnchorElement>(null)
  useEffect(() => {
    setAccountOpen(false)
    activeNavItem.current?.scrollIntoView({ block: "nearest" })
    if (view !== "tools") window.scrollTo(0, 0)
  }, [view])
  useEffect(() => {
    if (!accountOpen) return
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return
      event.preventDefault()
      event.stopPropagation()
      setAccountOpen(false)
      accountTrigger.current?.focus()
    }
    document.addEventListener("keydown", closeOnEscape, true)
    return () => document.removeEventListener("keydown", closeOnEscape, true)
  }, [accountOpen])
  const zh = locale === "zh-CN"
  const roleNames: Record<string, string> = zh
    ? { admin: "管理员", operator: "运维人员", viewer: "只读观察者" }
    : { admin: "Administrator", operator: "Operator", viewer: "Viewer" }
  const roles = [...new Set(user.roles.filter(Boolean))]
  if (!roles.length && user.role) roles.push(user.role)
  const roleLabels = roles.map(role => Object.hasOwn(roleNames, role) ? roleNames[role] : role).join(", ")
  const languageOptions = [{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]
  const allowedIds = groups.flatMap(group => group.items)
  function navigate(key: string) {
    if (!allowedIds.includes(key as ConsoleView)) return
    onNavigate(key as ConsoleView)
    setMobileOpen(false)
    setAccountOpen(false)
  }
  const mobileItems: MenuProps["items"] = groups.map(group => ({
    type: "group", key: items[group.items[0]].section, label: group.title,
    children: group.items.map(id => {
      const Icon = items[id].icon
      return { key: id, label: items[id].label, icon: <Icon size={16} aria-hidden="true" /> }
    }),
  }))

  return <div className="console-shell">
    <header className="console-header">
      <Button className="console-mobile-menu" type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} aria-label={zh ? "打开导航" : "Open navigation"} />
      <a href="#/dashboard" className="console-brand" aria-label={`Lingshu Gate ${version}`}>
        <img src="/lingshu-gate-icon.svg" alt="" />
        <span className="console-brand-label">
          <strong>Lingshu Gate</strong>
          <span className="console-version" title={version}>{version}</span>
        </span>
      </a>
      <span className="console-header-divider" />
      <span className="console-context" title={title}>{title}</span>
      <div className="console-header-actions">
        <Tooltip title={zh ? "搜索 · Ctrl K" : "Search · Ctrl K"}><Button type="text" icon={<SearchOutlined />} onClick={onSearch} aria-label={zh ? "搜索" : "Search"} /></Tooltip>
        <Tooltip title={zh ? "刷新当前页面" : "Refresh current page"}><Button type="text" icon={<ReloadOutlined />} loading={busy} onClick={onRefresh} aria-label={zh ? "刷新当前页面" : "Refresh current page"} /></Tooltip>
        <Select className="console-language" size="small" value={locale} onChange={setLocale} prefix={<GlobalOutlined />} variant="borderless" aria-label={zh ? "语言" : "Language"} options={languageOptions} />
        <Tooltip title={theme === "dark" ? (zh ? "切换浅色" : "Light theme") : (zh ? "切换深色" : "Dark theme")}>
          <Button type="text" icon={theme === "dark" ? <SunOutlined /> : <MoonOutlined />} onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={zh ? "切换主题" : "Toggle theme"} />
        </Tooltip>
        <Button className="console-header-secondary" type="text" icon={<ApiOutlined />} onClick={() => window.open("/docs", "_blank", "noreferrer")}>OpenAPI</Button>
        {user.auth_type !== "disabled" && <Button className="console-header-secondary" type="text" icon={<LogoutOutlined />} onClick={onLogout}>{zh ? "退出登录" : "Sign out"}</Button>}
        <Dropdown trigger={["click"]} placement="bottomRight" autoFocus destroyOnHidden open={accountOpen} onOpenChange={setAccountOpen} classNames={{ root: "console-account-menu" }} menu={{ onClick: () => {
          setAccountOpen(false)
          accountTrigger.current?.focus()
        }, items: [
          { key: "identity", label: `${user.display_name || user.username} · ${roleLabels}`, disabled: true },
          { type: "group", key: "version", label: <div className="console-account-version"><span>{zh ? "版本" : "Version"}</span><code>{version}</code></div>, children: [] },
          { key: "api", className: "console-account-mobile-action", icon: <ApiOutlined />, label: "OpenAPI", onClick: () => window.open("/docs", "_blank", "noreferrer") },
          ...(user.auth_type !== "disabled" ? [{ key: "logout", className: "console-account-mobile-action", icon: <LogoutOutlined />, label: zh ? "退出登录" : "Sign out", onClick: onLogout }] : []),
        ] }}>
          <Button ref={accountTrigger} type="text" className="console-account" aria-label={zh ? "账号菜单" : "Account menu"} aria-haspopup="menu" aria-expanded={accountOpen}>
            <Avatar size={28}>{(user.display_name || user.username || "U").slice(0, 1).toUpperCase()}</Avatar>
            <span>{user.display_name || user.username}</span><DownOutlined />
          </Button>
        </Dropdown>
      </div>
    </header>

    <nav className="console-rail" data-console-nav="desktop" aria-label={zh ? "主导航" : "Main navigation"}>
      {groups.map(group => {
        const section = items[group.items[0]].section
        return <div className="console-nav-group" key={section}>
          <div className="console-nav-group-title">{group.title}</div>
          {group.items.map(id => {
            const Icon = items[id].icon
            return <a key={id} ref={view === id ? activeNavItem : undefined} href={consoleViewHash(id)} className="console-rail-item" data-active={view === id} aria-current={view === id ? "page" : undefined} title={items[id].label} onClick={event => {
              if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
              event.preventDefault()
              navigate(id)
            }}><Icon size={17} aria-hidden="true" /><span>{items[id].label}</span></a>
          })}
        </div>
      })}
    </nav>
    <Drawer title="Lingshu Gate" placement="left" size={280} open={mobileOpen} onClose={() => setMobileOpen(false)} styles={{ body: { padding: 12 } }} footer={<Select style={{ width: "100%" }} value={locale} onChange={setLocale} prefix={<GlobalOutlined />} aria-label={zh ? "语言" : "Language"} options={languageOptions} />}>
      <Menu items={mobileItems} selectedKeys={[view]} mode="inline" onClick={({ key }) => navigate(key)} />
    </Drawer>
    <main className="console-main">
      <div className={`console-content${view === "servers" ? " console-content-services" : ""}`}>{children}</div>
    </main>
  </div>
}

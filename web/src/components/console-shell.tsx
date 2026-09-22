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
  const activeNavItem = useRef<HTMLAnchorElement>(null)
  useEffect(() => { activeNavItem.current?.scrollIntoView({ block: "nearest" }) }, [view])
  const zh = locale === "zh-CN"
  const languageOptions = [{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]
  const allowedIds = groups.flatMap(group => group.items)
  function navigate(key: string) {
    if (!allowedIds.includes(key as ConsoleView)) return
    onNavigate(key as ConsoleView)
    setMobileOpen(false)
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
      <a href="#/dashboard" className="console-brand" aria-label="Lingshu Gate">
        <img src="/console/lingshu-gate-icon.svg" alt="" />
        <strong>Lingshu Gate</strong>
      </a>
      <span className="console-header-divider" />
      <span className="console-context" title={title}>{title}</span>
      <div className="console-header-actions">
        <Tooltip title={zh ? "搜索 · Ctrl K" : "Search · Ctrl K"}><Button type="text" icon={<SearchOutlined />} onClick={onSearch} aria-label={zh ? "搜索" : "Search"} /></Tooltip>
        <Tooltip title={zh ? "刷新当前数据" : "Refresh data"}><Button type="text" icon={<ReloadOutlined />} loading={busy} onClick={onRefresh} aria-label={zh ? "刷新" : "Refresh"} /></Tooltip>
        <Select className="console-language" size="small" value={locale} onChange={setLocale} prefix={<GlobalOutlined />} variant="borderless" aria-label={zh ? "语言" : "Language"} options={languageOptions} />
        <Tooltip title={theme === "dark" ? (zh ? "切换浅色" : "Light theme") : (zh ? "切换深色" : "Dark theme")}>
          <Button type="text" icon={theme === "dark" ? <SunOutlined /> : <MoonOutlined />} onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={zh ? "切换主题" : "Toggle theme"} />
        </Tooltip>
        <Dropdown trigger={["click"]} menu={{ items: [
          { key: "identity", label: `${user.display_name || user.username} · ${user.roles.join(", ") || user.role}`, disabled: true },
          { key: "docs", label: "OpenAPI", icon: <ApiOutlined /> },
          ...(user.auth_type === "disabled" ? [] : [{ key: "logout", label: zh ? "退出登录" : "Sign out", icon: <LogoutOutlined /> }]),
        ], onClick: ({ key }) => { if (key === "logout") onLogout(); if (key === "docs") window.open("/docs", "_blank", "noreferrer") } }}>
          <Button type="text" className="console-account" aria-label={zh ? "账号菜单" : "Account menu"}>
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
      <span className="console-rail-version">{version}</span>
    </nav>
    <Drawer title="Lingshu Gate" placement="left" size={280} open={mobileOpen} onClose={() => setMobileOpen(false)} styles={{ body: { padding: 12 } }} footer={<Select style={{ width: "100%" }} value={locale} onChange={setLocale} prefix={<GlobalOutlined />} aria-label={zh ? "语言" : "Language"} options={languageOptions} />}>
      <Menu items={mobileItems} selectedKeys={[view]} mode="inline" onClick={({ key }) => navigate(key)} />
    </Drawer>
    <main className="console-main">
      <div className={`console-content${view === "servers" ? " console-content-services" : ""}`}>{children}</div>
    </main>
  </div>
}

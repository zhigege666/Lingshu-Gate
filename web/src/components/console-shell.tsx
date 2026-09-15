import { useState, type ReactNode } from "react"
import {
  ApiOutlined, AppstoreOutlined, CloudServerOutlined, DashboardOutlined, DownOutlined,
  GlobalOutlined, LogoutOutlined, MenuOutlined, MonitorOutlined, MoonOutlined,
  ReloadOutlined, SearchOutlined, SecurityScanOutlined, SunOutlined, ToolOutlined,
} from "@ant-design/icons"
import { Avatar, Button, Drawer, Dropdown, Menu, Select, Tooltip, type MenuProps } from "antd"
import type { AuthUser } from "@/components/auth-gate"
import { useConsoleDesign } from "@/components/console-design-provider"
import type { ConsoleNavItem } from "@/routing/use-console-navigation"
import type { ConsoleView } from "@/routing/console-routes"

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
  const zh = locale === "zh-CN"
  const languageOptions = [{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]
  const groupIcons: Record<string, ReactNode> = {
    overview: <DashboardOutlined />, manage: <CloudServerOutlined />, tools: <ToolOutlined />,
    ops: <MonitorOutlined />, access: <SecurityScanOutlined />,
  }
  const shortNames: Record<string, string> = {
    overview: zh ? "概览" : "Home", manage: zh ? "管理" : "Manage", tools: zh ? "工具" : "Tools",
    ops: zh ? "观测" : "Observe", access: zh ? "访问" : "Access",
  }
  const allowedIds = groups.flatMap(group => group.items)
  function navigate(key: string) {
    if (!allowedIds.includes(key as ConsoleView)) return
    onNavigate(key as ConsoleView)
    setMobileOpen(false)
  }
  const mobileItems: MenuProps["items"] = groups.map(group => ({
    type: "group", key: group.title, label: group.title,
    children: group.items.map(id => ({ key: id, label: items[id].label, icon: groupIcons[items[id].section] })),
  }))

  return <div className="console-shell">
    <header className="console-header">
      <Button className="console-mobile-menu" type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} aria-label={zh ? "打开导航" : "Open navigation"} />
      <a href="#/dashboard" className="console-brand" aria-label="Lingshu Gate">
        <img src="/console/lingshu-gate-icon.svg" alt="" />
        <strong>Lingshu Gate</strong>
      </a>
      <span className="console-header-divider" />
      <span className="console-context">{title}</span>
      <span className="console-header-caption">{zh ? "MCP 服务管理与工具访问治理" : "MCP services and tool access"}</span>
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
      {allowedIds.includes("servers") && <Tooltip title={zh ? "MCP 服务工作区" : "MCP service workspace"} placement="right">
        <button className="console-rail-item console-rail-primary" data-active={view === "servers"} aria-current={view === "servers" ? "page" : undefined} onClick={() => onNavigate("servers")}><CloudServerOutlined /><span>MCP</span></button>
      </Tooltip>}
      {groups.map(group => {
        const section = items[group.items[0]].section
        const active = group.items.includes(view) && view !== "servers"
        const button = <button className="console-rail-item" data-active={active} aria-label={group.title} aria-current={active ? "page" : undefined} onClick={group.items.length === 1 ? () => onNavigate(group.items[0]) : undefined}>{groupIcons[section] || <AppstoreOutlined />}<span>{shortNames[section] || group.title}</span></button>
        return group.items.length === 1 ? <Tooltip key={section} title={group.title} placement="right">{button}</Tooltip> : <Dropdown key={section} trigger={["click"]} placement="rightTop" menu={{ selectedKeys: [view], items: group.items.map(id => ({ key: id, label: items[id].label })), onClick: ({ key }) => navigate(key) }}>{button}</Dropdown>
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

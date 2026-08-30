import { lazy, Suspense, useEffect, useMemo, useState } from "react"
import {
  Activity,
  Braces,
  CircleUserRound,
  LogOut,
  Menu,
  RefreshCcw,
  Search,
  Shield,
} from "lucide-react"
import {
  api,
  type DiagnosticsResponse,
  type HealthResponse,
  type McpConfig,
  type McpServer,
  type ToolDefinition,
} from "@/api/client"
import { LanguageSwitcher } from "@/components/language-switcher"
import { useAuth } from "@/components/auth-gate"
import { RouteErrorBoundary, RouteLoadingFallback } from "@/components/route-boundary"
import { ThemeToggle } from "@/components/theme-toggle"
import { useConfirm } from "@/components/confirm-dialog"
import { HighlightText } from "@/components/highlight-text"
import { Button } from "@/components/ui/button"
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { getInitialLocale, saveLocale, translate, type Locale, type MessageKey, type TFunction } from "@/i18n"
import { cn, prettyJson } from "@/lib/utils"
import { useConsoleNavigation } from "@/routing/use-console-navigation"
import { useConsoleRoute } from "@/routing/use-console-route"
import { applyTheme, getInitialTheme, type ThemeMode } from "@/theme"

const CONSOLE_VERSION = `v${__LINGSHU_GATE_VERSION__}`

const AccessGrantsPage = lazy(() => import("@/pages/access-grants-page").then((module) => ({ default: module.AccessGrantsPage })))
const AccessRolesPage = lazy(() => import("@/pages/access-roles-page").then((module) => ({ default: module.AccessRolesPage })))
const AccessUsersPage = lazy(() => import("@/pages/access-users-page").then((module) => ({ default: module.AccessUsersPage })))
const BuildsPage = lazy(() => import("@/pages/builds-page").then((module) => ({ default: module.BuildsPage })))
const ConfigsPage = lazy(() => import("@/pages/configs-page").then((module) => ({ default: module.ConfigsPage })))
const CredentialsPage = lazy(() => import("@/pages/credentials-page").then((module) => ({ default: module.CredentialsPage })))
const DashboardPage = lazy(() => import("@/pages/dashboard-page").then((module) => ({ default: module.DashboardPage })))
const DiagnosticsPage = lazy(() => import("@/pages/diagnostics-page").then((module) => ({ default: module.DiagnosticsPage })))
const DownstreamCredentialsPage = lazy(() => import("@/pages/downstream-credentials-page").then((module) => ({ default: module.DownstreamCredentialsPage })))
const InvokePage = lazy(() => import("@/pages/invoke-page").then((module) => ({ default: module.InvokePage })))
const InvocationAuditPage = lazy(() => import("@/pages/invocation-audit-page").then((module) => ({ default: module.InvocationAuditPage })))
const LogsEventsPage = lazy(() => import("@/pages/logs-events-page").then((module) => ({ default: module.LogsEventsPage })))
const PersonalTokensPage = lazy(() => import("@/pages/personal-tokens-page").then((module) => ({ default: module.PersonalTokensPage })))
const RuntimeCachePage = lazy(() => import("@/pages/runtime-cache-page").then((module) => ({ default: module.RuntimeCachePage })))
const ServersPage = lazy(() => import("@/pages/servers-page").then((module) => ({ default: module.ServersPage })))
const ToolsPage = lazy(() => import("@/pages/tools-page").then((module) => ({ default: module.ToolsPage })))
const ToolClassificationsPage = lazy(() => import("@/pages/tool-classifications-page").then((module) => ({ default: module.ToolClassificationsPage })))
const UploadsPage = lazy(() => import("@/pages/uploads-page").then((module) => ({ default: module.UploadsPage })))

const genericTemplate = {
  id: "mcp-server",
  name: "MCP Server",
  enabled: false,
  launch: { type: "external" },
  transport: { type: "streamable_http", endpoint: "" },
  timeout_seconds: 120,
  permissions: { default: "read" },
  auto_start: false,
}

export default function App() {
  const { user, logout } = useAuth()
  const { view, routeBuildId, recentViews, navigate } = useConsoleRoute()
  const [locale, setLocale] = useState<Locale>(getInitialLocale())
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme())
  const t: TFunction = (key: MessageKey) => translate(locale, key)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null)
  const [servers, setServers] = useState<McpServer[]>([])
  const [loadErrors, setLoadErrors] = useState<string[]>([])
  const [tools, setTools] = useState<ToolDefinition[]>([])
  const [configs, setConfigs] = useState<McpConfig[]>([])
  const [configErrors, setConfigErrors] = useState<string[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState("")
  const [configText, setConfigText] = useState(prettyJson(genericTemplate))
  const [selectedToolId, setSelectedToolId] = useState("")
  const [invokeArgs, setInvokeArgs] = useState("{}")
  const [invokeResult, setInvokeResult] = useState(t("waiting"))
  const [serverToolOutput, setServerToolOutput] = useState(t("serverToolsHint"))
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [commandQuery, setCommandQuery] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)

  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null
  function dismissToast() { setError(null); setMessage(null) }

  const selectedTool = useMemo(() => tools.find((tool) => tool.id === selectedToolId), [tools, selectedToolId])

  useEffect(() => { applyTheme(theme) }, [theme])
  useEffect(() => { void refreshAll() }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        setCommandOpen((open) => !open)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
  useEffect(() => { if (!commandOpen) setCommandQuery("") }, [commandOpen])
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('nav[data-console-nav="desktop"] button[data-active="true"]')
        ?.closest<HTMLElement>("[data-nav-group]")
        ?.scrollIntoView({ block: "nearest" })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [view])

  function changeLocale(next: Locale) { setLocale(next); saveLocale(next) }

  async function refreshAll() {
    setBusy(true); setError(null)
    try {
      const refreshErrors: string[] = []
      const recordRefreshError = (label: string, reason: unknown) => {
        const detail = reason instanceof Error ? reason.message : String(reason)
        refreshErrors.push(`${label}: ${detail}`)
      }
      const requests: Promise<void>[] = [
        api.health()
          .then(setHealth)
          .catch((reason: unknown) => recordRefreshError("health", reason)),
      ]

      if (can("operations.manage")) {
        requests.push(Promise.allSettled([
          api.diagnostics(),
          api.servers(),
          api.configs(),
        ]).then(([diagnosticsResult, serverResult, configResult]) => {
          if (diagnosticsResult.status === "fulfilled") setDiagnostics(diagnosticsResult.value)
          else recordRefreshError("diagnostics", diagnosticsResult.reason)

          if (serverResult.status === "fulfilled") {
            setServers(serverResult.value.servers)
            setLoadErrors(serverResult.value.load_errors)
          } else recordRefreshError("servers", serverResult.reason)

          if (configResult.status === "fulfilled") {
            setConfigs(configResult.value.configs)
            setConfigErrors(configResult.value.errors)
          } else recordRefreshError("configs", configResult.reason)

        }))
      } else {
        // 账号权限发生变化时同步清空管理域数据，避免沿用上一身份的前端缓存。
        setDiagnostics(null); setServers([]); setLoadErrors([]); setConfigs([]); setConfigErrors([])
      }

      if (can("tools.read")) {
        requests.push(api.tools()
          .then((toolData) => {
            setTools(toolData)
            if (!selectedToolId && toolData[0]) setSelectedToolId(toolData[0].id)
          })
          .catch((reason: unknown) => recordRefreshError("tools", reason)))
      } else {
        setTools([])
        setSelectedToolId("")
      }

      await Promise.all(requests)
      if (refreshErrors.length > 0) setError(refreshErrors.join("; "))
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  function editConfig(config: McpConfig) { setSelectedConfigId(config.id); setConfigText(prettyJson(config.manifest)); navigate("configs") }
  function newConfig() { setSelectedConfigId(""); setConfigText(prettyJson(genericTemplate)); navigate("configs") }

  async function saveConfig(nextValue?: string) {
    const manifestText = nextValue || configText
    setBusy(true); setError(null)
    try {
      if (nextValue) setConfigText(nextValue)
      const parsed = JSON.parse(manifestText) as Record<string, unknown>
      const rawCredentialValues = parsed.user_credential_values
      const userCredentialValues: Record<string, string> = {}
      if (rawCredentialValues !== undefined) {
        if (!rawCredentialValues || typeof rawCredentialValues !== "object" || Array.isArray(rawCredentialValues)) {
          throw new Error("user_credential_values 必须是 slot id 到秘密字符串的对象")
        }
        for (const [slotId, value] of Object.entries(rawCredentialValues)) {
          if (typeof value !== "string") throw new Error(`user_credential_values.${slotId} 必须是字符串`)
          userCredentialValues[slotId] = value
        }
      }
      const manifest = { ...parsed }
      delete manifest.user_credential_values
      // 一次性秘密不得继续留在编辑器状态或后续 Manifest 查询中。
      setConfigText(prettyJson(manifest))
      const response = selectedConfigId
        ? await api.updateConfig(selectedConfigId, manifest, false, false, userCredentialValues)
        : await api.createConfig(manifest, false, false, userCredentialValues)
      setMessage(`${response.message}: ${response.config?.id || manifest.id}`)
      setSelectedConfigId(String(response.config?.id || manifest.id || ""))
      await refreshAll()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function deleteConfig(id: string) { if (!(await confirm({ title: t("confirmDeleteConfig"), description: id, destructive: true }))) return; setBusy(true); try { await api.deleteConfig(id); if (selectedConfigId === id) setSelectedConfigId(""); setMessage(`${t("deleted")}: ${id}`); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function reloadConfigs() { setBusy(true); try { await api.reloadConfigs(); setMessage("configs reloaded"); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function applyConfig(id: string) { setBusy(true); try { await api.applyConfig(id); setMessage(`applied: ${id}`); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function serverAction(id: string, action: "start" | "stop" | "restart") { setBusy(true); try { await api.serverAction(id, action); setMessage(`${action}: ${id}`); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function showServerTools(id: string) { try { setServerToolOutput(prettyJson(await api.serverTools(id))) } catch (err) { setServerToolOutput(err instanceof Error ? err.message : String(err)) } }
  async function runDiagnostics() { setBusy(true); try { setDiagnostics(await api.runDiagnostics()); setMessage("diagnostics completed") } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function invokeTool() { if (!selectedToolId) return; try { const args = JSON.parse(invokeArgs) as Record<string, unknown>; setInvokeResult("..."); setInvokeResult(prettyJson(await api.invoke(selectedToolId, args))) } catch (err) { setInvokeResult(err instanceof Error ? err.message : String(err)) } }

  const can = (permission: string) => user.auth_type === "disabled" || user.role === "admin" || user.roles.includes("admin") || user.permissions.includes(permission) || user.permissions.includes("*")
  const { nav, navById, navGroups, canAccessView } = useConsoleNavigation({
    locale,
    t,
    can,
    authenticated: user.auth_type !== "disabled",
  })
  const currentNavItem = nav.find((item) => item.id === view)
  const currentTitle = currentNavItem?.label || "Lingshu Gate"
  const viewAllowed = canAccessView(currentNavItem)
  const allowedRecentViews = recentViews.filter((id) => id !== view && canAccessView(navById[id]))

  const renderNav = (onSelect?: () => void) => navGroups.map((group) => (
    <div key={group.title} data-nav-group className="mb-5 last:mb-0">
      <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-sidebar-muted">{group.title}</div>
      <div className="flex flex-col gap-0.5">
        {group.items.map((id) => {
          const item = navById[id]
          const active = view === id
          return (
            <button key={id} data-active={active} onClick={() => { navigate(id); onSelect?.() }} className={cn("group relative flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm transition-colors", active ? "bg-sidebar-accent font-medium text-white shadow-sm shadow-black/20" : "text-sidebar-foreground/80 hover:bg-white/10 hover:text-white")}>
              <item.icon className="size-4" />{item.label}
            </button>
          )
        })}
      </div>
    </div>
  ))

  return (
    <div className="min-h-screen text-foreground">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[244px] flex-col bg-sidebar text-sidebar-foreground shadow-[4px_0_18px_rgba(15,23,42,0.16)] lg:flex">
        <div className="flex h-[72px] shrink-0 items-center gap-3 border-b border-white/10 px-5">
          <div className="flex size-9 items-center justify-center rounded-xl border border-white/15 bg-white shadow-md shadow-black/20"><img src="/console/lingshu-gate-icon.svg" alt="Lingshu Gate" className="size-6" /></div>
          <div><div className="text-sm font-semibold leading-tight text-white">Lingshu Gate</div><div className="text-xs text-sidebar-muted">Console {CONSOLE_VERSION}</div></div>
        </div>
        <nav data-console-nav="desktop" className="flex-1 overflow-y-auto px-3 py-4">
          {renderNav()}
        </nav>
      </aside>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-72 gap-0 border-r-0 bg-sidebar p-0 text-sidebar-foreground [&_[data-slot=sheet-close]]:text-white">
          <SheetHeader className="h-[72px] shrink-0 flex-row items-center gap-3 border-b border-white/10 px-5 py-0">
            <div className="flex size-9 items-center justify-center rounded-xl border border-white/15 bg-white shadow-md shadow-black/20"><img src="/console/lingshu-gate-icon.svg" alt="Lingshu Gate" className="size-6" /></div>
            <div><SheetTitle className="text-sm leading-tight text-white">Lingshu Gate</SheetTitle><div className="text-xs text-sidebar-muted">Console {CONSOLE_VERSION}</div></div>
          </SheetHeader>
          <nav data-console-nav="mobile" className="flex-1 overflow-y-auto bg-sidebar px-3 py-4">{renderNav(() => setMobileNavOpen(false))}</nav>
          <div className="flex items-center gap-2 border-t border-white/10 bg-sidebar p-3 text-sidebar-foreground">
            <CircleUserRound className="size-4 text-primary" />
            <div className="min-w-0 flex-1"><div className="truncate text-xs font-medium">{user.display_name || user.username}</div><div className="truncate text-[10px] text-sidebar-muted">{user.roles.join(", ") || user.role}</div></div>
            {user.auth_type !== "disabled" && <Button variant="ghost" size="sm" className="size-8 px-0" onClick={() => void logout()} aria-label={locale === "zh-CN" ? "退出登录" : "Sign out"}><LogOut /></Button>}
          </div>
        </SheetContent>
      </Sheet>

      <main className="lg:pl-[244px]">
        <header className="sticky top-0 z-10 border-b bg-card/90 px-6 py-4 backdrop-blur-xl lg:h-[72px] lg:px-8 lg:py-0">
          <div className="flex items-center gap-3 lg:h-full">
            <Button variant="outline" size="sm" className="lg:hidden" onClick={() => setMobileNavOpen(true)} aria-label="Menu"><Menu /></Button>
            <div className="min-w-0 flex-1 lg:hidden"><h1 className="truncate text-lg font-semibold tracking-tight sm:text-xl">{currentTitle}</h1></div>
            <div className="hidden flex-1 lg:block" />
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button variant="outline" size="sm" className="gap-2 text-muted-foreground" onClick={() => setCommandOpen(true)}><Search />
                <span className="hidden md:inline">{t("search")}</span>
                <kbd className="hidden rounded border bg-muted px-1.5 font-mono text-[10px] md:inline">Ctrl K</kbd>
              </Button>
              <LanguageSwitcher locale={locale} onChange={changeLocale} />
              <ThemeToggle theme={theme} onChange={setTheme} />
              <Button variant="secondary" onClick={refreshAll} disabled={busy}><RefreshCcw />{t("refresh")}</Button>
              <Button variant="outline" className="hidden xl:inline-flex" asChild><a href="/docs" target="_blank" rel="noreferrer">{t("openApi")}</a></Button>
              <div className="hidden items-center gap-2 rounded-lg border bg-background/80 px-2.5 py-1.5 lg:flex">
                <CircleUserRound className="size-4 text-primary" />
                <div className="max-w-28"><div className="truncate text-xs font-medium">{user.display_name || user.username}</div><div className="truncate text-[10px] text-muted-foreground">{user.roles.join(", ") || user.role}</div></div>
                {user.auth_type !== "disabled" && <Button variant="ghost" size="sm" className="size-7 px-0" onClick={() => void logout()} aria-label={locale === "zh-CN" ? "退出登录" : "Sign out"}><LogOut /></Button>}
              </div>
            </div>
          </div>
        </header>
        <div className="flex flex-col gap-4 p-6 lg:p-8">
          {!viewAllowed && (
            <div className="rounded-xl border border-dashed bg-card p-8 text-center">
              <Shield className="mx-auto mb-3 size-8 text-muted-foreground" />
              <div className="font-medium">{locale === "zh-CN" ? "当前账号无权访问此页面" : "Your account cannot access this page"}</div>
              <div className="mt-1 text-sm text-muted-foreground">{locale === "zh-CN" ? "请联系管理员分配对应控制面权限。" : "Ask an administrator to assign the required control-plane permission."}</div>
              <Button variant="secondary" className="mt-4" onClick={() => navigate("dashboard")}>{locale === "zh-CN" ? "返回概览" : "Back to overview"}</Button>
            </div>
          )}
          {viewAllowed && (
            <RouteErrorBoundary key={view} locale={locale}>
              <Suspense fallback={<RouteLoadingFallback locale={locale} />}>
                {view === "dashboard" && <DashboardPage health={health} servers={servers} tools={tools} operationsAllowed={can("operations.manage")} t={t} />}
                {view === "configs" && <ConfigsPage locale={locale} t={t} configs={configs} configErrors={configErrors} selectedConfigId={selectedConfigId} configText={configText} busy={busy} onNewConfig={newConfig} onReloadConfigs={reloadConfigs} onEditConfig={editConfig} onApplyConfig={applyConfig} onDeleteConfig={deleteConfig} onConfigTextChange={setConfigText} onSaveConfig={saveConfig} />}
                {view === "servers" && <ServersPage t={t} servers={servers} loadErrors={loadErrors} serverToolOutput={serverToolOutput} onServerAction={serverAction} onShowServerTools={showServerTools} />}
                {view === "builds" && <BuildsPage t={t} initialBuildId={routeBuildId} />}
                {view === "credentials" && <CredentialsPage t={t} />}
                {view === "accessUsers" && <AccessUsersPage locale={locale} t={t} />}
                {view === "accessRoles" && <AccessRolesPage locale={locale} t={t} />}
                {view === "accessGrants" && <AccessGrantsPage locale={locale} t={t} />}
                {view === "toolClassifications" && <ToolClassificationsPage locale={locale} t={t} />}
                {view === "personalTokens" && <PersonalTokensPage locale={locale} t={t} />}
                {view === "downstreamCredentials" && <DownstreamCredentialsPage locale={locale} t={t} />}
                {view === "invocationAudit" && <InvocationAuditPage locale={locale} t={t} />}
                {view === "logs" && <LogsEventsPage t={t} />}
                {view === "runtimeCache" && <RuntimeCachePage t={t} />}
                {view === "uploads" && <UploadsPage t={t} />}
                {view === "diagnostics" && <DiagnosticsPage diagnostics={diagnostics} t={t} onRunDiagnostics={runDiagnostics} />}
                {view === "tools" && <ToolsPage tools={tools} t={t} />}
                {view === "invoke" && <InvokePage t={t} tools={tools} selectedTool={selectedTool} selectedToolId={selectedToolId} invokeArgs={invokeArgs} invokeResult={invokeResult} onToolChange={setSelectedToolId} onArgsChange={setInvokeArgs} onInvoke={invokeTool} />}
              </Suspense>
            </RouteErrorBoundary>
          )}
        </div>
      </main>

      <CommandDialog open={commandOpen} onOpenChange={setCommandOpen} title={t("search")} description={t("subtitle")}>
        <CommandInput placeholder={t("search")} value={commandQuery} onValueChange={setCommandQuery} />
        <CommandList>
          <CommandEmpty>{t("noData")}</CommandEmpty>
          {!commandQuery && allowedRecentViews.length > 0 && (
            <CommandGroup heading={t("recent")}>
              {allowedRecentViews.map((id) => {
                const item = navById[id]
                return (
                  <CommandItem key={`recent-${id}`} value={`recent ${item.label} ${id}`} onSelect={() => { navigate(id); setCommandOpen(false) }}>
                    <item.icon className="size-4" />{item.label}
                  </CommandItem>
                )
              })}
            </CommandGroup>
          )}
          <CommandGroup heading={t("actions")}>
            <CommandItem value="refresh 刷新" onSelect={() => { setCommandOpen(false); void refreshAll() }}><RefreshCcw /><HighlightText text={t("refresh")} query={commandQuery} /></CommandItem>
            {can("operations.manage") && <CommandItem value="new config 新建配置" onSelect={() => { setCommandOpen(false); newConfig() }}><Braces /><HighlightText text={t("genericTemplate")} query={commandQuery} /></CommandItem>}
            {can("operations.manage") && <CommandItem value="run diagnostics 运行诊断" onSelect={() => { setCommandOpen(false); navigate("diagnostics"); void runDiagnostics() }}><Activity /><HighlightText text={t("runDiagnostics")} query={commandQuery} /></CommandItem>}
            <CommandItem value="openapi docs" onSelect={() => { setCommandOpen(false); window.open("/docs", "_blank", "noreferrer") }}><Braces /><HighlightText text={t("openApi")} query={commandQuery} /></CommandItem>
          </CommandGroup>
          {navGroups.map((group) => (
            <CommandGroup key={group.title} heading={group.title}>
              {group.items.map((id) => {
                const item = navById[id]
                return (
                  <CommandItem key={id} value={`${item.label} ${id}`} onSelect={() => { navigate(id); setCommandOpen(false) }}>
                    <item.icon className="size-4" /><HighlightText text={item.label} query={commandQuery} />
                  </CommandItem>
                )
              })}
            </CommandGroup>
          ))}
        </CommandList>
      </CommandDialog>

      <Toaster toast={toast} onClose={dismissToast} />
      {confirmDialog}
    </div>
  )
}

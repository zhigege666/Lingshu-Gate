import { EditorNavigationContext, useEditorNavigationGuards } from "@/components/editor-navigation-guard"
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react"
import { Activity, Braces, RefreshCcw, Shield } from "lucide-react"
import {
  api,
  type DiagnosticsResponse,
  type HealthResponse,
  type McpConfig,
  type McpServer,
  type ToolDefinition,
} from "@/api/client"
import { useAuth } from "@/components/auth-gate"
import { RouteErrorBoundary, RouteLoadingFallback } from "@/components/route-boundary"
import { useConfirm } from "@/components/confirm-dialog"
import { HighlightText } from "@/components/highlight-text"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { translate, type MessageKey, type TFunction } from "@/i18n"
import { prettyJson } from "@/lib/utils"
import { ConsoleShell } from "@/components/console-shell"
import { useConsoleDesign } from "@/components/console-design-provider"
import { useConsoleNavigation } from "@/routing/use-console-navigation"
import { PageRefreshContext, type PageRefreshHandler, type RegisterPageRefresh } from "@/components/page-refresh"
import type { ToolCatalogViewState } from "@/pages/tools-page"
import { useConsoleRoute } from "@/routing/use-console-route"

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
  const { locale } = useConsoleDesign()
  const t: TFunction = (key: MessageKey) => translate(locale, key)
  const { confirm, confirmDialog } = useConfirm(t)
  const [leaveState, setLeaveState] = useState({ dirty: false, pending: false })
  const { providerValue: editorNavigation, anyDirty: editorDirty, anyPending: editorPending } = useEditorNavigationGuards()
  async function requestLeave() {
    const zh = locale === "zh-CN"
    if (editorPending) {
      await confirm({ title: zh ? "正在提交，请稍候" : "Submission in progress", description: zh ? "请等待当前操作完成，再关闭编辑窗口或离开页面。" : "Wait for the current operation to finish before closing the editor or leaving.", confirmText: zh ? "返回编辑" : "Return to editor", hideCancel: true })
      return false
    }
    if (editorDirty && !(await confirm({ title: zh ? "放弃未保存的修改并离开？" : "Discard changes and leave?", description: zh ? "离开后，当前编辑窗口中尚未保存的输入将被清除。" : "Unsaved input in the current editor will be cleared when you leave.", confirmText: zh ? "放弃修改并离开" : "Discard and leave", cancelText: zh ? "继续编辑" : "Keep editing", destructive: true }))) return false
    if ((leaveState.dirty || leaveState.pending) && !(await confirm({
      title: zh ? "离开工具调用？" : "Leave tool invocation?",
      description: leaveState.pending
        ? (zh ? "请求可能继续执行。离开后，本次参数和结果不会保留；请勿因离开而重复提交。" : "The request may continue. Parameters and results will not be retained after leaving; do not resubmit because you left.")
        : (zh ? "离开后，修改过的调用参数和结果不会保留。" : "Edited parameters and results will not be retained after leaving."),
      confirmText: zh ? "离开" : "Leave", cancelText: zh ? "继续编辑" : "Stay",
    }))) return false
    if (configEditorOpen) { setConfigEditorOpen(false); setConfigText(prettyJson(genericTemplate)) }
    return true
  }
  const { view, routeBuildId, recentViews, navigate } = useConsoleRoute(requestLeave)
  const [toolCatalogView, setToolCatalogView] = useState<ToolCatalogViewState>({ query: "", service: "all", access: "all", page: 1, pageSize: 9, scrollTop: 0 })
  const pageRefresh = useRef<PageRefreshHandler | null>(null)
  const [pageBusy, setPageBusy] = useState(false)
  const registerPageRefresh = useCallback<RegisterPageRefresh>((handler, pending) => {
    pageRefresh.current = handler
    setPageBusy(pending)
    return () => { if (pageRefresh.current === handler) { pageRefresh.current = null; setPageBusy(false) } }
  }, [])
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (leaveState.dirty || leaveState.pending || editorDirty || editorPending) { event.preventDefault(); event.returnValue = "" }
    }
    window.addEventListener("beforeunload", beforeUnload)
    return () => window.removeEventListener("beforeunload", beforeUnload)
  }, [leaveState, editorDirty, editorPending])
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null)
  const [servers, setServers] = useState<McpServer[]>([])
  const [serversLoaded, setServersLoaded] = useState(false)
  const [serversError, setServersError] = useState<string | null>(null)
  const [loadErrors, setLoadErrors] = useState<string[]>([])
  const [tools, setTools] = useState<ToolDefinition[]>([])
  const [toolsLoaded, setToolsLoaded] = useState(false)
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [configs, setConfigs] = useState<McpConfig[]>([])
  const [configErrors, setConfigErrors] = useState<string[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState("")
  const [configText, setConfigText] = useState(prettyJson(genericTemplate))
  const [configEditorOpen, setConfigEditorOpen] = useState(false)
  const [selectedToolId, setSelectedToolId] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dashboardRefreshId, setDashboardRefreshId] = useState(0)
  const [commandOpen, setCommandOpen] = useState(false)
  const [commandQuery, setCommandQuery] = useState("")
  const toast: ToastState = message ? { message, tone: "success" } : null
  function dismissToast() { setMessage(null) }

  useEffect(() => { void refreshAll() }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        // A global command must not open another modal over an active editor or confirmation.
        if (document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"], [aria-modal="true"]')) return
        setCommandOpen((open) => !open)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])
  useEffect(() => { if (!commandOpen) setCommandQuery("") }, [commandOpen])
  async function refreshAll() {
    setBusy(true); setError(null); setToolsLoaded(false); setToolsError(null)
    setServersLoaded(false)
    try {
      const refreshErrors: string[] = []
      const recordRefreshError = (label: string, reason: unknown) => {
        const detail = reason instanceof Error ? reason.message : String(reason)
        refreshErrors.push(`${label}: ${detail}`)
      }
      const requests: Promise<void>[] = [
        api.health()
          .then(data => { setHealth(data); setHealthError(null) })
          .catch((reason: unknown) => {
            setHealthError(reason instanceof Error ? reason.message : String(reason))
            recordRefreshError("health", reason)
          }),
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
            setServersLoaded(true)
            setServersError(null)
          } else {
            setServersError(serverResult.reason instanceof Error ? serverResult.reason.message : String(serverResult.reason))
            recordRefreshError("servers", serverResult.reason)
          }

          if (configResult.status === "fulfilled") {
            setConfigs(configResult.value.configs)
            setConfigErrors(configResult.value.errors)
          } else recordRefreshError("configs", configResult.reason)

        }))
      } else {
        // 账号权限发生变化时同步清空管理域数据，避免沿用上一身份的前端缓存。
        setDiagnostics(null); setServers([]); setServersLoaded(false); setServersError(null); setLoadErrors([]); setConfigs([]); setConfigErrors([])
      }

      if (can("tools.read")) {
        requests.push(api.tools()
          .then((toolData) => {
            setTools(toolData)
            setToolsLoaded(true)
            if (!selectedToolId && toolData[0]) setSelectedToolId(toolData[0].id)
          })
          .catch((reason: unknown) => {
            setToolsError(reason instanceof Error ? reason.message : String(reason))
            recordRefreshError("tools", reason)
          }))
      } else {
        setTools([])
        setSelectedToolId("")
      }

      await Promise.all(requests)
      if (refreshErrors.length > 0) setError(refreshErrors.join("; "))
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false); setDashboardRefreshId((value) => value + 1) }
  }

  async function refreshCurrentPage() {
    if (busy || pageBusy) return
    setBusy(true); setError(null)
    try {
      if (pageRefresh.current) { await pageRefresh.current(); return }
      const reads: Promise<unknown>[] = []
      if (view === "dashboard") {
        reads.push(api.health().then(data => { setHealth(data); setHealthError(null) }).catch(reason => {
          setHealthError(reason instanceof Error ? reason.message : String(reason)); throw reason
        }))
      }
      if (can("operations.manage") && ["dashboard", "servers", "invoke", "tools"].includes(view)) {
        reads.push(api.servers().then(data => { setServers(data.servers); setLoadErrors(data.load_errors); setServersLoaded(true); setServersError(null) }).catch(reason => {
          setServersError(reason instanceof Error ? reason.message : String(reason)); throw reason
        }))
      }
      if (view === "configs" && can("operations.manage")) reads.push(api.configs().then(data => { setConfigs(data.configs); setConfigErrors(data.errors) }))
      if (view === "diagnostics" && can("operations.manage")) reads.push(api.diagnostics().then(setDiagnostics))
      if (can("tools.read") && ["dashboard", "servers", "invoke", "tools"].includes(view)) {
        reads.push(api.tools().then(data => { setTools(data); setToolsLoaded(true); setToolsError(null) }).catch(reason => {
          setToolsError(reason instanceof Error ? reason.message : String(reason)); throw reason
        }))
      }
      const settled = await Promise.allSettled(reads)
      const failures = settled.filter((r): r is PromiseRejectedResult => r.status === "rejected")
      if (failures.length) throw new Error(failures.map(r => r.reason instanceof Error ? r.reason.message : String(r.reason)).join("; "))
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function editConfig(config: McpConfig) {
    if (!(await (view === "configs" ? requestLeave() : navigate("configs")))) return
    setSelectedConfigId(config.id); setConfigText(prettyJson(config.manifest)); setConfigEditorOpen(true)
  }
  async function newConfig() {
    if (!(await (view === "configs" ? requestLeave() : navigate("configs")))) return
    setSelectedConfigId(""); setConfigText(prettyJson(genericTemplate)); setConfigEditorOpen(true)
  }

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
      setConfigEditorOpen(false)
      await refreshAll()
    } catch (err) {
      // 保存失败交回编辑器显示，避免错误提示被 Modal 遮挡且草稿被关闭。
      throw err
    }
    finally { setBusy(false) }
  }

  async function deleteConfig(id: string) { if (!(await confirm({ title: t("confirmDeleteConfig"), description: id, destructive: true }))) return; setBusy(true); try { await api.deleteConfig(id); if (selectedConfigId === id) setSelectedConfigId(""); setMessage(`${t("deleted")}: ${id}`); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function reloadConfigs() { setBusy(true); try { await api.reloadConfigs(); setMessage("configs reloaded"); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function applyConfig(id: string) { setBusy(true); try { await api.applyConfig(id); setMessage(`applied: ${id}`); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function serverAction(id: string, action: "start" | "stop" | "restart") { setBusy(true); try { await api.serverAction(id, action); setMessage(`${action}: ${id}`); await refreshAll() } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }
  async function runDiagnostics() { setBusy(true); try { setDiagnostics(await api.runDiagnostics()); setMessage("diagnostics completed") } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }

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

  return (
    <EditorNavigationContext.Provider value={editorNavigation}>
    <PageRefreshContext.Provider value={registerPageRefresh}>
    <ConsoleShell
      view={view} title={currentTitle} user={user} version={CONSOLE_VERSION}
      groups={navGroups} items={navById} busy={busy || pageBusy}
      onNavigate={navigate} onSearch={() => setCommandOpen(true)}
      onRefresh={() => void refreshCurrentPage()} onLogout={async () => { if (await requestLeave()) void logout() }}
    >
      {error && <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>}
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
            {view === "dashboard" && <DashboardPage health={health} healthError={healthError} servers={servers} serversLoaded={serversLoaded} serversError={serversError} tools={tools} principalId={user.id} globalRefreshId={dashboardRefreshId} operationsAllowed={can("operations.manage")} canReadAudit={can("audit.read")} canReadTools={can("tools.read")} toolsLoaded={toolsLoaded} toolsError={toolsError} t={t} />}
            {view === "configs" && <ConfigsPage locale={locale} t={t} configs={configs} configErrors={configErrors} selectedConfigId={selectedConfigId} configText={configText} busy={busy} editorOpen={configEditorOpen} onCloseEditor={() => { if (!busy) { setConfigEditorOpen(false); setConfigText(prettyJson(genericTemplate)) } }} onNewConfig={newConfig} onReloadConfigs={reloadConfigs} onEditConfig={editConfig} onApplyConfig={applyConfig} onDeleteConfig={deleteConfig} onConfigTextChange={setConfigText} onSaveConfig={saveConfig} />}
            {view === "servers" && <ServersPage locale={locale} t={t} servers={servers} loadErrors={loadErrors} busy={busy} visibleTools={toolsLoaded ? tools : null} toolsError={toolsError} canReadTools={can("tools.read")} canManageClassifications={can("classifications.manage")} onServerAction={serverAction} onRefresh={refreshCurrentPage} onNewConfig={newConfig} onNavigate={navigate} />}
            {view === "builds" && <BuildsPage t={t} initialBuildId={routeBuildId} />}
            {view === "credentials" && <CredentialsPage locale={locale} t={t} />}
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
            {view === "diagnostics" && <DiagnosticsPage diagnostics={diagnostics} t={t} busy={busy} onRefreshDiagnostics={async () => { setDiagnostics(await api.diagnostics()) }} onRunDiagnostics={runDiagnostics} />}
            {view === "tools" && <ToolsPage tools={tools} servers={servers} loading={!toolsLoaded && !toolsError} error={toolsError} t={t} viewState={toolCatalogView} onViewStateChange={setToolCatalogView} onRefresh={() => void refreshCurrentPage()} onInvoke={(toolId) => { setSelectedToolId(toolId); navigate("invoke") }} />}
            {view === "invoke" && <InvokePage locale={locale} t={t} tools={tools} servers={servers} toolsLoaded={toolsLoaded} toolsError={toolsError} selectedToolId={selectedToolId} onToolChange={setSelectedToolId} onLeaveStateChange={setLeaveState} onRefresh={refreshCurrentPage} />}
          </Suspense>
        </RouteErrorBoundary>
      )}
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
            <CommandItem value="refresh 刷新" onSelect={() => { setCommandOpen(false); void refreshCurrentPage() }}><RefreshCcw /><HighlightText text={t("refreshCurrentPage")} query={commandQuery} /></CommandItem>
            {can("operations.manage") && <CommandItem value="new config 新建配置" onSelect={() => { setCommandOpen(false); newConfig() }}><Braces /><HighlightText text={t("genericTemplate")} query={commandQuery} /></CommandItem>}
            {can("operations.manage") && <CommandItem value="run diagnostics 运行诊断" onSelect={() => { setCommandOpen(false); void (async () => { if (await navigate("diagnostics")) await runDiagnostics() })() }}><Activity /><HighlightText text={t("runDiagnostics")} query={commandQuery} /></CommandItem>}
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
    </ConsoleShell>
    </PageRefreshContext.Provider>
    </EditorNavigationContext.Provider>
  )
}

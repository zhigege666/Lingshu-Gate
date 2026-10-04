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
import { gateVersionText } from "@/features/gate-version"
import { createMcpConfigTemplate } from "@/features/mcp-config/model"
import { configurationApplyResultError } from "@/features/servers/configuration-result"
import { RouteErrorBoundary, RouteLoadingFallback } from "@/components/route-boundary"
import { useConfirm } from "@/components/confirm-dialog"
import { HighlightText } from "@/components/highlight-text"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { translate, type MessageKey, type TFunction } from "@/i18n"
import { prettyJson } from "@/lib/utils"
import { ConsoleShell } from "@/components/console-shell"
import { useConsoleDesign } from "@/components/console-design-provider"
import { useConsoleNavigation } from "@/routing/use-console-navigation"
import { PageRefreshContext, type PageRefreshHandler, type RegisterPageRefresh } from "@/components/page-refresh"
import type { PersonalWorkspaceViewState } from "@/pages/personal-workspace-page"
import { DEFAULT_TOOL_PAGE_SIZE } from "@/features/tool-catalog"
import type { ToolCatalogViewState } from "@/pages/tools-page"
import { useConsoleRoute } from "@/routing/use-console-route"

// Load search-only dependencies on the first explicit search action.
const CommandDialog = lazy(() => import("@/components/ui/command").then(module => ({ default: module.CommandDialog })))
const CommandEmpty = lazy(() => import("@/components/ui/command").then(module => ({ default: module.CommandEmpty })))
const CommandGroup = lazy(() => import("@/components/ui/command").then(module => ({ default: module.CommandGroup })))
const CommandInput = lazy(() => import("@/components/ui/command").then(module => ({ default: module.CommandInput })))
const CommandItem = lazy(() => import("@/components/ui/command").then(module => ({ default: module.CommandItem })))
const CommandList = lazy(() => import("@/components/ui/command").then(module => ({ default: module.CommandList })))

const ConnectionInfrastructurePage = lazy(() => import("@/pages/external-connections-page").then(module => ({ default: module.ConnectionInfrastructurePage })))
const PersonalWorkspacePage = lazy(() => import("@/pages/personal-workspace-page").then(module => ({ default: module.PersonalWorkspacePage })))

const initialPersonalWorkspaceView: PersonalWorkspaceViewState = { query: "", page: 1, selectedId: "", detailPage: 1, scrollTop: 0 }

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
const SystemSettingsPage = lazy(() => import("@/pages/system-settings-page").then((module) => ({ default: module.SystemSettingsPage })))

export default function App() {
  const { user, logout, runtimeVersion } = useAuth()
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
        : (zh ? "离开将清除本页临时参数和结果；已按记录策略保存的调用记录不受影响。" : "Leaving clears this page’s temporary parameters and results. Invocation records already saved under the recording policy are unaffected."),
      confirmText: zh ? "离开" : "Leave", cancelText: zh ? "继续编辑" : "Stay",
    }))) return false
    if (configEditorOpen) { setConfigEditorOpen(false); setConfigText(prettyJson(createMcpConfigTemplate())) }
    return true
  }
  const { view, routeBuildId, routeServerId, recentViews, navigate } = useConsoleRoute(requestLeave)
  const [toolCatalogView, setToolCatalogView] = useState<ToolCatalogViewState>({ query: "", service: "all", access: "all", page: 1, pageSize: DEFAULT_TOOL_PAGE_SIZE, scrollTop: 0 })
  const [personalViews, setPersonalViews] = useState<Record<string, PersonalWorkspaceViewState>>({})
  useEffect(() => { setPersonalViews({}); setToolCatalogView({ query: "", service: "all", access: "all", page: 1, pageSize: DEFAULT_TOOL_PAGE_SIZE, scrollTop: 0 }) }, [user.id])
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
  const [selectedConfigDigest, setSelectedConfigDigest] = useState<string | undefined>()
  const [configText, setConfigText] = useState(() => prettyJson(createMcpConfigTemplate()))
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
  const can = (permission: string) => (user.auth_type === "disabled" || user.permissions.includes(permission) || user.permissions.includes("*")) && (user.auth_type !== "token" && user.auth_type !== "oauth" || user.scopes.includes(permission) || user.scopes.includes("*"))
  // Delivery pages own their tasks; entering the service route reads a new
  // runtime snapshot so a newly deployed service needs no document reload.
  const canManageOperations = can("operations.manage")
  const canManageHttpTrust = user.auth_type !== "disabled" && user.auth_type !== "oauth" && (user.roles || [user.role]).includes("admin") && canManageOperations
  const canReadTools = can("tools.read")
  useEffect(() => {
    if (view !== "diagnostics" || !canManageOperations) return
    let active = true
    api.diagnostics().then(result => { if (active) setDiagnostics(result) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : String(reason)) })
    return () => { active = false }
  }, [view, canManageOperations, user.id])
  useEffect(() => {
    if (view !== "servers" || !canManageOperations) return
    let active = true
    setServersLoaded(false)
    void api.servers().then(data => {
      if (!active) return
      setServers(data.servers); setLoadErrors(data.load_errors)
      setServersLoaded(true); setServersError(null)
    }).catch(reason => {
      if (!active) return
      const message = reason instanceof Error ? reason.message : String(reason)
      setServersError(message); setLoadErrors([message])
    })
    if (canReadTools) {
      setToolsLoaded(false)
      void api.tools().then(data => {
        if (!active) return
        setTools(data); setToolsLoaded(true); setToolsError(null)
      }).catch(reason => {
        if (active) setToolsError(reason instanceof Error ? reason.message : String(reason))
      })
    }
    return () => { active = false }
  }, [view, routeServerId, user.id, canManageOperations, canReadTools])

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
          api.servers(),
          api.configs(),
        ]).then(([serverResult, configResult]) => {
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
    setSelectedConfigId(config.id); setSelectedConfigDigest(config.digest); setConfigText(prettyJson(config.manifest)); setConfigEditorOpen(true)
  }
  async function newConfig() {
    if (!(await (view === "configs" ? requestLeave() : navigate("configs")))) return
    setSelectedConfigId(""); setSelectedConfigDigest(undefined); setConfigText(prettyJson(createMcpConfigTemplate())); setConfigEditorOpen(true)
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
        ? await api.updateConfig(selectedConfigId, manifest, false, false, userCredentialValues, selectedConfigDigest)
        : await api.createConfig(manifest, false, false, userCredentialValues)
      if (response.config?.id !== String(manifest.id || selectedConfigId)) throw new Error(locale === "zh-CN" ? "保存结果未知，请刷新配置后核对。" : "Save result unknown. Refresh the configuration to reconcile.")
      setMessage(`${locale === "zh-CN" ? "已保存，尚未应用到服务" : "Saved; not applied to the service"}: ${response.config.id}`)
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
  async function applyConfig(id: string) {
    if (busy || !(await confirm({ title: locale === "zh-CN" ? "应用配置并保持停止？" : "Apply configuration and leave stopped?", description: locale === "zh-CN" ? `${id}：此操作会停止并替换当前运行实例，不是热更新。应用后需另行启动。` : `${id}: This stops and replaces the current instance. It is not a hot update; start the service separately afterwards.`, destructive: true }))) return
    setBusy(true); setError(null)
    try {
      const result = await api.applyConfig(id)
      const outcomeError = configurationApplyResultError(result, id, locale === "zh-CN")
      if (outcomeError) throw new Error(outcomeError)
      const disabled = result.server?.enabled === false
      setMessage(`${disabled ? (locale === "zh-CN" ? "已应用，服务仍为停用" : "Applied; service remains disabled") : (locale === "zh-CN" ? "已应用，尚未启动" : "Applied; not started")}: ${id}`)
      await refreshAll()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  async function serverAction(id: string, action: "start" | "stop" | "restart") {
    if (busy) return
    setBusy(true); setError(null)
    try {
      const result = await api.serverAction(id, action)
      const expected = action === "stop" ? "stopped" : "running"
      if (result.id !== id || result.status !== expected) throw new Error(result.last_error || `${action}: ${id} — ${result.status || "unknown"}`)
      setMessage(`${action}: ${id}`)
      await refreshAll()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  async function runDiagnostics() { setBusy(true); try { setDiagnostics(await api.runDiagnostics()); setMessage("diagnostics completed") } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) } }

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
      view={view} title={currentTitle} user={user} version={gateVersionText(runtimeVersion, locale)}
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
            {(["myServers", "myConnections", "myInvocations"] as string[]).includes(view) && <PersonalWorkspacePage key={`${user.id}:${view}`} view={view as "myServers" | "myConnections" | "myInvocations"} viewState={personalViews[`${user.id}:${view}`] || initialPersonalWorkspaceView} onViewStateChange={state => setPersonalViews(previous => ({ ...previous, [`${user.id}:${view}`]: state }))} locale={locale} t={t} onNavigate={navigate} onInvoke={async toolId => { if (await navigate("invoke")) setSelectedToolId(toolId) }} />}
            {view === "connectionInfrastructure" && <ConnectionInfrastructurePage locale={locale} t={t} />}
            {view === "dashboard" && <DashboardPage health={health} healthError={healthError} servers={servers} serversLoaded={serversLoaded} serversError={serversError} tools={tools} principalId={user.id} globalRefreshId={dashboardRefreshId} operationsAllowed={can("operations.manage")} canReadAudit={can("audit.read")} canReadTools={can("tools.read")} toolsLoaded={toolsLoaded} toolsError={toolsError} t={t} />}
            {view === "configs" && <ConfigsPage canManageHttpTrust={canManageHttpTrust} locale={locale} t={t} configs={configs} configErrors={configErrors} selectedConfigId={selectedConfigId} configText={configText} busy={busy} editorOpen={configEditorOpen} onCloseEditor={() => { if (!busy) { setConfigEditorOpen(false); setConfigText(prettyJson(createMcpConfigTemplate())) } }} onNewConfig={newConfig} onReloadConfigs={reloadConfigs} onEditConfig={editConfig} onApplyConfig={applyConfig} onDeleteConfig={deleteConfig} onConfigTextChange={setConfigText} onSaveConfig={saveConfig} />}
            {view === "servers" && <ServersPage canManageHttpTrust={canManageHttpTrust} initialServerId={routeServerId} locale={locale} t={t} servers={servers} loadErrors={loadErrors} busy={busy} visibleTools={toolsLoaded ? tools : null} toolsError={toolsError} canReadTools={can("tools.read")} canManageClassifications={can("classifications.manage")} onServerAction={serverAction} onRefresh={refreshCurrentPage} onNewConfig={newConfig} onNavigate={navigate} onInvoke={async toolId => { if (await navigate("invoke")) setSelectedToolId(toolId) }} />}
            {view === "builds" && <BuildsPage t={t} initialBuildId={routeBuildId} />}
            {view === "credentials" && <CredentialsPage locale={locale} t={t} />}
            {view === "accessUsers" && <AccessUsersPage locale={locale} t={t} />}
            {view === "accessRoles" && <AccessRolesPage locale={locale} t={t} />}
            {view === "accessGrants" && <AccessGrantsPage locale={locale} t={t} />}
            {view === "toolClassifications" && <ToolClassificationsPage locale={locale} t={t} />}
            {view === "personalTokens" && <PersonalTokensPage locale={locale} t={t} />}
            {view === "downstreamCredentials" && <DownstreamCredentialsPage locale={locale} t={t} />}
            {view === "invocationAudit" && <InvocationAuditPage locale={locale} t={t} canReadPayload={can("audit.payload.read")} />}
            {view === "logs" && <LogsEventsPage t={t} canManageRetention={can("retention.manage")} />}
            {view === "runtimeCache" && <RuntimeCachePage locale={locale} t={t} />}
            {view === "uploads" && <UploadsPage t={t} />}
            {view === "systemSettings" && <SystemSettingsPage t={t} />}
            {view === "diagnostics" && <DiagnosticsPage diagnostics={diagnostics} t={t} busy={busy} onRefreshDiagnostics={async () => { setDiagnostics(await api.diagnostics()) }} onRunDiagnostics={runDiagnostics} />}
            {view === "tools" && <ToolsPage locale={locale} tools={tools} servers={servers} loading={!toolsLoaded && !toolsError} error={toolsError} t={t} viewState={toolCatalogView} onViewStateChange={setToolCatalogView} onRefresh={() => void refreshCurrentPage()} onInvoke={async toolId => { if (await navigate("invoke")) setSelectedToolId(toolId) }} />}
            {view === "invoke" && <InvokePage locale={locale} t={t} tools={tools} servers={servers} toolsLoaded={toolsLoaded} toolsError={toolsError} selectedToolId={selectedToolId} onToolChange={setSelectedToolId} onLeaveStateChange={setLeaveState} onRefresh={refreshCurrentPage} />}
          </Suspense>
        </RouteErrorBoundary>
      )}
      {commandOpen && <RouteErrorBoundary locale={locale} fallback={<Dialog open onOpenChange={setCommandOpen}><DialogContent closeLabel={t("close")} aria-describedby={undefined}><DialogHeader><DialogTitle>{t("search")}</DialogTitle></DialogHeader><p role="alert">{locale === "zh-CN" ? "搜索资源加载失败。请先关闭此窗口，保存正在编辑的内容，再刷新页面重试。" : "Search could not load. Close this window, save any edits, then refresh the page to retry."}</p></DialogContent></Dialog>}><Suspense fallback={<Dialog open onOpenChange={setCommandOpen}><DialogContent closeLabel={t("close")} aria-describedby={undefined}><DialogHeader><DialogTitle>{t("search")}</DialogTitle></DialogHeader><p role="status">{t("loadingData")}</p></DialogContent></Dialog>}>
      <CommandDialog closeLabel={t("close")} open={commandOpen} onOpenChange={setCommandOpen} title={t("search")} description={t("subtitle")}>
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
            {can("operations.manage") && <CommandItem value="run diagnostics 运行诊断" onSelect={() => { setCommandOpen(false); void (async () => { if (view === "diagnostics") await runDiagnostics(); else await navigate("diagnostics") })() }}><Activity /><HighlightText text={t("runDiagnostics")} query={commandQuery} /></CommandItem>}
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
      </Suspense></RouteErrorBoundary>}

      <Toaster toast={toast} onClose={dismissToast} />
      {confirmDialog}
    </ConsoleShell>
    </PageRefreshContext.Provider>
    </EditorNavigationContext.Provider>
  )
}

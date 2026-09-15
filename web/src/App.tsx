import { lazy, Suspense, useEffect, useMemo, useState } from "react"
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
import { Button } from "@/components/ui/button"
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { translate, type MessageKey, type TFunction } from "@/i18n"
import { prettyJson } from "@/lib/utils"
import { ConsoleShell } from "@/components/console-shell"
import { useConsoleDesign } from "@/components/console-design-provider"
import { useConsoleNavigation } from "@/routing/use-console-navigation"
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
  const { view, routeBuildId, recentViews, navigate } = useConsoleRoute()
  const { locale } = useConsoleDesign()
  const t: TFunction = (key: MessageKey) => translate(locale, key)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null)
  const [servers, setServers] = useState<McpServer[]>([])
  const [loadErrors, setLoadErrors] = useState<string[]>([])
  const [tools, setTools] = useState<ToolDefinition[]>([])
  const [toolsLoaded, setToolsLoaded] = useState(false)
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [configs, setConfigs] = useState<McpConfig[]>([])
  const [configErrors, setConfigErrors] = useState<string[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState("")
  const [configText, setConfigText] = useState(prettyJson(genericTemplate))
  const [selectedToolId, setSelectedToolId] = useState("")
  const [invokeArgs, setInvokeArgs] = useState("{}")
  const [invokeResult, setInvokeResult] = useState(t("waiting"))
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [commandQuery, setCommandQuery] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)

  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null
  function dismissToast() { setError(null); setMessage(null) }

  const selectedTool = useMemo(() => tools.find((tool) => tool.id === selectedToolId), [tools, selectedToolId])

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
  async function refreshAll() {
    setBusy(true); setError(null); setToolsLoaded(false); setToolsError(null)
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

  return (
    <ConsoleShell
      view={view} title={currentTitle} user={user} version={CONSOLE_VERSION}
      groups={navGroups} items={navById} busy={busy}
      onNavigate={navigate} onSearch={() => setCommandOpen(true)}
      onRefresh={() => void refreshAll()} onLogout={() => void logout()}
    >
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
            {view === "servers" && <ServersPage locale={locale} t={t} servers={servers} loadErrors={loadErrors} busy={busy} visibleTools={toolsLoaded ? tools : null} toolsError={toolsError} canReadTools={can("tools.read")} canManageClassifications={can("classifications.manage")} onServerAction={serverAction} onRefresh={refreshAll} onNewConfig={newConfig} onNavigate={navigate} />}
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
    </ConsoleShell>
  )
}

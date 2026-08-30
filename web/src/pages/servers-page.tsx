import { useMemo, useState, type ReactNode } from "react"
import { api, type McpServer, type McpServerDetail } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { ColGroup, SortHead, useColumnWidths } from "@/components/table-tools"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { localizeStatus, type TFunction } from "@/i18n"
import { formatBytes, formatDateTime } from "@/lib/utils"
import { codePanelClass, statusBadge, TableEmptyRow } from "@/pages/page-utils"

export function ServersPage(props: {
  t: TFunction
  servers: McpServer[]
  loadErrors: string[]
  serverToolOutput: string
  onServerAction: (id: string, action: "start" | "stop" | "restart") => void
  onShowServerTools: (id: string) => void
}) {
  const { t, servers, loadErrors, serverToolOutput, onServerAction, onShowServerTools } = props
  const [detail, setDetail] = useState<McpServerDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailBusy, setDetailBusy] = useState(false)
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("__all")
  const { widths, startResize } = useColumnWidths("lingshu-gate-cols-servers", { id: 180, status: 110, type: 150, pid: 80, tools: 80, restart: 160, lastError: 200 })
  const runningCount = servers.filter((server) => server.status === "running").length
  const failedCount = servers.filter((server) => server.status === "failed").length
  const managedCount = servers.filter((server) => server.launch_type !== "external").length
  const autoRestartCount = servers.filter((server) => Boolean(getRecord(server.restart_policy).enabled)).length
  const filteredServers = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return servers.filter((server) => {
      if (statusFilter !== "__all" && server.status !== statusFilter) return false
      if (!needle) return true
      return `${server.id} ${server.name || ""} ${server.launch_type} ${server.transport_type} ${server.last_error || ""}`.toLowerCase().includes(needle)
    })
  }, [query, servers, statusFilter])

  async function loadDetail(serverId: string) {
    setDetailBusy(true)
    setDetailError(null)
    try {
      setDetail(await api.serverDetail(serverId))
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err))
    } finally {
      setDetailBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("runtimeOperations")}
        title={t("servers")}
        description={loadErrors.length ? loadErrors.join("; ") : t("serverOverviewDesc")}
        stats={[
          { label: t("total"), value: servers.length },
          { label: t("running"), value: runningCount, tone: runningCount === servers.length && servers.length > 0 ? "success" : "default" },
          { label: t("failed"), value: failedCount, tone: failedCount ? "danger" : "success" },
          { label: t("restartPolicy"), value: `${autoRestartCount}/${managedCount}`, tone: autoRestartCount === managedCount && managedCount > 0 ? "success" : "warning" },
        ]}
      />

      <Card>
        <CardContent className="flex flex-col gap-3 pt-5">
          <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("name")} / ${t("lastError")}`} resultCount={filteredServers.length} resultLabel={t("servers")} clearLabel={t("clearSearch")}>
            <Select value={statusFilter} onValueChange={setStatusFilter}><SelectTrigger className="w-36"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{t("all")}</SelectItem>{Array.from(new Set(servers.map((server) => server.status))).map((status) => <SelectItem key={status} value={status}>{localizeStatus(t, status)}</SelectItem>)}</SelectContent></Select>
          </PageToolbar>
          <div className="overflow-x-auto rounded-lg border">
            <Table className="table-fixed">
              <ColGroup order={["id", "status", "type", "pid", "tools", "restart", "lastError", "actions"]} widths={widths} />
              <TableHeader><TableRow><SortHead label={t("id")} onResizeStart={startResize("id")} /><SortHead label={t("status")} onResizeStart={startResize("status")} /><SortHead label={t("type")} onResizeStart={startResize("type")} /><SortHead label={t("pid")} onResizeStart={startResize("pid")} /><SortHead label={t("tools")} onResizeStart={startResize("tools")} /><SortHead label={t("restartPolicy")} onResizeStart={startResize("restart")} /><SortHead label={t("lastError")} onResizeStart={startResize("lastError")} /><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {filteredServers.length === 0 ? <TableEmptyRow colSpan={8} title={t("noData")} /> : filteredServers.map((server) => {
                  const actions = server.allowed_actions || fallbackActions(server.status)
                  const external = server.launch_type === "external"
                  return <TableRow key={server.id} className="cursor-pointer" onClick={() => loadDetail(server.id)}>
                    <TableCell className="align-top"><code className="break-all">{server.id}</code><div className="text-xs text-muted-foreground">{server.name}</div></TableCell>
                    <TableCell>{statusBadge(server.status, t)}<div className="mt-1 text-xs text-muted-foreground">{t("desiredState")}: {server.desired_state === "running" ? t("keepRunning") : t("keepStopped")}</div></TableCell>
                    <TableCell><div>{server.launch_type} {server.transport_type}</div></TableCell>
                    <TableCell>{server.pid || "-"}</TableCell>
                    <TableCell>{server.tool_count}</TableCell>
                    <TableCell><RestartSummary server={server} t={t} /></TableCell>
                    <TableCell className="max-w-xs whitespace-pre-wrap text-xs text-destructive">{server.last_error || server.restore_blocked_reason || "-"}</TableCell>
                    <TableCell onClick={(event) => event.stopPropagation()}>
                      <ActionMenu label={t("actions")}>
                        <ActionMenuItem onClick={() => void loadDetail(server.id)}>{t("detail")}</ActionMenuItem>
                        {actions.includes("start") ? <ActionMenuItem onClick={() => onServerAction(server.id, "start")}>{external ? t("connect") : t("start")}</ActionMenuItem> : null}
                        {actions.includes("restart") ? <ActionMenuItem onClick={() => onServerAction(server.id, "restart")}>{server.status === "failed" ? t("retry") : t("restart")}</ActionMenuItem> : null}
                        {actions.includes("stop") ? <ActionMenuItem destructive onClick={() => onServerAction(server.id, "stop")}>{external ? t("disconnect") : t("stop")}</ActionMenuItem> : null}
                        {server.status.toLowerCase() === "running" ? <ActionMenuItem onClick={() => onShowServerTools(server.id)}>{t("viewTools")}</ActionMenuItem> : null}
                      </ActionMenu>
                    </TableCell>
                  </TableRow>
                })}
              </TableBody>
            </Table>
          </div>
          <details className="rounded-lg border bg-muted/20 p-3">
            <summary className="cursor-pointer text-sm font-medium">tools/list · {t("serverToolsHint")}</summary>
            <div className="mt-3"><JsonPanel text={serverToolOutput} maxHeight="max-h-[420px]" /></div>
          </details>
        </CardContent>
      </Card>
      {detailError && <Alert variant="destructive"><AlertDescription>{detailError}</AlertDescription></Alert>}
      <Dialog open={Boolean(detail)} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent className="max-w-6xl">
          <DialogHeader>
            <DialogTitle>{detail ? `${t("serverDetail")}: ${detail.server.id}` : ""}</DialogTitle>
            {detail?.server.manifest_path ? <DialogDescription>{detail.server.manifest_path}</DialogDescription> : null}
          </DialogHeader>
          <DialogBody>{detail ? <ServerDetailPanel t={t} detail={detail} /> : null}</DialogBody>
          {detail ? <DialogFooter><Button size="sm" variant="secondary" onClick={() => loadDetail(detail.server.id)} disabled={detailBusy}>{t("refresh")}</Button></DialogFooter> : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function fallbackActions(status: string): Array<"start" | "stop" | "restart"> {
  const normalized = status.toLowerCase()
  if (["loaded", "stopped", "failed"].includes(normalized)) return ["start"]
  if (normalized === "starting") return ["stop"]
  if (normalized === "running") return ["restart", "stop"]
  return []
}

function ServerDetailPanel({ t, detail }: { t: TFunction; detail: McpServerDetail }) {
  const launch = getRecord(detail.manifest.launch)
  const transport = getRecord(detail.manifest.transport)
  const pkg = getRecord(launch.package)
  const restartPolicy = getRecord(detail.server.restart_policy)
  const restartEnabled = Boolean(restartPolicy.enabled)
  const summary = detail.recovery_summary || {}
  const latestEvent = summary.latest_event_label || summary.latest_event_type || "-"
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
      <Card className="xl:col-span-2">
        <CardHeader><CardTitle>{t("status")}</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <Info label={t("status")} value={localizeStatus(t, detail.server.status)} badge={statusBadge(detail.server.status, t)} />
          <Info label={t("pid")} value={String(detail.server.pid || "-")} />
          <Info label={t("runtimeType")} value={`${detail.server.launch_type} / ${detail.server.transport_type}`} />
          <Info label={t("tools")} value={String(detail.server.tool_count)} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("failureHints")}</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2">
          {detail.failure_hints.map((hint) => <div key={hint.code} className="rounded-md border p-2 text-sm"><div className="mb-1 flex items-center gap-2"><Badge variant={hint.severity === "error" ? "danger" : hint.severity === "warning" ? "warning" : "outline"}>{localizeStatus(t, hint.severity)}</Badge><code className="text-xs">{hint.code}</code></div><div>{hint.message}</div></div>)}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("recoverySummary")}</CardTitle><CardDescription>{t("recoverySummaryDesc")}</CardDescription></CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <Info label={t("totalEvents")} value={String(summary.total_events ?? 0)} />
          <Info label={t("attemptsRemaining")} value={String(summary.attempts_remaining ?? 0)} />
          <Info label={t("scheduledRestarts")} value={String(summary.scheduled_restarts ?? 0)} />
          <Info label={t("autoRestarts")} value={String(summary.auto_restarts ?? 0)} />
          <Info label={t("healthFailures")} value={String(summary.health_failures ?? 0)} />
          <Info label={t("healthRecoveries")} value={String(summary.health_recoveries ?? 0)} />
          <Info label={t("skippedExitCode")} value={String(summary.skipped_exit_code_restarts ?? 0)} />
          <Info label={t("exhaustedRestarts")} value={String(summary.exhausted_restarts ?? 0)} />
          <Info label={t("activeSchedule")} value={String(Boolean(summary.active_restart_scheduled))} />
          <Info label={t("latestRecoveryEvent")} value={`${latestEvent}${summary.latest_event_at ? ` · ${formatDateTime(summary.latest_event_at)}` : ""}`} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("restartPolicy")}</CardTitle><CardDescription>{t("restartPolicyDesc")}</CardDescription></CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          {!restartEnabled ? <Alert className="md:col-span-2"><AlertDescription>{t("restartPolicyDisabledHint")}</AlertDescription></Alert> : null}
          <Info label={t("enabled")} value={restartEnabled ? t("enabled") : t("disabled")} />
          <Info label={t("restartCount")} value={String(detail.server.restart_count || 0)} />
          <Info label={t("restartAttempts")} value={restartEnabled ? `${detail.server.restart_attempts || 0} / ${String(restartPolicy.max_attempts ?? 0)}` : "-"} />
          <Info label={t("lastExitCode")} value={String(detail.server.last_exit_code ?? "-")} />
          <Info label={t("lastRestartAt")} value={formatDateTime(detail.server.last_restart_at)} />
          <Info label={t("nextRestartAt")} value={formatDateTime(detail.server.next_restart_at)} />
          <Info label={t("healthStatus")} value={restartEnabled ? localizeStatus(t, detail.server.health_status || "unknown") : "-"} />
          <Info label={t("healthFailures")} value={restartEnabled ? String(detail.server.consecutive_health_failures || 0) : "-"} />
          <Info label={t("lastHealthCheckAt")} value={restartEnabled ? formatDateTime(detail.server.last_health_check_at) : "-"} />
          <Info label={t("lastHealthOkAt")} value={restartEnabled ? formatDateTime(detail.server.last_health_ok_at) : "-"} />
          <div className="md:col-span-2"><pre className={codePanelClass("max-h-[180px]")}>{JSON.stringify(restartPolicy, null, 2)}</pre></div>
        </CardContent>
      </Card>

      <Card className="xl:col-span-2">
        <CardHeader><CardTitle>{t("recoveryEvents")}</CardTitle><CardDescription>{t("recoveryEventsDesc")}</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-4">
          <RecoveryChart detail={detail} t={t} />
          <Table><TableHeader><TableRow><TableHead>{t("time")}</TableHead><TableHead>{t("level")}</TableHead><TableHead>{t("eventType")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>{t("detail")}</TableHead></TableRow></TableHeader><TableBody>{detail.restart_history.length === 0 ? <TableEmptyRow colSpan={5} title={t("noData")} /> : detail.restart_history.slice(0, 20).map((item) => <TableRow key={item.id}><TableCell className="whitespace-nowrap text-xs">{formatDateTime(item.created_at)}</TableCell><TableCell><Badge variant={item.level === "error" ? "danger" : item.level === "warning" ? "warning" : "outline"}>{localizeStatus(t, item.level)}</Badge></TableCell><TableCell><code>{item.event_type}</code></TableCell><TableCell>{item.message}</TableCell><TableCell><pre className="max-h-28 overflow-auto text-xs">{JSON.stringify(item.payload, null, 2)}</pre></TableCell></TableRow>)}</TableBody></Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("runtimeCache")}</CardTitle></CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <Info label={t("cacheDir")} value={String(detail.runtime_cache.cache_dir || "-")} />
          <Info label={t("cacheSize")} value={formatBytes(Number(detail.runtime_cache.size_bytes || 0))} />
          <Info label={t("writable")} value={String(Boolean(detail.runtime_cache.writable))} />
          <Info label={t("parentWritable")} value={String(Boolean(detail.runtime_cache.parent_writable))} />
          <Info label={t("packageName")} value={String(detail.runtime_cache.package_name || pkg.name || "-")} />
          <Info label={t("packageVersion")} value={String(detail.runtime_cache.package_version || pkg.version || "-")} />
        </CardContent>
      </Card>

      <Card className="xl:col-span-2">
        <CardHeader><CardTitle>{t("startupTimeline")}</CardTitle></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>{t("status")}</TableHead><TableHead>{t("type")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>{t("detail")}</TableHead></TableRow></TableHeader><TableBody>{detail.timeline.length === 0 ? <TableEmptyRow colSpan={4} title={t("noData")} /> : detail.timeline.map((item, index) => <TableRow key={`${item.event_type}-${index}`}><TableCell><Badge variant={item.level === "error" ? "danger" : item.level === "warning" ? "warning" : "outline"}>{localizeStatus(t, item.level || item.source)}</Badge><div className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(item.created_at)}</div></TableCell><TableCell><code>{item.event_type}</code></TableCell><TableCell>{item.message || "-"}</TableCell><TableCell><pre className="max-h-28 overflow-auto text-xs">{JSON.stringify(item.payload, null, 2)}</pre></TableCell></TableRow>)}</TableBody></Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("manifest")}</CardTitle><CardDescription>{String(launch.command || "-")} {Array.isArray(launch.args) ? launch.args.join(" ") : ""} · {String(transport.type || "-")}</CardDescription></CardHeader>
        <CardContent><JsonPanel data={detail.manifest} maxHeight="max-h-[420px]" /></CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("recentStderr")}</CardTitle></CardHeader>
        <CardContent><JsonPanel text={detail.recent_stderr.length ? detail.recent_stderr.join("\n") : t("noData")} maxHeight="max-h-[420px]" /></CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("latestServerLogs")}</CardTitle></CardHeader>
        <CardContent><JsonPanel data={detail.logs.slice(0, 30)} maxHeight="max-h-[420px]" /></CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("latestServerEvents")}</CardTitle></CardHeader>
        <CardContent><JsonPanel data={detail.events.slice(0, 30)} maxHeight="max-h-[420px]" /></CardContent>
      </Card>
    </div>
  )
}

function RestartSummary({ server, t }: { server: McpServer; t: TFunction }) {
  if (server.launch_type === "external") return <div className="flex flex-col gap-1 text-xs"><Badge variant="outline">{t("externalRuntime")}</Badge><div className="text-muted-foreground">{t("externalRuntimeDesc")}</div></div>
  const policy = getRecord(server.restart_policy)
  const enabled = Boolean(policy.enabled)
  return <div className="flex flex-col gap-1 text-xs">
    <Badge variant={enabled ? "success" : "outline"} title={enabled ? undefined : t("restartPolicyDisabledHint")}>{enabled ? t("enabled") : t("disabled")}</Badge>
    <div>{t("restartCount")}: {server.restart_count || 0}</div>
    <div>{t("restartAttempts")}: {enabled ? `${server.restart_attempts || 0}/${String(policy.max_attempts ?? 0)}` : "-"}</div>
    <div>{t("healthStatus")}: {enabled ? localizeStatus(t, server.health_status || "unknown") : "-"}</div>
    {server.next_restart_at && <div>{t("nextRestartAt")}: {formatDateTime(server.next_restart_at)}</div>}
    {server.last_exit_code !== undefined && server.last_exit_code !== null && <div>{t("lastExitCode")}: {server.last_exit_code}</div>}
  </div>
}

function RecoveryChart({ detail, t }: { detail: McpServerDetail; t: TFunction }) {
  const data = detail.recovery_chart || []
  const max = Math.max(1, ...data.map((item) => item.count))
  if (data.length === 0) return <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">{t("noData")}</div>
  return <div className="flex flex-col gap-2">
    {data.map((item) => <div key={item.event_type} className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-3 text-xs"><code>{item.label || item.event_type}</code><span>{item.count}</span></div>
      <div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(4, (item.count / max) * 100)}%` }} /></div>
    </div>)}
  </div>
}

function Info({ label, value, badge }: { label: string; value: string; badge?: ReactNode }) {
  return <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 break-all text-sm font-medium">{badge || value}</div></div>
}

function getRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

import { useEffect, useState } from "react"
import { Activity, AlertTriangle, BarChart3, MousePointerClick, RefreshCw, ScrollText, Server, Wrench, Zap } from "lucide-react"
import { api, type HealthResponse, type InvocationStatistics, type McpServer, type ToolDefinition } from "@/api/client"
import { useConsoleDesign } from "@/components/console-design-provider"
import { PageHeader } from "@/components/page-shell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import type { Locale, TFunction } from "@/i18n"
import { Metric, statusBadge } from "@/pages/page-utils"

export function DashboardPage({ health, servers, tools, principalId, globalRefreshId, operationsAllowed, canReadAudit, canReadTools, toolsLoaded, toolsError, t }: { health: HealthResponse | null; servers: McpServer[]; tools: ToolDefinition[]; principalId: string; globalRefreshId: number; operationsAllowed: boolean; canReadAudit: boolean; canReadTools: boolean; toolsLoaded: boolean; toolsError: string | null; t: TFunction }) {
  const { locale } = useConsoleDesign()
  const [hours, setHours] = useState<24 | 168>(24)
  const [refreshId, setRefreshId] = useState(0)
  const [statistics, setStatistics] = useState<{ key: string; data: InvocationStatistics } | null>(null)
  const [statisticsLoading, setStatisticsLoading] = useState(canReadAudit)
  const [statisticsError, setStatisticsError] = useState(false)
  const statisticsKey = `${principalId}:${hours}`
  const currentStatistics = statistics?.key === statisticsKey ? statistics.data : null
  useEffect(() => {
    if (!canReadAudit) {
      setStatistics(null)
      setStatisticsLoading(false)
      setStatisticsError(false)
      return
    }
    if (globalRefreshId === 0) return
    let active = true
    setStatisticsLoading(true)
    setStatisticsError(false)
    api.invocationStatistics(hours)
      .then((result) => { if (active) setStatistics({ key: statisticsKey, data: result }) })
      .catch(() => { if (active) setStatisticsError(true) })
      .finally(() => { if (active) setStatisticsLoading(false) })
    return () => { active = false }
  }, [canReadAudit, globalRefreshId, hours, principalId, refreshId, statisticsKey])
  function selectHours(next: 24 | 168) {
    if (next === hours) return
    setStatisticsLoading(true)
    setHours(next)
  }
  function refreshStatistics() {
    setStatisticsLoading(true)
    setRefreshId((value) => value + 1)
  }
  const loading = health === null
  const runningCount = servers.filter((server) => server.status === "running").length
  const mcpToolCount = tools.filter((tool) => tool.source === "mcp").length
  const attentionServers = servers.filter((server) => ["failed", "unsupported"].includes(server.status))

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("controlPlane")}
        title={t("dashboard")}
        description={t("subtitle")}
        helpLabel={t("pageHelp")}
        actions={operationsAllowed ? <>
          <Button variant="secondary" asChild><a href="#/servers"><Server />{t("servers")}</a></Button>
          <Button variant="outline" asChild><a href="#/logs"><ScrollText />{t("logs")}</a></Button>
        </> : null}
      />

      {operationsAllowed && attentionServers.length ? <Card className="border-warning/40 bg-warning/5">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 size-5 text-warning" /><div><div className="font-medium">{attentionServers.length} {t("warning")}</div><div className="text-sm text-muted-foreground">{attentionServers.map((server) => server.name || server.id).join(" · ")}</div></div></div>
          <Button size="sm" variant="outline" asChild><a href="#/servers">{t("detail")}</a></Button>
        </CardContent>
      </Card> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {loading ? (
          <>
            <MetricSkeleton />
            <MetricSkeleton />
            {operationsAllowed && <MetricSkeleton />}
            {canReadTools && <MetricSkeleton />}
          </>
        ) : (
          <>
            <Metric title={t("status")} value={health?.status || "-"} badge={statusBadge(health?.status, t)} icon={<Activity className="size-[18px]" />} />
            {operationsAllowed && <Metric title={t("mcpServers")} value={String(servers.length)} hint={`${runningCount} ${t("running")}`} icon={<Server className="size-[18px]" />} />}
            {canReadTools && (toolsError ? <Metric title={t("tools")} value="—" hint={t("dashboardToolsUnavailable")} icon={<Wrench className="size-[18px]" />} /> : toolsLoaded ? <Metric title={t("tools")} value={String(tools.length)} hint={`${mcpToolCount} ${t("mcpTools")}`} icon={<Wrench className="size-[18px]" />} /> : <MetricSkeleton />)}
          </>
        )}
      </div>

      {canReadAudit && <section className="space-y-4" aria-labelledby="dashboard-usage-title">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="dashboard-usage-title" className="text-lg font-semibold tracking-tight">{t("dashboardUsage")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("dashboardUsageDesc")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border bg-card p-1" role="group" aria-label={t("dashboardUsage")}>
              <Button size="sm" variant={hours === 24 ? "secondary" : "ghost"} aria-pressed={hours === 24} onClick={() => selectHours(24)}>{t("dashboard24Hours")}</Button>
              <Button size="sm" variant={hours === 168 ? "secondary" : "ghost"} aria-pressed={hours === 168} onClick={() => selectHours(168)}>{t("dashboard7Days")}</Button>
            </div>
            <Button size="sm" variant="outline" aria-label={t("refresh")} onClick={refreshStatistics} disabled={statisticsLoading}><RefreshCw className="size-4" />{t("refresh")}</Button>
          </div>
        </div>

        {statisticsLoading || (!currentStatistics && !statisticsError) ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"><MetricSkeleton /><MetricSkeleton /><MetricSkeleton /><MetricSkeleton /></div> : statisticsError || !currentStatistics ? <Card><CardContent className="p-5 text-sm text-muted-foreground" role="status">{t("dashboardStatsUnavailable")}</CardContent></Card> : <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Metric title={t("dashboardToolRequests")} value={currentStatistics.totals.requests.toLocaleString(locale)} hint={t("dashboardToolRequestsHint")} icon={<MousePointerClick className="size-[18px]" />} />
            <Metric title={t("dashboardMcpCalls")} value={currentStatistics.totals.mcp_calls.toLocaleString(locale)} hint={t("dashboardMcpCallsHint")} icon={<Server className="size-[18px]" />} />
            <Metric title={t("dashboardToolCalls")} value={currentStatistics.totals.calls.toLocaleString(locale)} hint={t("dashboardToolCallsHint")} icon={<Wrench className="size-[18px]" />} />
            <Metric title={t("dashboardSuccessRate")} value={currentStatistics.totals.calls ? `${Math.round(currentStatistics.totals.success / currentStatistics.totals.calls * 100)}%` : "—"} hint={t("dashboardSuccessRateHint")} icon={<Activity className="size-[18px]" />} />
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <UsageTrend statistics={currentStatistics} locale={locale} t={t} />
            <TopTools statistics={currentStatistics} locale={locale} t={t} />
          </div>
        </>}
        <p className="text-xs text-muted-foreground">{t("dashboardStatsScope")}</p>
      </section>}

      {operationsAllowed ? <Card>
        <CardHeader>
          <CardTitle>{t("serverOverview")}</CardTitle>
          <CardDescription>{t("serverOverviewDesc")}</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : servers.length === 0 ? (
            <Empty className="border-none py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon"><Server /></EmptyMedia>
                <EmptyTitle>{t("noData")}</EmptyTitle>
                <EmptyDescription>{t("serverOverviewDesc")}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="grid gap-2 md:grid-cols-2">
              {servers.map((server) => (
                <div key={server.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{server.name || server.id}</div>
                    <div className="truncate text-xs text-muted-foreground">{server.launch_type} · {server.transport_type} · {server.tool_count} {t("tools")}</div>
                  </div>
                  {statusBadge(server.status, t)}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card> : null}
    </div>
  )
}

function MetricSkeleton() {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-3 w-20" />
        </div>
        <Skeleton className="size-9 rounded-lg" />
      </CardContent>
    </Card>
  )
}

function UsageTrend({ statistics, locale, t }: { statistics: InvocationStatistics; locale: Locale; t: TFunction }) {
  const max = Math.max(1, ...statistics.series.map((point) => point.requests))
  const hasRequests = statistics.totals.requests > 0
  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2"><BarChart3 className="size-5 text-primary" />{t("dashboardTrend")}</CardTitle>
      <CardDescription>{statistics.bucket_hours === 2 ? t("dashboardTrend24Hours") : t("dashboardTrend7Days")}</CardDescription>
    </CardHeader>
    <CardContent>
      {hasRequests ? <>
        <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{max.toLocaleString(locale)}</span><span>{t("dashboardToolRequests")}</span></div>
        <div className="mt-2 flex h-36 items-end gap-1 border-b border-border/80 pb-1" role="img" aria-label={`${t("dashboardTrend")}: ${statistics.totals.requests} ${t("dashboardToolRequests")}, ${statistics.totals.calls} ${t("dashboardToolCalls")}, ${statistics.totals.mcp_calls} ${t("dashboardMcpCalls")}`}>
          {statistics.series.map((point) => <div key={point.start} className="flex h-full min-w-0 flex-1 items-end justify-center gap-0.5" title={`${new Date(point.start).toLocaleString(locale)} · ${point.requests} ${t("dashboardToolRequests")} · ${point.calls} ${t("dashboardToolCalls")} · ${point.mcp_calls} ${t("dashboardMcpCalls")}`}>
            {point.requests > 0 && <div className="w-1.5 max-w-[30%] rounded-t-sm bg-primary/30" style={{ height: `${Math.max(5, point.requests / max * 100)}%` }} />}
            {point.calls > 0 && <div className="w-1.5 max-w-[30%] rounded-t-sm bg-primary" style={{ height: `${Math.max(5, point.calls / max * 100)}%` }} />}
            {point.mcp_calls > 0 && <div className="w-1.5 max-w-[30%] rounded-t-sm bg-success" style={{ height: `${Math.max(5, point.mcp_calls / max * 100)}%` }} />}
          </div>)}
        </div>
        <div className="mt-2 flex gap-1 text-[10px] text-muted-foreground">
          {statistics.series.map((point, index) => <span key={point.start} className="min-w-0 flex-1 text-center"><span className={statistics.bucket_hours === 2 && index % 2 === 1 ? "hidden sm:inline" : ""}>{new Intl.DateTimeFormat(locale, statistics.bucket_hours === 2 ? { hour: "2-digit" } : { month: "numeric", day: "numeric" }).format(new Date(point.start))}</span></span>)}
        </div>
        <table className="sr-only"><caption>{t("dashboardTrend")}</caption><thead><tr><th>{t("time")}</th><th>{t("dashboardToolRequests")}</th><th>{t("dashboardToolCalls")}</th><th>{t("dashboardMcpCalls")}</th></tr></thead><tbody>{statistics.series.map((point) => <tr key={point.start}><td>{new Date(point.start).toLocaleString(locale)}</td><td>{point.requests}</td><td>{point.calls}</td><td>{point.mcp_calls}</td></tr>)}</tbody></table>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground"><span className="flex items-center gap-2"><span className="size-2.5 rounded-sm bg-primary/30" />{t("dashboardToolRequests")}</span><span className="flex items-center gap-2"><span className="size-2.5 rounded-sm bg-primary" />{t("dashboardToolCalls")}</span><span className="flex items-center gap-2"><span className="size-2.5 rounded-sm bg-success" />{t("dashboardMcpCalls")}</span><span>{statistics.totals.not_invoked.toLocaleString(locale)} {t("dashboardNotInvoked")}</span></div>
      </> : <p className="py-14 text-center text-sm text-muted-foreground">{t("dashboardNoCalls")}</p>}
    </CardContent>
  </Card>
}

function TopTools({ statistics, locale, t }: { statistics: InvocationStatistics; locale: Locale; t: TFunction }) {
  const max = statistics.top_tools[0]?.calls || 1
  return <Card>
    <CardHeader>
      <CardTitle>{t("dashboardTopTools")}</CardTitle>
      <CardDescription>{t("dashboardTopToolsDesc")}</CardDescription>
    </CardHeader>
    <CardContent>
      {statistics.top_tools.length ? <ol className="space-y-4">
        {statistics.top_tools.map((tool) => <li key={`${tool.server_id}:${tool.tool_id}`}>
          <div className="flex items-start justify-between gap-3 text-sm"><div className="min-w-0"><div className="truncate font-medium" title={tool.tool_id}>{tool.tool_id}</div><div className="truncate text-xs text-muted-foreground" title={tool.server_id}>{tool.server_id}{tool.errors > 0 && ` · ${tool.errors} ${t("error")}`}</div></div><strong className="tabular-nums">{tool.calls.toLocaleString(locale)}</strong></div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${tool.calls / max * 100}%` }} /></div>
        </li>)}
      </ol> : <p className="py-14 text-center text-sm text-muted-foreground">{t("dashboardNoCalls")}</p>}
      <a href="#/invocationAudit" className="mt-5 inline-flex text-sm font-medium text-primary hover:underline">{t("dashboardViewAudit")}</a>
    </CardContent>
  </Card>
}

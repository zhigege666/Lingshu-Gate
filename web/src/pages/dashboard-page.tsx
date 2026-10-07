import { trendGeometry, trendPointerIndex } from "@/features/dashboard-trend"
import { useRemainingViewport } from "@/components/use-remaining-viewport"
import { useEffect, useId, useMemo, useState, type ReactNode } from "react"
import { Activity, AlertTriangle, ArrowUpRight, BarChart3, Info, MousePointerClick, RefreshCw, Server, Wrench } from "lucide-react"
import { api, type HealthResponse, type InvocationStatistics, type McpServer, type ToolDefinition } from "@/api/client"
import { useConsoleDesign } from "@/components/console-design-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Popover } from "antd"
import { Skeleton } from "@/components/ui/skeleton"
import type { Locale, TFunction } from "@/i18n"
import { Metric } from "@/pages/page-utils"
import "@/pages/dashboard-page.css"

export function DashboardPage({ health, healthError, servers, tools, principalId, globalRefreshId, operationsAllowed, canReadAudit, canReadTools, toolsLoaded, toolsError, serversLoaded, serversError, t }: { health: HealthResponse | null; healthError: string | null; servers: McpServer[]; tools: ToolDefinition[]; principalId: string; globalRefreshId: number; operationsAllowed: boolean; canReadAudit: boolean; canReadTools: boolean; toolsLoaded: boolean; toolsError: string | null; serversLoaded: boolean; serversError: string | null; t: TFunction }) {
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
  const attentionServers = servers.filter((server) => ["failed", "unsupported"].includes(server.status))

  return (
    <div className="dashboard-page">
      <h1 className="sr-only">{t("dashboard")}</h1>

      <DashboardResourceOverview health={health} healthError={healthError} servers={servers} tools={tools} operationsAllowed={operationsAllowed} canReadTools={canReadTools} toolsLoaded={toolsLoaded} toolsError={toolsError} serversLoaded={serversLoaded} serversError={serversError} locale={locale} t={t} />

      {operationsAllowed && serversLoaded && !serversError && attentionServers.length ? <Card className="dashboard-attention border-warning/40 bg-warning/5">
        <CardContent className="dashboard-attention-content">
          <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 size-5 text-warning" /><div><div className="font-medium">{attentionServers.length} {t("warning")}</div><div className="text-sm text-muted-foreground">{attentionServers.slice(0, 5).map((server) => server.name || server.id).join(" · ")}</div></div></div>
          <Button size="sm" variant="outline" asChild><a href="#/servers">{t("detail")}</a></Button>
        </CardContent>
      </Card> : null}

      {canReadAudit && <section className="dashboard-usage" aria-labelledby="dashboard-usage-title">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="dashboard-usage-title" className="text-lg font-semibold tracking-tight">{t("dashboardUsage")}</h2>

          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Popover trigger={["click"]} title={t("dashboardStatsHelp")} content={<div className="dashboard-statistics-help"><p>{t("dashboardUsageDesc")}</p><p>{t("dashboardStatsScope")}</p></div>}><Button size="sm" variant="ghost" aria-label={t("dashboardStatsHelp")}><Info className="size-4" /></Button></Popover>
            <div className="inline-flex rounded-lg border bg-card p-1" role="group" aria-label={t("dashboardUsage")}>
              <Button size="sm" variant={hours === 24 ? "secondary" : "ghost"} aria-pressed={hours === 24} onClick={() => selectHours(24)}>{t("dashboard24Hours")}</Button>
              <Button size="sm" variant={hours === 168 ? "secondary" : "ghost"} aria-pressed={hours === 168} onClick={() => selectHours(168)}>{t("dashboard7Days")}</Button>
            </div>
            <Button size="sm" variant="outline" aria-label={t("refresh")} onClick={refreshStatistics} disabled={statisticsLoading}><RefreshCw className="size-4" />{t("refresh")}</Button>
          </div>
        </div>

        {statisticsLoading || (!currentStatistics && !statisticsError) ? <div className="dashboard-metric-grid"><MetricSkeleton /><MetricSkeleton /><MetricSkeleton /><MetricSkeleton /></div> : statisticsError || !currentStatistics ? <Card><CardContent className="p-5 text-sm text-muted-foreground" role="status">{t("dashboardStatsUnavailable")}</CardContent></Card> : <>
          <div className="dashboard-metric-grid">
            <Metric title={t("dashboardToolRequests")} value={currentStatistics.totals.requests.toLocaleString(locale)} hint={t("dashboardToolRequestsHint")} icon={<MousePointerClick className="size-[18px]" />} />
            <Metric title={t("dashboardMcpCalls")} value={currentStatistics.totals.mcp_calls.toLocaleString(locale)} hint={t("dashboardMcpCallsHint")} icon={<Server className="size-[18px]" />} />
            <Metric title={t("dashboardToolCalls")} value={currentStatistics.totals.calls.toLocaleString(locale)} hint={t("dashboardToolCallsHint")} icon={<Wrench className="size-[18px]" />} />
            <Metric title={t("dashboardSuccessRate")} value={currentStatistics.totals.calls ? `${Math.round(currentStatistics.totals.success / currentStatistics.totals.calls * 100)}%` : "—"} hint={t("dashboardSuccessRateHint")} icon={<Activity className="size-[18px]" />} />
          </div>
          <DashboardInsights>
            <UsageTrend statistics={currentStatistics} locale={locale} t={t} />
            <TopTools statistics={currentStatistics} locale={locale} t={t} />
          </DashboardInsights>
        </>}
      </section>}


    </div>
  )
}

/** A read-only snapshot and two real navigation links; it does not fetch data. */
export function DashboardResourceOverview({ health, healthError, servers, tools, operationsAllowed, canReadTools, toolsLoaded, toolsError, serversLoaded, serversError, locale, t }: {
  health: HealthResponse | null
  healthError: string | null
  servers: McpServer[]
  tools: ToolDefinition[]
  operationsAllowed: boolean
  canReadTools: boolean
  toolsLoaded: boolean
  toolsError: string | null
  serversLoaded: boolean
  serversError: string | null
  locale: Locale
  t: TFunction
}) {
  const running = servers.filter(server => server.status === "running").length
  const attention = servers.filter(server => server.status === "failed" || server.status === "unsupported").length
  const otherServers = servers.length - running - attention
  const builtin = tools.filter(tool => tool.source === "builtin").length
  const mcp = tools.filter(tool => tool.source === "mcp").length
  const otherTools = tools.length - builtin - mcp
  const healthy = health?.status === "ok"
  const count = (value: number) => value.toLocaleString(locale)
  const healthLabel = healthy ? t("dashboardGateResponding") : health?.status === "starting" ? t("dashboardGateStarting") : t("dashboardGateNeedsAttention")

  return <section className="dashboard-resource-overview" data-slot="dashboard-overview" data-columns={1 + Number(operationsAllowed) + Number(canReadTools)} aria-label={t("dashboardResourceOverview")}>
    <div className="dashboard-resource dashboard-gate" data-resource="gate" aria-busy={!healthError && health === null}>
      <div className="dashboard-resource-label"><Activity aria-hidden="true" /><span>{t("dashboardGateHealth")}</span></div>
      {healthError ? <><div className="dashboard-health-value needs-attention" role="status">{t("dashboardGateUnavailable")}</div><p className="dashboard-resource-detail">{t("dashboardRefreshHint")}</p></> : health === null ? <OverviewLoading label={t("dashboardGateHealth")} t={t} /> : <>
        <div className={`dashboard-health-value ${healthy ? "is-healthy" : "needs-attention"}`}><span className="dashboard-health-dot" aria-hidden="true" />{healthLabel}</div>
        <p className="dashboard-resource-detail">{t("dashboardGateHealthScope")}</p>
      </>}
    </div>

    {operationsAllowed && <a className="dashboard-resource dashboard-resource-link" data-resource="servers" href="#/servers" aria-busy={!serversError && !serversLoaded}>
      <div className="dashboard-resource-label"><Server aria-hidden="true" /><span>{t("mcpServers")}</span><ArrowUpRight className="dashboard-resource-arrow" aria-hidden="true" /></div>
      {serversError ? <><strong className="dashboard-resource-value">—</strong><p className="dashboard-resource-detail" role="status">{t("dashboardServersUnavailable")}</p></> : !serversLoaded ? <OverviewLoading label={t("mcpServers")} t={t} /> : <>
        <strong className="dashboard-resource-value">{count(servers.length)}<span>{t("dashboardRegistered")}</span></strong>
        <p className="dashboard-resource-detail"><span className="dashboard-detail-item"><i className="is-running" aria-hidden="true" />{count(running)} {t("running")}</span>{attention > 0 && <span className="dashboard-detail-item"><i className="is-attention" aria-hidden="true" />{count(attention)} {t("dashboardServerAttention")}</span>}{otherServers > 0 && <span className="dashboard-detail-item"><i className="is-other" aria-hidden="true" />{count(otherServers)} {t("dashboardServerOther")}</span>}</p>
      </>}
    </a>}

    {canReadTools && <a className="dashboard-resource dashboard-resource-link" data-resource="tools" href="#/tools" aria-busy={!toolsError && !toolsLoaded}>
      <div className="dashboard-resource-label"><Wrench aria-hidden="true" /><span>{t("toolRegistry")}</span><ArrowUpRight className="dashboard-resource-arrow" aria-hidden="true" /></div>
      {toolsError ? <><strong className="dashboard-resource-value">—</strong><p className="dashboard-resource-detail" role="status">{t("dashboardToolsUnavailable")}</p></> : !toolsLoaded ? <OverviewLoading label={t("toolRegistry")} t={t} /> : <>
        <strong className="dashboard-resource-value">{count(tools.length)}<span>{t("dashboardVisibleToYou")}</span></strong>
        <p className="dashboard-resource-detail"><span className="dashboard-detail-item"><i className="is-mcp" aria-hidden="true" />{count(mcp)} MCP</span><span className="dashboard-detail-item"><i className="is-builtin" aria-hidden="true" />{count(builtin)} {t("dashboardBuiltinSource")}</span>{otherTools > 0 && <span className="dashboard-detail-item"><i className="is-other" aria-hidden="true" />{count(otherTools)} {t("dashboardOtherSource")}</span>}</p>
      </>}
    </a>}
  </section>
}

function OverviewLoading({ label, t }: { label: string; t: TFunction }) {
  return <div className="dashboard-resource-loading" role="status" aria-label={`${label} · ${t("loadingData")}`}><span className="sr-only">{t("loadingData")}</span><Skeleton className="h-7 w-24" /><Skeleton className="mt-2 h-3 w-32" /></div>
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

export function dashboardTrendTicks(series: readonly { start: string }[], bucketHours: number, locale: Locale, limit = 7) {
  const format = new Intl.DateTimeFormat(locale, bucketHours <= 2
    ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }
    : { month: "numeric", day: "numeric" })
  const seen = new Set<string>()
  const candidates = series.flatMap((point, index) => {
    const label = format.format(new Date(point.start))
    if (seen.has(label)) return []
    seen.add(label)
    return [{ index, label }]
  })
  if (candidates.length <= limit) return candidates
  return Array.from({ length: limit }, (_, index) => candidates[Math.round(index * (candidates.length - 1) / (limit - 1))])
}

export function UsageTrend({ statistics, locale, t }: { statistics: InvocationStatistics; locale: Locale; t: TFunction }) {
  const [metric, setMetric] = useState<"requests" | "calls" | "mcp_calls">("requests")
  const [active, setActive] = useState<number | null>(null)
  const gradientId = useId().replace(/:/g, "")
  const geometry = useMemo(() => trendGeometry(statistics.series.map(point => point[metric])), [statistics.series, metric])
  const ticks = useMemo(() => dashboardTrendTicks(statistics.series, statistics.bucket_hours, locale), [statistics.series, statistics.bucket_hours, locale])
  const selected = active === null ? null : Math.min(active, statistics.series.length - 1)
  const point = selected === null ? null : statistics.series[selected]
  const labels = { requests: t("dashboardToolRequests"), calls: t("dashboardToolCalls"), mcp_calls: t("dashboardMcpCalls") }
  const total = statistics.totals[metric]
  const shortNumber = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 })
  return <Card className="min-w-0" data-dashboard-trend>
    <CardHeader className="dashboard-chart-header dashboard-trend-header">
      <div><CardTitle className="flex items-center gap-2"><BarChart3 className="size-5 text-primary" />{t("dashboardTrend")}</CardTitle>
      <CardDescription>{locale === "zh-CN" ? `${statistics.bucket_hours} 小时间隔 · 从零起算` : `${statistics.bucket_hours}-hour intervals · zero baseline`}</CardDescription></div>
      <div className="dashboard-trend-total"><strong>{total.toLocaleString(locale)}</strong><span>{locale === "zh-CN" ? "所选时段合计" : "Period total"}</span></div>
    </CardHeader>
    <CardContent className="dashboard-chart-body">
      <div className="dashboard-trend-switch" role="group" aria-label={t("dashboardTrend")}>
        {(Object.keys(labels) as Array<keyof typeof labels>).map(key => <button type="button" key={key} aria-pressed={metric === key} onClick={() => { setMetric(key); setActive(null) }}>{labels[key]}</button>)}
      </div>
      {statistics.series.length ? <>
        <div className="dashboard-line-layout">
          <div className="dashboard-line-y" aria-hidden="true">{geometry.ticks.map(value => <span key={value} title={value.toLocaleString(locale)}>{shortNumber.format(value)}</span>)}</div>
          <div className="dashboard-line-plot" tabIndex={0} role="group" aria-label={locale === "zh-CN" ? "趋势图，左右方向键查看时间点" : "Trend chart. Use left and right arrows to inspect points"}
            onPointerMove={event => { const bounds = event.currentTarget.getBoundingClientRect(); const next = trendPointerIndex(event.clientX - bounds.left, bounds.width, statistics.series.length); setActive(previous => previous === next ? previous : next) }}
            onPointerLeave={() => setActive(null)} onBlur={() => setActive(null)} onFocus={() => setActive(statistics.series.length - 1)}
            onKeyDown={event => {
              const index = selected ?? statistics.series.length - 1
              if (["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) event.preventDefault()
              if (event.key === "ArrowLeft") setActive(Math.max(0, index - 1))
              if (event.key === "ArrowRight") setActive(Math.min(statistics.series.length - 1, index + 1))
              if (event.key === "Home") setActive(0)
              if (event.key === "End") setActive(statistics.series.length - 1)
              if (event.key === "Escape") setActive(null)
            }}>
            <svg viewBox="0 0 720 160" preserveAspectRatio="none" aria-hidden="true">
              <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="currentColor" stopOpacity=".22" /><stop offset="100%" stopColor="currentColor" stopOpacity=".025" /></linearGradient></defs>
              {[0,40,80,120,160].map(y => <line key={y} x1="0" x2="720" y1={y} y2={y} className="dashboard-line-grid" vectorEffect="non-scaling-stroke" />)}
              <path d={geometry.area} fill={`url(#${gradientId})`} />
              <path d={geometry.line} fill="none" stroke="currentColor" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
              {selected !== null && geometry.points[selected] && <line x1={geometry.points[selected].x * 7.2} x2={geometry.points[selected].x * 7.2} y1="0" y2="160" stroke="currentColor" strokeDasharray="4 4" strokeOpacity=".5" vectorEffect="non-scaling-stroke" />}
            </svg>
            {(selected !== null || geometry.points.length === 1) && geometry.points[selected ?? 0] && <i className="dashboard-line-point" style={{ left: `${geometry.points[selected ?? 0].x}%`, top: `${geometry.points[selected ?? 0].y}%` }} />}
          </div>
          <div className="dashboard-line-x" data-trend-axis aria-hidden="true">{ticks.map((tick, index) => <span key={tick.index} style={{ left: `${statistics.series.length === 1 ? 50 : tick.index / (statistics.series.length - 1) * 100}%`, transform: index === 0 ? undefined : index === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>{tick.label}</span>)}</div>
        </div>
        <div className="dashboard-trend-readout" aria-live="polite" aria-atomic="true">
          {point ? <><span>{new Date(point.start).toLocaleString(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}</span><strong>{point[metric].toLocaleString(locale)} <small>{labels[metric]}</small></strong></> : <><span>{total ? (locale === "zh-CN" ? "悬停或用方向键查看每个时段" : "Hover or use arrow keys to inspect each interval") : t("dashboardNoCalls")}</span><span>{statistics.totals.not_invoked.toLocaleString(locale)} {t("dashboardNotInvoked")}</span></>}
        </div>
        <div className="sr-only"><table><caption>{t("dashboardTrend")}</caption><thead><tr><th>{t("time")}</th><th>{t("dashboardToolRequests")}</th><th>{t("dashboardToolCalls")}</th><th>{t("dashboardMcpCalls")}</th></tr></thead><tbody>{statistics.series.map(item => <tr key={item.start}><td>{new Date(item.start).toLocaleString(locale)}</td><td>{item.requests}</td><td>{item.calls}</td><td>{item.mcp_calls}</td></tr>)}</tbody></table></div>
      </> : <p className="py-14 text-center text-sm text-muted-foreground">{t("dashboardNoCalls")}</p>}
    </CardContent>
  </Card>
}

function TopTools({ statistics, locale, t }: { statistics: InvocationStatistics; locale: Locale; t: TFunction }) {
  const max = statistics.top_tools[0]?.calls || 1
  return <Card className="min-w-0" data-dashboard-ranking>
    <CardHeader className="dashboard-chart-header">
      <CardTitle>{t("dashboardTopTools")}</CardTitle>
      <CardDescription>{t("dashboardTopToolsDesc")}</CardDescription>
    </CardHeader>
    <CardContent className="dashboard-chart-body">
      {statistics.top_tools.length ? <ol className="dashboard-ranking-list space-y-4 overflow-y-auto overscroll-contain pr-2" tabIndex={0} aria-label={t("dashboardTopTools")}>
        {statistics.top_tools.map((tool) => <li key={`${tool.server_id}:${tool.tool_id}`}>
          <div className="flex items-start justify-between gap-3 text-sm"><div className="min-w-0"><div className="truncate font-medium" title={tool.tool_id}>{tool.tool_id}</div><div className="truncate text-xs text-muted-foreground" title={tool.server_id}>{tool.server_id}{tool.errors > 0 && ` · ${tool.errors} ${t("error")}`}</div></div><strong className="tabular-nums">{tool.calls.toLocaleString(locale)}</strong></div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${tool.calls / max * 100}%` }} /></div>
        </li>)}
      </ol> : <p className="py-14 text-center text-sm text-muted-foreground">{t("dashboardNoCalls")}</p>}
      <a href="#/invocationAudit" className="mt-5 inline-flex text-sm font-medium text-primary hover:underline">{t("dashboardViewAudit")}</a>
    </CardContent>
  </Card>
}

function DashboardInsights({ children }: { children: ReactNode }) {
  const ref = useRemainingViewport(20)
  return <div ref={ref} className="dashboard-insights">{children}</div>
}

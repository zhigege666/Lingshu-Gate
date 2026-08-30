import { Activity, AlertTriangle, ScrollText, Server, Wrench, Zap } from "lucide-react"
import type { HealthResponse, McpServer, ToolDefinition } from "@/api/client"
import { PageHeader } from "@/components/page-shell"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import type { TFunction } from "@/i18n"
import { Metric, statusBadge } from "@/pages/page-utils"

export function DashboardPage({ health, servers, tools, operationsAllowed, t }: { health: HealthResponse | null; servers: McpServer[]; tools: ToolDefinition[]; operationsAllowed: boolean; t: TFunction }) {
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
        stats={operationsAllowed ? [
          { label: t("status"), value: health?.status || t("waiting"), tone: health?.status === "ok" ? "success" : "warning" },
          { label: t("running"), value: `${runningCount}/${servers.length}`, tone: runningCount === servers.length && servers.length > 0 ? "success" : "default" },
          { label: t("tools"), value: tools.length },
          { label: t("warning"), value: attentionServers.length, tone: attentionServers.length ? "warning" : "success" },
        ] : [
          { label: t("status"), value: health?.status || t("waiting"), tone: health?.status === "ok" ? "success" : "warning" },
          { label: t("tools"), value: tools.length },
        ]}
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

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {loading ? (
          <>
            <MetricSkeleton />
            <MetricSkeleton />
            <MetricSkeleton />
            <MetricSkeleton />
          </>
        ) : (
          <>
            <Metric title={t("service")} value={health?.service || "-"} hint={`${t("version")} ${health?.version || "-"}`} icon={<Zap className="size-[18px]" />} />
            <Metric title={t("status")} value={health?.status || "-"} badge={statusBadge(health?.status, t)} icon={<Activity className="size-[18px]" />} />
            {operationsAllowed ? <>
              <Metric title={t("mcpServers")} value={String(health?.mcp_server_count ?? 0)} hint={`${runningCount} ${t("running")}`} icon={<Server className="size-[18px]" />} />
              <Metric title={t("tools")} value={String(health?.tool_count ?? 0)} hint={`${mcpToolCount} ${t("mcpTools")}`} icon={<Wrench className="size-[18px]" />} />
            </> : <Metric title={t("tools")} value={String(tools.length)} icon={<Wrench className="size-[18px]" />} />}
          </>
        )}
      </div>

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

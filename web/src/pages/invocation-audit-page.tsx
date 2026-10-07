import { FilterRadio } from "@/components/filter-radio"
import { auditSafety } from "@/features/observability/audit-safety"
import "./invocation-audit-page.css"
import { InvocationContent } from "@/components/invocation-content"
import { RemainingList, ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import { usePageRefresh } from "@/components/page-refresh"
import { QueryStatus, querySignature } from "@/components/query-status"
import { useEffect, useMemo, useState } from "react"
import { ShieldCheck, ShieldX } from "lucide-react"
import { api, type InvocationAudit, type InvocationAuditFilterOptions } from "@/api/client"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 调用审计",
    title: "调用审计",
    description: "记录谁通过什么凭据调用了哪个 Tool、分类要求、实际授权、策略决策和执行结果。默认仅记录参数摘要；可选内容记录会脱敏并限长，需独立权限读取。",
    blocked: "已拦截，工具未执行",
    inconsistent: "安全警示：授权与执行记录矛盾，请按关联 ID 排查",
    blockedHint: "可能来自旧目录缓存、撤权后的客户端或直接请求工具 ID；该条记录不代表工具已执行。",
    technical: "技术信息",
    time: "时间",
    actor: "调用者",
    resource: "资源",
    access: "权限判断",
    decision: "决策",
    outcome: "结果",
    duration: "耗时",
    allow: "允许",
    deny: "拒绝",
    allDecisions: "全部决策",
    allOutcomes: "全部结果",
    userId: "用户",
    serverId: "MCP 服务",
    toolId: "工具",
    allUsers: "全部用户",
    allServers: "全部 MCP 服务",
    allTools: "全部工具",
    search: "在当前结果中搜索用户、MCP 服务、工具或关联 ID",
    filterHint: "决策和结果单选即时筛选；用户、服务和工具条件需点击「应用筛选」。搜索只匹配当前结果，最多 300 条。",
    noData: "暂无调用审计",
    detail: "审计详情",
    payload: "参数摘要",
    correlation: "关联 ID",
    authType: "凭据类型",
    required: "要求",
    granted: "已授权",
    success: "成功",
    error: "错误",
    not_invoked: "未执行",
    noneLevel: "无权限",
    unknownLevel: "待判定",
    readLevel: "只读",
    writeLevel: "读写",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · INVOCATION AUDIT",
    title: "Invocation Audit",
    description: "Track who invoked which tool, through which credential, what classification and grant applied, and how execution ended. Metadata is recorded by default; optional content recording is redacted, bounded, and requires separate access.",
    blocked: "Blocked — tool was not executed",
    inconsistent: "Security warning: authorization and execution records conflict. Investigate using the correlation ID.",
    blockedHint: "This may come from a stale catalog, a client after revocation or a direct tool-ID request. This record does not mean the tool executed.",
    technical: "Technical details",
    time: "Time",
    actor: "Actor",
    resource: "Resource",
    access: "Access decision",
    decision: "Decision",
    outcome: "Outcome",
    duration: "Duration",
    allow: "Allow",
    deny: "Deny",
    allDecisions: "All decisions",
    allOutcomes: "All outcomes",
    userId: "User",
    serverId: "MCP server",
    toolId: "Tool",
    allUsers: "All users",
    allServers: "All MCP servers",
    allTools: "All tools",
    search: "Search current results by actor, server, tool, or correlation ID",
    filterHint: "Decision and outcome apply immediately. Apply user, service and tool conditions separately; search covers up to 300 loaded records.",
    noData: "No invocation audits",
    detail: "Audit detail",
    payload: "Payload summary",
    correlation: "Correlation ID",
    authType: "Credential type",
    required: "Required",
    granted: "Granted",
    success: "Success",
    error: "Error",
    not_invoked: "Not invoked",
    noneLevel: "None",
    unknownLevel: "Unclassified",
    readLevel: "Read",
    writeLevel: "Read & write",
  },
} satisfies Record<Locale, Record<string, string>>

export function InvocationAuditPage({ locale, t, canReadPayload = false }: { locale: Locale; t: TFunction; canReadPayload?: boolean }) {
  const c = copy[locale]
  const [audits, setAudits] = useState<InvocationAudit[]>([])
  const [query, setQuery] = useState("")
  const [decision, setDecision] = useState("__all")
  const [outcome, setOutcome] = useState("__all")
  const [userId, setUserId] = useState("__all")
  const [serverId, setServerId] = useState("__all")
  const [toolId, setToolId] = useState("__all")
  const [applied, setApplied] = useState({ userId: "__all", serverId: "__all", toolId: "__all", decision: "__all", outcome: "__all" })
  const [lastLoadedAt, setLastLoadedAt] = useState("")
  const [filterOptions, setFilterOptions] = useState<InvocationAuditFilterOptions>({ users: [], servers: [], tools: [] })
  const [selected, setSelected] = useState<InvocationAudit | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const visibleAudits = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return audits
    return audits.filter((item) => `${item.username} ${item.user_id} ${item.server_id} ${item.tool_id} ${item.correlation_id}`.toLowerCase().includes(needle))
  }, [audits, query])
  const toolOptions = useMemo(
    () => filterOptions.tools.filter((item) => serverId === "__all" || item.server_id === serverId),
    [filterOptions.tools, serverId],
  )

  const paging = useListPage(visibleAudits, JSON.stringify([query, applied]))

  usePageRefresh(() => load(applied), busy)
  useEffect(() => { void load(applied) }, [])

  async function load(snapshot = { userId, serverId, toolId, decision, outcome }) {
    setBusy(true)
    setError(null)
    try {
      const result = await api.invocationAudits({
        user_id: snapshot.userId === "__all" ? undefined : snapshot.userId,
        server_id: snapshot.serverId === "__all" ? undefined : snapshot.serverId,
        tool_id: snapshot.toolId === "__all" ? undefined : snapshot.toolId,
        decision: snapshot.decision === "__all" ? undefined : snapshot.decision,
        outcome: snapshot.outcome === "__all" ? undefined : snapshot.outcome,
        limit: 300,
      })
      setApplied(snapshot)
      setLastLoadedAt(new Date().toISOString())
      setAudits(result.audits)
      setFilterOptions(result.filter_options)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const allowCount = audits.filter((item) => item.decision === "allow").length
  const denyCount = audits.filter((item) => item.decision === "deny").length
  const errorCount = audits.filter((item) => item.outcome === "error").length
  const advancedFilters = [
    userId !== "__all" && `${c.userId}: ${filterOptions.users.find((user) => user.id === userId)?.username || userId}`,
    serverId !== "__all" && `${c.serverId}: ${serverId}`,
    toolId !== "__all" && `${c.toolId}: ${toolId}`,
  ].filter(Boolean)

  function changeServer(value: string) {
    setServerId(value)
    if (toolId === "__all") return
    const toolStillMatches = filterOptions.tools.some((item) => item.tool_id === toolId && (value === "__all" || item.server_id === value))
    if (!toolStillMatches) setToolId("__all")
  }

  function changeTool(value: string) {
    setToolId(value)
    if (value === "__all" || serverId !== "__all") return
    const selectedTool = filterOptions.tools.find((item) => item.tool_id === value)
    if (selectedTool) setServerId(selectedTool.server_id)
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader closeLabel={t("close")}
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        helpLabel={t("pageHelp")}
        helpContent={<p>{c.filterHint}</p>}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={c.search} resultCount={visibleAudits.length} resultLabel={c.title} clearLabel={t("clearSearch")}>
          <FilterRadio label={c.decision} value={decision} disabled={busy} onChange={value => { setDecision(value); void load({ ...applied, decision: value }) }} options={[{ value: "__all", label: t("all") }, { value: "allow", label: c.allow }, { value: "deny", label: c.deny }]} />
          <FilterRadio label={c.outcome} value={outcome} disabled={busy} onChange={value => { setOutcome(value); void load({ ...applied, outcome: value }) }} options={[{ value: "__all", label: t("all") }, { value: "success", label: c.success }, { value: "error", label: c.error }, { value: "not_invoked", label: c.not_invoked }]} />
        </PageToolbar>}
        stats={[
          { label: c.allow, value: allowCount, tone: "success" },
          { label: c.deny, value: denyCount, tone: denyCount ? "danger" : "default" },
          { label: c.error, value: errorCount, tone: errorCount ? "warning" : "default" },
        ]}
        actions={<><Button variant="outline" disabled={busy} onClick={() => { const defaults = { userId: "__all", serverId: "__all", toolId: "__all", decision: "__all", outcome: "__all" }; setQuery(""); setUserId(defaults.userId); setServerId(defaults.serverId); setToolId(defaults.toolId); setDecision(defaults.decision); setOutcome(defaults.outcome); void load(defaults) }}>{t("resetConditions")}</Button><Button onClick={() => void load()} disabled={busy}>{t("applyFilters")}</Button></>}
      />
      <QueryStatus t={t} pendingChanges={querySignature({ userId, serverId, toolId, decision, outcome }) !== querySignature(applied)} lastLoadedAt={lastLoadedAt} summary={Object.entries(applied).filter(([, value]) => value !== "__all").map(([key, value]) => `${c[key as keyof typeof c] || key}: ${value}`).join(" · ") || `${t("all")} · ${t("limit")}: 300`} />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <Card>
        <CardContent className="flex flex-col gap-3 p-3 md:p-4">
          <details className="rounded-md border bg-muted/20 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">{t("advancedFilters")} ({advancedFilters.length}){advancedFilters.length > 0 && <span className="ml-2 break-words font-normal">{advancedFilters.join(" · ")}</span>}</summary>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <FilterField label={c.userId}><Select value={userId} onValueChange={setUserId}><SelectTrigger aria-label={c.userId}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allUsers}</SelectItem>{filterOptions.users.map((user) => <SelectItem key={user.id} value={user.id}>{user.username} · {user.id}</SelectItem>)}</SelectContent></Select></FilterField>
              <FilterField label={c.serverId}><Select value={serverId} onValueChange={changeServer}><SelectTrigger aria-label={c.serverId}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allServers}</SelectItem>{filterOptions.servers.map((server) => <SelectItem key={server} value={server}>{server}</SelectItem>)}</SelectContent></Select></FilterField>
              <FilterField label={c.toolId}><Select value={toolId} onValueChange={changeTool}><SelectTrigger aria-label={c.toolId}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allTools}</SelectItem>{toolOptions.map((tool) => <SelectItem key={`${tool.server_id}:${tool.tool_id}`} value={tool.tool_id}>{tool.tool_id}{serverId === "__all" ? ` · ${tool.server_id}` : ""}</SelectItem>)}</SelectContent></Select></FilterField>
            </div>
          </details>
          <RemainingList className="rounded-lg border">
            <ListViewport actions={false} viewport={paging.viewport} label={t("toolShowing")}>
            <Table>
              <TableHeader><TableRow><TableHead>{c.time}</TableHead><TableHead>{c.actor}</TableHead><TableHead>{c.resource}</TableHead><TableHead>{c.access}</TableHead><TableHead>{c.decision}</TableHead><TableHead>{c.outcome}</TableHead><TableHead className="whitespace-nowrap">{c.duration}</TableHead></TableRow></TableHeader>
              <TableBody>
                {visibleAudits.length === 0 ? <TableEmptyRow colSpan={7} title={busy ? t("loadingData") : error ? t("notLoaded") : query.trim() ? t("noCurrentMatches") : Object.values(applied).some(value => value !== "__all") ? t("noAppliedMatches") : c.noData} /> : paging.items.map((item) => <TableRow key={item.id} className="cursor-pointer" onClick={() => setSelected(item)}>
                  <TableCell className="whitespace-nowrap text-xs">{formatDateTime(item.created_at)}</TableCell>
                  <TableCell><div className="font-medium">{item.username}</div><div className="text-xs text-muted-foreground">{item.auth_type}{item.api_token_id ? ` · ${item.api_token_id.slice(0, 8)}` : ""}</div></TableCell>
                  <TableCell><button type="button" className="text-left font-medium underline underline-offset-4 focus-visible:outline focus-visible:outline-2" onClick={e => { e.stopPropagation(); setSelected(item) }}>{item.tool_id}</button><div className="text-xs text-muted-foreground">{item.server_id}</div></TableCell>
                  <TableCell><div className="flex flex-col gap-1 text-xs"><span>{c.required}: <AccessBadge access={item.required_access} labels={c} /></span><span>{c.granted}: <AccessBadge access={item.granted_access} labels={c} /></span></div></TableCell>
                  <TableCell><Badge variant={item.decision === "allow" ? "success" : "danger"}>{item.decision === "allow" ? <ShieldCheck /> : <ShieldX />}{c[item.decision]}</Badge></TableCell>
                  <TableCell>{auditSafety(item) === "inconsistent" ? <Badge variant="danger">{c.inconsistent}</Badge> : <OutcomeBadge outcome={item.outcome} labels={c} />}</TableCell>
                  <TableCell>{item.duration_ms === null || item.duration_ms === undefined ? "-" : `${item.duration_ms} ms`}</TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
            </ListViewport>
            <ListPagination paging={paging} t={t} />
          </RemainingList>
        </CardContent>
      </Card>

      <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null) }}>
        <DialogContent closeLabel={t("close")} className="max-w-3xl">
          <DialogHeader><DialogTitle>{c.detail}</DialogTitle><DialogDescription>{selected?.correlation_id || ""}</DialogDescription></DialogHeader>
          <DialogBody className="space-y-4">
            {selected && <Alert variant={auditSafety(selected) === "inconsistent" ? "destructive" : "default"}>
              <AlertDescription><strong>{auditSafety(selected) === "inconsistent" ? c.inconsistent : auditSafety(selected) === "blocked" ? c.blocked : `${c[selected.decision]} · ${c[selected.outcome]}`}</strong>
                {auditSafety(selected) === "blocked" && <p>{c.blockedHint}</p>}
                <p className="break-words">{selected.reason}</p>
              </AlertDescription>
            </Alert>}
            <div className="audit-detail-grid">
              <Detail label={c.actor} value={selected?.username} />
              <Detail label={c.time} value={selected ? formatDateTime(selected.created_at) : ""} />
              <Detail label={c.resource} value={selected ? `${selected.server_id} / ${selected.tool_id}` : ""} />
              <Detail label={c.duration} value={selected?.duration_ms == null ? "—" : `${selected.duration_ms} ms`} />
              <Detail label={c.required} value={selected ? accessLabel(selected.required_access, c) : ""} />
              <Detail label={c.granted} value={selected ? accessLabel(selected.granted_access, c) : ""} />
            </div>
            {canReadPayload && selected && <InvocationContent key={selected.id} auditId={selected.id} locale={locale} />}
            <details className="audit-technical"><summary>{c.technical}</summary><div className="audit-detail-grid">
              <Detail label={c.correlation} value={selected?.correlation_id} />
              <Detail label={c.authType} value={selected?.auth_type} />
              <Detail label={`${c.userId} ID`} value={selected?.user_id} />
            </div><Label>{c.payload}</Label><JsonPanel copyLabel={t("copy")} data={selected?.payload || {}} maxHeight="max-h-64" /></details>
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1"><Label className="text-xs">{label}</Label>{children}</div>
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return <div className="min-w-0"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 break-all text-sm">{value || "-"}</div></div>
}

function AccessBadge({ access, labels }: { access: string; labels: Record<string, string> }) {
  if (access === "unknown") return <Badge variant="warning">{labels.unknownLevel}</Badge>
  if (access === "write") return <Badge variant="warning">{labels.writeLevel}</Badge>
  if (access === "read") return <Badge variant="success">{labels.readLevel}</Badge>
  return <Badge variant="secondary">{labels.noneLevel}</Badge>
}

function accessLabel(access: string, labels: Record<string, string>) {
  if (access === "unknown") return labels.unknownLevel
  if (access === "write") return labels.writeLevel
  if (access === "read") return labels.readLevel
  return labels.noneLevel
}

function OutcomeBadge({ outcome, labels }: { outcome: InvocationAudit["outcome"]; labels: Record<string, string> }) {
  const variant = outcome === "success" ? "success" : outcome === "error" ? "danger" : "secondary"
  return <Badge variant={variant}>{labels[outcome]}</Badge>
}

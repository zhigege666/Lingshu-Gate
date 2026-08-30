import { useEffect, useMemo, useState } from "react"
import { RefreshCcw, ShieldCheck, ShieldX } from "lucide-react"
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
    description: "记录谁通过什么凭据调用了哪个 Tool、分类要求、实际授权、策略决策和执行结果。敏感参数值不落库，只记录键名与载荷大小。",
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
    search: "搜索用户、MCP 服务、工具或关联 ID",
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
    readLevel: "只读",
    writeLevel: "读写",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · INVOCATION AUDIT",
    title: "Invocation Audit",
    description: "Track who invoked which tool, through which credential, what classification and grant applied, and how execution ended. Sensitive values are never stored.",
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
    search: "Search actor, server, tool, or correlation ID",
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
    readLevel: "Read",
    writeLevel: "Read & write",
  },
} satisfies Record<Locale, Record<string, string>>

export function InvocationAuditPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const [audits, setAudits] = useState<InvocationAudit[]>([])
  const [query, setQuery] = useState("")
  const [decision, setDecision] = useState("__all")
  const [outcome, setOutcome] = useState("__all")
  const [userId, setUserId] = useState("__all")
  const [serverId, setServerId] = useState("__all")
  const [toolId, setToolId] = useState("__all")
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

  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.invocationAudits({
        user_id: userId === "__all" ? undefined : userId,
        server_id: serverId === "__all" ? undefined : serverId,
        tool_id: toolId === "__all" ? undefined : toolId,
        decision: decision === "__all" ? undefined : decision,
        outcome: outcome === "__all" ? undefined : outcome,
        limit: 300,
      })
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
      <PageHeader
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        stats={[
          { label: c.allow, value: allowCount, tone: "success" },
          { label: c.deny, value: denyCount, tone: denyCount ? "danger" : "default" },
          { label: c.error, value: errorCount, tone: errorCount ? "warning" : "default" },
        ]}
        actions={<Button variant="outline" onClick={() => void load()} disabled={busy}><RefreshCcw />{t("refresh")}</Button>}
      />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <Card>
        <CardContent className="flex flex-col gap-3 p-3 md:p-4">
          <div className="grid gap-3 rounded-lg border bg-muted/20 p-3 md:grid-cols-2 xl:grid-cols-[repeat(5,minmax(0,1fr))_auto]">
            <FilterField label={c.userId}><Select value={userId} onValueChange={setUserId}><SelectTrigger aria-label={c.userId}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allUsers}</SelectItem>{filterOptions.users.map((user) => <SelectItem key={user.id} value={user.id}>{user.username} · {user.id}</SelectItem>)}</SelectContent></Select></FilterField>
            <FilterField label={c.serverId}><Select value={serverId} onValueChange={changeServer}><SelectTrigger aria-label={c.serverId}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allServers}</SelectItem>{filterOptions.servers.map((server) => <SelectItem key={server} value={server}>{server}</SelectItem>)}</SelectContent></Select></FilterField>
            <FilterField label={c.toolId}><Select value={toolId} onValueChange={changeTool}><SelectTrigger aria-label={c.toolId}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allTools}</SelectItem>{toolOptions.map((tool) => <SelectItem key={`${tool.server_id}:${tool.tool_id}`} value={tool.tool_id}>{tool.tool_id}{serverId === "__all" ? ` · ${tool.server_id}` : ""}</SelectItem>)}</SelectContent></Select></FilterField>
            <FilterField label={c.decision}><Select value={decision} onValueChange={setDecision}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allDecisions}</SelectItem><SelectItem value="allow">{c.allow}</SelectItem><SelectItem value="deny">{c.deny}</SelectItem></SelectContent></Select></FilterField>
            <FilterField label={c.outcome}><Select value={outcome} onValueChange={setOutcome}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allOutcomes}</SelectItem><SelectItem value="success">{c.success}</SelectItem><SelectItem value="error">{c.error}</SelectItem><SelectItem value="not_invoked">{c.not_invoked}</SelectItem></SelectContent></Select></FilterField>
            <div className="flex items-end md:justify-end"><Button className="w-full xl:w-auto" onClick={() => void load()} disabled={busy}>{t("search")}</Button></div>
          </div>
          <PageToolbar query={query} onQueryChange={setQuery} placeholder={c.search} resultCount={visibleAudits.length} resultLabel={c.title} clearLabel={t("clearSearch")} />
          <div className="max-h-[620px] overflow-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>{c.time}</TableHead><TableHead>{c.actor}</TableHead><TableHead>{c.resource}</TableHead><TableHead>{c.access}</TableHead><TableHead>{c.decision}</TableHead><TableHead>{c.outcome}</TableHead><TableHead>{c.duration}</TableHead></TableRow></TableHeader>
              <TableBody>
                {visibleAudits.length === 0 ? <TableEmptyRow colSpan={7} title={c.noData} /> : visibleAudits.map((item) => <TableRow key={item.id} className="cursor-pointer" onClick={() => setSelected(item)}>
                  <TableCell className="whitespace-nowrap text-xs">{formatDateTime(item.created_at)}</TableCell>
                  <TableCell><div className="font-medium">{item.username}</div><div className="text-xs text-muted-foreground">{item.auth_type}{item.api_token_id ? ` · ${item.api_token_id.slice(0, 8)}` : ""}</div></TableCell>
                  <TableCell><div className="font-medium">{item.tool_id}</div><div className="text-xs text-muted-foreground">{item.server_id}</div></TableCell>
                  <TableCell><div className="flex items-center gap-2"><AccessBadge access={item.required_access} labels={c} /><span className="text-muted-foreground">≤</span><AccessBadge access={item.granted_access} labels={c} /></div></TableCell>
                  <TableCell><Badge variant={item.decision === "allow" ? "success" : "danger"}>{item.decision === "allow" ? <ShieldCheck /> : <ShieldX />}{c[item.decision]}</Badge></TableCell>
                  <TableCell><OutcomeBadge outcome={item.outcome} labels={c} /></TableCell>
                  <TableCell>{item.duration_ms === null || item.duration_ms === undefined ? "-" : `${item.duration_ms} ms`}</TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null) }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader><DialogTitle>{c.detail}</DialogTitle><DialogDescription>{selected?.correlation_id || ""}</DialogDescription></DialogHeader>
          <DialogBody className="grid max-h-[72vh] gap-4 overflow-y-auto lg:grid-cols-[0.85fr_1.15fr]">
            <div className="flex flex-col gap-3">
              <Detail label={c.correlation} value={selected?.correlation_id} />
              <Detail label={c.actor} value={selected ? `${selected.username} (${selected.user_id})` : ""} />
              <Detail label={c.authType} value={selected?.auth_type} />
              <Detail label={c.resource} value={selected ? `${selected.server_id} / ${selected.tool_id}` : ""} />
              <Detail label={c.required} value={selected ? accessLabel(selected.required_access, c) : ""} />
              <Detail label={c.granted} value={selected ? accessLabel(selected.granted_access, c) : ""} />
              <Detail label={c.decision} value={selected ? `${selected.decision} · ${selected.reason}` : ""} />
              <Detail label={c.outcome} value={selected?.outcome} />
            </div>
            <div><Label>{c.payload}</Label><div className="mt-2"><JsonPanel data={selected?.payload || {}} maxHeight="max-h-[500px]" /></div></div>
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
  return <div className="rounded-lg border bg-muted/20 p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 break-all text-sm">{value || "-"}</div></div>
}

function AccessBadge({ access, labels }: { access: string; labels: Record<string, string> }) {
  if (access === "write") return <Badge variant="warning">{labels.writeLevel}</Badge>
  if (access === "read") return <Badge variant="success">{labels.readLevel}</Badge>
  return <Badge variant="secondary">{labels.noneLevel}</Badge>
}

function accessLabel(access: string, labels: Record<string, string>) {
  if (access === "write") return labels.writeLevel
  if (access === "read") return labels.readLevel
  return labels.noneLevel
}

function OutcomeBadge({ outcome, labels }: { outcome: InvocationAudit["outcome"]; labels: Record<string, string> }) {
  const variant = outcome === "success" ? "success" : outcome === "error" ? "danger" : "secondary"
  return <Badge variant={variant}>{labels[outcome]}</Badge>
}

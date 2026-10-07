import { InvocationPayloadPanel, payloadText, type InvocationDetail } from "@/components/invocation-payload-panel"
import { ExternalGrantsPage } from "@/pages/external-connections-page"
import { useCallback, useEffect, useRef, useState } from "react"
import { Alert, Button, Drawer, Input, Table } from "antd"
import { request, queryString } from "@/api/http"
import { PageHeader } from "@/components/page-shell"
import { useRemainingViewport } from "@/components/use-remaining-viewport"
import { usePageRefresh } from "@/components/page-refresh"
import { formatDateTime } from "@/lib/utils"
import type { Locale, TFunction } from "@/i18n"
import type { ConsoleView } from "@/routing/console-routes"
import "./personal-workspace-page.css"

export type PersonalWorkspaceViewState = { query: string; page: number; selectedId: string; detailPage: number; scrollTop: number }
export const initialPersonalWorkspaceView: PersonalWorkspaceViewState = { query: "", page: 1, selectedId: "", detailPage: 1, scrollTop: 0 }

type Service = { id: string; name: string; tool_count: number; read_tool_count: number; write_tool_count: number }
type ServiceDetail = Service & { tools: Array<{ id: string; name: string; description: string; required_access: string }> }
export function personalToolAccessLabel(access: string, locale: Locale) {
  if (access === "read") return locale === "zh-CN" ? "只读" : "Read only"
  if (access === "write") return locale === "zh-CN" ? "读写" : "Read and write"
  return locale === "zh-CN" ? "待确认" : "Unconfirmed"
}
export function personalCallLabel(value: string, locale: Locale) {
  const labels: Record<string, [string, string]> = { allow: ["允许", "Allowed"], deny: ["拒绝", "Denied"], success: ["成功", "Succeeded"], error: ["失败", "Failed"], not_invoked: ["未执行", "Not invoked"] }
  return labels[value]?.[locale === "zh-CN" ? 0 : 1] ?? value
}
type Audit = { id: string; correlation_id: string; server_id: string; tool_id: string; decision: string; outcome: string; created_at: string }

type PersonalWorkspaceProps = {
  view: "myServers" | "myConnections" | "myInvocations"; locale: Locale; t: TFunction
  viewState?: PersonalWorkspaceViewState; onViewStateChange?: (state: PersonalWorkspaceViewState) => void
  onNavigate: (view: ConsoleView) => unknown; onInvoke: (toolId: string) => unknown
}

export function PersonalWorkspacePage(props: PersonalWorkspaceProps) {
  return props.view === "myConnections" ? <ExternalGrantsPage locale={props.locale} t={props.t} /> : <PersonalResourcesPage {...props} />
}
function PersonalResourcesPage({ view, locale, t, onInvoke, viewState = initialPersonalWorkspaceView, onViewStateChange }: PersonalWorkspaceProps) {
  const zh = locale === "zh-CN"
  const [query, setQuery] = useState(viewState.query)
  const [page, setPage] = useState(viewState.page)
  const [services, setServices] = useState<Service[]>([])
  const [audits, setAudits] = useState<Audit[]>([])
  const [total, setTotal] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [detail, setDetail] = useState<ServiceDetail | null>(null)
  const [selected, setSelected] = useState(viewState.selectedId)
  const [detailPage, setDetailPage] = useState(viewState.detailPage)
  const [scrollTop, setScrollTop] = useState(viewState.scrollTop)
  const tableRegion = useRemainingViewport()
  const restoreTop = useRef(viewState.scrollTop)
  const notifyView = useRef(onViewStateChange)
  notifyView.current = onViewStateChange
  useEffect(() => { notifyView.current?.({ query, page, selectedId: selected, detailPage, scrollTop }) }, [query, page, selected, detailPage, scrollTop])
  const [auditSelected, setAuditSelected] = useState("")
  const [auditDetail, setAuditDetail] = useState<InvocationDetail | null>(null)
  const [auditError, setAuditError] = useState("")
  const auditGeneration = useRef(0)
  const [detailError, setDetailError] = useState("")
  const generation = useRef(0)
  const detailGeneration = useRef(0)
  const serverQuery = view === "myServers" ? query : ""
  const serverPage = view === "myServers" ? page : 1
  const load = useCallback(async () => {
    if (view === "myConnections") return
    const revision = ++generation.current
    setBusy(true); setError("")
    try {
      if (view === "myServers") {
        const result = await request<{ servers: Service[]; total: number }>(`/v1/me/mcp-servers${queryString({ q: serverQuery, offset: (serverPage - 1) * 20, limit: 20 })}`)
        if (revision === generation.current) { setServices(result.servers); setTotal(result.total) }
      } else {
        const result = await request<{ audits: Audit[] }>("/v1/me/invocations?limit=500")
        if (revision === generation.current) setAudits(result.audits)
      }
    } catch (cause) { if (revision === generation.current) setError(String(cause)) }
    finally { if (revision === generation.current) setBusy(false) }
  }, [view, serverQuery, serverPage])
  useEffect(() => { void load(); return () => { generation.current++ } }, [load])
  usePageRefresh(load, busy)
  async function fetchDetail(id: string) {
    const revision = ++detailGeneration.current
    setDetail(null); setDetailError("")
    try {
      const result = await request<ServiceDetail>(`/v1/me/mcp-servers/${encodeURIComponent(id)}`)
      if (revision === detailGeneration.current) setDetail(result)
    } catch (cause) { if (revision === detailGeneration.current) setDetailError(String(cause)) }
  }
  useEffect(() => {
    if (selected && view === "myServers") void fetchDetail(selected)
    return () => { detailGeneration.current++ }
  }, [selected, view])
  useEffect(() => {
    const body = tableRegion.current?.querySelector<HTMLElement>(".ant-table-body")
    if (body) body.scrollTop = restoreTop.current
  }, [services, audits, page, query])
  useEffect(() => {
    auditGeneration.current++
    setAuditSelected(""); setAuditDetail(null); setAuditError("")
  }, [view])
  useEffect(() => () => { auditGeneration.current++ }, [])
  async function loadAudit(id: string) {
    const revision = ++auditGeneration.current
    setAuditSelected(id); setAuditDetail(null); setAuditError("")
    try {
      const result = await request<InvocationDetail>(`/v1/me/invocations/${encodeURIComponent(id)}`)
      if (revision === auditGeneration.current) setAuditDetail(result)
    } catch (cause) { if (revision === auditGeneration.current) setAuditError(String(cause)) }
  }
  async function copyAudit(side: "input" | "output") {
    const id = auditSelected
    const revision = ++auditGeneration.current
    let fresh: InvocationDetail
    try { fresh = await request<InvocationDetail>(`/v1/me/invocations/${encodeURIComponent(id)}`) }
    catch (cause) {
      if (revision === auditGeneration.current) { setAuditDetail(null); setAuditError(String(cause)) }
      throw cause
    }
    if (revision !== auditGeneration.current) throw new Error("Selection changed")
    const text = payloadText(fresh[side])
    setAuditDetail(fresh)
    if (text === null) throw new Error("Content unavailable")
    await navigator.clipboard.writeText(text)
  }
  function changePage(next: number) { restoreTop.current = 0; setScrollTop(0); setPage(next) }
  function openDetail(id: string) { setDetailPage(1); setSelected(id) }
  const title = view === "myServers" ? (zh ? "我的 MCP" : "My MCP") : view === "myConnections" ? (zh ? "我的连接" : "My connections") : (zh ? "我的调用" : "My invocations")
  const filtered = audits.filter(item => `${item.server_id} ${item.tool_id} ${item.correlation_id} ${item.outcome}`.toLowerCase().includes(query.toLowerCase()))
  return <div className="personal-workspace-page" ref={tableRegion}>
    {view !== "myConnections" && <PageHeader closeLabel={t("close")} title={title} />}
    {error && <Alert type="error" title={error} action={<Button onClick={() => void load()}>{t("refresh")}</Button>} />}
    {view === "myConnections" ? <ExternalGrantsPage locale={locale} t={t} /> : <>
      <Input.Search aria-label={zh ? "搜索" : "Search"} placeholder={view === "myServers" ? (zh ? "搜索获准的服务或工具" : "Search authorized services or tools") : (zh ? "搜索已加载的最近500条本人记录" : "Search up to 500 loaded personal records")} value={query} onChange={event => { setQuery(event.target.value); changePage(1) }} allowClear />
      {view === "myServers" && <p className="text-sm text-muted-foreground">{zh ? "仅显示当前账号获准查看的工具所属服务；已配置但没有可见工具的服务不会列在这里。" : "Services with tools visible to your account. Configured services without visible tools are not listed here."}</p>}
      {view === "myServers" ? <Table locale={{ emptyText: query.trim() ? t("noMatchingRecords") : t("noData") }} className="personal-services-table" rowKey="id" size="small" loading={busy} onScroll={event => { restoreTop.current = event.currentTarget.scrollTop; setScrollTop(event.currentTarget.scrollTop) }} dataSource={error ? [] : services} scroll={{ x: 500, y: "100%" }} pagination={{ current: page, pageSize: 20, total, hideOnSinglePage: true, showSizeChanger: false, onChange: changePage }} columns={[
        { title: zh ? "服务" : "Service", dataIndex: "name", render: (name: string, item: Service) => <Button type="link" onClick={() => void openDetail(item.id)}>{name}</Button> },
        { title: zh ? "可见工具" : "Visible tools", dataIndex: "tool_count" },
        { title: zh ? "只读" : "Read", dataIndex: "read_tool_count" },
        { title: zh ? "写入" : "Write", dataIndex: "write_tool_count" },
      ]} /> : <>
        <p className="text-sm text-muted-foreground">{zh ? "仅本人的最近记录；最多加载500条，非全量统计。" : "Only your recent records; up to 500 loaded, not an all-time total."}</p>
        <Table locale={{ emptyText: query.trim() ? t("noMatchingRecords") : t("noData") }} rowKey="id" size="small" loading={busy} onScroll={event => { restoreTop.current = event.currentTarget.scrollTop; setScrollTop(event.currentTarget.scrollTop) }} dataSource={error ? [] : filtered} pagination={{ current: page, pageSize: 20, showSizeChanger: false, hideOnSinglePage: true, onChange: changePage }} scroll={{ x: 700, y: "100%" }} columns={[
          { title: zh ? "时间" : "Time", dataIndex: "created_at", render: (value: string) => formatDateTime(value) }, { title: zh ? "服务" : "Service", dataIndex: "server_id" },
          { title: zh ? "工具" : "Tool", dataIndex: "tool_id" }, { title: zh ? "授权决定" : "Decision", dataIndex: "decision", render: (value: string) => personalCallLabel(value, locale) }, { title: zh ? "结果" : "Outcome", dataIndex: "outcome", render: (value: string) => personalCallLabel(value, locale) },
          { title: zh ? "操作" : "Actions", key: "detail", fixed: "right", width: 132, render: (_, item: Audit) => <Button onClick={() => void loadAudit(item.id)}>{zh ? "查看详情" : "Details"}</Button> },
        ]} />
      </>}
    </>}
    <Drawer className="personal-tools-drawer" title={detail?.name || (zh ? "服务工具" : "Service tools")} open={view === "myServers" && Boolean(selected)} onClose={() => { detailGeneration.current++; setSelected(""); setDetail(null) }} size="large">
      <p className="mb-3 break-all text-xs text-muted-foreground">{zh ? "服务 ID" : "Service ID"}: {selected}</p>
      {detailError && <Alert type="error" title={detailError} action={<Button onClick={() => void fetchDetail(selected)}>{t("refresh")}</Button>} />}
      <Table rowKey="id" size="small" loading={!detail && !detailError} dataSource={detail?.tools || []} pagination={{ current: detailPage, pageSize: 20, hideOnSinglePage: true, showSizeChanger: false, onChange: setDetailPage }} scroll={{ x: 420, y: "100%" }} columns={[
        { title: zh ? "工具" : "Tool", dataIndex: "name" }, { title: zh ? "权限" : "Access", dataIndex: "required_access", width: 110, render: (access: string) => <span className="whitespace-nowrap">{personalToolAccessLabel(access, locale)}</span> },
        { title: zh ? "操作" : "Actions", key: "actions", render: (_, item) => <Button onClick={() => onInvoke(item.id)}>{zh ? "测试工具" : "Test tool"}</Button> },
      ]} />
    </Drawer>
    <Drawer title={zh ? "本人调用详情" : "My invocation detail"} open={Boolean(auditSelected)} onClose={() => { auditGeneration.current++; setAuditSelected(""); setAuditDetail(null); setAuditError("") }} size="large">
      <div className="space-y-4">
        <p className="break-all text-sm">{auditSelected}</p>
        <p className="text-sm text-muted-foreground">{zh ? "仅显示记录时已保留、已脱敏的内容。未记录或已清理的原文不可恢复；脱敏无法自动识别所有业务秘密。" : "Only retained, redacted content is available. Unrecorded or deleted originals cannot be recovered; redaction cannot identify every business secret."}</p>
        {auditError && <Alert type="error" title={auditError} action={<Button onClick={() => void loadAudit(auditSelected)}>{t("refresh")}</Button>} />}
        {!auditDetail && !auditError && <p role="status">{zh ? "正在加载…" : "Loading…"}</p>}
        {auditDetail && <>
          <p className="break-all text-sm">{auditDetail.audit.tool_id} · {formatDateTime(auditDetail.audit.created_at)} · {personalCallLabel(auditDetail.audit.outcome, locale)}</p>
          <InvocationPayloadPanel key={`${auditSelected}:input`} title={zh ? "输入" : "Input"} payload={auditDetail.input} locale={locale} onCopy={() => copyAudit("input")} />
          <InvocationPayloadPanel key={`${auditSelected}:output`} title={zh ? "输出" : "Output"} payload={auditDetail.output} locale={locale} onCopy={() => copyAudit("output")} />
        </>}
      </div>
    </Drawer>
  </div>
}

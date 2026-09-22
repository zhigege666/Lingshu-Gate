import { useEffect, useMemo, useState, type ReactNode } from "react"
import {
  ArrowLeftOutlined, ArrowRightOutlined, CloudServerOutlined, CodeOutlined, ExportOutlined,
  InfoCircleOutlined, MoreOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, UnorderedListOutlined,
} from "@ant-design/icons"
import { Alert, Badge, Button, Collapse, Drawer, Dropdown, Empty, Grid, Input, Segmented, Skeleton, Table, Tabs, Tag, Tooltip, type TableColumnsType } from "antd"
import type { McpServer, McpServerDetailSlice, ToolClassification, ToolDefinition } from "@/api/client"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { serverCopy, type ServerCopy } from "@/features/servers/copy"
import { useServerDetails, type DetailSection, type DetailState } from "@/features/servers/use-server-details"
import { localizeStatus, type Locale, type TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import type { ConsoleView } from "@/routing/console-routes"

type Action = "start" | "stop" | "restart"
type MainTab = "overview" | "tools" | "logs" | "configuration"
type LogTab = "logs" | "events" | "recovery"
type RecordValue = Record<string, unknown>
type ToolRow = { key: string; name: string; description: string; schema: RecordValue; raw: RecordValue }
type LogRow = { key: string; time: string; level: string; type: string; message: string; raw: RecordValue }
type Props = {
  locale: Locale
  t: TFunction
  servers: McpServer[]
  loadErrors: string[]
  busy: boolean
  visibleTools: ToolDefinition[] | null
  toolsError: string | null
  canReadTools: boolean
  canManageClassifications: boolean
  onServerAction: (id: string, action: Action) => Promise<void> | void
  onRefresh: () => Promise<void> | void
  onNewConfig: () => void
  onNavigate: (view: ConsoleView) => void
}

export function ServersPage(props: Props) {
  const { t, servers, locale } = props
  const c = serverCopy(locale)
  const screens = Grid.useBreakpoint()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState("all")
  const [tab, setTab] = useState<MainTab>("overview")
  const [logTab, setLogTab] = useState<LogTab>("logs")
  const [toolQuery, setToolQuery] = useState("")
  const [selectedTool, setSelectedTool] = useState<ToolRow | null>(null)
  const [selectedRecord, setSelectedRecord] = useState<RecordValue | null>(null)
  const [actionBusy, setActionBusy] = useState(false)
  const selected = servers.find(server => server.id === selectedId) || null
  const { states, load } = useServerDetails(selected?.id || null, servers, props.canManageClassifications)
  const activeSection: DetailSection = tab === "logs" ? logTab : tab

  function chooseServer(id: string | null) {
    setSelectedId(id)
    setTab("overview")
    setToolQuery("")
    setSelectedTool(null)
    setSelectedRecord(null)
  }

  useEffect(() => {
    if (selectedId && !servers.some(server => server.id === selectedId)) {
      chooseServer(screens.md && servers[0] ? servers[0].id : null)
    } else if (!selectedId && screens.md && servers[0]) {
      chooseServer(servers[0].id)
    }
  }, [selectedId, servers, screens.md])
  useEffect(() => {
    if (!selected) return
    void load(activeSection)
    if (activeSection !== "overview") void load("overview")
  }, [selected?.id, activeSection, servers, load])

  const filteredServers = useMemo(() => servers.filter(server => {
    if (filter === "running" && server.status !== "running") return false
    if (filter === "issues" && !["failed", "unsupported"].includes(server.status) && !server.last_error && !server.restore_blocked_reason) return false
    const needle = query.trim().toLowerCase()
    return !needle || [server.id, server.name, server.last_error].filter(Boolean).join(" ").toLowerCase().includes(needle)
  }), [servers, query, filter])
  const runningCount = servers.filter(server => server.status === "running").length
  const issueCount = servers.filter(server => ["failed", "unsupported"].includes(server.status) || server.last_error || server.restore_blocked_reason).length
  const server = states.overview?.data?.server || selected
  const visible = selected && props.visibleTools ? props.visibleTools.filter(tool => tool.source === "mcp" && asRecord(tool.metadata).server_id === selected.id) : null
  const preview = visible ? toTools(visible.map(tool => asRecord(tool))) : []
  const classifications = states.overview?.classifications
  const published = classifications?.filter(item => item.status === "published" && asRecord(item.evidence.lifecycle).status !== "retired").length
  const classificationByName = useMemo(() => {
    const result = new Map<string, ToolClassification>()
    for (const item of classifications || []) {
      result.set(item.tool_name, item)
      result.set(item.tool_id, item)
    }
    return result
  }, [classifications])

  function classification(row: ToolRow) {
    const item = classificationByName.get(row.name) || classificationByName.get(String(row.raw.id || ""))
    if (item?.status === "published") return <Tag color={item.effective_access === "read" ? "success" : "warning"}>{item.effective_access === "read" ? c.read : c.write}</Tag>
    if (item) return <Tag>{c.review}</Tag>
    return <span className="service-description">{c.unknownAccess}</span>
  }

  const toolColumns: TableColumnsType<ToolRow> = [
    { title: c.name, dataIndex: "name", key: "name", width: "30%", render: (_, row) => <Button type="link" size="small" className="service-tool-name" onClick={() => setSelectedTool(row)} title={row.name}>{row.name}</Button> },
    { title: c.description, dataIndex: "description", key: "description", ellipsis: true, render: text => <span className="service-description" title={text}>{text || "-"}</span> },
    { title: c.classification, key: "classification", width: 120, render: (_, row) => classification(row) },
  ]
  const logColumns: TableColumnsType<LogRow> = [
    { title: c.time, dataIndex: "time", key: "time", width: 165 },
    { title: c.level, dataIndex: "level", key: "level", width: 80, render: value => <Tag color={value === "error" ? "error" : value === "warning" ? "warning" : undefined}>{value || "-"}</Tag> },
    { title: c.eventType, dataIndex: "type", key: "type", width: 190, ellipsis: true },
    { title: c.message, key: "message", ellipsis: true, render: (_, row) => <Button type="link" size="small" onClick={() => setSelectedRecord(row.raw)} title={row.message}>{row.message || c.recordDetails}</Button> },
  ]
  const actions = server ? server.allowed_actions ?? fallbackActions(server.status) : []
  async function runAction(action: Action) {
    if (!server || !actions.includes(action)) return
    setActionBusy(true)
    try { await props.onServerAction(server.id, action) }
    finally { setActionBusy(false) }
  }
  const actionName = (action: Action) => action === "start" ? (server?.launch_type === "external" ? c.connect : c.start) : action === "stop" ? (server?.launch_type === "external" ? c.disconnect : c.stop) : c.restart
  const rows = toTools(states.tools?.data?.tools || [])
  const filteredTools = rows.filter(row => [row.name, row.description].join(" ").toLowerCase().includes(toolQuery.trim().toLowerCase()))

  const overview = server && <div>
    {states.overview?.error && <Alert className="service-panel-error" type="warning" showIcon title={c.loadFailed} description={states.overview.error} action={<Button onClick={() => void load("overview", true)}>{c.retry}</Button>} />}
    {(server.last_error || server.restore_blocked_reason) && <Alert className="service-panel-error" type="error" showIcon title={c.lastError} description={server.last_error || server.restore_blocked_reason} />}
    <div className="service-summary-grid">
      <section>
        <h2 className="service-section-title"><CodeOutlined aria-hidden="true" />{c.connection}</h2>
        <dl className="service-facts">
          <dt>{c.transport}</dt><dd>{server.transport_type}</dd>
          <dt>{c.process}</dt><dd><RuntimeBadge server={server} t={t} /></dd>
          <dt>{c.launch}</dt><dd>{server.launch_type}</dd>
          <dt>{c.pid}</dt><dd>{server.pid ?? "-"}</dd>
          <dt>{c.discovered}</dt><dd>{server.tool_count}</dd>
          <dt>{c.health}</dt><dd>{asRecord(asRecord(server.restart_policy).health_check).enabled ? localizeStatus(t, server.health_status || "unknown") : <>{c.healthOff}<span className="service-fact-note">{c.healthOffHint}</span></>}</dd>
        </dl>
      </section>
      <section>
        <h2 className="service-section-title"><CloudServerOutlined aria-hidden="true" />{c.readiness}</h2>
        <dl className="service-facts">
          <dt>{c.discovered}</dt><dd>{server.tool_count}</dd>
          <dt>{c.published}</dt><dd>{!props.canManageClassifications ? c.noClassificationAccess : states.overview?.loading ? c.loading : states.overview?.classificationError ? c.unread : published === undefined ? c.unread : <Button type="link" size="small" style={{ padding: 0, height: "auto" }} onClick={() => props.onNavigate("toolClassifications")} aria-label={`${c.openClassification} · ${published}`}>{published}<ArrowRightOutlined /></Button>}</dd>
          <dt>{c.visible}</dt><dd>{!props.canReadTools ? c.noToolsAccess : props.toolsError ? c.visibleError : visible === null ? c.loading : visible.length}<span className="service-fact-note">{c.visibleHint}</span></dd>
          <dt>{c.client}</dt><dd>{c.clientUnknown} <Tooltip title={c.clientHint}><InfoCircleOutlined /></Tooltip><span className="service-fact-note">{c.clientHint}</span></dd>
        </dl>
      </section>
    </div>
    <section className="service-preview">
      <div className="service-section-heading">
        <h2 className="service-section-title"><UnorderedListOutlined aria-hidden="true" />{c.preview}</h2>
        <Button type="link" onClick={() => setTab("tools")}>{c.allTools}<ArrowRightOutlined /></Button>
      </div>
      {props.canReadTools && visible === null && !props.toolsError ? <Skeleton active paragraph={{ rows: 3 }} /> :
        <Table className="service-table" columns={toolColumns} dataSource={preview.slice(0, 4)} pagination={false} size="small" tableLayout="fixed" locale={{ emptyText: props.toolsError ? c.visibleError : !props.canReadTools ? c.noToolsAccess : c.noTools }} />}
    </section>
  </div>

  return <div className="server-workspace" data-selected={Boolean(selected)}>
    <aside className="service-directory" aria-label={c.directory}>
      <div className="service-directory-header">
        <div className="service-directory-title"><h2>{c.directory}</h2><Tooltip title={c.refresh}><Button type="text" size="small" loading={props.busy} icon={<ReloadOutlined />} onClick={() => void props.onRefresh()} aria-label={c.refresh} /></Tooltip></div>
        <PageToolbar query={query} onQueryChange={setQuery} placeholder={c.search} clearLabel={t("clearSearch")} />
        <Segmented aria-label={c.directory} block size="large" value={filter} onChange={value => setFilter(String(value))} options={[
          { value: "all", label: c.all + " (" + servers.length + ")" },
          { value: "running", label: c.running + " (" + runningCount + ")" },
          { value: "issues", label: c.issues + " (" + issueCount + ")" },
        ]} />
      </div>
      {props.loadErrors.length > 0 && <Alert type="error" showIcon title={c.loadFailed} description={props.loadErrors.join("; ")} />}
      <div className="service-directory-list">
        {filteredServers.map(item => <button key={item.id} className="service-entry" data-active={item.id === selectedId} aria-pressed={item.id === selectedId} onClick={() => chooseServer(item.id)}>
          <span><span className="service-entry-name" title={item.name || item.id}>{item.name || item.id}</span><span className="service-entry-subtitle" title={item.id}>{item.id}</span></span>
          <span className="service-entry-meta"><RuntimeBadge server={item} t={t} /><span className="service-entry-count">{item.tool_count}</span></span>
        </button>)}
        {filteredServers.length === 0 && <div className="inline-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={servers.length ? c.noMatches : <>{c.emptyServices}<p className="service-fact-note">{c.emptyHint}</p></>} /></div>}
      </div>
      <div className="service-directory-footer"><Button block icon={<PlusOutlined />} onClick={props.onNewConfig}>{c.add}</Button></div>
    </aside>

    <section className="service-detail" aria-label={selected ? selected.id : c.selectService}>
      {server ? <>
        <Button type="text" className="service-detail-back" icon={<ArrowLeftOutlined />} onClick={() => chooseServer(null)}>{c.back}</Button>
        <div className="service-breadcrumb">{c.directory} <span aria-hidden="true">/</span> {server.id}</div>
        <PageHeader variant="detail" title={server.name || server.id} description={server.id} titleExtra={<RuntimeBadge server={server} t={t} pill />} actions={<>
          <Button type="primary" size="large" icon={<ExportOutlined />} onClick={() => setTab("tools")}>{c.viewTools}</Button>
          <Dropdown trigger={["click"]} menu={{ items: actions.map(action => ({ key: action, label: actionName(action), danger: action === "stop", disabled: actionBusy || props.busy })), onClick: ({ key }) => { if (actions.includes(key as Action)) void runAction(key as Action) } }}>
            <Button size="large" icon={<MoreOutlined />} loading={actionBusy} disabled={actions.length === 0} aria-label={c.more} />
          </Dropdown>
        </>} />
        <div className="service-detail-identity"><code>{server.launch_type} / {server.transport_type}</code></div>
        <Tabs className="service-detail-tabs" activeKey={tab} onChange={value => setTab(value as MainTab)} items={[
          { key: "overview", label: c.overview, children: overview },
          { key: "tools", label: c.tools + " " + server.tool_count, children: <SectionContent state={states.tools} c={c} onRetry={() => void load("tools", true)}>{() => <>
            <div className="service-panel-toolbar"><Input value={toolQuery} onChange={event => setToolQuery(event.target.value)} placeholder={c.searchTools} aria-label={c.searchTools} prefix={<SearchOutlined />} allowClear /><Button icon={<ReloadOutlined />} onClick={() => void load("tools", true)}>{c.refresh}</Button></div>
            <Table className="service-table" columns={toolColumns} dataSource={filteredTools} size="small" tableLayout="fixed" pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 25, 50], hideOnSinglePage: true }} scroll={{ x: 620 }} locale={{ emptyText: c.noTools }} />
          </>}</SectionContent> },
          { key: "logs", label: c.logs, children: <div className="service-panel-stack">
            <div className="service-panel-toolbar"><Segmented aria-label={c.logs} value={logTab} onChange={value => setLogTab(value as LogTab)} options={[{ value: "logs", label: c.serviceLogs }, { value: "events", label: c.events }, { value: "recovery", label: c.recovery }]} /><Button icon={<ReloadOutlined />} onClick={() => void load(logTab, true)} aria-label={c.refresh} /></div>
            <SectionContent state={states[logTab]} c={c} onRetry={() => void load(logTab, true)}>{data => <>
              <Table className="service-table" columns={logColumns} dataSource={toLogs(logTab === "logs" ? data.logs || [] : logTab === "events" ? data.events || [] : data.restart_history || [])} pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }} size="small" scroll={{ x: 680 }} tableLayout="fixed" locale={{ emptyText: c.noRecords }} />
              <div className="service-panel-toolbar"><span className="service-fact-note">{c.logLimit}</span><Button type="link" onClick={() => props.onNavigate("logs")}>{c.openLogs}<ArrowRightOutlined /></Button></div>
            </>}</SectionContent>
          </div> },
          { key: "configuration", label: c.configuration, children: <div className="service-panel-stack">
            <SectionContent state={states.configuration} c={c} onRetry={() => void load("configuration", true)}>{data => <>
              <h2 className="service-section-title"><CodeOutlined aria-hidden="true" />{c.manifest}</h2>
              <dl className="service-facts">
                <dt>{c.desired}</dt><dd>{server.desired_state === "running" ? c.keepRunning : server.desired_state === "stopped" ? c.keepStopped : "-"}</dd>
                <dt>{c.lastStarted}</dt><dd>{formatDateTime(server.last_started_at)}</dd>
                <dt>{c.configPath}</dt><dd>{server.manifest_path || "-"}</dd>
              </dl>
              <JsonPanel data={data.manifest || {}} maxHeight="max-h-[480px]" />
            </>}</SectionContent>
            <Collapse onChange={keys => { if (keys.includes("cache")) void load("cache"); if (keys.includes("diagnostics")) void load("diagnostics") }} items={[
              { key: "cache", label: c.runtimeCache, children: <><p className="service-fact-note">{c.cacheHint}</p><SectionContent state={states.cache} c={c} onRetry={() => void load("cache", true)}>{data => <JsonPanel data={data.runtime_cache || {}} />}</SectionContent></> },
              { key: "diagnostics", label: c.fullDiagnostics, children: <><p className="service-fact-note">{c.diagnosticHint}</p><SectionContent state={states.diagnostics} c={c} onRetry={() => void load("diagnostics", true)}>{data => <div className="service-panel-stack">{(data.failure_hints || []).map(hint => <Alert key={hint.code} showIcon type={hint.severity === "error" ? "error" : hint.severity === "warning" ? "warning" : "info"} title={hint.code} description={hint.message} />)}</div>}</SectionContent></> },
            ]} />
          </div> },
        ]} />
      </> : <div className="service-unselected"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={c.selectService} /></div>}
    </section>

    <Drawer className="service-tool-drawer" title={selectedTool?.name || c.toolDetails} size={560} open={selectedTool !== null} onClose={() => setSelectedTool(null)} destroyOnHidden>
      {selectedTool && <div className="service-panel-stack">
        <p className="service-description" style={{ whiteSpace: "normal" }}>{selectedTool.description}</p>
        <h3 className="service-section-title"><CodeOutlined aria-hidden="true" />{c.inputSchema}</h3>
        <JsonPanel data={selectedTool.schema} maxHeight="max-h-[480px]" />
        <Collapse items={[{ key: "metadata", label: c.metadata, children: <JsonPanel data={selectedTool.raw} maxHeight="max-h-80" /> }]} />
      </div>}
    </Drawer>
    <Drawer title={c.recordDetails} size={640} open={selectedRecord !== null} onClose={() => setSelectedRecord(null)} destroyOnHidden>
      {selectedRecord && <JsonPanel data={selectedRecord} maxHeight="max-h-[calc(100vh-140px)]" />}
    </Drawer>
  </div>
}

function RuntimeBadge({ server, t, pill = false }: { server: McpServer; t: TFunction; pill?: boolean }) {
  const status = server.status === "running" ? "success" : ["failed", "unsupported"].includes(server.status) ? "error" : server.status === "starting" ? "processing" : "default"
  const badge = <Badge status={status} text={localizeStatus(t, server.status)} />
  return pill ? <Tag className="service-title-state" color={status === "default" ? undefined : status}>{badge}</Tag> : badge
}

function SectionContent({ state, c, onRetry, children }: { state?: DetailState; c: ServerCopy; onRetry: () => void; children: (data: McpServerDetailSlice) => ReactNode }) {
  if (state?.error) return <Alert type="error" showIcon title={c.loadFailed} description={state.error} action={<Button onClick={onRetry}>{c.retry}</Button>} />
  if (!state?.data || state.loading) return <Skeleton active paragraph={{ rows: 4 }} />
  return <>{children(state.data)}</>
}

function asRecord(value: unknown): RecordValue {
  return value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {}
}

function toTools(values: RecordValue[]): ToolRow[] {
  return values.map((raw, index) => ({
    key: String(raw.id || raw.name || index),
    name: String(raw.name || raw.id || "-"),
    description: typeof raw.description === "string" ? raw.description : "",
    schema: asRecord(raw.input_schema || raw.inputSchema),
    raw,
  }))
}

function toLogs(values: object[]): LogRow[] {
  return values.map((value, index) => {
    const raw = asRecord(value)
    return { key: String(raw.id || index), time: formatDateTime(String(raw.created_at || "")), level: String(raw.level || ""), type: String(raw.event_type || raw.type || ""), message: String(raw.message || raw.type || ""), raw }
  })
}

function fallbackActions(status: string): Action[] {
  const normalized = status.toLowerCase()
  if (["loaded", "stopped", "failed"].includes(normalized)) return ["start"]
  if (normalized === "starting") return ["stop"]
  if (normalized === "running") return ["restart", "stop"]
  return []
}

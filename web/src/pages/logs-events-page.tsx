import "./logs-events-page.css"
import { RetentionPolicySettings } from "@/components/retention-policy-settings"
import { FilterRadio } from "@/components/filter-radio"
import { changeLogScope } from "@/features/observability/model"
import { ObservabilityMcpSelector } from "@/components/observability-mcp-selector"
import { cleanObservabilityFilters, createRequestOwner, observabilityHash, readObservabilityHash } from "@/features/observability/model"
import { RemainingList, ListViewport } from "@/components/list-pagination"
import { usePageRefresh } from "@/components/page-refresh"
import { QueryStatus, querySignature } from "@/components/query-status"
import { useEffect, useMemo, useRef, useState } from "react"
import { Tabs } from "antd"
import { api, type EventFilters, type LogFilters, type ObservabilityEvent, type ObservabilityLog } from "@/api/client"
import { PageHeader } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table"
import { JsonPanel } from "@/components/json-panel"
import { ColGroup, Pager, SortHead, useColumnWidths, usePagedSorted } from "@/components/table-tools"
import { localizeStatus, type TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const ALL_VALUE = "__all__"
const LIMIT_OPTIONS = [50, 80, 100, 200, 500]
const LEVEL_OPTIONS = ["debug", "info", "warning", "error"]
type SnapshotSource = "logs" | "events"
type QuerySnapshot = { logs: LogFilters; events: EventFilters }

export function LogsEventsPage({ t, canManageRetention = false }: { t: TFunction; canManageRetention?: boolean }) {
  const [loadingSources, setLoadingSources] = useState({ logs: false, events: false })
  const busy = loadingSources.logs || loadingSources.events
  const [errors, setErrors] = useState<Record<SnapshotSource, string | null>>({ logs: null, events: null })
  const [logs, setLogs] = useState<ObservabilityLog[]>([])
  const [events, setEvents] = useState<ObservabilityEvent[]>([])
  const [selectedPayload, setSelectedPayload] = useState<unknown | null>(null)
  const [snapshotTimes, setSnapshotTimes] = useState({ logs: "", events: "" })
  const [initial] = useState(() => readObservabilityHash(typeof window === "undefined" ? "" : window.location.hash))
  const [logFilters, setLogFilters] = useState<LogFilters>(initial.logs)
  const [eventFilters, setEventFilters] = useState<EventFilters>(initial.events)
  const [applied, setApplied] = useState({ logs: { limit: 80 } as LogFilters, events: { limit: 80 } as EventFilters })
  const appliedRef = useRef(applied)
  const [activeTab, setActiveTab] = useState<"logs" | "events">(initial.tab)
  const activeTabRef = useRef(activeTab)
  activeTabRef.current = activeTab
  const knownHash = useRef(typeof window === "undefined" ? "" : window.location.hash)
  const requestOwners = useRef({ logs: createRequestOwner(), events: createRequestOwner() })
  const activeRequests = useRef<Partial<Record<SnapshotSource, AbortController>>>({})
  const draftFilters = useRef<QuerySnapshot>({ logs: initial.logs, events: initial.events })
  const queryTimer = useRef<number | undefined>(undefined)
  const queuedSources = useRef(new Set<SnapshotSource>())
  const failedSnapshot = useRef<Partial<QuerySnapshot>>({})
  const zh = t("all") === "全部"
  const selectedScope = logFilters.server_id || ""
  const error = errors[activeTab]
  const lastLoadedAt = snapshotTimes[activeTab]

  const filterLabels: Record<string, string> = { level: t("level"), server_id: t("serverId"), subject_id: t("serverId"), tool_id: t("toolId"), event_type: t("eventType"), source: t("source"), keyword: t("keyword"), limit: t("limit") }
  const currentApplied = activeTab === "logs" ? applied.logs : applied.events
  const hasAppliedFilters = Object.entries(currentApplied).some(([key, value]) => key !== "limit" && value !== undefined && value !== "")
  const emptyLabel = loadingSources[activeTab] ? t("loadingData") : error ? t("notLoaded") : hasAppliedFilters ? t("noAppliedMatches") : t("noData")
  const logEventTypes = useMemo(() => unique(logs.map((item) => item.event_type).filter(Boolean) as string[]), [logs])
  const logSources = useMemo(() => unique(logs.map((item) => item.source).filter(Boolean)), [logs])
  const eventTypes = useMemo(() => unique(events.map((item) => item.type).filter(Boolean)), [events])
  const eventSources = useMemo(() => unique(events.map((item) => item.source).filter(Boolean)), [events])
  usePageRefresh(() => { window.clearTimeout(queryTimer.current); queuedSources.current.clear(); return loadLogsEvents(draftFilters.current, true) }, busy)
  useEffect(() => {
    void loadLogsEvents({ logs: initial.logs, events: initial.events })
    function restoreHash() {
      if (!/^#\/?logs(?:\/|$)/.test(window.location.hash) || window.location.hash === knownHash.current) return
      knownHash.current = window.location.hash
      const next = readObservabilityHash(window.location.hash)
      window.clearTimeout(queryTimer.current); queuedSources.current.clear()
      draftFilters.current = { logs: next.logs, events: next.events }
      setLogFilters(next.logs); setEventFilters(next.events); setActiveTab(next.tab)
      void loadLogsEvents({ logs: next.logs, events: next.events })
    }
    window.addEventListener("hashchange", restoreHash)
    window.addEventListener("popstate", restoreHash)
    return () => {
      window.clearTimeout(queryTimer.current)
      for (const source of ["logs", "events"] as const) { activeRequests.current[source]?.abort(); requestOwners.current[source].invalidate() }
      window.removeEventListener("hashchange", restoreHash)
      window.removeEventListener("popstate", restoreHash)
    }
  }, [])

  async function loadLogsEvents(snapshot = draftFilters.current, updateUrl = false, sources: SnapshotSource[] = ["logs", "events"]) {
    // Independent request ownership lets a log filter change leave an event
    // query in flight. Only the newest request for each source can update it.
    await Promise.allSettled(sources.map(async source => {
      const owner = requestOwners.current[source]
      const id = owner.next()
      activeRequests.current[source]?.abort()
      const controller = new AbortController()
      activeRequests.current[source] = controller
      setLoadingSources(current => ({ ...current, [source]: true }))
      setErrors(current => ({ ...current, [source]: null }))
      try {
        const response = source === "logs"
          ? await api.logs(snapshot.logs, controller.signal)
          : await api.events(snapshot.events, controller.signal)
        if (!owner.owns(id) || controller.signal.aborted) return
        if ("logs" in response) setLogs(response.logs)
        else setEvents(response.events)
        delete failedSnapshot.current[source]
        const next = { ...appliedRef.current, [source]: snapshot[source] }
        appliedRef.current = next
        setApplied(next)
        setSnapshotTimes(current => ({ ...current, [source]: new Date().toISOString() }))
        // A URL only represents successful snapshots with a shared MCP scope.
        if (updateUrl) writeAppliedHash(next, activeTabRef.current)
      } catch (err) {
        if (!owner.owns(id) || controller.signal.aborted) return
        failedSnapshot.current = { ...failedSnapshot.current, [source]: snapshot[source] }
        setErrors(current => ({ ...current, [source]: err instanceof Error ? err.message : String(err) }))
      } finally {
        if (owner.owns(id) && !controller.signal.aborted) setLoadingSources(current => ({ ...current, [source]: false }))
      }
    }))
  }

  function queryFilters(snapshot: QuerySnapshot, sources: SnapshotSource[], deferred = false) {
    draftFilters.current = snapshot
    setLogFilters(snapshot.logs); setEventFilters(snapshot.events)
    sources.forEach(source => queuedSources.current.add(source))
    window.clearTimeout(queryTimer.current)
    const flush = () => {
      const pendingSources = Array.from(queuedSources.current)
      queuedSources.current.clear()
      void loadLogsEvents(draftFilters.current, true, pendingSources)
    }
    if (deferred) queryTimer.current = window.setTimeout(flush, 350)
    else flush()
  }

  function changeLogFilters(patch: Partial<LogFilters>, deferred = false) {
    queryFilters({ ...draftFilters.current, logs: cleanFilters({ ...draftFilters.current.logs, ...patch }) }, ["logs"], deferred)
  }
  function changeEventFilters(patch: Partial<EventFilters>, deferred = false) {
    queryFilters({ ...draftFilters.current, events: cleanFilters({ ...draftFilters.current.events, ...patch }) }, ["events"], deferred)
  }

  function writeAppliedHash(snapshot: { logs: LogFilters; events: EventFilters }, tab: "logs" | "events") {
    if ((snapshot.logs.server_id || "") !== (snapshot.events.server_id || "")) return
    knownHash.current = observabilityHash({ ...snapshot, tab })
    window.history.replaceState(window.history.state, "", knownHash.current)
  }

  function changeScope(server_id: string) {
    queryFilters({ logs: changeLogScope(draftFilters.current.logs, server_id), events: cleanFilters({ ...draftFilters.current.events, server_id: server_id || undefined }) }, ["logs", "events"])
  }

  function resetFilters() {
    queryFilters({ logs: { limit: 80 }, events: { limit: 80 } }, ["logs", "events"])
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader closeLabel={t("close")}
        eyebrow={t("observability")}
        title={t("logs")}
        description={t("logFiltersDesc")}
        helpLabel={t("pageHelp")}
        stats={[
          { label: t("error"), value: snapshotTimes.logs ? logs.filter((item) => item.level === "error").length : "—", tone: logs.some((item) => item.level === "error") ? "danger" : "default" },
          { label: t("updatedAt"), value: lastLoadedAt ? formatDateTime(lastLoadedAt) : t("waiting") },
        ]}
        actions={canManageRetention && <RetentionPolicySettings t={t} />}
      />
      <QueryStatus t={t} pendingChanges={false} lastLoadedAt={lastLoadedAt} summary={Object.entries(activeTab === "logs" ? applied.logs : applied.events).map(([key, value]) => `${filterLabels[key] || key}: ${value}`).join(" · ")} />
      {loadingSources[activeTab] && <p role="status" className="text-xs text-muted-foreground">{t("loadingData")}</p>}
      {error && <Alert variant="destructive" role="alert"><AlertDescription className="flex flex-wrap items-center justify-between gap-2"><span>{error}</span><Button variant="outline" disabled={busy} onClick={() => void loadLogsEvents({ ...appliedRef.current, ...failedSnapshot.current }, true, [activeTab])}>{t("retry")}</Button></AlertDescription></Alert>}
      <Card>
        <CardContent className="p-3 md:p-4" aria-busy={busy}>
          <Tabs
            activeKey={activeTab}
            onChange={next => { const tab = next === "events" ? "events" : "logs"; setActiveTab(tab); writeAppliedHash(applied, tab) }}
            items={[
              {
                key: "logs",
                label: `${t("logRows")} (${logs.length})${errors.logs ? ` · ${t("error")}` : ""}`,
                // 保留两个表格的分页、排序与列宽状态，切换标签不重新挂载。
                forceRender: true,
                children: <div className="flex flex-col gap-3">
                  {activeTab === "logs" && <div className="observability-filter-row">
                    <ObservabilityMcpSelector value={selectedScope} onChange={changeScope} zh={zh} />
                    <ObservabilityMcpSelector value={logFilters.tool_id || ""} serverId={selectedScope} onChange={tool_id => changeLogFilters({ tool_id: tool_id || undefined })} zh={zh} />
                    <FilterSelect t={t} localize label={t("level")} value={logFilters.level || ALL_VALUE} options={LEVEL_OPTIONS} onChange={(value) => changeLogFilters({ level: fromSelectValue(value) })} />
                    <FilterInput label={t("keyword")} value={logFilters.keyword || ""} onChange={(value) => changeLogFilters({ keyword: value }, true)} placeholder="stderr / timeout / example-server" />

                    <FilterSelect t={t} label={t("eventType")} value={logFilters.event_type || ALL_VALUE} options={logEventTypes} onChange={(value) => changeLogFilters({ event_type: fromSelectValue(value) })} allowCustom />
                    <FilterSelect t={t} label={t("source")} value={logFilters.source || ALL_VALUE} options={logSources} onChange={(value) => changeLogFilters({ source: fromSelectValue(value) })} allowCustom />
                    <LimitSelect t={t} value={logFilters.limit || 80} onChange={(value) => changeLogFilters({ limit: value })} />
                    <div className="observability-filter-actions"><Button variant="outline" onClick={resetFilters}>{t("resetConditions")}</Button></div>
                  </div>}
                  <LogTable filterKey={querySignature(applied.logs)} t={t} logs={logs} emptyLabel={emptyLabel} onSelect={setSelectedPayload} />
                </div>,
              },
              {
                key: "events",
                label: `${t("events")} (${events.length})${errors.events ? ` · ${t("error")}` : ""}`,
                forceRender: true,
                children: <div className="flex flex-col gap-3">
                  {activeTab === "events" && <div className="observability-filter-row">
                    <ObservabilityMcpSelector value={selectedScope} onChange={changeScope} zh={zh} />
                    <FilterInput label={t("keyword")} value={eventFilters.keyword || ""} onChange={(value) => changeEventFilters({ keyword: value }, true)} placeholder="gate.server.failed / gate.config" />

                    <FilterSelect t={t} label={t("eventType")} value={eventFilters.event_type || ALL_VALUE} options={eventTypes} onChange={(value) => changeEventFilters({ event_type: fromSelectValue(value) })} allowCustom />
                    <FilterSelect t={t} label={t("source")} value={eventFilters.source || ALL_VALUE} options={eventSources} onChange={(value) => changeEventFilters({ source: fromSelectValue(value) })} allowCustom />
                    <LimitSelect t={t} value={eventFilters.limit || 80} onChange={(value) => changeEventFilters({ limit: value })} />
                    <div className="observability-filter-actions"><Button variant="outline" onClick={resetFilters}>{t("resetConditions")}</Button></div>
                  </div>}
                  <EventTable filterKey={querySignature(applied.events)} t={t} events={events} emptyLabel={emptyLabel} onSelect={setSelectedPayload} />
                </div>,
              },
            ]}
          />
        </CardContent>
      </Card>

      <Dialog open={selectedPayload !== null} onOpenChange={(open) => { if (!open) setSelectedPayload(null) }}>
        <DialogContent closeLabel={t("close")} className="max-w-4xl">
          <DialogHeader><DialogTitle>{t("selectedPayload")}</DialogTitle><DialogDescription>{t("selectedPayloadDesc")}</DialogDescription></DialogHeader>
          <DialogBody><JsonPanel copyLabel={t("copy")} text={selectedPayload ? JSON.stringify(selectedPayload, null, 2) : t("noData")} maxHeight="max-h-[60vh]" /></DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function FilterInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="gate-form-row"><span className="gate-form-label">{label}</span><span className="gate-form-control"><Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></span></label>
}

function FilterSelect({ t, label, value, options, onChange, allowCustom = false, localize = false }: { t: TFunction; label: string; value: string; options: string[]; onChange: (value: string) => void; allowCustom?: boolean; localize?: boolean }) {
  const visibleOptions = value !== ALL_VALUE && !options.includes(value) && allowCustom ? [value, ...options] : options
  if (localize) return <div className="gate-form-row observability-choice-field"><span className="gate-form-label">{label}</span><div className="gate-form-control"><FilterRadio label={label} hideLabel value={value} onChange={onChange} options={[{ value: ALL_VALUE, label: t("all") }, ...visibleOptions.map(option => ({ value: option, label: localizeStatus(t, option) }))]} /></div></div>
  return <label className="gate-form-row"><span className="gate-form-label">{label}</span><span className="gate-form-control"><Select value={value} onValueChange={onChange}><SelectTrigger aria-label={label}><SelectValue /></SelectTrigger><SelectContent><SelectItem value={ALL_VALUE}>{t("all")}</SelectItem>{visibleOptions.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select></span></label>
}

function LimitSelect({ t, value, onChange }: { t: TFunction; value: number; onChange: (value: number) => void }) {
  return <div className="gate-form-row observability-choice-field"><span className="gate-form-label">{t("limit")}</span><div className="gate-form-control"><FilterRadio label={t("limit")} hideLabel value={String(value)} onChange={next => onChange(Number(next))} options={LIMIT_OPTIONS.map(option => ({ value: String(option), label: option }))} /></div></div>
}

function EventTable({ t, events, emptyLabel, onSelect, filterKey }: { filterKey: string; emptyLabel: string; t: TFunction; events: ObservabilityEvent[]; onSelect: (value: unknown) => void }) {
  const { pageRows, page, setPage, pageCount, total, sortKey, sortDir, toggleSort } = usePagedSorted(events, { filterKey, pageSize: 15, initialSortKey: "created_at", getSortValue: (event, key) => (event as unknown as Record<string, string>)[key] })
  const viewport = useRef<HTMLDivElement>(null)
  useEffect(() => { if (viewport.current) viewport.current.scrollTop = 0 }, [page, sortKey, sortDir])
  const { widths, startResize } = useColumnWidths("lingshu-gate-cols-events", { created_at: 170, type: 280, source: 220 })
  // 为末列保留可读宽度；窄屏或拖宽其他列时在表格内横向滚动。
  const minWidth = widths.created_at + widths.type + widths.source + 200
  return <RemainingList>
    <ListViewport viewport={viewport} label={t("toolShowing")} actions={false}><Table className="table-fixed" style={{ minWidth }}><ColGroup order={["created_at", "type", "source", "subject_id"]} widths={widths} /><TableHeader><TableRow>
      <SortHead label={t("time")} sortKey="created_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("created_at")} />
      <SortHead label={t("eventType")} sortKey="type" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("type")} />
      <SortHead label={t("source")} sortKey="source" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("source")} />
      <SortHead label={t("serverId")} />
    </TableRow></TableHeader><TableBody>{total === 0 ? <TableEmptyRow colSpan={4} title={emptyLabel} /> : pageRows.map((event) => <TableRow key={event.id} className="cursor-pointer" onClick={() => onSelect(event)}><TableCell className="whitespace-nowrap text-xs">{formatDateTime(event.created_at)}</TableCell><TableCell className="break-all"><button type="button" className="text-left underline underline-offset-4 focus-visible:outline focus-visible:outline-2" onClick={e => { e.stopPropagation(); onSelect(event) }}><code>{event.type}</code></button></TableCell><TableCell className="break-words" title={event.source}>{event.source}</TableCell><TableCell className="break-all" title={event.subject_id || undefined}>{event.subject_id || "-"}</TableCell></TableRow>)}</TableBody></Table></ListViewport>
    <Pager t={t} page={page} pageCount={pageCount} total={total} onPage={setPage} />
  </RemainingList>
}

function LogTable({ t, logs, emptyLabel, onSelect, filterKey }: { filterKey: string; emptyLabel: string; t: TFunction; logs: ObservabilityLog[]; onSelect: (value: unknown) => void }) {
  const { pageRows, page, setPage, pageCount, total, sortKey, sortDir, toggleSort } = usePagedSorted(logs, { filterKey, pageSize: 15, initialSortKey: "created_at", getSortValue: (log, key) => (log as unknown as Record<string, string>)[key] })
  const viewport = useRef<HTMLDivElement>(null)
  useEffect(() => { if (viewport.current) viewport.current.scrollTop = 0 }, [page, sortKey, sortDir])
  const { widths, startResize } = useColumnWidths("lingshu-gate-cols-logs", { created_at: 170, level: 100, server_id: 240, event_type: 280 })
  const minWidth = widths.created_at + widths.level + widths.server_id + widths.event_type + 240
  return <RemainingList>
    <ListViewport viewport={viewport} label={t("toolShowing")} actions={false}><Table className="table-fixed" style={{ minWidth }}><ColGroup order={["created_at", "level", "server_id", "event_type", "message"]} widths={widths} /><TableHeader><TableRow>
      <SortHead label={t("time")} sortKey="created_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("created_at")} />
      <SortHead label={t("level")} sortKey="level" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("level")} />
      <SortHead label={t("serverId")} sortKey="server_id" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("server_id")} />
      <SortHead label={t("eventType")} onResizeStart={startResize("event_type")} />
      <SortHead label={t("description")} />
    </TableRow></TableHeader><TableBody>{total === 0 ? <TableEmptyRow colSpan={5} title={emptyLabel} /> : pageRows.map((log) => <TableRow key={log.id} className="cursor-pointer" onClick={() => onSelect(log)}><TableCell className="whitespace-nowrap text-xs">{formatDateTime(log.created_at)}</TableCell><TableCell><Badge variant={log.level === "error" ? "danger" : log.level === "warning" ? "warning" : "outline"}>{localizeStatus(t, log.level)}</Badge></TableCell><TableCell className="break-all" title={log.server_id || undefined}>{log.server_id || "-"}</TableCell><TableCell className="break-all" title={log.event_type || undefined}><code>{log.event_type || "-"}</code></TableCell><TableCell className="whitespace-pre-wrap text-xs"><button type="button" className="text-left underline underline-offset-4 focus-visible:outline focus-visible:outline-2" onClick={e => { e.stopPropagation(); onSelect(log) }}>{log.message || t("detail")}</button></TableCell></TableRow>)}</TableBody></Table></ListViewport>
    <Pager t={t} page={page} pageCount={pageCount} total={total} onPage={setPage} />
  </RemainingList>
}

function cleanFilters<T extends object>(filters: T): T {
  return cleanObservabilityFilters(filters)
}

function fromSelectValue(value: string) {
  return value === ALL_VALUE ? undefined : value
}

function unique(values: string[]) {
  return Array.from(new Set(values)).sort()
}

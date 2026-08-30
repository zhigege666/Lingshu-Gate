import { useEffect, useMemo, useState, type ReactNode } from "react"
import { api, type EventFilters, type LogFilters, type ObservabilityEvent, type ObservabilityLog } from "@/api/client"
import { PageHeader } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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

export function LogsEventsPage({ t }: { t: TFunction }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [logs, setLogs] = useState<ObservabilityLog[]>([])
  const [events, setEvents] = useState<ObservabilityEvent[]>([])
  const [selectedPayload, setSelectedPayload] = useState<unknown | null>(null)
  const [lastLoadedAt, setLastLoadedAt] = useState("")
  const [logFilters, setLogFilters] = useState<LogFilters>({ limit: 80 })
  const [eventFilters, setEventFilters] = useState<EventFilters>({ limit: 80 })

  const logEventTypes = useMemo(() => unique(logs.map((item) => item.event_type).filter(Boolean) as string[]), [logs])
  const logSources = useMemo(() => unique(logs.map((item) => item.source).filter(Boolean)), [logs])
  const eventTypes = useMemo(() => unique(events.map((item) => item.type).filter(Boolean)), [events])
  const eventSources = useMemo(() => unique(events.map((item) => item.source).filter(Boolean)), [events])

  useEffect(() => { void loadLogsEvents() }, [])

  async function loadLogsEvents() {
    setBusy(true); setError(null)
    try {
      const [logResponse, eventResponse] = await Promise.all([
        api.logs(cleanFilters(logFilters)),
        api.events(cleanFilters(eventFilters)),
      ])
      setLogs(logResponse.logs)
      setEvents(eventResponse.events)
      setLastLoadedAt(new Date().toISOString())
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  function resetFilters() {
    setLogFilters({ limit: 80 })
    setEventFilters({ limit: 80 })
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("observability")}
        title={t("logs")}
        description={t("logFiltersDesc")}
        stats={[
          { label: t("logRows"), value: logs.length },
          { label: t("events"), value: events.length },
          { label: t("error"), value: logs.filter((item) => item.level === "error").length, tone: logs.some((item) => item.level === "error") ? "danger" : "success" },
          { label: t("updatedAt"), value: lastLoadedAt ? formatDateTime(lastLoadedAt) : t("waiting") },
        ]}
        actions={<Button onClick={loadLogsEvents} disabled={busy}>{t("applyFilters")}</Button>}
      />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><CardTitle>{t("logFilters")}</CardTitle><CardDescription>{t("logFiltersDesc")}</CardDescription></div>
            <Button size="sm" variant="secondary" onClick={resetFilters} disabled={busy}>{t("resetFilters")}</Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-2">
          <FilterPanel title={t("logRows")}>
            <FilterInput label={t("serverId")} value={logFilters.server_id || ""} onChange={(value) => setLogFilters((current) => ({ ...current, server_id: value }))} placeholder="example-server" />
            <FilterSelect t={t} localize label={t("level")} value={logFilters.level || ALL_VALUE} options={LEVEL_OPTIONS} onChange={(value) => setLogFilters((current) => ({ ...current, level: fromSelectValue(value) }))} />
            <FilterSelect t={t} label={t("eventType")} value={logFilters.event_type || ALL_VALUE} options={logEventTypes} onChange={(value) => setLogFilters((current) => ({ ...current, event_type: fromSelectValue(value) }))} allowCustom />
            <FilterSelect t={t} label={t("source")} value={logFilters.source || ALL_VALUE} options={logSources} onChange={(value) => setLogFilters((current) => ({ ...current, source: fromSelectValue(value) }))} allowCustom />
            <FilterInput label={t("toolId")} value={logFilters.tool_id || ""} onChange={(value) => setLogFilters((current) => ({ ...current, tool_id: value }))} placeholder="mcp.example-server.*" />
            <FilterInput label={t("keyword")} value={logFilters.keyword || ""} onChange={(value) => setLogFilters((current) => ({ ...current, keyword: value }))} placeholder="stderr / timeout / example-server" />
            <LimitSelect t={t} value={logFilters.limit || 80} onChange={(value) => setLogFilters((current) => ({ ...current, limit: value }))} />
          </FilterPanel>
          <FilterPanel title={t("events")}>
            <FilterInput label={t("serverId")} value={eventFilters.subject_id || ""} onChange={(value) => setEventFilters((current) => ({ ...current, subject_id: value }))} placeholder="example-server" />
            <FilterSelect t={t} label={t("eventType")} value={eventFilters.event_type || ALL_VALUE} options={eventTypes} onChange={(value) => setEventFilters((current) => ({ ...current, event_type: fromSelectValue(value) }))} allowCustom />
            <FilterSelect t={t} label={t("source")} value={eventFilters.source || ALL_VALUE} options={eventSources} onChange={(value) => setEventFilters((current) => ({ ...current, source: fromSelectValue(value) }))} allowCustom />
            <FilterInput label={t("keyword")} value={eventFilters.keyword || ""} onChange={(value) => setEventFilters((current) => ({ ...current, keyword: value }))} placeholder="gate.server.failed / gate.config" />
            <LimitSelect t={t} value={eventFilters.limit || 80} onChange={(value) => setEventFilters((current) => ({ ...current, limit: value }))} />
          </FilterPanel>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <SummaryCard title={t("logRows")} value={logs.length} detail={summaryBy(logs, "level")} />
        <SummaryCard title={t("events")} value={events.length} detail={summaryBy(events, "source")} />
        <SummaryCard title={t("selectedPayload")} value={selectedPayload ? 1 : 0} detail={selectedPayload ? t("detail") : t("noData")} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>{t("events")}</CardTitle><CardDescription>{t("latestEvents")}</CardDescription></CardHeader><CardContent><EventTable t={t} events={events} onSelect={setSelectedPayload} /></CardContent></Card>
        <Card><CardHeader><CardTitle>{t("logRows")}</CardTitle><CardDescription>{t("latestLogs")}</CardDescription></CardHeader><CardContent><LogTable t={t} logs={logs} onSelect={setSelectedPayload} /></CardContent></Card>
      </div>

      <Dialog open={selectedPayload !== null} onOpenChange={(open) => { if (!open) setSelectedPayload(null) }}>
        <DialogContent className="max-w-4xl">
          <DialogHeader><DialogTitle>{t("selectedPayload")}</DialogTitle><DialogDescription>{t("selectedPayloadDesc")}</DialogDescription></DialogHeader>
          <DialogBody><JsonPanel text={selectedPayload ? JSON.stringify(selectedPayload, null, 2) : t("noData")} maxHeight="max-h-[60vh]" /></DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function FilterPanel({ title, children }: { title: string; children: ReactNode }) {
  return <div className="rounded-lg border p-3"><div className="mb-3 text-sm font-semibold">{title}</div><div className="grid gap-3 md:grid-cols-2">{children}</div></div>
}

function FilterInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground"><span>{label}</span><Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>
}

function FilterSelect({ t, label, value, options, onChange, allowCustom = false, localize = false }: { t: TFunction; label: string; value: string; options: string[]; onChange: (value: string) => void; allowCustom?: boolean; localize?: boolean }) {
  const visibleOptions = value !== ALL_VALUE && !options.includes(value) && allowCustom ? [value, ...options] : options
  return <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground"><span>{label}</span><Select value={value} onValueChange={onChange}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value={ALL_VALUE}>{t("all")}</SelectItem>{visibleOptions.map((option) => <SelectItem key={option} value={option}>{localize ? localizeStatus(t, option) : option}</SelectItem>)}</SelectContent></Select></label>
}

function LimitSelect({ t, value, onChange }: { t: TFunction; value: number; onChange: (value: number) => void }) {
  return <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground"><span>{t("limit")}</span><Select value={String(value)} onValueChange={(next) => onChange(Number(next))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{LIMIT_OPTIONS.map((option) => <SelectItem key={option} value={String(option)}>{option}</SelectItem>)}</SelectContent></Select></label>
}

function EventTable({ t, events, onSelect }: { t: TFunction; events: ObservabilityEvent[]; onSelect: (value: unknown) => void }) {
  const { pageRows, page, setPage, pageCount, total, sortKey, sortDir, toggleSort } = usePagedSorted(events, { pageSize: 15, initialSortKey: "created_at", getSortValue: (event, key) => (event as unknown as Record<string, string>)[key] })
  const { widths, startResize } = useColumnWidths("lingshu-gate-cols-events", { created_at: 170, type: 160, source: 120 })
  return <div>
    <div className="max-h-[520px] overflow-auto"><Table className="table-fixed"><ColGroup order={["created_at", "type", "source", "subject_id"]} widths={widths} /><TableHeader><TableRow>
      <SortHead label={t("time")} sortKey="created_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("created_at")} />
      <SortHead label={t("eventType")} sortKey="type" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("type")} />
      <SortHead label={t("source")} sortKey="source" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("source")} />
      <SortHead label={t("serverId")} />
    </TableRow></TableHeader><TableBody>{total === 0 ? <TableEmptyRow colSpan={4} title={t("noData")} /> : pageRows.map((event) => <TableRow key={event.id} className="cursor-pointer" onClick={() => onSelect(event)}><TableCell className="whitespace-nowrap text-xs">{formatDateTime(event.created_at)}</TableCell><TableCell className="truncate"><code>{event.type}</code></TableCell><TableCell className="truncate">{event.source}</TableCell><TableCell className="truncate">{event.subject_id || "-"}</TableCell></TableRow>)}</TableBody></Table></div>
    <Pager t={t} page={page} pageCount={pageCount} total={total} onPage={setPage} />
  </div>
}

function LogTable({ t, logs, onSelect }: { t: TFunction; logs: ObservabilityLog[]; onSelect: (value: unknown) => void }) {
  const { pageRows, page, setPage, pageCount, total, sortKey, sortDir, toggleSort } = usePagedSorted(logs, { pageSize: 15, initialSortKey: "created_at", getSortValue: (log, key) => (log as unknown as Record<string, string>)[key] })
  const { widths, startResize } = useColumnWidths("lingshu-gate-cols-logs", { created_at: 170, level: 100, server_id: 120, event_type: 150 })
  return <div>
    <div className="max-h-[520px] overflow-auto"><Table className="table-fixed"><ColGroup order={["created_at", "level", "server_id", "event_type", "message"]} widths={widths} /><TableHeader><TableRow>
      <SortHead label={t("time")} sortKey="created_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("created_at")} />
      <SortHead label={t("level")} sortKey="level" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("level")} />
      <SortHead label={t("serverId")} sortKey="server_id" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("server_id")} />
      <SortHead label={t("eventType")} onResizeStart={startResize("event_type")} />
      <SortHead label={t("description")} />
    </TableRow></TableHeader><TableBody>{total === 0 ? <TableEmptyRow colSpan={5} title={t("noData")} /> : pageRows.map((log) => <TableRow key={log.id} className="cursor-pointer" onClick={() => onSelect(log)}><TableCell className="whitespace-nowrap text-xs">{formatDateTime(log.created_at)}</TableCell><TableCell><Badge variant={log.level === "error" ? "danger" : log.level === "warning" ? "warning" : "outline"}>{localizeStatus(t, log.level)}</Badge></TableCell><TableCell className="truncate">{log.server_id || "-"}</TableCell><TableCell className="truncate"><code>{log.event_type || "-"}</code></TableCell><TableCell className="whitespace-pre-wrap text-xs">{log.message}</TableCell></TableRow>)}</TableBody></Table></div>
    <Pager t={t} page={page} pageCount={pageCount} total={total} onPage={setPage} />
  </div>
}

function SummaryCard({ title, value, detail }: { title: string; value: number; detail: string }) {
  return <Card><CardHeader className="pb-2"><CardDescription>{title}</CardDescription><CardTitle>{value}</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">{detail}</CardContent></Card>
}

function cleanFilters<T extends object>(filters: T): T {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== undefined && value !== "" && value !== ALL_VALUE)) as T
}

function fromSelectValue(value: string) {
  return value === ALL_VALUE ? undefined : value
}

function unique(values: string[]) {
  return Array.from(new Set(values)).sort()
}

function summaryBy(items: object[], key: string) {
  const counts = new Map<string, number>()
  for (const item of items) {
    const value = String((item as Record<string, unknown>)[key] || "unknown")
    counts.set(value, (counts.get(value) || 0) + 1)
  }
  return Array.from(counts.entries()).slice(0, 5).map(([name, count]) => `${name}: ${count}`).join(" · ") || "-"
}

import { ListViewport, RemainingList, ListPagination, useListPage } from "@/components/list-pagination"
import { useEffect, useMemo, useState } from "react"
import type { BuildLog } from "@/api/builds"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { StatusBadge } from "@/components/builds/status-badge"
import { TableEmptyRow } from "@/pages/page-utils"

type LogFilter = "all" | "error" | "warning" | "command" | "prepare"

export function filterBuildLogs(logs: BuildLog[], filter: LogFilter, keyword = "") {
  const normalizedKeyword = keyword.trim().toLowerCase()
  const phaseFiltered = filter === "all" ? logs : filter === "command" || filter === "prepare" ? logs.filter((log) => log.phase === filter) : logs.filter((log) => log.level === filter)
  if (!normalizedKeyword) return phaseFiltered
  return phaseFiltered.filter((log) => `${log.phase} ${log.level} ${log.message} ${log.command?.join(" ")} ${log.stdout} ${log.stderr}`.toLowerCase().includes(normalizedKeyword))
}

type WindowNavigation = { busy: boolean; following: boolean; earlier: boolean; later: boolean; onEarlier: () => void; onLater: () => void; onLatest: () => void; onPause: () => void }
export function BuildLogsTable({ logs, filter, onFilterChange, selectedBuildLabel, live, t, windowNavigation }: { logs: BuildLog[]; filter: LogFilter; onFilterChange: (filter: LogFilter) => void; selectedBuildLabel: string; live?: boolean; t: TFunction; windowNavigation?: WindowNavigation }) {
  const [keyword, setKeyword] = useState("")
  const zh = t("uploads") === "项目上传"
  const visibleLogs = useMemo(() => filterBuildLogs(logs, filter, keyword), [logs, filter, keyword])
  const paging = useListPage(visibleLogs, `${logs[0]?.id || ""}:${filter}:${keyword}`, 50)
  const viewport = paging.viewport
  useEffect(() => {
    if (live || windowNavigation?.following) {
      paging.setPage(paging.pageCount)
      if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight
    }
  }, [logs.at(-1)?.id, live, windowNavigation?.following, paging.pageCount])
  return (
    <Card className="build-log-table">
      <CardHeader>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle>{t("logRows")} {live ? "· Live" : ""}</CardTitle>
            <CardDescription>{selectedBuildLabel}</CardDescription>
          </div>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,220px)_180px_auto]">
            <Input value={keyword} onChange={(event) => { windowNavigation?.onPause(); setKeyword(event.target.value) }} placeholder={zh ? "检索当前日志窗口" : "Search current log window"} aria-label={t("keyword")} />
            <Select value={filter} onValueChange={(value) => { windowNavigation?.onPause(); onFilterChange(value as LogFilter) }}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("allLogLevels")}</SelectItem>
                <SelectItem value="error">{t("errorLogsOnly")}</SelectItem>
                <SelectItem value="warning">{t("warningLogsOnly")}</SelectItem>
                <SelectItem value="command">{t("commandLogsOnly")}</SelectItem>
                <SelectItem value="prepare">{t("prepareLogsOnly")}</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="secondary" onClick={() => { onFilterChange("all"); setKeyword("") }}>{t("clearFilter")}</Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <RemainingList bottomGap={40}>
        {windowNavigation && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground" role="group" aria-label={zh ? "日志窗口导航" : "Log window navigation"}>
          <span>{zh ? "仅载入当前最多 200 条，历史仍保留在服务端" : "At most 200 records loaded; history remains on the server"}{logs.length ? ` · #${logs[0].sequence}–${logs.at(-1)?.sequence}` : ""}</span>
          <div className="flex gap-2"><Button size="sm" variant="outline" disabled={windowNavigation.busy || !windowNavigation.earlier} onClick={windowNavigation.onEarlier}>{zh ? "更早记录" : "Earlier records"}</Button><Button size="sm" variant="outline" disabled={windowNavigation.busy || !windowNavigation.later} onClick={windowNavigation.onLater}>{zh ? "较新记录" : "Newer records"}</Button><Button size="sm" variant="outline" disabled={windowNavigation.busy} onClick={windowNavigation.onLatest}>{zh ? "回到最新" : "Latest records"}</Button>{live && <Button size="sm" variant="outline" onClick={windowNavigation.onPause}>{zh ? "暂停跟随" : "Pause following"}</Button>}</div>
        </div>}

        <ListViewport viewport={viewport} label={t("logRows")} actions={false}>
        <Table>
          <TableHeader><TableRow><TableHead>#</TableHead><TableHead>{t("level")}</TableHead><TableHead>{t("type")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>ms</TableHead></TableRow></TableHeader>
          <TableBody>{visibleLogs.length === 0 ? <TableEmptyRow colSpan={5} title={t("noData")} /> : paging.items.map((log) => <TableRow key={log.id}><TableCell>{log.sequence}</TableCell><TableCell><StatusBadge value={log.level} t={t} /></TableCell><TableCell><code>{log.phase}</code><div className="text-xs text-muted-foreground">{log.command?.join(" ") || "-"}</div></TableCell><TableCell className="max-w-xl whitespace-pre-wrap text-xs">{log.message}</TableCell><TableCell>{log.duration_ms ?? "-"}</TableCell></TableRow>)}</TableBody>
        </Table>
        </ListViewport>
        <ListPagination paging={{ ...paging, setPage: page => { windowNavigation?.onPause(); paging.setPage(page) } }} t={t} />
        </RemainingList>
      </CardContent>
    </Card>
  )
}

export type { LogFilter }

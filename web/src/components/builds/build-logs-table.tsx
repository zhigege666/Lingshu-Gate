import { useEffect, useRef, useState } from "react"
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

export function BuildLogsTable({ logs, filter, onFilterChange, selectedBuildLabel, live, t }: { logs: BuildLog[]; filter: LogFilter; onFilterChange: (filter: LogFilter) => void; selectedBuildLabel: string; live?: boolean; t: TFunction }) {
  const [keyword, setKeyword] = useState("")
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const visibleLogs = filterBuildLogs(logs, filter, keyword)
  useEffect(() => {
    if (live) bottomRef.current?.scrollIntoView({ block: "end" })
  }, [visibleLogs.length, live])
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle>{t("logRows")} {live ? "· Live" : ""}</CardTitle>
            <CardDescription>{selectedBuildLabel}</CardDescription>
          </div>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,220px)_180px_auto]">
            <Input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder={t("keyword")} />
            <Select value={filter} onValueChange={(value) => onFilterChange(value as LogFilter)}>
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
      <CardContent className="max-h-[560px] overflow-auto">
        <Table>
          <TableHeader><TableRow><TableHead>#</TableHead><TableHead>{t("level")}</TableHead><TableHead>{t("type")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>ms</TableHead></TableRow></TableHeader>
          <TableBody>{visibleLogs.length === 0 ? <TableEmptyRow colSpan={5} title={t("noData")} /> : visibleLogs.map((log) => <TableRow key={log.id}><TableCell>{log.sequence}</TableCell><TableCell><StatusBadge value={log.level} t={t} /></TableCell><TableCell><code>{log.phase}</code><div className="text-xs text-muted-foreground">{log.command?.join(" ") || "-"}</div></TableCell><TableCell className="max-w-xl whitespace-pre-wrap text-xs">{log.message}</TableCell><TableCell>{log.duration_ms ?? "-"}</TableCell></TableRow>)}</TableBody>
        </Table>
        <div ref={bottomRef} />
      </CardContent>
    </Card>
  )
}

export type { LogFilter }

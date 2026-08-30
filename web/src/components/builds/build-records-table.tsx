import type { BuildRecord } from "@/api/builds"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { formatDateTime, shortId } from "@/components/builds/build-utils"
import { StatusBadge } from "@/components/builds/status-badge"
import { ColGroup, Pager, SortHead, useColumnWidths, usePagedSorted } from "@/components/table-tools"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { buildPageText } from "@/pages/builds-page-text"
import { TableEmptyRow } from "@/pages/page-utils"

const ACTIVE_BUILD_STATUSES = new Set(["queued", "running", "cancel_requested"])
const RETRYABLE_BUILD_STATUSES = new Set(["failed", "cancelled", "unsupported"])

function sortValue(build: BuildRecord, key: string): string | number | null | undefined {
  if (key === "id") return build.id
  if (key === "runtime") return build.runtime
  if (key === "status") return build.status
  if (key === "created_at") return build.created_at
  if (key === "updated_at") return build.updated_at
  return undefined
}

type BuildRecordsTableProps = {
  builds: BuildRecord[]
  busy: boolean
  selectedBuildId: string
  canRequestStop: (build: BuildRecord) => boolean
  onShowBuild: (build: BuildRecord) => void
  onLoadLogs: (build: BuildRecord) => void
  onRequestStop: (buildId: string) => void
  onDeploy: (buildId: string) => void
  onRetry: (build: BuildRecord) => void
  onDelete: (build: BuildRecord) => void
  t: TFunction
}

export function BuildRecordsTable({ builds, busy, selectedBuildId, canRequestStop, onShowBuild, onLoadLogs, onRequestStop, onDeploy, onRetry, onDelete, t }: BuildRecordsTableProps) {
  const { pageRows, page, setPage, pageCount, total, sortKey, sortDir, toggleSort } = usePagedSorted(builds, { pageSize: 10, initialSortKey: "created_at", getSortValue: sortValue })
  const { widths, startResize } = useColumnWidths("lingshu-gate-cols-builds", { id: 200, runtime: 110, status: 120, created_at: 170, updated_at: 170 })
  const tx = (key: string) => buildPageText(t, key)

  return <Card>
    <CardHeader><CardTitle>{t("buildRecords")}</CardTitle><CardDescription>{t("buildRecordsDesc")}</CardDescription></CardHeader>
    <CardContent>
      <Table className="table-fixed">
        <ColGroup order={["id", "runtime", "status", "created_at", "updated_at", "actions"]} widths={widths} />
        <TableHeader><TableRow>
          <SortHead label={t("id")} sortKey="id" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("id")} />
          <SortHead label={t("runtimeType")} sortKey="runtime" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("runtime")} />
          <SortHead label={t("status")} sortKey="status" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("status")} />
          <SortHead label={t("createdAt")} sortKey="created_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("created_at")} />
          <SortHead label={t("updatedAt")} sortKey="updated_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} onResizeStart={startResize("updated_at")} />
          <TableHead className="text-right">{t("actions")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>{total === 0 ? <TableEmptyRow colSpan={6} title={t("noData")} /> : pageRows.map((build) => {
          const selected = build.id === selectedBuildId
          return <TableRow
            key={build.id}
            data-state={selected ? "selected" : undefined}
            className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            tabIndex={0}
            onClick={() => onShowBuild(build)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onShowBuild(build) } }}
          >
            <TableCell><code className="text-xs" title={build.id}>{shortId(build.id)}</code><div className="text-xs text-muted-foreground" title={build.upload_id}>{t("uploadId")}: {shortId(build.upload_id)}</div></TableCell>
            <TableCell>{build.runtime}</TableCell>
            <TableCell><StatusBadge value={build.status} t={t} /></TableCell>
            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(build.created_at)}</TableCell>
            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(build.updated_at)}</TableCell>
            <TableCell className="text-right" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
              <ActionMenu label={tx("moreActions")}>
                <ActionMenuItem onClick={() => onShowBuild(build)}>{tx("view")}</ActionMenuItem>
                <ActionMenuItem onClick={() => onLoadLogs(build)}>{tx("viewLogs")}</ActionMenuItem>
                {canRequestStop(build) ? <ActionMenuItem disabled={busy} onClick={() => onRequestStop(build.id)}>{t("requestStop")}</ActionMenuItem> : null}
                {build.status === "success" ? <ActionMenuItem disabled={busy} onClick={() => onDeploy(build.id)}>{t("deployBuild")}</ActionMenuItem> : null}
                {RETRYABLE_BUILD_STATUSES.has(build.status) ? <ActionMenuItem disabled={busy} onClick={() => onRetry(build)}>{tx("retryBuild")}</ActionMenuItem> : null}
                <ActionMenuItem destructive disabled={busy || ACTIVE_BUILD_STATUSES.has(build.status)} onClick={() => onDelete(build)}>{tx("deleteRecord")}</ActionMenuItem>
              </ActionMenu>
            </TableCell>
          </TableRow>
        })}</TableBody>
      </Table>
      <Pager t={t} page={page} pageCount={pageCount} total={total} onPage={setPage} />
    </CardContent>
  </Card>
}

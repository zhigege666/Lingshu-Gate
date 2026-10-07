import "./build-records-table.css"
import { RemainingList } from "@/components/list-pagination"
import { useMemo, useState } from "react"
import { RecordListToolbar } from "./record-list-toolbar"
import type { DeploymentRecord } from "@/api/builds"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { formatDateTime, shortId } from "@/components/builds/build-utils"
import { StatusBadge } from "@/components/builds/status-badge"
import { SortHead, usePagedSorted } from "@/components/table-tools"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { buildPageText } from "@/pages/builds-page-text"
import { TableEmptyRow } from "@/pages/page-utils"

const ACTIVE_DEPLOYMENT_STATUSES = new Set(["queued", "running"])

function sortValue(deployment: DeploymentRecord, key: string): string | number | null | undefined {
  if (key === "id") return deployment.id
  if (key === "server_id") return deployment.server_id
  if (key === "status") return deployment.status
  if (key === "started") return deployment.started ? 1 : 0
  if (key === "created_at") return deployment.created_at
  return undefined
}

type DeploymentRecordsTableProps = {
  deployments: DeploymentRecord[]
  busy: boolean
  selectedDeploymentId: string
  onSelect: (deployment: DeploymentRecord) => void
  onDetail: (deployment: DeploymentRecord) => void
  onRollback: (deploymentId: string) => void
  onDelete: (deployment: DeploymentRecord) => void
  t: TFunction
}

export function DeploymentRecordsTable({ deployments, busy, selectedDeploymentId, onSelect, onDetail, onRollback, onDelete, t }: DeploymentRecordsTableProps) {
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("")
  const filtered = useMemo(() => deployments.filter(row => (!status || row.status === status) && JSON.stringify(row).toLowerCase().includes(query.trim().toLowerCase())), [deployments, query, status])
  const { pageRows, page, setPage, total, sortKey, sortDir, toggleSort } = usePagedSorted(filtered, { filterKey: JSON.stringify([query, status]), pageSize: 10, initialSortKey: "created_at", getSortValue: sortValue })
  const tx = (key: string) => buildPageText(t, key)

  return <Card role="region" aria-label={t("deploymentRecords")}>
    <CardContent className="delivery-records-content">
      <RemainingList bottomGap={40}>
      <RecordListToolbar kind="deployment" query={query} onQueryChange={value => { setQuery(value); setPage(1) }}
        status={status} onStatusChange={value => { setStatus(value); setPage(1) }}
        statuses={Array.from(new Set(deployments.map(row => row.status)))} page={page} total={total}
        filtered={Boolean(query.trim() || status)} onPage={setPage} t={t} />
      <div className="delivery-records-table">
      <Table>
        <TableHeader><TableRow>
          <SortHead label={t("id")} sortKey="id" activeKey={sortKey} dir={sortDir} onSort={toggleSort} />
          <SortHead label={t("serverId")} sortKey="server_id" activeKey={sortKey} dir={sortDir} onSort={toggleSort} />
          <SortHead label={t("status")} sortKey="status" activeKey={sortKey} dir={sortDir} onSort={toggleSort} />
          <SortHead label={t("start")} sortKey="started" activeKey={sortKey} dir={sortDir} onSort={toggleSort} />
          <SortHead label={t("createdAt")} sortKey="created_at" activeKey={sortKey} dir={sortDir} onSort={toggleSort} />
          <TableHead className="text-right">{t("actions")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>{total === 0 ? <TableEmptyRow colSpan={6} title={t(query.trim() || status ? "noMatchingRecords" : "noData")} /> : pageRows.map((deployment) => {
          const selected = deployment.id === selectedDeploymentId
          return <TableRow
            key={deployment.id}
            data-state={selected ? "selected" : undefined}
            className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            tabIndex={0}
            onClick={() => onSelect(deployment)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(deployment) } }}
          >
            <TableCell><code className="text-xs" title={deployment.id}>{shortId(deployment.id)}</code><div className="text-xs text-muted-foreground" title={deployment.build_id}>{t("buildId")}: {shortId(deployment.build_id)}</div></TableCell>
            <TableCell>{deployment.server_id}</TableCell>
            <TableCell><StatusBadge value={deployment.status} t={t} /></TableCell>
            <TableCell>{deployment.started ? <Badge variant="success">{t("started")}</Badge> : <Badge variant="outline">{t("notStarted")}</Badge>}</TableCell>
            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(deployment.created_at)}</TableCell>
            <TableCell className="text-right" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
              <ActionMenu inline label={t("actions")}>
                <ActionMenuItem onClick={() => onDetail(deployment)}>{tx("view")}</ActionMenuItem>
                <ActionMenuItem onClick={() => window.location.assign(`#/servers/${encodeURIComponent(deployment.server_id)}`)}>{t("viewServerDetail")}</ActionMenuItem>
                {deployment.rollback_available ? <ActionMenuItem disabled={busy} onClick={() => onRollback(deployment.id)}>{t("rollback")}</ActionMenuItem> : null}
                <ActionMenuItem destructive disabled={busy || ACTIVE_DEPLOYMENT_STATUSES.has(deployment.status)} onClick={() => onDelete(deployment)}>{tx("deleteRecord")}</ActionMenuItem>
              </ActionMenu>
            </TableCell>
          </TableRow>
        })}</TableBody>
      </Table>
      </div>
      </RemainingList>
    </CardContent>
  </Card>
}

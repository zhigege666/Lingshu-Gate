import { Pagination, Select } from "antd"
import { PageToolbar } from "@/components/page-shell"
import { localizeStatus, type TFunction } from "@/i18n"
import { buildPageText } from "@/pages/builds-page-text"

export function RecordListToolbar({ kind, query, onQueryChange, status, onStatusChange, statuses, page, total, filtered, onPage, t }: {
  kind: "build" | "deployment"
  query: string
  onQueryChange: (value: string) => void
  status: string
  onStatusChange: (value: string) => void
  statuses: string[]
  page: number
  total: number
  filtered: boolean
  onPage: (page: number) => void
  t: TFunction
}) {
  const tx = (key: string) => buildPageText(t, key)
  const start = total ? (page - 1) * 10 + 1 : 0
  const end = Math.min(page * 10, total)
  return <div className="record-list-toolbar">
    <PageToolbar query={query} onQueryChange={onQueryChange}
      placeholder={tx(kind === "build" ? "searchBuildRecords" : "searchDeploymentRecords")} clearLabel={t("clearSearch")} resetFilters={{ label: t("resetFilters"), disabled: !filtered, onReset: () => { onQueryChange(""); onStatusChange(""); onPage(1) } }}>
      <Select aria-label={t("status")} value={status} onChange={onStatusChange}
        options={[{ value: "", label: tx("allStatuses") }, ...statuses.map(value => ({ value, label: localizeStatus(t, value) }))]} />
    </PageToolbar>
    <nav className="record-list-pagination" aria-label={t("toolPage")}>
      <span role="status">{filtered ? `${tx("matchingRecords")} ${total} · ` : ""}{t("toolShowing")} {start}–{end}</span>
      <Pagination current={page} pageSize={10} total={total} onChange={onPage}
        size="small" simple showSizeChanger={false} hideOnSinglePage />
    </nav>
  </div>
}

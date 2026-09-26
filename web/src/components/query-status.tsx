import type { TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"

export function querySignature(value: object): string {
  return JSON.stringify(Object.entries(value).filter(([, v]) => v !== undefined && v !== "").sort(([a], [b]) => a.localeCompare(b)))
}

/** Remote query snapshot, independent from controls that edit the next query. */
export function QueryStatus({ pendingChanges, lastLoadedAt, summary, t }: {
  pendingChanges: boolean; lastLoadedAt: string; summary: string; t: TFunction
}) {
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" role="status">
    {pendingChanges && <strong className="text-foreground">{t("unappliedFilters")}</strong>}
    <span>{t("appliedFilters")}: {lastLoadedAt ? summary : t("notLoaded")}</span>
    {lastLoadedAt && <span>{t("snapshotAt")}: {formatDateTime(lastLoadedAt)}</span>}
  </div>
}

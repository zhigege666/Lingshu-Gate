import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react"
import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"
import { useRemainingListViewport } from "@/components/use-remaining-list-viewport"
import "./list-pagination.css"

// Presentation of an already authorized, loaded collection only. Callers retain
// filtering, request limits, selection, detail identity, and mutation ownership.
export function listPage<T>(items: readonly T[], requestedPage: number, pageSize = 50) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))
  const page = Math.min(pageCount, Math.max(1, requestedPage))
  const offset = (page - 1) * pageSize
  return { items: items.slice(offset, offset + pageSize), page, pageCount, total: items.length, start: items.length ? offset + 1 : 0, end: Math.min(offset + pageSize, items.length) }
}

export function useListPage<T>(items: readonly T[], filterKey = "", pageSize = 50) {
  const [position, setPosition] = useState({ page: 1, filterKey })
  const viewport = useRef<HTMLDivElement>(null)
  // Persist the new filter identity, so clearing it cannot resurrect an old page.
  if (position.filterKey !== filterKey) setPosition({ page: 1, filterKey })
  const result = listPage(items, position.filterKey === filterKey ? position.page : 1, pageSize)
  useEffect(() => { if (viewport.current) viewport.current.scrollTop = 0 }, [result.page, filterKey])
  return { ...result, viewport, setPage: (page: number) => setPosition({ page, filterKey }) }
}

type PageControls = { page: number; pageCount: number; total: number; start: number; end: number; setPage: (page: number) => void }
export function ListPagination({ paging, t }: { paging: PageControls; t: TFunction }) {
  return <nav className="list-pagination" aria-label={t("toolPage")}>
    <span role="status">{t("toolShowing")} {paging.start}–{paging.end} / {paging.total}</span>
    {paging.pageCount > 1 && <div><Button variant="outline" size="sm" disabled={paging.page <= 1} onClick={() => paging.setPage(paging.page - 1)}>{t("previousPage")}</Button><span>{paging.page} / {paging.pageCount}</span><Button variant="outline" size="sm" disabled={paging.page >= paging.pageCount} onClick={() => paging.setPage(paging.page + 1)}>{t("nextPage")}</Button></div>}
  </nav>
}

export function ListViewport({ children, viewport, label, actions = true }: { children: ReactNode; viewport: RefObject<HTMLDivElement | null>; label: string; actions?: boolean }) {
  return <div ref={viewport} className={`bounded-list-scroll${actions ? " bounded-list-actions" : ""}`} role="region" aria-label={label} tabIndex={0}>{children}</div>
}

/** Opt-in main-list group. Pagination and other siblings retain their natural
 * height; only the row viewport shrinks. Existing embedded pickers are unchanged.
 */
export function RemainingList({ children, className = "", bottomGap = 32, standaloneSection = false }: { children: ReactNode; className?: string; bottomGap?: number; standaloneSection?: boolean }) {
  const ref = useRemainingListViewport(bottomGap, standaloneSection)
  return <div ref={ref} className={`remaining-list-group ${className}`}>{children}</div>
}

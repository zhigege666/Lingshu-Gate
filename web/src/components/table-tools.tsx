import { useCallback, useMemo, useState, type ReactNode } from "react"
import { ArrowDown, ArrowUp, ChevronsUpDown, ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TableHead } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { cn } from "@/lib/utils"

export type SortDir = "asc" | "desc"

/** Persisted, drag-resizable column widths keyed by a stable storage key. */
export function useColumnWidths(storageKey: string, defaults: Record<string, number>) {
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw) return { ...defaults, ...(JSON.parse(raw) as Record<string, number>) }
    } catch { /* ignore */ }
    return defaults
  })

  const startResize = useCallback((key: string) => (event: React.PointerEvent) => {
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    const startWidth = widths[key] ?? defaults[key] ?? 120
    const onMove = (moveEvent: PointerEvent) => {
      const width = Math.max(60, Math.round(startWidth + (moveEvent.clientX - startX)))
      setWidths((current) => ({ ...current, [key]: width }))
    }
    const onUp = () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      document.body.style.cursor = ""
      setWidths((current) => {
        try { localStorage.setItem(storageKey, JSON.stringify(current)) } catch { /* ignore */ }
        return current
      })
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    document.body.style.cursor = "col-resize"
  }, [widths, defaults, storageKey])

  return { widths, startResize }
}

/** <colgroup> that applies persisted widths; columns without a width auto-size. */
export function ColGroup({ order, widths }: { order: string[]; widths: Record<string, number> }) {
  return <colgroup>{order.map((key) => <col key={key} style={widths[key] ? { width: `${widths[key]}px` } : undefined} />)}</colgroup>
}

function ColResizeHandle({ onPointerDown }: { onPointerDown: (event: React.PointerEvent) => void }) {
  return <span onPointerDown={onPointerDown} className="absolute right-0 top-0 z-10 h-full w-1.5 cursor-col-resize touch-none select-none rounded-full transition-colors hover:bg-primary/50" aria-hidden />
}

/**
 * Client-side sorting + pagination for a list of rows.
 * `getSortValue(row, key)` returns a comparable (string | number) for the active sort key.
 */
export function usePagedSorted<T>(rows: T[], options: {
  pageSize?: number
  initialSortKey?: string
  initialSortDir?: SortDir
  getSortValue?: (row: T, key: string) => string | number | null | undefined
}) {
  const { pageSize = 10, initialSortKey = "", initialSortDir = "desc", getSortValue } = options
  const [sortKey, setSortKey] = useState(initialSortKey)
  const [sortDir, setSortDir] = useState<SortDir>(initialSortDir)
  const [page, setPage] = useState(1)

  const sorted = useMemo(() => {
    if (!sortKey || !getSortValue) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = getSortValue(a, sortKey)
      const bv = getSortValue(b, sortKey)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (av < bv) return sortDir === "asc" ? -1 : 1
      if (av > bv) return sortDir === "asc" ? 1 : -1
      return 0
    })
    return copy
  }, [rows, sortKey, sortDir, getSortValue])

  const total = sorted.length
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const safePage = Math.min(page, pageCount)
  const pageRows = useMemo(() => sorted.slice((safePage - 1) * pageSize, safePage * pageSize), [sorted, safePage, pageSize])

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
    setPage(1)
  }

  return { pageRows, page: safePage, setPage, pageCount, total, sortKey, sortDir, toggleSort }
}

/** Table header cell: optionally sortable, optionally resizable. */
export function SortHead({ label, sortKey, activeKey, dir, onSort, onResizeStart, className }: { label: ReactNode; sortKey?: string; activeKey?: string; dir?: SortDir; onSort?: (key: string) => void; onResizeStart?: (event: React.PointerEvent) => void; className?: string }) {
  const sortable = Boolean(sortKey && onSort)
  const active = sortable && activeKey === sortKey
  return (
    <TableHead className={cn("relative", className)}>
      {sortable ? (
        <button type="button" onClick={() => onSort?.(sortKey as string)} className={cn("inline-flex items-center gap-1 transition-colors hover:text-foreground", active ? "text-foreground" : "text-muted-foreground")}>
          {label}
          {active ? (dir === "asc" ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />) : <ChevronsUpDown className="size-3.5 opacity-50" />}
        </button>
      ) : (
        <span className="truncate">{label}</span>
      )}
      {onResizeStart ? <ColResizeHandle onPointerDown={onResizeStart} /> : null}
    </TableHead>
  )
}

/** Prev / next pager with page + total info. Hidden when everything fits on one page. */
export function Pager({ t, page, pageCount, total, onPage }: { t: TFunction; page: number; pageCount: number; total: number; onPage: (page: number) => void }) {
  if (pageCount <= 1) return null
  return (
    <div className="flex items-center justify-between gap-3 pt-3 text-xs text-muted-foreground">
      <span>{t("total")} {total}</span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-7 px-2" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous"><ChevronLeft /></Button>
        <span>{page} / {pageCount}</span>
        <Button size="sm" variant="outline" className="h-7 px-2" disabled={page >= pageCount} onClick={() => onPage(page + 1)} aria-label="Next"><ChevronRight /></Button>
      </div>
    </div>
  )
}

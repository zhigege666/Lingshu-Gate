import { useRemainingViewport } from "@/components/use-remaining-viewport"
import "./maintenance-lists.css"
import { ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { usePageRefresh } from "@/components/page-refresh"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { api, type RuntimeCacheStatus } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { Locale, TFunction } from "@/i18n"
import { formatBytes, formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

import { cacheAccess, cacheClearBlock, cacheCleanupConfirmed, cacheCopy } from "./runtime-cache-state"

type RuntimeCacheEntry = RuntimeCacheStatus["caches"][number]

export function RuntimeCachePage({ t, locale = "en-US" }: { t: TFunction; locale?: Locale }) {
  const remainingViewport = useRemainingViewport()
  const c = cacheCopy[locale]
  const clearing = useRef(false)
  const generation = useRef(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [status, setStatus] = useState<RuntimeCacheStatus | null>(null)
  const [lastResult, setLastResult] = useState<unknown | null>(null)
  const [detail, setDetail] = useState<RuntimeCacheEntry | null>(null)
  const [query, setQuery] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)
  const filteredCaches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return status?.caches || []
    return (status?.caches || []).filter((cache) => `${cache.name} ${cache.path}`.toLowerCase().includes(needle))
  }, [query, status?.caches])

  const paging = useListPage(filteredCaches, query)

  usePageRefresh(load, busy)
  useEffect(() => { void load(); return () => { generation.current++ } }, [])

  async function load() {
    const revision = ++generation.current
    setBusy(true)
    setError(null)
    try {
      const result = await api.runtimeCache()
      if (revision === generation.current) setStatus(result)
    } catch (err) {
      if (revision === generation.current) setError(err instanceof Error ? err.message : String(err))
    } finally {
      if (revision === generation.current) setBusy(false)
    }
  }

  async function clearCache(cache: RuntimeCacheEntry) {
    if (clearing.current || busy || error || cacheClearBlock(cache)) return
    clearing.current = true
    try {
      if (!(await confirm({ title: t("confirmClearCache"), description: `${cache.name} · ${cache.path}\n${formatBytes(cache.size_bytes)} · ${cache.file_count} ${c.files}\n${c.impact}`, destructive: true }))) return
      generation.current++
      setBusy(true); setError(null); setMessage(null)
      const result = await api.clearRuntimeCache(cache.name)
      setLastResult(result)
      if (!cacheCleanupConfirmed(result, cache.name)) throw new Error(c.clearFailed)
      setDetail(current => current?.name === cache.name ? result.after : current)
      setStatus(current => current ? { ...current, caches: current.caches.map(item => item.name === cache.name ? result.after : item), total_size_bytes: current.caches.reduce((total, item) => total + (item.name === cache.name ? 0 : item.size_bytes), 0) } : current)
      const alreadyEmpty = result.before.file_count === 0 && result.before.size_bytes === 0
      setMessage(`${alreadyEmpty ? c.alreadyEmpty : t("cacheCleared")}: ${cache.name}`)
      try { setStatus(await api.runtimeCache()) }
      catch { setError(c.refreshFailed) }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      clearing.current = false
      setBusy(false)
    }
  }

  const toast: ToastState = message ? { message, tone: "success" } : null

  return (
    <div ref={remainingViewport} className="maintenance-list-page flex flex-col gap-4">
      <PageHeader closeLabel={t("close")}
        eyebrow={t("runtimeStorage")}
        title={t("runtimeCache")}
        description={t("runtimeCacheDesc")}
        helpLabel={t("pageHelp")}
        helpContent={<>
          <p>{t("cacheListDesc")}</p>
          <div><div className="font-medium">{t("cacheRoot")}</div><code className="break-all text-xs">{status?.root.path || "-"}</code></div>
        </>}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ${t("name")} / ${t("path")}`} resultCount={filteredCaches.length} resultLabel={t("cacheCount")} clearLabel={t("clearSearch")} />}
        stats={[
          { label: t("cacheSize"), value: status ? formatBytes(status.total_size_bytes) : "-" },
          { label: c.access, value: status ? c[cacheAccess(status.root)] : "-", tone: !status ? "default" : ["writable", "creatable"].includes(cacheAccess(status.root)) ? "success" : "danger" },
        ]}
      />

      {error && <Alert variant="destructive"><AlertDescription className="flex items-center justify-between gap-3"><span>{error}</span><Button variant="outline" size="sm" disabled={busy} onClick={() => void load()}>{t("retry")}</Button></AlertDescription></Alert>}
      <Card className="maintenance-list-card">
        <CardContent className="maintenance-list-content p-3 md:p-4">
          <ListViewport viewport={paging.viewport} label={t("toolShowing")}>
            <Table className="maintenance-table maintenance-cache-table">
            <TableHeader><TableRow><TableHead>{t("name")}</TableHead><TableHead>{t("path")}</TableHead><TableHead>{t("cacheSize")}</TableHead><TableHead>{t("fileCount")}</TableHead><TableHead>{c.access}</TableHead><TableHead>{t("lastModified")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
            <TableBody>
              {filteredCaches.length === 0 ? <TableEmptyRow colSpan={7} title={busy ? t("loadingData") : error ? t("error") : query.trim() ? t("noMatchingRecords") : t("noData")} /> : paging.items.map((cache) => <TableRow key={cache.name} className="cursor-pointer" onClick={() => setDetail(cache)}>
                <TableCell><button type="button" className="text-left underline underline-offset-4" onClick={e => { e.stopPropagation(); setDetail(cache) }}><code>{cache.name}</code></button><div className="maintenance-row-summary">{accessBadge(cache, locale)}<span>{formatBytes(cache.size_bytes)} · {cache.file_count} {c.files}</span></div></TableCell>
                <TableCell className="text-xs"><span className="maintenance-cache-path" title={cache.path}>{cache.path}</span></TableCell>
                <TableCell>{formatBytes(cache.size_bytes)}</TableCell>
                <TableCell>{cache.file_count}</TableCell>
                <TableCell>{accessBadge(cache, locale)}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{formatDateTime(cache.last_modified_at)}</TableCell>
                <TableCell onClick={(event) => event.stopPropagation()}><ActionMenu inline label={t("actions")}><ActionMenuItem onClick={() => setDetail(cache)}>{t("detail")}</ActionMenuItem><ActionMenuItem destructive={!cacheClearBlock(cache)} disabled={busy || Boolean(error) || Boolean(cacheClearBlock(cache))} title={cacheClearBlock(cache) ? c[cacheClearBlock(cache)!] : undefined} onClick={() => void clearCache(cache)}>{cacheClearBlock(cache) === "emptyHint" ? c.empty : cacheClearBlock(cache) ? c.unchanged : t("clearCache")}</ActionMenuItem></ActionMenu></TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
            </ListViewport>
            <ListPagination paging={paging} t={t} />
        </CardContent>
      </Card>

      <details className="rounded-lg border bg-card p-4 shadow-sm">
        <summary className="cursor-pointer font-medium">{t("result")} · {t("runtimeCacheResultDesc")}</summary>
        <div className="mt-3"><JsonPanel copyLabel={t("copy")} data={lastResult ?? status} maxHeight="max-h-[420px]" /></div>
      </details>

      <Dialog open={detail !== null} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent closeLabel={t("close")} className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><code>{detail?.name}</code>{detail ? accessBadge(detail, locale) : null}</DialogTitle>
            <DialogDescription className="break-all">{detail?.path}</DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            <div className="grid gap-2 md:grid-cols-2">
              <Info label={t("cacheSize")} value={formatBytes(detail?.size_bytes || 0)} />
              <Info label={t("fileCount")} value={String(detail?.file_count ?? 0)} />
              <Info label={c.access} value={detail ? c[cacheAccess(detail)] : "-"} />
              <Info label={t("lastModified")} value={formatDateTime(detail?.last_modified_at)} />
            </div>
            {detail && cacheClearBlock(detail) && <p className="text-sm text-muted-foreground">{c[cacheClearBlock(detail)!]}</p>}
            <JsonPanel copyLabel={t("copy")} data={detail} maxHeight="max-h-[320px]" />
          </DialogBody>
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => setMessage(null)} />
    </div>
  )
}

function Info({ label, value, badge }: { label: string; value: string; badge?: ReactNode }) {
  return <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 break-all text-sm font-medium">{badge || value}</div></div>
}

function accessBadge(value: RuntimeCacheEntry, locale: Locale) {
  const state = cacheAccess(value)
  return <Badge variant={state === "writable" || state === "creatable" ? "success" : "danger"}>{cacheCopy[locale][state]}</Badge>
}

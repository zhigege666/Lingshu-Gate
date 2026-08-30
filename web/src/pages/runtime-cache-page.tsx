import { useEffect, useMemo, useState, type ReactNode } from "react"
import { api, type RuntimeCacheStatus } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { formatBytes, formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

type RuntimeCacheEntry = RuntimeCacheStatus["caches"][number]

export function RuntimeCachePage({ t }: { t: TFunction }) {
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

  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      setStatus(await api.runtimeCache())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function clearCache(name: string) {
    if (!(await confirm({ title: t("confirmClearCache"), description: name, destructive: true }))) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const result = await api.clearRuntimeCache(name)
      setLastResult(result)
      setMessage(`${t("cacheCleared")}: ${name}`)
      setStatus(await api.runtimeCache())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("runtimeStorage")}
        title={t("runtimeCache")}
        description={t("runtimeCacheDesc")}
        stats={[
          { label: t("cacheSize"), value: formatBytes(status?.total_size_bytes || 0) },
          { label: t("cacheCount"), value: status?.caches.length || 0 },
          { label: t("writable"), value: String(Boolean(status?.root.writable || status?.root.parent_writable)), tone: status?.root.writable || status?.root.parent_writable ? "success" : "danger" },
          { label: t("cacheRoot"), value: status?.root.path || "-" },
        ]}
        actions={<Button variant="outline" onClick={load} disabled={busy}>{t("refresh")}</Button>}
      />

      <Card>
        <CardHeader><CardTitle>{t("cacheList")}</CardTitle><CardDescription>{t("cacheListDesc")}</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ${t("name")} / ${t("path")}`} resultCount={filteredCaches.length} resultLabel={t("cacheCount")} clearLabel={t("clearSearch")} />
          <Table>
            <TableHeader><TableRow><TableHead>{t("name")}</TableHead><TableHead>{t("path")}</TableHead><TableHead>{t("cacheSize")}</TableHead><TableHead>{t("fileCount")}</TableHead><TableHead>{t("writable")}</TableHead><TableHead>{t("lastModified")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
            <TableBody>
              {filteredCaches.length === 0 ? <TableEmptyRow colSpan={7} title={t("noData")} /> : filteredCaches.map((cache) => <TableRow key={cache.name} className="cursor-pointer" onClick={() => setDetail(cache)}>
                <TableCell><code>{cache.name}</code></TableCell>
                <TableCell className="max-w-md break-all text-xs">{cache.path}</TableCell>
                <TableCell>{formatBytes(cache.size_bytes)}</TableCell>
                <TableCell>{cache.file_count}</TableCell>
                <TableCell>{booleanBadge(cache.writable || cache.parent_writable)}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{formatDateTime(cache.last_modified_at)}</TableCell>
                <TableCell onClick={(event) => event.stopPropagation()}><ActionMenu label={t("actions")}><ActionMenuItem onClick={() => setDetail(cache)}>{t("detail")}</ActionMenuItem><ActionMenuItem destructive disabled={busy} onClick={() => void clearCache(cache.name)}>{t("clearCache")}</ActionMenuItem></ActionMenu></TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <details className="rounded-lg border bg-card p-4 shadow-sm">
        <summary className="cursor-pointer font-medium">{t("result")} · {t("runtimeCacheResultDesc")}</summary>
        <div className="mt-3"><JsonPanel data={lastResult ?? status} maxHeight="max-h-[420px]" /></div>
      </details>

      <Dialog open={detail !== null} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><code>{detail?.name}</code>{detail ? booleanBadge(detail.writable || detail.parent_writable) : null}</DialogTitle>
            <DialogDescription className="break-all">{detail?.path}</DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            <div className="grid gap-2 md:grid-cols-2">
              <Info label={t("cacheSize")} value={formatBytes(detail?.size_bytes || 0)} />
              <Info label={t("fileCount")} value={String(detail?.file_count ?? 0)} />
              <Info label={t("writable")} value={String(Boolean(detail?.writable || detail?.parent_writable))} />
              <Info label={t("lastModified")} value={formatDateTime(detail?.last_modified_at)} />
            </div>
            <JsonPanel data={detail} maxHeight="max-h-[320px]" />
          </DialogBody>
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => { setMessage(null); setError(null) }} />
    </div>
  )
}

function Info({ label, value, badge }: { label: string; value: string; badge?: ReactNode }) {
  return <div className="rounded-md border p-2"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 break-all text-sm font-medium">{badge || value}</div></div>
}

function booleanBadge(value: boolean) {
  return <Badge variant={value ? "success" : "danger"}>{String(value)}</Badge>
}

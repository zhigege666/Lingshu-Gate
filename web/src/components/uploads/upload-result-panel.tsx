import { useEffect, useMemo, useState } from "react"
import { JsonPanel } from "@/components/json-panel"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import type { TFunction } from "@/i18n"

type ResultView = "json" | "manifest" | "analysis"

export function UploadResultPanel({ result, onSaveManifest, t }: { result: unknown; onSaveManifest: (manifest: Record<string, unknown>) => void; t: TFunction }) {
  const [view, setView] = useState<ResultView>("json")
  const [editing, setEditing] = useState(false)
  const [manifestText, setManifestText] = useState("")
  const [manifestError, setManifestError] = useState<string | null>(null)
  const manifest = useMemo(() => extractManifest(result), [result])
  useEffect(() => {
    setManifestText(manifest ? JSON.stringify(manifest, null, 2) : "")
    setManifestError(null)
    setEditing(false)
  }, [manifest])
  const displayValue = useMemo(() => {
    if (view === "manifest") return extractManifest(result) || t("noData")
    if (view === "analysis") return extractAnalysis(result) || t("noData")
    return result
  }, [result, view, t])
  const text = typeof displayValue === "string" ? displayValue : JSON.stringify(displayValue, null, 2) || ""

  return (
    <Card className="min-w-0">
      <CardHeader>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>{t("result")}</CardTitle>
            <CardDescription>{t("uploadResultDesc")}</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant={view === "json" ? "default" : "secondary"} onClick={() => setView("json")}>JSON</Button>
            <Button size="sm" variant={view === "manifest" ? "default" : "secondary"} onClick={() => setView("manifest")}>{t("manifest")}</Button>
            <Button size="sm" variant={view === "analysis" ? "default" : "secondary"} onClick={() => setView("analysis")}>Analysis</Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="min-w-0">
        {manifest && <div className="mb-4 rounded-md border bg-muted/20 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div><div className="text-sm font-medium">运行配置</div><div className="text-xs text-muted-foreground">Manifest 仅作为内部配置模型，默认使用表单结果；高级用户可编辑 JSON。</div></div>
            <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setEditing((value) => !value)}>{editing ? "收起编辑" : "编辑配置"}</Button>{editing && <Button size="sm" onClick={() => { try { const value = JSON.parse(manifestText) as Record<string, unknown>; setManifestError(null); onSaveManifest(value) } catch { setManifestError("Manifest JSON 格式不正确") } }}>{t("save")}</Button>}</div>
          </div>
          {editing ? <><Textarea className="min-h-[220px] font-mono text-xs" value={manifestText} onChange={(event) => setManifestText(event.target.value)} aria-label="Manifest JSON" />{manifestError && <div className="mt-2 text-xs text-destructive">{manifestError}</div>}</> : <div className="grid gap-2 text-sm md:grid-cols-3"><div><span className="text-muted-foreground">名称：</span>{String(manifest.name || manifest.id || "-")}</div><div><span className="text-muted-foreground">启动：</span>{formatLaunch(manifest)}</div><div><span className="text-muted-foreground">传输：</span>{formatTransport(manifest)}</div></div>}
        </div>}
        <details className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">高级数据 / 原始 JSON</summary>
          <div className="mt-3"><JsonPanel text={text} maxHeight="max-h-[520px]" /></div>
        </details>
      </CardContent>
    </Card>
  )
}

function formatLaunch(manifest: Record<string, unknown>) {
  const launch = asRecord(manifest.launch)
  if (!launch) return "-"
  return [launch.command, ...(Array.isArray(launch.args) ? launch.args : [])].filter(Boolean).join(" ") || "-"
}

function formatTransport(manifest: Record<string, unknown>): string {
  return String(asRecord(manifest.transport)?.type || "stdio")
}

function extractManifest(value: unknown): Record<string, unknown> | null {
  const record = asRecord(value)
  if (!record) return null
  return asRecord(record.manifest)
    || asRecord(asRecord(record.draft)?.manifest)
    || asRecord(asRecord(record.build)?.manifest)
}

function extractAnalysis(value: unknown): Record<string, unknown> | null {
  const record = asRecord(value)
  if (!record) return null
  return asRecord(record.analysis)
    || asRecord(asRecord(record.upload)?.analysis)
    || asRecord(asRecord(record.manifest)?.analysis)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

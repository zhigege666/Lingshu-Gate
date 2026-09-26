import { useEffect, useState } from "react"
import type { ProjectUpload } from "@/api/builds"
import { useConfirm } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { JsonPanel } from "@/components/json-panel"
import { McpConfigEditor } from "@/components/mcp-config-editor"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { uploadCopy } from "@/components/uploads/upload-copy"
import { asRecord, prepareUploadManifest, type UploadActionResult } from "@/components/uploads/upload-state"
import type { TFunction } from "@/i18n"

export function UploadResultPanel({ upload, result, busy, onSaveManifest, t }: {
  upload: ProjectUpload
  result: UploadActionResult | null
  busy: boolean
  onSaveManifest: (manifest: Record<string, unknown>, credentialValues: Record<string, string>) => Promise<void>
  t: TFunction
}) {
  const [editing, setEditing] = useState(false)
  const [manifestText, setManifestText] = useState("")
  const [initialText, setInitialText] = useState("")
  const [editorPending, setEditorPending] = useState(false)
  const [editorDirty, setEditorDirty] = useState(false)
  const [footerContainer, setFooterContainer] = useState<HTMLDivElement | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)
  const c = uploadCopy(t)
  const manifest = result?.manifest || null
  const analysis = result?.analysis || upload.analysis
  const dirty = editing && (manifestText !== initialText || editorDirty)
  const pending = busy || editorPending
  const locale = t("uploads") === "项目上传" ? "zh-CN" : "en-US"

  useEffect(() => {
    if (!dirty) return
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    window.addEventListener("beforeunload", beforeUnload)
    return () => window.removeEventListener("beforeunload", beforeUnload)
  }, [dirty])

  function openEditor() {
    if (!manifest) return
    const text = JSON.stringify(manifest, null, 2)
    setInitialText(text)
    setManifestText(text)
    setEditorDirty(false)
    setEditing(true)
  }

  async function closeEditor() {
    if (pending) return
    if (dirty && !(await confirm({ title: c.discard, description: c.discardHint, confirmText: c.discardAction, cancelText: c.keepEditing }))) return
    setEditing(false)
    setManifestText("")
    setInitialText("")
  }

  async function save(nextText?: string) {
    const { manifest: nextManifest, credentialValues } = prepareUploadManifest(nextText ?? manifestText)
    const cleanText = JSON.stringify(nextManifest, null, 2)
    // Remove one-time values before the request. A failed save keeps only the non-secret draft.
    setManifestText(cleanText)
    await onSaveManifest(nextManifest, credentialValues)
    setInitialText(cleanText)
    setEditing(false)
    setManifestText("")
  }

  if (!manifest && !result && !Object.keys(analysis || {}).length) return null
  return <>
    <Card className="min-w-0">
      <CardHeader><CardTitle className="text-base">{result ? `${c.latestAction}: ${c[result.action]}` : c.analysis}</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3">
        {result?.action === "save" && <p role="status" className="text-sm text-muted-foreground">{c.saved}</p>}
        {manifest && <section className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">{c.runtimeConfig}</h3><Button size="sm" variant="outline" disabled={busy} onClick={openEditor}>{c.editConfig}</Button></div>
          <dl className="grid gap-2 text-sm md:grid-cols-3">
            <div><dt className="text-xs text-muted-foreground">{t("name")}</dt><dd className="break-words">{String(manifest.name || manifest.id || "—")}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{t("start")}</dt><dd className="break-all">{formatLaunch(manifest)}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{c.transport}</dt><dd>{String(asRecord(manifest.transport)?.type || "stdio")}</dd></div>
          </dl>
        </section>}
        {analysis && Object.keys(analysis).length > 0 && <details><summary className="cursor-pointer text-sm font-medium">{c.analysis}</summary><div className="mt-2"><JsonPanel data={analysis} maxHeight="max-h-80" /></div></details>}
        {manifest && <details><summary className="cursor-pointer text-sm font-medium">{t("manifest")}</summary><div className="mt-2"><JsonPanel data={manifest} maxHeight="max-h-80" /></div></details>}
        {result && <details><summary className="cursor-pointer text-sm font-medium">{c.raw}</summary><div className="mt-2"><JsonPanel data={result.data} maxHeight="max-h-80" /></div></details>}
      </CardContent>
    </Card>
    <FormDialog dirty={dirty} open={editing} onClose={() => void closeEditor()} title={`${c.editConfig} · ${upload.filename}`} description={c.saveHint} closeLabel={t("close")} pending={pending} className="max-w-5xl" footer={<div className="w-full" ref={setFooterContainer} />}>
      {editing && <McpConfigEditor locale={locale} selectedConfigId="" value={manifestText} onChange={setManifestText} onSave={save} onClose={() => void closeEditor()} busy={busy} backendPrecheck={false} loadCredentials={false} onPendingChange={setEditorPending} onDraftDirtyChange={setEditorDirty} footerContainer={footerContainer} />}
    </FormDialog>
    {confirmDialog}
  </>
}

function formatLaunch(manifest: Record<string, unknown>) {
  const launch = asRecord(manifest.launch)
  return launch ? [launch.command, ...(Array.isArray(launch.args) ? launch.args : [])].filter(value => value !== undefined && value !== null).join(" ") || String(launch.type || "—") : "—"
}

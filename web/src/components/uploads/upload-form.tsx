import { createPortal } from "react-dom"
import { useEffect, useId, useRef } from "react"
import { FieldLabel } from "@/components/field-help"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"

export function UploadForm({ busy, selectedFile, onFileChange, onUpload, t, actionContainer }: { busy: boolean; selectedFile: File | null; onFileChange: (file: File | null) => void; onUpload: () => void; t: TFunction; actionContainer?: HTMLElement | null }) {
  const input = useRef<HTMLInputElement>(null)
  const fieldId = useId()
  const zh = t("uploads") === "项目上传"
  useEffect(() => { if (!selectedFile && input.current) input.current.value = "" }, [selectedFile])
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle aria-label={t("uploadZip")}><label htmlFor={fieldId}><FieldLabel label={t("uploadZip")} help={t("uploadDesc")} helpId={`${fieldId}-help`} zh={zh} /></label></CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Input ref={input} id={fieldId} disabled={busy} aria-label={t("uploadZip")} aria-describedby={`${fieldId}-help`} type="file" accept=".zip,application/zip" onChange={(event) => onFileChange(event.target.files?.[0] || null)} />
        {actionContainer ? createPortal(<Button onClick={onUpload} disabled={busy || !selectedFile}>{t("uploadAndAnalyze")}</Button>, actionContainer) : <Button onClick={onUpload} disabled={busy || !selectedFile}>{t("uploadAndAnalyze")}</Button>}
      </CardContent>
    </Card>
  )
}

import { createPortal } from "react-dom"
import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"

export function UploadForm({ busy, selectedFile, onFileChange, onUpload, t, actionContainer }: { busy: boolean; selectedFile: File | null; onFileChange: (file: File | null) => void; onUpload: () => void; t: TFunction; actionContainer?: HTMLElement | null }) {
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { if (!selectedFile && input.current) input.current.value = "" }, [selectedFile])
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>{t("uploadZip")}</CardTitle>
        <CardDescription>{t("uploadDesc")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Input ref={input} disabled={busy} aria-label={t("uploadZip")} type="file" accept=".zip,application/zip" onChange={(event) => onFileChange(event.target.files?.[0] || null)} />
        {actionContainer ? createPortal(<Button onClick={onUpload} disabled={busy || !selectedFile}>{t("uploadAndAnalyze")}</Button>, actionContainer) : <Button onClick={onUpload} disabled={busy || !selectedFile}>{t("uploadAndAnalyze")}</Button>}
      </CardContent>
    </Card>
  )
}

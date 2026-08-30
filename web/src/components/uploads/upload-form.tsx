import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"

export function UploadForm({ busy, selectedFile, onFileChange, onUpload, onRefresh, t }: { busy: boolean; selectedFile: File | null; onFileChange: (file: File | null) => void; onUpload: () => void; onRefresh: () => void; t: TFunction }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>{t("uploadZip")}</CardTitle>
        <CardDescription>{t("uploadDesc")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Input type="file" accept=".zip,application/zip" onChange={(event) => onFileChange(event.target.files?.[0] || null)} />
        <div className="flex flex-wrap gap-2">
          <Button onClick={onUpload} disabled={busy || !selectedFile}>{t("uploadAndAnalyze")}</Button>
          <Button variant="secondary" onClick={onRefresh} disabled={busy}>{t("refreshList")}</Button>
        </div>
      </CardContent>
    </Card>
  )
}

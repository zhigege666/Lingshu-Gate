import type { BuildRecord, DeploymentRecord } from "@/api/builds"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { localizeStatus, type TFunction } from "@/i18n"
import { uploadCopy } from "@/components/uploads/upload-copy"
import type { UploadItem } from "@/components/uploads/upload-types"

export function UploadList({ uploads, builds, deployments, selectedId, busy, loading, failed, filtered, onSelect, onDraft, onCreateBuild, onDelete, t }: { uploads: UploadItem[]; builds: BuildRecord[]; deployments: DeploymentRecord[]; selectedId: string; busy: boolean; loading: boolean; failed: boolean; filtered: boolean; onSelect: (uploadId: string) => void; onDraft: (uploadId: string) => void; onCreateBuild: (uploadId: string) => void; onDelete: (uploadId: string) => void; t: TFunction }) {
  const c = uploadCopy(t)
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle>{c.records}</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-2" aria-busy={loading}>
        {loading && <p role="status" className="text-sm text-muted-foreground">{c.loading}</p>}
        {uploads.length === 0 ? !loading && !failed && <div className="text-sm text-muted-foreground">{filtered ? c.noMatches : c.empty}</div> : uploads.map((upload) => (
          <div key={upload.id} className={`flex min-w-0 items-center gap-3 rounded-md border p-2 transition-colors ${selectedId === upload.id ? "border-primary bg-primary/5" : "hover:bg-accent/40"}`}>
            <button type="button" className="min-w-0 flex-1 rounded-sm p-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSelect(upload.id)}>
              <div className="break-words font-medium">{upload.filename}</div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{upload.detected_runtime}</span><Badge variant="outline">{localizeStatus(t, projectStatus(upload.id, upload.status, builds, deployments))}</Badge></div>
            </button>
            <div className="flex shrink-0 items-center">
              <ActionMenu label={t("actions")}>
                <ActionMenuItem onClick={() => onDraft(upload.id)} disabled={busy}>{t("draftManifest")}</ActionMenuItem>
                <ActionMenuItem onClick={() => onCreateBuild(upload.id)} disabled={busy}>{t("createBuild")}</ActionMenuItem>
                <ActionMenuItem destructive onClick={() => onDelete(upload.id)} disabled={busy}>{t("delete")}</ActionMenuItem>
              </ActionMenu>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function projectStatus(uploadId: string, uploadStatus: string, builds: BuildRecord[], deployments: DeploymentRecord[]) {
  const build = builds.find((item) => item.upload_id === uploadId)
  return deployments.find((item) => item.build_id === build?.id)?.status || build?.status || uploadStatus
}

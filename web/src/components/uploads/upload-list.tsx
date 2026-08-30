import type { BuildRecord, DeploymentRecord } from "@/api/builds"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { localizeStatus, type TFunction } from "@/i18n"
import type { UploadItem } from "@/components/uploads/upload-types"

export function UploadList({ uploads, builds, deployments, selectedId, busy, onSelect, onDraft, onCreateBuild, onDelete, t }: { uploads: UploadItem[]; builds: BuildRecord[]; deployments: DeploymentRecord[]; selectedId: string; busy: boolean; onSelect: (uploadId: string) => void; onDraft: (uploadId: string) => void; onCreateBuild: (uploadId: string) => void; onDelete: (uploadId: string) => void; t: TFunction }) {
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle>{t("refreshList")}</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-2">
        {uploads.length === 0 ? <div className="text-sm text-muted-foreground">{t("noData")}</div> : uploads.map((upload) => (
          <div key={upload.id} className={`min-w-0 rounded-md border p-2 transition-colors ${selectedId === upload.id ? "border-primary bg-primary/5" : "hover:bg-accent/40"}`}>
            <button type="button" className="w-full rounded-sm p-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSelect(upload.id)}>
              <div className="break-words font-medium">{upload.filename}</div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{upload.detected_runtime}</span><Badge variant="outline">{localizeStatus(t, projectStatus(upload.id, upload.status, builds, deployments))}</Badge></div>
            </button>
            <div className="mt-3 flex justify-end">
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

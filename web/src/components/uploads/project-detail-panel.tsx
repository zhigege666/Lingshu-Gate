import { useState } from "react"
import type { DeploymentRecord, BuildRecord, ProjectUpload } from "@/api/builds"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { localizeStatus, type TFunction } from "@/i18n"
import { uploadCopy } from "@/components/uploads/upload-copy"
import { buildPageText } from "@/pages/builds-page-text"

export function ProjectDetailPanel({ upload, build, deployment, busy, onBuild, onDeploy, t }: {
  upload: ProjectUpload
  build: BuildRecord | null
  deployment: DeploymentRecord | null
  busy: boolean
  onBuild: (options: { run_install: boolean; run_build: boolean; project_root: string }) => void
  onDeploy: (buildId: string, options: { server_id?: string; start: boolean; overwrite: boolean }) => void
  t: TFunction
}) {
  const [installEnabled, setInstallEnabled] = useState(true)
  const [projectRoot, setProjectRoot] = useState(".")
  const [serverId, setServerId] = useState("")
  const [overwrite, setOverwrite] = useState(false)
  const [start, setStart] = useState(false)
  const c = uploadCopy(t)
  const tx = (key: string) => buildPageText(t, key)
  const manifestTarget = typeof build?.manifest?.id === "string" ? build.manifest.id : ""
  return <Card className="min-w-0">
    <CardHeader><CardTitle className="text-base break-words">{upload.filename}</CardTitle><CardDescription>{upload.root_dir}</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-4">
      <div className="grid gap-2 text-sm md:grid-cols-4">
        <div><div className="text-muted-foreground">{t("status")}</div><Badge variant={statusVariant(build?.status || deployment?.status || upload.status)}>{localizeStatus(t, build?.status || deployment?.status || upload.status)}</Badge></div>
        <div><div className="text-muted-foreground">{t("runtimeType")}</div><div>{upload.detected_runtime}</div></div>
        <div><div className="text-muted-foreground">{tx("latestBuild")}</div><div>{build ? localizeStatus(t, build.status) : tx("noBuild")}</div></div>
        <div><div className="text-muted-foreground">{tx("latestDeployment")}</div><div>{deployment ? localizeStatus(t, deployment.status) : tx("notDeployed")}</div></div>
      </div>
      <fieldset disabled={busy} className="border-t pt-3">
        <div className="mb-2 text-sm font-medium">{c.buildPlan}</div>
        <label className="mb-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={installEnabled} onChange={(event) => setInstallEnabled(event.target.checked)} /> {c.install}</label>
        <label className="mb-2 flex flex-col gap-1 text-sm"><span>{tx("projectRoot")}</span><Input className="font-mono text-xs" value={projectRoot} onChange={(event) => setProjectRoot(event.target.value)} aria-describedby={`project-root-hint-${upload.id}`} /><span id={`project-root-hint-${upload.id}`} className="text-xs text-muted-foreground">{c.projectRootHint}</span></label>
        <div className="text-xs text-muted-foreground">{c.buildHint}</div>
      </fieldset>
      {build?.status === "success" ? <fieldset disabled={busy} className="border-t pt-3">
        <div className="mb-2 text-sm font-medium">{tx("deploymentSummary")}</div>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground" htmlFor={`deploy-target-${build.id}`}>{tx("deploymentTarget")}</label>
            <Input id={`deploy-target-${build.id}`} value={serverId} onChange={(event) => setServerId(event.target.value)} placeholder={manifestTarget || tx("unavailableTarget")} />
          </div>
          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} /><span><span className="font-medium">{tx("overwriteExisting")}</span><span className="block text-xs text-muted-foreground">{tx("overwriteExistingDesc")}</span></span></label>
          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={start} onChange={(event) => setStart(event.target.checked)} /><span><span className="font-medium">{tx("startAfterDeploy")}</span><span className="block text-xs text-muted-foreground">{tx("startAfterDeployDesc")}</span></span></label>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">{tx("deploymentTarget")}: <span className="font-mono text-foreground">{serverId.trim() || manifestTarget || tx("unavailableTarget")}</span> · {tx("overwriteExisting")}: {overwrite ? tx("enabledChoice") : tx("disabledChoice")} · {tx("startAfterDeploy")}: {start ? tx("enabledChoice") : tx("disabledChoice")}</div>
      </fieldset> : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || ["queued", "running"].includes(build?.status || "")} onClick={() => onBuild({ run_install: installEnabled, run_build: true, project_root: projectRoot || "." })}>{build?.status === "failed" ? tx("retryBuild") : t("createBuild")}</Button>
        {build?.status === "success" && <Button size="sm" variant="secondary" disabled={busy} onClick={() => onDeploy(build.id, { server_id: serverId.trim() || undefined, start, overwrite })}>{t("deployBuild")}</Button>}
      </div>
    </CardContent>
  </Card>
}

function statusVariant(status: string): "success" | "warning" | "danger" | "outline" {
  if (["success", "running"].includes(status)) return "success"
  if (["queued", "starting", "warning"].includes(status)) return "warning"
  if (["failed", "error"].includes(status)) return "danger"
  return "outline"
}

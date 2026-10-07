import { createPortal } from "react-dom"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useContext, useEffect, useState } from "react"
import type { DeploymentRecord, BuildRecord, PackageManagerOverride, ProjectUpload } from "@/api/builds"
import { PackageManagerFields } from "@/components/builds/package-manager-fields"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { localizeStatus, type TFunction } from "@/i18n"
import { uploadCopy } from "@/components/uploads/upload-copy"
import { buildPageText } from "@/pages/builds-page-text"

export function ProjectDetailPanel({ upload, build, deployment, busy, onBuild, onDeploy, t, actionContainer, onDraftDirtyChange, initialOptions, packageChoices, onSaveOptions }: {
  upload: ProjectUpload
  build: BuildRecord | null
  deployment: DeploymentRecord | null
  busy: boolean
  onBuild: (options: { run_install: boolean; run_build: boolean; project_root: string; runtime_override: string | null; server_id: string | null; package_manager_override: PackageManagerOverride | null }) => void
  onDeploy: (buildId: string, options: { server_id?: string; start: boolean; overwrite: boolean }) => void
  t: TFunction
  actionContainer?: HTMLElement | null
  onDraftDirtyChange?: (dirty: boolean) => void
  initialOptions?: { project_root?: string; runtime_override?: string | null; server_id?: string | null; overwrite: boolean; start: boolean; package_manager_override?: PackageManagerOverride | null }
  packageChoices?: PackageManagerOverride[]
  onSaveOptions?: (options: { project_root: string; runtime_override: string | null; package_manager_override: PackageManagerOverride | null }) => void
}) {
  const [runtimeOverride, setRuntimeOverride] = useState(initialOptions?.runtime_override || "auto")
  const [packageManagerOverride, setPackageManagerOverride] = useState<PackageManagerOverride | null>(initialOptions?.package_manager_override || null)
  const [installEnabled, setInstallEnabled] = useState(true)
  const [projectRoot, setProjectRoot] = useState(initialOptions?.project_root || ".")
  const [serverId, setServerId] = useState(initialOptions?.server_id || "")
  const [overwrite, setOverwrite] = useState(initialOptions?.overwrite || false)
  const [start, setStart] = useState(initialOptions?.start || false)
  const registerExit = useContext(EditorNavigationContext)
  const dirty = runtimeOverride !== (initialOptions?.runtime_override || "auto") || !installEnabled || projectRoot !== (initialOptions?.project_root || ".") || serverId !== (initialOptions?.server_id || "") || overwrite !== Boolean(initialOptions?.overwrite) || start !== Boolean(initialOptions?.start) || JSON.stringify(packageManagerOverride) !== JSON.stringify(initialOptions?.package_manager_override || null)
  useEffect(() => registerExit?.({ dirty, pending: false }), [registerExit, dirty])
  useEffect(() => { onDraftDirtyChange?.(dirty); return () => onDraftDirtyChange?.(false) }, [dirty, onDraftDirtyChange])
  const actions = <>
    {build?.status === "success" ? <Button disabled={busy} onClick={() => onDeploy(build.id, { server_id: serverId.trim() || undefined, start, overwrite })}>{t("deployBuild")}</Button>
      : <Button disabled={busy || ["queued", "running"].includes(build?.status || "")} onClick={() => onBuild({ run_install: installEnabled, run_build: true, project_root: projectRoot || ".", runtime_override: runtimeOverride === "auto" ? null : runtimeOverride, server_id: serverId.trim() || null, package_manager_override: packageManagerOverride })}>{t("createBuild")}</Button>}
  </>
  const c = uploadCopy(t)
  const tx = (key: string) => buildPageText(t, key)
  const zh = t("uploads") === "项目上传"
  const manifestTarget = typeof build?.manifest?.id === "string" ? build.manifest.id : ""
  return <Card className="min-w-0">
    <CardHeader><CardTitle className="break-words">{build?.status === "success" ? (zh ? "部署配置" : "Deployment configuration") : (zh ? "准备创建构建" : "Prepare to create a build")}</CardTitle><CardDescription>{zh ? "确认运行时与项目根目录，构建不会修改现有服务。" : "Confirm the runtime and project root. Building does not change an existing service."}</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 text-sm"><strong className="break-all">{upload.filename}</strong><Badge variant="outline">{upload.detected_runtime}</Badge><span className="text-muted-foreground">{zh ? "分析完成" : "Analysis complete"}</span></div>
      <fieldset disabled={busy} className="pt-1">
        <label className="mb-3 flex flex-col gap-1 text-sm"><span>{t("runtimeType")}</span><select disabled={build?.status === "success"} aria-label={t("runtimeType")} className="h-9 rounded-md border border-input bg-transparent px-3" value={runtimeOverride} onChange={event => setRuntimeOverride(event.target.value)}><option value="auto">{zh ? "自动检测" : "Auto detect"}</option><option value="node">Node.js</option><option value="python">Python</option></select></label>


        <label className="mb-2 flex flex-col gap-1 text-sm"><span>{tx("projectRoot")}</span><Input disabled={build?.status === "success"} className="font-mono text-xs" value={projectRoot} onChange={(event) => setProjectRoot(event.target.value)} aria-describedby={`project-root-hint-${upload.id}`} /><span id={`project-root-hint-${upload.id}`} className="text-xs text-muted-foreground">{c.projectRootHint}</span></label>
        {build?.status === "success" && <p className="mb-3 text-xs text-muted-foreground">{zh ? "这些构建参数属于当前产物；更改运行时或根目录需要重新构建。" : "These build parameters belong to the current artifact. Changing the runtime or project root requires a new build."}</p>}
        <label className="mb-3 flex flex-col gap-1 text-sm"><span>{tx("deploymentTarget")}</span><Input aria-label={tx("deploymentTarget")} value={serverId} onChange={event => setServerId(event.target.value)} placeholder={manifestTarget || tx("unavailableTarget")} /><span className="text-xs text-muted-foreground">{zh ? "用于后续部署，不改变本次构建验证。" : "Used by the later deployment; does not change build validation."}</span></label>
        <details className="delivery-auxiliary"><summary>{zh ? "高级构建选项" : "Advanced build options"}</summary>
        <label className="mb-2 flex items-center gap-2 text-sm"><input type="checkbox" disabled={build?.status === "success"} checked={installEnabled} onChange={(event) => setInstallEnabled(event.target.checked)} /> {c.install}</label>
        <PackageManagerFields value={packageManagerOverride} onChange={setPackageManagerOverride} choices={packageChoices} disabled={busy || build?.status === "success"} zh={zh} />
        {onSaveOptions && dirty && build?.status !== "success" && <Button type="button" variant="outline" className="mt-2" onClick={() => onSaveOptions({ project_root: projectRoot || ".", runtime_override: runtimeOverride === "auto" ? null : runtimeOverride, package_manager_override: packageManagerOverride })}>{zh ? "保存构建选项" : "Save build options"}</Button>}
        <div className="text-xs text-muted-foreground">{c.buildHint}</div>
        </details>
      </fieldset>
      {build?.status === "success" ? <fieldset disabled={busy} className="border-t pt-3">
        <div className="mb-2 text-sm font-medium">{tx("deploymentSummary")}</div>
        <div className="grid gap-3 md:grid-cols-3">

          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} /><span><span className="font-medium">{tx("overwriteExisting")}</span><span className="block text-xs text-muted-foreground">{tx("overwriteExistingDesc")}</span></span></label>
          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={start} onChange={(event) => setStart(event.target.checked)} /><span><span className="font-medium">{tx("startAfterDeploy")}</span><span className="block text-xs text-muted-foreground">{tx("startAfterDeployDesc")}</span></span></label>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">{tx("deploymentTarget")}: <span className="font-mono text-foreground">{serverId.trim() || manifestTarget || tx("unavailableTarget")}</span> · {tx("overwriteExisting")}: {overwrite ? tx("enabledChoice") : tx("disabledChoice")} · {tx("startAfterDeploy")}: {start ? tx("enabledChoice") : tx("disabledChoice")}</div>
      </fieldset> : null}
      <details className="delivery-auxiliary"><summary>{zh ? "项目与执行详情" : "Project and execution details"}</summary>
        <p className="my-3 break-all text-xs text-muted-foreground">{upload.root_dir}</p>
      <div className="grid gap-2 text-sm md:grid-cols-4">
        <div><div className="text-muted-foreground">{t("status")}</div><Badge variant={statusVariant(deployment?.status || build?.status || upload.status)}>{localizeStatus(t, deployment?.status || build?.status || upload.status)}</Badge></div>
        <div><div className="text-muted-foreground">{t("runtimeType")}</div><div>{upload.detected_runtime}</div></div>
        <div><div className="text-muted-foreground">{tx("latestBuild")}</div><div>{build ? localizeStatus(t, build.status) : tx("noBuild")}</div></div>
        <div><div className="text-muted-foreground">{tx("latestDeployment")}</div><div>{deployment ? localizeStatus(t, deployment.status) : tx("notDeployed")}</div></div>
      </div>
      </details>
      {actionContainer ? createPortal(actions, actionContainer) : <div className="flex flex-wrap gap-2">{actions}</div>}
    </CardContent>
  </Card>
}

function statusVariant(status: string): "success" | "warning" | "danger" | "outline" {
  if (["success", "running"].includes(status)) return "success"
  if (["queued", "starting", "warning"].includes(status)) return "warning"
  if (["failed", "error"].includes(status)) return "danger"
  return "outline"
}

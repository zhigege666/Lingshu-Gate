import { createPortal } from "react-dom"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useContext, useEffect, useId, useState } from "react"
import type { DeploymentRecord, BuildRecord, PackageManagerOverride, ProjectUpload } from "@/api/builds"
import { PackageManagerFields } from "@/components/builds/package-manager-fields"
import { FilterRadio } from "@/components/filter-radio"
import { FieldLabel } from "@/components/field-help"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
  const fieldId = useId()
  const [runtimeOverride, setRuntimeOverride] = useState(initialOptions?.runtime_override || "auto")
  const [packageManagerOverride, setPackageManagerOverride] = useState<PackageManagerOverride | null>(initialOptions?.package_manager_override || null)
  const [installEnabled, setInstallEnabled] = useState(true)
  const [projectRoot, setProjectRoot] = useState(initialOptions?.project_root || ".")
  const [serverId, setServerId] = useState(initialOptions?.server_id || "")
  const [overwrite, setOverwrite] = useState(initialOptions?.overwrite || false)
  const [start, setStart] = useState(initialOptions?.start || false)
  const registerExit = useContext(EditorNavigationContext)
  const buildOptionsDirty = runtimeOverride !== (initialOptions?.runtime_override || "auto") || projectRoot !== (initialOptions?.project_root || ".") || JSON.stringify(packageManagerOverride) !== JSON.stringify(initialOptions?.package_manager_override || null)
  const dirty = buildOptionsDirty || !installEnabled || serverId !== (initialOptions?.server_id || "") || overwrite !== Boolean(initialOptions?.overwrite) || start !== Boolean(initialOptions?.start)
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
  const runtimeHelp = [
    zh ? "确认运行时与项目根目录，构建不会修改现有服务。" : "Confirm the runtime and project root. Building does not change an existing service.",
    build?.status === "success" ? (zh ? "这些构建参数属于当前产物；更改运行时或根目录需要重新构建。" : "These build parameters belong to the current artifact. Changing the runtime or project root requires a new build.") : null,
  ].filter(Boolean).join(" ")
  return <Card className="min-w-0">
    <CardHeader><CardTitle className="break-words">{build?.status === "success" ? (zh ? "部署配置" : "Deployment configuration") : (zh ? "准备创建构建" : "Prepare to create a build")}</CardTitle></CardHeader>
    <CardContent className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 text-sm"><strong className="break-all">{upload.filename}</strong><Badge variant="outline">{upload.detected_runtime}</Badge><span className="text-muted-foreground">{zh ? "分析完成" : "Analysis complete"}</span></div>
      <fieldset disabled={busy} className="gate-form-fields">
        <div className="gate-form-row"><label className="gate-form-label" htmlFor={`${fieldId}-runtime`}><FieldLabel label={t("runtimeType")} zh={zh} helpId={`${fieldId}-runtime-help`} help={runtimeHelp} /></label><div className="gate-form-control"><FilterRadio id={`${fieldId}-runtime`} aria-describedby={`${fieldId}-runtime-help`} label={t("runtimeType")} hideLabel disabled={busy || build?.status === "success"} value={runtimeOverride} onChange={setRuntimeOverride} options={[{ value: "auto", label: zh ? "自动检测" : "Auto detect" }, { value: "node", label: "Node.js" }, { value: "python", label: "Python" }]} /></div></div>
        <label className="gate-form-row" htmlFor={`${fieldId}-root`}><FieldLabel className="gate-form-label" label={tx("projectRoot")} help={c.projectRootHint} helpId={`project-root-hint-${upload.id}`} zh={zh} /><span className="gate-form-control"><Input id={`${fieldId}-root`} aria-label={tx("projectRoot")} disabled={build?.status === "success"} className="font-mono text-xs" value={projectRoot} onChange={(event) => setProjectRoot(event.target.value)} aria-describedby={`project-root-hint-${upload.id}`} /></span></label>
        <label className="gate-form-row" htmlFor={`${fieldId}-target`}><FieldLabel className="gate-form-label" label={tx("deploymentTarget")} zh={zh} helpId={`${fieldId}-target-help`} help={zh ? "用于后续部署，不改变本次构建验证。" : "Used by the later deployment; does not change build validation."} /><span className="gate-form-control"><Input id={`${fieldId}-target`} aria-label={tx("deploymentTarget")} aria-describedby={`${fieldId}-target-help`} value={serverId} onChange={event => setServerId(event.target.value)} placeholder={manifestTarget || tx("unavailableTarget")} /></span></label>
        <details className="delivery-auxiliary"><summary>{zh ? "高级构建选项" : "Advanced build options"}</summary>
        <div className="gate-form-fields mt-4">
        <label className="flex items-center gap-2 text-sm" htmlFor={`${fieldId}-install`}><input id={`${fieldId}-install`} type="checkbox" aria-label={c.install} aria-describedby={`${fieldId}-install-help`} disabled={build?.status === "success"} checked={installEnabled} onChange={(event) => setInstallEnabled(event.target.checked)} /><FieldLabel label={c.install} help={c.buildHint} helpId={`${fieldId}-install-help`} zh={zh} /></label>
        <PackageManagerFields value={packageManagerOverride} onChange={setPackageManagerOverride} choices={packageChoices} disabled={busy || build?.status === "success"} zh={zh} />
        {onSaveOptions && buildOptionsDirty && build?.status !== "success" && <div className="flex justify-end"><Button type="button" variant="outline" onClick={() => onSaveOptions({ project_root: projectRoot || ".", runtime_override: runtimeOverride === "auto" ? null : runtimeOverride, package_manager_override: packageManagerOverride })}>{zh ? "保存构建选项" : "Save build options"}</Button></div>}
        </div>
        </details>
      </fieldset>
      {build?.status === "success" ? <fieldset disabled={busy} className="border-t pt-3">
        <div className="mb-2 text-sm font-medium">{tx("deploymentSummary")}</div>
        <div className="grid gap-3 md:grid-cols-3">

          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} /><span><span className="font-medium">{tx("overwriteExisting")}</span><span className="block text-xs text-muted-foreground">{tx("overwriteExistingDesc")}</span></span></label>
          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm" htmlFor={`${fieldId}-start`}><input id={`${fieldId}-start`} type="checkbox" className="mt-1" aria-label={tx("startAfterDeploy")} aria-describedby={`${fieldId}-start-help`} checked={start} onChange={(event) => setStart(event.target.checked)} /><FieldLabel className="font-medium" label={tx("startAfterDeploy")} help={tx("startAfterDeployDesc")} helpId={`${fieldId}-start-help`} zh={zh} /></label>
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

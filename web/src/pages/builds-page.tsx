import { useEffect, useState, type ReactNode } from "react"
import { BuildApiError, buildApi, type BuildBlockedDetail, type BuildLog, type BuildPlan, type BuildPreflightResult, type BuildPreflightTool, type BuildRecord, type DeploymentRecord, type ProjectUpload } from "@/api/builds"
import { BuildDetailCard } from "@/components/builds/build-detail-card"
import { BuildHintCard } from "@/components/builds/build-hint-card"
import { BuildLogsTable, type LogFilter } from "@/components/builds/build-logs-table"
import { BuildOutputPanels } from "@/components/builds/build-output-panels"
import { BuildRecordsTable } from "@/components/builds/build-records-table"
import { BuildTimelineCard } from "@/components/builds/build-timeline-card"
import { DeploymentRecordsTable } from "@/components/builds/deployment-records-table"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, WorkflowSteps } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Toaster, type ToastState, type ToastTone } from "@/components/ui/toast"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { localizeStatus, type TFunction } from "@/i18n"
import { formatDeploymentSummary, formatRollbackSummary, resolveDeploymentTarget } from "@/features/deployment-options"
import { buildPageText } from "@/pages/builds-page-text"

const ACTIVE_BUILD_STATUSES = new Set(["queued", "running", "cancel_requested"])
const STOP_REQUESTABLE_BUILD_STATUSES = new Set(["queued", "running"])
const MANUAL_RUNTIME_REQUIRED = new Set(["unknown", "ambiguous", "docker"])
type WorkspaceSection = "workspace" | "builds" | "deployments" | "logs"

export function BuildsPage({ t, initialBuildId = "" }: { t: TFunction; initialBuildId?: string }) {
  const [uploads, setUploads] = useState<ProjectUpload[]>([])
  const [builds, setBuilds] = useState<BuildRecord[]>([])
  const [buildLogs, setBuildLogs] = useState<BuildLog[]>([])
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([])
  const [selectedUploadId, setSelectedUploadId] = useState("")
  const [selectedBuildId, setSelectedBuildId] = useState(initialBuildId)
  const [selectedDeploymentId, setSelectedDeploymentId] = useState("")
  const [activeSection, setActiveSection] = useState<WorkspaceSection>("workspace")
  const [serverId, setServerId] = useState("")
  const [deployOverwrite, setDeployOverwrite] = useState(false)
  const [deployStart, setDeployStart] = useState(false)
  const [rollbackStart, setRollbackStart] = useState(false)
  const [projectRoot, setProjectRoot] = useState(".")
  const [runtimeOverride, setRuntimeOverride] = useState("auto")
  const [preflight, setPreflight] = useState<BuildPreflightResult | null>(null)
  const [plan, setPlan] = useState<BuildPlan | null>(null)
  const [detailDialog, setDetailDialog] = useState<{ title: string; body: string } | null>(null)
  const [toast, setToast] = useState<ToastState>(null)
  const [busy, setBusy] = useState(false)
  const [logFilter, setLogFilter] = useState<LogFilter>("all")
  const [liveTail, setLiveTail] = useState(false)
  const { confirm, confirmDialog } = useConfirm(t)

  const selectedUpload = uploads.find((upload) => upload.id === selectedUploadId) || null
  const selectedBuild = builds.find((build) => build.id === selectedBuildId) || null
  const latestDeployment = deployments.find((deployment) => deployment.build_id === selectedBuildId) || null
  const selectedBuildLog = buildLogs[buildLogs.length - 1] || null
  const polling = Boolean(selectedBuild && ACTIVE_BUILD_STATUSES.has(selectedBuild.status))
  const runtimeOverrideValue = runtimeOverride === "auto" ? null : runtimeOverride
  const tx = (key: string) => buildPageText(t, key)
  const notify = (message: string, tone: ToastTone = "info") => setToast({ message, tone })
  const notifyError = (err: unknown) => notify(err instanceof Error ? err.message : String(err), "error")

  useEffect(() => { void refresh(initialBuildId) }, [])

  useEffect(() => {
    if (!initialBuildId || initialBuildId === selectedBuildId) return
    const nextBuild = builds.find((build) => build.id === initialBuildId)
    if (nextBuild) setSelectedUploadId(nextBuild.upload_id)
    setSelectedBuildId(initialBuildId)
    void loadBuildLogs(initialBuildId)
  }, [initialBuildId, builds])

  useEffect(() => {
    if (!selectedBuildId || !polling) return undefined
    setLiveTail(true)
    const source = new EventSource(`/v1/builds/${encodeURIComponent(selectedBuildId)}/logs/stream`)
    source.addEventListener("log", (event) => {
      const log = JSON.parse((event as MessageEvent).data) as BuildLog
      setBuildLogs((previous) => previous.some((item) => item.id === log.id) ? previous : [...previous, log].sort((a, b) => a.sequence - b.sequence))
    })
    source.addEventListener("status", (event) => {
      const status = JSON.parse((event as MessageEvent).data) as { status?: string }
      if (status.status && !ACTIVE_BUILD_STATUSES.has(status.status)) {
        source.close()
        setLiveTail(false)
        void refresh(selectedBuildId)
      }
    })
    source.onerror = () => { source.close(); setLiveTail(false) }
    return () => { source.close(); setLiveTail(false) }
  }, [selectedBuildId, polling])

  async function loadBuildLogs(buildId: string) {
    if (!buildId) return
    try {
      const response = await buildApi.buildLogs(buildId, 200)
      setBuildLogs(response.logs)
    } catch (err) {
      setBuildLogs([])
      notifyError(err)
    }
  }

  async function refresh(preferredBuildId = selectedBuildId, preferredUploadId = selectedUploadId) {
    try {
      const [uploadData, buildData, deploymentData] = await Promise.all([buildApi.uploads(), buildApi.builds(), buildApi.deployments()])
      setUploads(uploadData.uploads)
      setBuilds(buildData.builds)
      setDeployments(deploymentData.deployments)
      const preferredBuild = buildData.builds.find((build) => build.id === preferredBuildId)
      const nextUploadId = preferredBuild?.upload_id
        || (uploadData.uploads.some((upload) => upload.id === preferredUploadId) ? preferredUploadId : "")
        || uploadData.uploads[0]?.id
        || ""
      const nextBuild = preferredBuild || buildData.builds.find((build) => build.upload_id === nextUploadId) || null
      const nextDeployment = deploymentData.deployments.find((deployment) => deployment.id === selectedDeploymentId)
        || deploymentData.deployments.find((deployment) => deployment.build_id === nextBuild?.id)
        || null
      setSelectedUploadId(nextUploadId)
      setSelectedBuildId(nextBuild?.id || "")
      setSelectedDeploymentId(nextDeployment?.id || "")
      if (nextBuild) {
        writeBuildHash(nextBuild.id, true)
        await loadBuildLogs(nextBuild.id)
      } else {
        setBuildLogs([])
      }
    } catch (err) {
      notifyError(err)
    }
  }

  async function runPreflight(uploadId = selectedUploadId, refresh = false) {
    if (!uploadId) return null
    setBusy(true)
    try {
      const response = await buildApi.preflightBuild(uploadId, { runtime_override: runtimeOverrideValue, project_root: projectRoot || ".", refresh })
      setPreflight(response)
      notify(`${tx("buildPreflight")}: ${response.status} · ${response.runtime}`, response.status === "error" ? "error" : "success")
      return response
    } catch (err) {
      notifyError(err)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function previewPlan(uploadId = selectedUploadId, refresh = false) {
    if (!uploadId) return null
    setBusy(true)
    try {
      const response = await buildApi.planBuild(uploadId, { runtime_override: runtimeOverrideValue, project_root: projectRoot || ".", refresh })
      setPreflight(response.preflight)
      setPlan(response.plan)
      notify(`${tx("buildPlan")}: ${response.plan.buildable ? tx("buildable") : tx("notBuildable")} · ${(response.plan.steps || []).length} ${tx("planSteps")}`, response.plan.buildable ? "success" : "error")
      return response
    } catch (err) {
      notifyError(err)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function createBuild(uploadId = selectedUploadId, options: { runtimeOverride?: string | null; projectRoot?: string } = {}) {
    if (!uploadId) return
    const nextRuntimeOverride = options.runtimeOverride === undefined ? runtimeOverrideValue : options.runtimeOverride
    const nextProjectRoot = options.projectRoot || projectRoot || "."
    setBusy(true)
    try {
      const preflightResult = await buildApi.preflightBuild(uploadId, { runtime_override: nextRuntimeOverride, project_root: nextProjectRoot })
      setPreflight(preflightResult)
      if (preflightResult.status === "error") {
        notify(tx("preflightBlocked"), "error")
        return
      }
      if (!nextRuntimeOverride && MANUAL_RUNTIME_REQUIRED.has(preflightResult.runtime)) {
        notify(tx("preflightManualRuntimeRequired"), "error")
        return
      }
      const build = await buildApi.createBuild(uploadId, { run_install: true, run_build: true, timeout_seconds: 300, runtime_override: nextRuntimeOverride, project_root: nextProjectRoot })
      setSelectedBuildId(build.id)
      writeBuildHash(build.id)
      notify(`${t("createBuild")}: ${build.status} · ${build.id.slice(0, 8)}`, "success")
      await refresh(build.id)
      await loadBuildLogs(build.id)
    } catch (err) {
      const detail = err instanceof BuildApiError ? err.detail : undefined
      if (detail && typeof detail === "object") {
        const blocked = detail as BuildBlockedDetail
        if (blocked.preflight) setPreflight(blocked.preflight)
        notify(`${tx("buildBlocked")} [${blocked.code}]: ${blocked.message}`, "error")
      } else {
        notifyError(err)
      }
    } finally {
      setBusy(false)
    }
  }

  async function requestStopBuild(buildId = selectedBuildId) {
    if (!buildId) return
    if (!(await confirm({ title: t("requestStopBuild"), description: t("requestStopConfirm") }))) return
    setBusy(true)
    try {
      const build = await buildApi.cancelBuild(buildId)
      setSelectedBuildId(build.id)
      writeBuildHash(build.id)
      notify(`${t("requestStopSent")} · ${t("stopRequestHint")}`, "info")
      await refresh(build.id)
      await loadBuildLogs(build.id)
    } catch (err) {
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function deployBuild(buildId = selectedBuildId) {
    if (!buildId) return
    const build = builds.find((item) => item.id === buildId) || null
    const target = resolveDeploymentTarget(serverId, build?.manifest?.id, tx("unavailableTarget"))
    const summary = formatDeploymentSummary(target, { start: deployStart, overwrite: deployOverwrite }, {
      target: tx("deploymentTarget"),
      overwrite: tx("overwriteExisting"),
      start: tx("startAfterDeploy"),
      yes: tx("enabledChoice"),
      no: tx("disabledChoice"),
      unresolved: tx("unavailableTarget"),
    })
    if (!(await confirm({ title: tx("confirmDeploymentTitle"), description: summary }))) return
    setBusy(true)
    try {
      const deployment = await buildApi.deployBuild(buildId, {
        server_id: serverId.trim() || undefined,
        start: deployStart,
        overwrite: deployOverwrite,
      })
      notify(`${t("deployBuild")}: ${deployment.status} · ${deployment.server_id}`, deployment.status === "failed" ? "error" : "success")
      await refresh(buildId)
    } catch (err) {
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function rollback(deploymentId: string) {
    const deployment = deployments.find((item) => item.id === deploymentId)
    const summary = formatRollbackSummary(deployment?.server_id || "", rollbackStart, {
      target: tx("deploymentTarget"),
      restore: tx("restoresSnapshot"),
      start: tx("startAfterRollback"),
      yes: tx("enabledChoice"),
      no: tx("disabledChoice"),
      unresolved: tx("unavailableTarget"),
    })
    if (!(await confirm({ title: tx("confirmRollbackTitle"), description: summary, destructive: true }))) return
    setBusy(true)
    try {
      const response = await buildApi.rollback(deploymentId, rollbackStart)
      notify(response.message || t("rollback"), "success")
      await refresh(selectedBuildId)
    } catch (err) {
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function deleteUpload(upload: ProjectUpload) {
    if (!(await confirm({ title: tx("deleteUploadTitle"), description: tx("deleteUploadDesc"), destructive: true }))) return
    setBusy(true)
    try {
      await buildApi.deleteUpload(upload.id)
      notify(tx("deleteSuccess"), "success")
      setPreflight(null)
      setPlan(null)
      await refresh("", "")
    } catch (err) {
      // 409 的结构化 detail.message 已由 API 层提取，直接作为 Toast 展示。
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function deleteBuild(build: BuildRecord) {
    if (!(await confirm({ title: tx("deleteBuildTitle"), description: tx("deleteBuildDesc"), destructive: true }))) return
    setBusy(true)
    try {
      await buildApi.deleteBuild(build.id)
      notify(tx("deleteSuccess"), "success")
      await refresh("", build.upload_id)
    } catch (err) {
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function deleteDeployment(deployment: DeploymentRecord) {
    if (!(await confirm({ title: tx("deleteDeploymentTitle"), description: tx("deleteDeploymentDesc"), destructive: true }))) return
    setBusy(true)
    try {
      await buildApi.deleteDeployment(deployment.id)
      notify(tx("deleteSuccess"), "success")
      setSelectedDeploymentId("")
      await refresh(selectedBuildId, selectedUploadId)
    } catch (err) {
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  function retryBuild(build: BuildRecord) {
    showBuild(build, "workspace")
    const retryRuntime = build.runtime === "node" || build.runtime === "python" ? build.runtime : null
    void createBuild(build.upload_id, { runtimeOverride: retryRuntime, projectRoot: build.plan?.project_root_dir || "." })
  }

  function showBuild(build: BuildRecord, section: WorkspaceSection = "workspace") {
    setSelectedUploadId(build.upload_id)
    setSelectedBuildId(build.id)
    setActiveSection(section)
    writeBuildHash(build.id)
    void loadBuildLogs(build.id)
  }

  function showDeployment(deployment: DeploymentRecord, detail = false) {
    setSelectedDeploymentId(deployment.id)
    const build = builds.find((item) => item.id === deployment.build_id)
    if (build) {
      setSelectedBuildId(build.id)
      setSelectedUploadId(build.upload_id)
    }
    if (detail) setDetailDialog({ title: `${t("deploymentRecords")} · ${deployment.server_id}`, body: JSON.stringify(deployment, null, 2) })
  }

  function canRequestStop(build: BuildRecord) {
    return STOP_REQUESTABLE_BUILD_STATUSES.has(build.status)
  }

  function onCopied(message: string) {
    notify(`${t("copied")}: ${message}`, "success")
  }

  function changeSelectedUpload(uploadId: string) {
    setSelectedUploadId(uploadId)
    const nextBuild = builds.find((build) => build.upload_id === uploadId) || null
    setSelectedBuildId(nextBuild?.id || "")
    setSelectedDeploymentId(nextBuild ? deployments.find((deployment) => deployment.build_id === nextBuild.id)?.id || "" : "")
    setBuildLogs([])
    if (nextBuild) {
      writeBuildHash(nextBuild.id, true)
      void loadBuildLogs(nextBuild.id)
    }
    setRuntimeOverride("auto")
    setProjectRoot(".")
    setServerId("")
    setPreflight(null)
    setPlan(null)
  }

  return <div className="flex flex-col gap-4">
    <PageHeader
      eyebrow={t("projectPipeline")}
      title={t("builds")}
      description={`${t("buildDeployDesc")} ${t("longBuildHint")}`}
      actions={<Button variant="outline" disabled={busy} onClick={() => void refresh()}>{t("refresh")}</Button>}
      stats={[
        { label: t("uploads"), value: uploads.length },
        { label: t("buildRecords"), value: builds.length },
        { label: t("deploymentRecords"), value: deployments.length },
        { label: t("status"), value: selectedBuild?.status || "-", tone: selectedBuild?.status === "success" ? "success" : selectedBuild?.status === "failed" ? "danger" : "default" },
      ]}
    />
    <WorkflowSteps ariaLabel={t("workflowProgress")} steps={[
      { label: t("selectUpload"), state: selectedUpload ? "done" : "current" },
      { label: tx("runPreflight"), state: preflight ? "done" : selectedUpload ? "current" : "next" },
      { label: t("createBuild"), state: selectedBuild ? "done" : preflight ? "current" : "next" },
      { label: t("deployBuild"), state: latestDeployment ? "done" : selectedBuild?.status === "success" ? "current" : "next" },
    ]} />
    <Card>
      <CardContent className="p-2"><div role="tablist" aria-label={tx("workspaceNavigation")} className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1 md:grid-cols-4">
        {(["workspace", "builds", "deployments", "logs"] as WorkspaceSection[]).map((section) => <Button key={section} type="button" role="tab" aria-selected={activeSection === section} variant={activeSection === section ? "secondary" : "ghost"} onClick={() => setActiveSection(section)}>{tx(`${section}Tab`)}</Button>)}
      </div></CardContent>
    </Card>

    {activeSection === "workspace" ? <>
    <Card>
      <CardHeader className="gap-3 md:flex-row md:items-start md:justify-between">
        <div><CardTitle>{tx("projectContext")}</CardTitle><CardDescription>{tx("projectContextDesc")}</CardDescription></div>
        <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => selectedUpload && void deleteUpload(selectedUpload)} disabled={busy || !selectedUpload}>{tx("deleteUpload")}</Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <Field label={t("selectUpload")}>
            <Select value={selectedUploadId || undefined} onValueChange={changeSelectedUpload}>
              <SelectTrigger><SelectValue placeholder={t("selectUpload")} /></SelectTrigger>
              <SelectContent>{uploads.map((upload) => <SelectItem key={upload.id} value={upload.id}>{upload.filename} · {upload.detected_runtime}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm"><div className="text-xs text-muted-foreground">{tx("latestBuild")}</div><div className="font-medium">{selectedBuild ? `${selectedBuild.status} · ${selectedBuild.runtime}` : tx("noBuild")}</div></div>
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm"><div className="text-xs text-muted-foreground">{tx("latestDeployment")}</div><div className="font-medium">{latestDeployment ? `${latestDeployment.status} · ${latestDeployment.server_id}` : tx("notDeployed")}</div></div>
        </div>
        <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{tx("advancedSettings")}</summary><div className="mt-3 grid gap-3 md:grid-cols-3">
          <Field label={t("runtimeType")}><Select value={runtimeOverride} onValueChange={(value) => { setRuntimeOverride(value); setPreflight(null); setPlan(null) }}><SelectTrigger><SelectValue placeholder={t("runtimeType")} /></SelectTrigger><SelectContent><SelectItem value="auto">{tx("runtimeAuto")}</SelectItem><SelectItem value="node">{tx("runtimeNode")}</SelectItem><SelectItem value="python">{tx("runtimePython")}</SelectItem></SelectContent></Select></Field>
          <Field label={tx("projectRoot")}><Input placeholder={tx("projectRootPlaceholder")} value={projectRoot} onChange={(event) => { setProjectRoot(event.target.value); setPreflight(null); setPlan(null) }} /></Field>
          <Field label={t("overrideServerId")}><Input placeholder={t("overrideServerId")} value={serverId} onChange={(event) => setServerId(event.target.value)} /></Field>
        </div></details>
        <div className="rounded-md border p-3">
          <div className="mb-3 text-sm font-medium">{tx("deploymentOptions")}</div>
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-md bg-muted/30 px-3 py-2 text-sm">
              <div className="text-xs text-muted-foreground">{tx("deploymentTarget")}</div>
              <div className="break-all font-mono">{serverId.trim() || (typeof selectedBuild?.manifest?.id === "string" ? selectedBuild.manifest.id : tx("unavailableTarget"))}</div>
            </div>
            <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <input type="checkbox" className="mt-1" checked={deployOverwrite} onChange={(event) => setDeployOverwrite(event.target.checked)} />
              <span><span className="font-medium">{tx("overwriteExisting")}</span><span className="block text-xs text-muted-foreground">{tx("overwriteExistingDesc")}</span></span>
            </label>
            <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm">
              <input type="checkbox" className="mt-1" checked={deployStart} onChange={(event) => setDeployStart(event.target.checked)} />
              <span><span className="font-medium">{tx("startAfterDeploy")}</span><span className="block text-xs text-muted-foreground">{tx("startAfterDeployDesc")}</span></span>
            </label>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Button variant="secondary" onClick={() => void runPreflight()} disabled={busy || !selectedUploadId}>{tx("runPreflight")}</Button>
          <Button variant="outline" onClick={() => void runPreflight(selectedUploadId, true)} disabled={busy || !selectedUploadId}>{tx("forceRefresh")}</Button>
          <Button variant="secondary" onClick={() => void previewPlan()} disabled={busy || !selectedUploadId}>{tx("previewPlan")}</Button>
          <div className="mx-1 hidden h-6 w-px bg-border sm:block" />
          <Button onClick={() => createBuild()} disabled={busy || !selectedUploadId}>{t("createBuild")}</Button>
          <Button variant="secondary" onClick={() => deployBuild()} disabled={busy || !selectedBuildId || selectedBuild?.status !== "success"}>{t("deployBuild")}</Button>
          <Button variant="outline" onClick={() => requestStopBuild()} disabled={busy || !selectedBuild || !canRequestStop(selectedBuild)}>{t("requestStopBuild")}</Button>
        </div>
      </CardContent>
    </Card>

    {preflight ? <PreflightCard preflight={preflight} t={t} /> : null}
    {plan ? <BuildPlanCard plan={plan} t={t} /> : null}

    <BuildHintCard build={selectedBuild} t={t} />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
      <BuildDetailCard build={selectedBuild} logs={buildLogs} polling={polling} t={t} onCopied={onCopied} />
      <BuildTimelineCard build={selectedBuild} logs={buildLogs} t={t} />
    </div>

    </> : null}

    {activeSection === "builds" ? <BuildRecordsTable builds={builds} busy={busy} selectedBuildId={selectedBuildId} canRequestStop={canRequestStop} onShowBuild={(build) => showBuild(build, "workspace")} onLoadLogs={(build) => showBuild(build, "logs")} onRequestStop={(id) => void requestStopBuild(id)} onDeploy={(id) => void deployBuild(id)} onRetry={retryBuild} onDelete={(build) => void deleteBuild(build)} t={t} /> : null}
    {activeSection === "deployments" ? <>
      <Card>
        <CardHeader><CardTitle>{tx("rollbackSummary")}</CardTitle><CardDescription>{tx("startAfterRollbackDesc")}</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="rounded-md bg-muted/30 px-3 py-2 text-sm"><div className="text-xs text-muted-foreground">{tx("deploymentTarget")}</div><div className="break-all font-mono">{deployments.find((item) => item.id === selectedDeploymentId)?.server_id || tx("unavailableTarget")}</div></div>
          <div className="rounded-md bg-muted/30 px-3 py-2 text-sm"><div className="text-xs text-muted-foreground">{tx("restoresSnapshot")}</div><div>{tx("enabledChoice")}</div></div>
          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={rollbackStart} onChange={(event) => setRollbackStart(event.target.checked)} /><span><span className="font-medium">{tx("startAfterRollback")}</span><span className="block text-xs text-muted-foreground">{tx("startAfterRollbackDesc")}</span></span></label>
        </CardContent>
      </Card>
      <DeploymentRecordsTable deployments={deployments} busy={busy} selectedDeploymentId={selectedDeploymentId} onSelect={(deployment) => showDeployment(deployment)} onDetail={(deployment) => showDeployment(deployment, true)} onRollback={(id) => void rollback(id)} onDelete={(deployment) => void deleteDeployment(deployment)} t={t} />
    </> : null}
    {activeSection === "logs" ? <div className="flex flex-col gap-4"><BuildLogsTable logs={buildLogs} filter={logFilter} onFilterChange={setLogFilter} selectedBuildLabel={selectedBuild ? `${selectedBuild.id} · ${selectedBuild.status} · ${buildLogs.length}` : t("noData")} live={liveTail} t={t} /><BuildOutputPanels build={selectedBuild} log={selectedBuildLog} t={t} /></div> : null}

    <Toaster toast={toast} onClose={() => setToast(null)} />
    {confirmDialog}

    <Dialog open={detailDialog !== null} onOpenChange={(open) => { if (!open) setDetailDialog(null) }}>
      <DialogContent className="max-w-4xl">
        <DialogHeader><DialogTitle>{detailDialog?.title || ""}</DialogTitle></DialogHeader>
        <DialogBody><JsonPanel text={detailDialog?.body} maxHeight="max-h-[60vh]" /></DialogBody>
      </DialogContent>
    </Dialog>
  </div>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex flex-col gap-1"><label className="text-xs font-medium text-muted-foreground">{label}</label>{children}</div>
}

const RUNTIME_BLOCKED = new Set(["unknown", "ambiguous", "docker"])

function PreflightCard({ preflight, t }: { preflight: BuildPreflightResult; t: TFunction }) {
  const visibleChecks = preflight.checks.slice(0, 16)
  const tx = (key: string) => buildPageText(t, key)
  const tools = Object.entries(preflight.tools || {}) as Array<[string, BuildPreflightTool]>
  const scripts = Array.isArray(preflight.metadata?.package_scripts) ? preflight.metadata.package_scripts : []
  const recommendations = [...preflight.recommendations].sort((a, b) => Number(b.platform === preflight.platform) - Number(a.platform === preflight.platform))
  const runtimeBlocked = RUNTIME_BLOCKED.has(preflight.runtime)
  const statusVariant = preflight.status === "error" ? "danger" : preflight.status === "warning" ? "warning" : "success"

  const cache = preflight.cache
  const diff = preflight.diff
  const affected = new Set(diff?.affected_checks || [])
  const showDiff = Boolean(diff?.has_previous && !diff?.unchanged && ((diff?.changed_files.added.length || diff?.changed_files.removed.length || diff?.changed_files.modified.length || diff?.tool_changes.length || diff?.affected_checks.length)))

  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        {tx("buildPreflight")}
        {cache ? <Badge variant={cache.hit ? "success" : "secondary"} className="font-normal" title={cache.cache_key}>{cache.hit ? `${tx("cacheHit")} · ${cache.cached_at}` : tx("cacheMiss")}</Badge> : null}
        {cache?.reused_tools ? <Badge variant="outline" className="border-primary/40 font-normal text-primary" title={tx("reusedToolsHint")}>{tx("reusedTools")}</Badge> : null}
      </CardTitle>
      <CardDescription>{tx("preflightDesc")}</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-col gap-4">
      <div className="grid gap-2 text-sm md:grid-cols-4">
        <div><span className="text-muted-foreground">{tx("preflightStatus")}</span><div><Badge variant={statusVariant}>{localizeStatus(t, preflight.status)}</Badge></div></div>
        <div><span className="text-muted-foreground">{tx("preflightRuntime")}</span><div className={`font-mono ${runtimeBlocked ? "text-destructive" : ""}`}>{preflight.runtime}{preflight.detected_runtime && preflight.detected_runtime !== preflight.runtime ? ` (${tx("detected")}: ${preflight.detected_runtime})` : ""}</div></div>
        <div><span className="text-muted-foreground">{tx("projectRoot")}</span><div className="truncate font-mono" title={preflight.project_root_dir}>{preflight.project_root_dir}</div></div>
        <div><span className="text-muted-foreground">{t("platform")}</span><div className="font-mono">{preflight.platform}</div></div>
      </div>

      {runtimeBlocked ? <Alert variant="destructive"><AlertDescription>{tx("preflightManualRuntimeRequired")}</AlertDescription></Alert> : null}

      {preflight.project_root_auto_descended ? <Alert><AlertDescription>{tx("autoDescended")}: {preflight.project_root_auto_descended}</AlertDescription></Alert> : null}

      {showDiff && diff ? <div className="rounded-md border bg-muted px-3 py-2 text-sm">
        <div className="mb-1 font-medium">{tx("changesSinceLast")}</div>
        <div className="flex flex-wrap gap-2">
          {diff.changed_files.modified.map((name) => <Badge key={`m-${name}`} variant="warning" className="font-mono">~ {name}</Badge>)}
          {diff.changed_files.added.map((name) => <Badge key={`a-${name}`} variant="success" className="font-mono">+ {name}</Badge>)}
          {diff.changed_files.removed.map((name) => <Badge key={`r-${name}`} variant="danger" className="font-mono">- {name}</Badge>)}
          {diff.tool_changes.map((change) => <Badge key={`t-${change.name}`} variant="outline" className="border-primary/40 font-mono text-primary">{change.name}: {change.from ? tx("available") : tx("missing")} → {change.to ? tx("available") : tx("missing")}</Badge>)}
        </div>
        <div className="mt-2 text-xs text-muted-foreground">{tx("fileCountDelta")}: {diff.file_count_delta >= 0 ? `+${diff.file_count_delta}` : diff.file_count_delta} · {tx("affectedChecks")}: {diff.affected_checks.length}</div>
      </div> : null}

      <div>
        <div className="mb-1 text-sm font-medium">{tx("toolStatus")}</div>
        <div className="flex flex-wrap gap-2">
          {tools.map(([name, info]) => <Badge key={name} variant={info.available ? "success" : "secondary"} className="font-mono" title={info.version || info.error || info.path || ""}>{name}: {info.available ? tx("available") : tx("missing")}{info.version ? ` · ${info.version}` : ""}</Badge>)}
        </div>
      </div>

      <div>
        <div className="mb-1 text-sm font-medium">{tx("packageScripts")}</div>
        {scripts.length ? <div className="flex flex-wrap gap-2">{scripts.map((name) => <Badge key={name} variant="outline" className="font-mono">{name}</Badge>)}</div> : <div className="text-sm text-muted-foreground">{tx("noScripts")}</div>}
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead><tr className="border-b"><th className="px-3 py-2 text-left">{t("check")}</th><th className="px-3 py-2 text-left">{t("status")}</th><th className="px-3 py-2 text-left">{t("description")}</th></tr></thead>
          <tbody>{visibleChecks.map((check) => <tr key={check.id} className={`border-b last:border-0 ${affected.has(check.id) ? "bg-muted" : ""}`}><td className="px-3 py-2 font-mono">{check.id}{affected.has(check.id) ? <span className="ml-1 text-primary">●</span> : null}</td><td className="px-3 py-2">{localizeStatus(t, check.status)}</td><td className="px-3 py-2">{check.message}<div className="text-xs text-muted-foreground">{check.detail}</div></td></tr>)}</tbody>
        </table>
      </div>
      <div>
        <div className="mb-1 text-sm font-medium">{tx("preflightRecommendations")}</div>
        <ul className="list-disc pl-5 text-sm text-muted-foreground [&>li+li]:mt-1">
          {recommendations.map((item) => <li key={`${item.platform}-${item.message}`}><span className="font-mono">{item.platform}{item.platform === preflight.platform ? " ★" : ""}</span>: {item.message}</li>)}
        </ul>
      </div>
    </CardContent>
  </Card>
}

function BuildPlanCard({ plan, t }: { plan: BuildPlan; t: TFunction }) {
  const tx = (key: string) => buildPageText(t, key)
  const manifest = plan.manifest
  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        {tx("buildPlan")}
        <Badge variant="outline" className="font-normal text-muted-foreground">IR v{plan.ir_version}</Badge>
        <Badge variant={plan.buildable ? "success" : "danger"} className="font-normal">{plan.buildable ? tx("buildable") : tx("notBuildable")}</Badge>
      </CardTitle>
      <CardDescription>{tx("buildPlanDesc")}</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-col gap-4">
      <div className="grid gap-2 text-sm md:grid-cols-3">
        <div><span className="text-muted-foreground">{tx("preflightRuntime")}</span><div className="font-mono">{plan.runtime}</div></div>
        <div><span className="text-muted-foreground">{tx("projectRoot")}</span><div className="truncate font-mono" title={plan.project_root_dir || ""}>{plan.project_root_dir}</div></div>
        <div><span className="text-muted-foreground">{tx("artifactStrategy")}</span><div className="font-mono">{plan.artifact?.strategy || "-"}</div></div>
      </div>

      <div>
        <div className="mb-1 text-sm font-medium">{tx("planSteps")}</div>
        {plan.steps.length ? <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead><tr className="border-b"><th className="px-3 py-2 text-left">#</th><th className="px-3 py-2 text-left">{tx("phase")}</th><th className="px-3 py-2 text-left">{tx("command")}</th><th className="px-3 py-2 text-left">{tx("dependsOn")}</th><th className="px-3 py-2 text-left">{tx("reason")}</th></tr></thead>
            <tbody>{plan.steps.map((step, index) => <tr key={step.id} className="border-b last:border-0"><td className="px-3 py-2 font-mono">{index + 1}</td><td className="px-3 py-2 font-mono">{step.phase}</td><td className="px-3 py-2 font-mono">{step.command.join(" ")}</td><td className="px-3 py-2 font-mono text-muted-foreground">{step.depends_on && step.depends_on.length ? step.depends_on.join(", ") : "-"}</td><td className="px-3 py-2 text-muted-foreground">{step.reason}</td></tr>)}</tbody>
          </table>
        </div> : <div className="text-sm text-muted-foreground">{tx("noSteps")}</div>}
      </div>

      {manifest ? <div>
        <div className="mb-1 text-sm font-medium">{tx("manifestStrategy")}</div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="outline" className="font-mono">{manifest.launch_type} · {manifest.transport}</Badge>
          {manifest.start_script ? <Badge variant="success" className="font-mono">npm run start</Badge> : null}
          {manifest.python_entrypoint ? <Badge variant="outline" className="font-mono">python {manifest.python_entrypoint}</Badge> : null}
          {(manifest.entrypoint_candidates || []).map((entry) => <Badge key={entry} variant="outline" className="font-mono text-muted-foreground">{entry}</Badge>)}
          {manifest.resolve_after_build ? <Badge variant="outline" className="border-primary/40 font-mono text-primary">{tx("resolveAfterBuild")}</Badge> : null}
        </div>
      </div> : null}

      {plan.warnings.length ? <Alert><AlertDescription><ul className="list-disc pl-5 [&>li+li]:mt-1">{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></AlertDescription></Alert> : null}
    </CardContent>
  </Card>
}

export function buildHash(buildId: string) {
  return `#/builds/${encodeURIComponent(buildId)}`
}

function writeBuildHash(buildId: string, replace = false) {
  const hash = buildHash(buildId)
  if (replace) {
    window.history.replaceState(null, "", hash)
    return
  }
  if (window.location.hash !== hash) window.location.hash = hash
}

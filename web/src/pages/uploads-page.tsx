import { useRemainingViewport } from "@/components/use-remaining-viewport"
import { UploadOutlined, FileSearchOutlined, BuildOutlined, CloudUploadOutlined, PlayCircleOutlined } from "@ant-design/icons"
import { Drawer, Segmented } from "antd"
import { GitImportForm } from "@/features/network/git-import-form"
import { networkApi } from "@/api/network"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { JsonPanel } from "@/components/json-panel"
import { deliveryDraftRequest, manifestPatch, mergeManifestPatch } from "@/features/servers/delivery-draft"
import { useContext, useEffect, useMemo, useRef, useState } from "react"
import { buildApi, type BuildRecord, type DeploymentRecord, type ProjectUpload, type DeliveryDraft, type PackageManagerOverride } from "@/api/builds"
import { useConfirm } from "@/components/confirm-dialog"
import { usePageRefresh } from "@/components/page-refresh"
import { PageHeader, PageToolbar, WorkflowSteps } from "@/components/page-shell"
import { UploadForm } from "@/components/uploads/upload-form"
import { UploadList } from "@/components/uploads/upload-list"
import { UploadResultPanel } from "@/components/uploads/upload-result-panel"
import { ProjectDetailPanel } from "@/components/uploads/project-detail-panel"
import { confirmedBuildAttempt, type BuildAttempt } from "@/features/network/build-attempt"
import { uploadCopy } from "@/components/uploads/upload-copy"
import { asRecord, completeUploadAction, resultForUpload, type UploadAction, type UploadResults } from "@/components/uploads/upload-state"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { localizeStatus, type TFunction } from "@/i18n"
import { buildPageText } from "@/pages/builds-page-text"
import { formatDeploymentSummary, resolveDeploymentTarget } from "@/features/deployment-options"

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json", ...(init?.headers || {}) }, ...init })
  const text = await response.text()
  const data = text ? JSON.parse(text) : {}
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || `${response.status} ${response.statusText}`)
  return data as T
}

export function UploadsPage({ t }: { t: TFunction }) {
  const workspace = useRemainingViewport<HTMLDivElement>(12)
  const manifestBases = useRef<Record<string, Record<string, unknown>>>({})
  const [historyOpen, setHistoryOpen] = useState(false)
  const [sourceMode, setSourceMode] = useState<"zip" | "git">("zip")
  const [gitState, setGitState] = useState({ dirty: false, pending: false })
  const [taskResetVersion, setTaskResetVersion] = useState(0)
  const [selectionDirty, setSelectionDirty] = useState(false)
  const [actionContainer, setActionContainer] = useState<HTMLDivElement | null>(null)
  const [drafts, setDrafts] = useState<Record<string, DeliveryDraft>>({})
  const [packageChoices, setPackageChoices] = useState<Record<string, PackageManagerOverride[]>>({})
  const buildAttempts = useRef(new Map<string, BuildAttempt>())
  const [busy, setBusy] = useState(false)
  const [completedBuildTarget, setCompletedBuildTarget] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<{ uploadId: string | null; message: string } | null>(null)
  const [uploads, setUploads] = useState<ProjectUpload[]>([])
  const [builds, setBuilds] = useState<BuildRecord[]>([])
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([])
  const [selection, setSelection] = useState<ProjectUpload | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [results, setResults] = useState<UploadResults>({})
  const [query, setQuery] = useState("")
  const mounted = useRef(true)
  const running = useRef(false)
  const loadRequest = useRef(0)
  const actionRequest = useRef(0)
  const selectionRevision = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const tx = (key: string) => buildPageText(t, key)
  const c = uploadCopy(t)
  const selectedUploadId = selection?.id || ""


  const registerExit = useContext(EditorNavigationContext)
  const zh = t("uploads") === "项目上传"
  useEffect(() => registerExit?.({ dirty: Boolean(selectedFile), pending: busy }), [registerExit, selectedFile, busy])
  // Wait for the saved draft and pending/dirty exit flags to commit before
  // normal guarded navigation. Never bypass another editor's exit protection.
  useEffect(() => {
    if (!completedBuildTarget || busy || selectionDirty) return
    const frame = window.requestAnimationFrame(() => {
      setCompletedBuildTarget(null)
      window.location.hash = `#/builds/${encodeURIComponent(completedBuildTarget)}`
    })
    return () => window.cancelAnimationFrame(frame)
  }, [completedBuildTarget, busy, selectionDirty])

  async function requestSelection(upload: ProjectUpload | null) {
    if (busy || gitState.pending) return false
    if (upload && upload.id === selection?.id) { setHistoryOpen(false); return true }
    if ((selectionDirty || selectedFile) && !(await confirm({ title: zh ? "放弃当前未保存的交付输入？" : "Discard unsaved delivery input?", destructive: true }))) return false
    setSelectionDirty(false); setSelectedFile(null); selectUpload(upload); setHistoryOpen(false)
    return true
  }


  useEffect(() => {
    mounted.current = true
    void loadUploads()
    return () => { mounted.current = false; loadRequest.current += 1 }
  }, [])
  usePageRefresh(loadUploads, loading || busy)

  useEffect(() => {
    let active = true
    if (selectedUploadId) void buildApi.deliveryDraft(selectedUploadId).then(draft => {
      if (!active) return
      setDrafts(previous => ({ ...previous, [selectedUploadId]: draft }))

    }).catch(error => { if (active) setActionError({ uploadId: selectedUploadId, message: String(error) }) })
    return () => { active = false }
  }, [selectedUploadId])

  function selectUpload(upload: ProjectUpload | null) {
    selectionRevision.current += 1
    setSelection(upload)
  }

  async function run<T>(uploadId: string | null, action: UploadAction, task: () => Promise<T>, options: { manifest?: Record<string, unknown>; throwOnError?: boolean } = {}): Promise<T | null> {
    if (running.current) return null
    running.current = true
    const requestId = ++actionRequest.current
    setBusy(true)
    setActionError(null)
    try {
      const value = await task()
      const ownerId = uploadId || asRecord(value)?.id
      if (mounted.current && typeof ownerId === "string") {
        setResults(previous => completeUploadAction(previous, { uploadId: ownerId, action, requestId, data: value, manifest: options.manifest }))
      }
      return value
    } catch (err) {
      if (options.throwOnError) throw err
      if (mounted.current) setActionError({ uploadId, message: err instanceof Error ? err.message : String(err) })
      return null
    } finally {
      running.current = false
      if (mounted.current) setBusy(false)
    }
  }

  async function loadUploads() {
    const requestId = ++loadRequest.current
    setLoading(true)
    setLoadError(null)
    try {
      const [uploadData, buildData, deploymentData] = await Promise.all([buildApi.uploads(), buildApi.builds(), buildApi.deployments()])
      if (!mounted.current || requestId !== loadRequest.current) return
      setUploads(uploadData.uploads)
      setBuilds(buildData.builds)
      setDeployments(deploymentData.deployments)
      // Refresh metadata without changing the selected object or its editor session.
      setSelection(previous => previous ? uploadData.uploads.find(upload => upload.id === previous.id) || previous : null)
    } catch (err) {
      if (mounted.current && requestId === loadRequest.current) setLoadError(err instanceof Error ? err.message : String(err))
    } finally {
      if (mounted.current && requestId === loadRequest.current) setLoading(false)
    }
  }

  async function uploadZip() {
    if (!selectedFile || running.current) return
    const selectedAtStart = selectionRevision.current
    const body = new FormData()
    body.append("file", selectedFile)
    const upload = await run(null, "upload", () => requestJson<ProjectUpload>("/v1/projects/upload", { method: "POST", body }))
    if (!upload || !mounted.current) return
    setSelectedFile(null)
    setUploads(previous => [upload, ...previous.filter(item => item.id !== upload.id)])
    if (selectionRevision.current === selectedAtStart) selectUpload(upload)
    await loadUploads()
  }

  async function draftUpload(uploadId: string) {
    const upload = uploads.find(item => item.id === uploadId)
    if (!upload || running.current) return
    if (!(await requestSelection(upload))) return
    await run(uploadId, "draft", async () => {
      const response = await requestJson<{ manifest?: Record<string, unknown>; draft?: { manifest?: Record<string, unknown> } }>(`/v1/projects/uploads/${encodeURIComponent(uploadId)}/draft-manifest`, { method: "POST" })
      const base = response.manifest || response.draft?.manifest
      if (!base) throw new Error("Generated manifest is unavailable")
      manifestBases.current[uploadId] = base
      return { ...response, manifest: mergeManifestPatch(base, drafts[uploadId]?.manifest_patch || {}) }
    })
  }

  async function deleteUpload(uploadId: string) {
    if (running.current || !(await confirm({ title: t("confirmDeleteUploadTitle"), description: t("confirmDeleteUploadDesc"), destructive: true }))) return
    const deleted = await run(uploadId, "delete", () => requestJson(`/v1/projects/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE" }))
    if (!deleted || !mounted.current) return
    setSelection(previous => previous?.id === uploadId ? null : previous)
    setResults(previous => { const next = { ...previous }; delete next[uploadId]; return next })
    await loadUploads()
  }

  async function saveManifest(uploadId: string, manifest: Record<string, unknown>, credentialValues: Record<string, string>) {
    if (Object.keys(credentialValues).length) throw new Error("Set secrets in personal credential bindings; delivery drafts accept credential references only.")
    const current = drafts[uploadId]
    if (!current) throw new Error("Delivery draft is unavailable. Reload before saving.")
    const base = manifestBases.current[uploadId]
    if (!base) throw new Error("Generate the project manifest before editing delivery configuration.")
    const patch = manifestPatch(base, manifest)
    const saved = await run(uploadId, "save", () => buildApi.saveDeliveryDraft(uploadId, deliveryDraftRequest(current, { manifest_patch: patch })), { manifest, throwOnError: true })
    if (!saved) throw new Error(t("failed"))
    setDrafts(previous => ({ ...previous, [uploadId]: saved }))
  }

  async function buildProject(uploadId: string, options: { run_install: boolean; run_build: boolean; project_root: string; runtime_override?: string | null; server_id?: string | null; package_manager_override?: PackageManagerOverride | null }) {
    if (running.current || busy) return
    const existingDraft = drafts[uploadId] || await run(uploadId, "build", () => buildApi.deliveryDraft(uploadId))
    if (!existingDraft) return
    const configuredDraft = await run(uploadId, "build", () => buildApi.saveDeliveryDraft(uploadId, deliveryDraftRequest(existingDraft, {
      project_root: options.project_root, runtime_override: options.runtime_override === undefined ? existingDraft.runtime_override : options.runtime_override,
      server_id: options.server_id === undefined ? existingDraft.server_id : options.server_id,
      package_manager_override: options.package_manager_override === undefined ? existingDraft.package_manager_override : options.package_manager_override,
    })))
    if (!configuredDraft) return
    setDrafts(previous => ({ ...previous, [uploadId]: configuredDraft }))
    const build = await run(uploadId, "build", async () => {
      const buildOptions = { run_install: options.run_install, run_build: options.run_build, project_root: configuredDraft.project_root || ".", runtime_override: configuredDraft.runtime_override, package_manager_override: configuredDraft.package_manager_override }
      const preview = await buildApi.planBuild(uploadId, buildOptions)
      setPackageChoices(previous => ({ ...previous, [uploadId]: preview.plan.recommended_choices || [] }))
      if (!preview.plan.buildable) throw new Error(preview.plan.warnings.join("; ") || "build_plan_blocked")
      const upload = uploads.find(item => item.id === uploadId)
      if (preview.plan.requires_safe_executor) {
        const bundle = await networkApi.planBuild(uploadId, buildOptions)
        if (!bundle.validation.ok || !bundle.plan.buildable) throw new Error(bundle.plan.warnings.join("; ") || "build_plan_blocked")
        if (!(await confirm({ title: zh ? "确认执行此安装与构建计划？" : "Confirm this installation and build plan?", description: `${bundle.source_sha256}\n${bundle.plan_fingerprint}`, details: <JsonPanel copyLabel={t("copy")} data={{ plan: bundle.plan, included_files: upload?.analysis.included_files, file_list_sha256: upload?.analysis.file_list_sha256 }} /> }))) return null
        const attempt = confirmedBuildAttempt(buildAttempts.current.get(uploadId), bundle.plan_fingerprint, builds, () => `git-build-${crypto.randomUUID()}`)
        buildAttempts.current.set(uploadId, attempt)
        const created = await networkApi.build(bundle, buildOptions, attempt.key)
        attempt.buildId = created.build_id
        const record = (await buildApi.builds()).builds.find(item => item.id === created.build_id)
        if (!record) throw new Error(`Build ${created.build_id} was created; refresh before retrying.`)
        return record
      }
      return buildApi.createBuild(uploadId, { ...buildOptions, timeout_seconds: 300 })
    })
    if (build && mounted.current) {
      setBuilds(previous => [build, ...previous.filter(item => item.id !== build.id)])
      const draft = configuredDraft
      if (draft) {
        const saved = await run(uploadId, "build", () => buildApi.saveDeliveryDraft(uploadId, deliveryDraftRequest(draft, { build_id: build.id, deployment_id: null, project_root: options.project_root })).catch(error => { throw new Error(`Build ${build.id} was created. Task context could not be saved; open this build before retrying. ${String(error)}`) }))
        if (!saved) return
        setDrafts(previous => ({ ...previous, [uploadId]: saved }))
        setSelectionDirty(false)
        setTaskResetVersion(value => value + 1)
      }
      setCompletedBuildTarget(build.id)
    }
  }

  async function saveBuildOptions(uploadId: string, options: Partial<DeliveryDraft>) {
    const current = drafts[uploadId]
    if (!current) return
    const saved = await run(uploadId, "save", () => buildApi.saveDeliveryDraft(uploadId, deliveryDraftRequest(current, options)))
    if (!saved || !mounted.current) return
    setDrafts(previous => ({ ...previous, [uploadId]: saved }))
    setSelectionDirty(false)
    setTaskResetVersion(value => value + 1)
  }

  async function deployProject(buildId: string, options: { server_id?: string; start: boolean; overwrite: boolean }) {
    const build = builds.find(item => item.id === buildId)
    if (!build || running.current) return
    const target = resolveDeploymentTarget(options.server_id, build.manifest?.id, tx("unavailableTarget"))
    const summary = formatDeploymentSummary(target, options, {
      target: tx("deploymentTarget"), overwrite: tx("overwriteExisting"), start: tx("startAfterDeploy"),
      yes: tx("enabledChoice"), no: tx("disabledChoice"), unresolved: tx("unavailableTarget"),
    })
    const deployment = await run(build.upload_id, "deploy", async () => {
      const draft = drafts[build.upload_id]
      if (!draft) throw new Error("Delivery draft is unavailable. Reload before deploying.")
      const requestOptions = { ...options, manifest_patch: draft.manifest_patch }
      const preview = await buildApi.previewDeployment(buildId, requestOptions)
      if (!(await confirm({ title: tx("confirmDeploymentTitle"), description: `${summary}\n${preview.changed_fields.join(", ")}\n${preview.config_digest}`, details: <JsonPanel copyLabel={t("copy")} data={{ build_id: preview.build_id, credential_state: preview.credential_state, interrupts_existing_service: preview.interrupts_existing_service, manifest: preview.manifest }} /> }))) return null
      const result = await buildApi.deployBuild(buildId, { ...requestOptions,
        expected_config_digest: preview.config_digest,
        expected_previous_config_digest: preview.expected_previous_config_digest,
        expected_credential_binding_digest: preview.expected_credential_binding_digest,
      })
      if (result.status !== "success") throw new Error(`${result.status}: ${result.server_id}`)
      const saved = await buildApi.saveDeliveryDraft(build.upload_id, deliveryDraftRequest(draft, { build_id: buildId, deployment_id: result.id, server_id: result.server_id, start: options.start, overwrite: options.overwrite })).catch(error => { throw new Error(`Deployment ${result.id}: ${result.status}. Task context could not be saved; refresh before retrying. ${String(error)}`) })
      setDrafts(previous => ({ ...previous, [build.upload_id]: saved }))
      setTaskResetVersion(value => value + 1)
      return result
    })
    if (deployment && mounted.current) await loadUploads()
  }

  const selectedBuild = builds.filter(build => build.upload_id === selectedUploadId).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0] || null
  const selectedDeployment = selectedBuild ? deployments.find(deployment => deployment.build_id === selectedBuild.id) || null : null
  const result = resultForUpload(results, selectedUploadId)
  const visibleUploads = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return keyword ? uploads.filter(upload => [upload.id, upload.filename, upload.detected_runtime, upload.status].some(value => value?.toLowerCase().includes(keyword))) : uploads
  }, [query, uploads])
  const visibleActionError = actionError && (!actionError.uploadId || actionError.uploadId === selectedUploadId) ? actionError.message : null

  const completedStatus = zh ? "已完成" : "Completed"
  const buildStepStatus = selectedBuild ? selectedBuild.status === "success" ? completedStatus : localizeStatus(t, selectedBuild.status) : (zh ? "待创建" : "Awaiting creation")
  const deployStepStatus = selectedDeployment ? selectedDeployment.status === "success" ? completedStatus : localizeStatus(t, selectedDeployment.status) : (zh ? "待部署" : "Awaiting deployment")
  const startStepStatus = selectedDeployment?.started ? completedStatus : (zh ? "待启动" : "Awaiting start")
  const currentStepStatus = selectedDeployment?.status === "success" ? startStepStatus : selectedBuild?.status === "success" ? deployStepStatus : selection ? buildStepStatus : (zh ? "待上传" : "Awaiting upload")

  return <div ref={workspace} className="delivery-focus-workspace">
    <PageHeader closeLabel={t("close")} eyebrow={t("projectDelivery")} title={t("uploads")} description={t("uploadDesc")} helpLabel={t("pageHelp")}
      actions={<><Button variant="outline" disabled={gitState.pending} onClick={() => setHistoryOpen(true)}>{zh ? "查看上传记录" : "View upload history"}</Button><Button asChild variant="outline"><a href={selectedBuild ? `#/builds/${encodeURIComponent(selectedBuild.id)}` : "#/builds"}>{t("builds")}</a></Button></>} />
    <p className="delivery-mobile-progress" role="status">{zh ? "当前步骤" : "Current step"} {selectedDeployment?.status === "success" ? 5 : selectedBuild?.status === "success" ? 4 : selection ? 3 : 1}/5 · {selectedDeployment?.status === "success" ? t("start") : selectedBuild?.status === "success" ? (zh ? "部署" : "Deploy") : selection ? (zh ? "构建" : "Build") : (zh ? "上传" : "Upload")} · {currentStepStatus}</p>
    <WorkflowSteps stacked stateLabels={zh ? { done: "已完成", current: "当前步骤", next: "未开始" } : { done: "Completed", current: "Current step", next: "Not started" }} responsive={false} ariaLabel={t("workflowProgress")} steps={[
      { icon: <UploadOutlined />, statusLabel: selection ? completedStatus : (zh ? "待上传" : "Awaiting upload"), label: zh ? "上传" : "Upload", state: selection ? "done" : "current" },
      { icon: <FileSearchOutlined />, statusLabel: selection ? completedStatus : (zh ? "待分析" : "Awaiting analysis"), label: zh ? "分析" : "Analyze", state: selection ? "done" : "next" },
      { icon: <BuildOutlined />, statusLabel: buildStepStatus, failed: selectedBuild?.status === "failed", label: zh ? "构建" : "Build", state: selectedBuild?.status === "success" ? "done" : selection ? "current" : "next" },
      { icon: <CloudUploadOutlined />, statusLabel: deployStepStatus, failed: selectedDeployment?.status === "failed", label: zh ? "部署" : "Deploy", state: selectedDeployment?.status === "success" ? "done" : selectedBuild?.status === "success" ? "current" : "next" },
      { icon: <PlayCircleOutlined />, statusLabel: startStepStatus, label: t("start"), state: selectedDeployment?.started ? "done" : selectedDeployment?.status === "success" ? "current" : "next" },
    ]} />
    <div className="delivery-focus-content">
      {loadError && <Alert variant="destructive" role="alert"><AlertDescription className="flex flex-wrap items-center justify-between gap-2"><span>{c.loadingFailed}: {loadError}</span><Button size="sm" variant="outline" disabled={loading} onClick={() => void loadUploads()}>{t("retry")}</Button></AlertDescription></Alert>}
      {visibleActionError && <Alert variant="destructive" role="alert"><AlertDescription>{visibleActionError}</AlertDescription></Alert>}
      {!selection ? <>
        <Segmented aria-label={zh ? "项目来源" : "Project source"} disabled={busy || gitState.pending} value={sourceMode} options={[{ value: "zip", label: "ZIP" }, { value: "git", label: zh ? "Git 仓库" : "Git repository" }]} onChange={value => setSourceMode(value as "zip" | "git")} />
        <div hidden={sourceMode !== "zip"}><UploadForm busy={busy} selectedFile={selectedFile} onFileChange={setSelectedFile} onUpload={() => void uploadZip()} t={t} actionContainer={sourceMode === "zip" ? actionContainer : undefined} /></div>
        <div hidden={sourceMode !== "git"}><GitImportForm t={t} onState={setGitState} onImported={upload => { setUploads(previous => [upload, ...previous.filter(item => item.id !== upload.id)]); selectUpload(upload); setGitState({ dirty: false, pending: false }) }} /></div>
      </> : <>
        {!loading && !loadError && !uploads.some(upload => upload.id === selection.id) && <Alert><AlertDescription>{c.removed}</AlertDescription></Alert>}
        <ProjectDetailPanel key={`project:${selection.id}:${drafts[selection.id] ? "ready" : "loading"}:${taskResetVersion}`} upload={selection} build={selectedBuild} deployment={selectedDeployment} busy={busy || !drafts[selection.id]} initialOptions={drafts[selection.id]} packageChoices={packageChoices[selection.id]} onSaveOptions={options => void saveBuildOptions(selection.id, options)} onDraftDirtyChange={setSelectionDirty} actionContainer={actionContainer} onBuild={options => void buildProject(selection.id, options)} onDeploy={(id, options) => void deployProject(id, options)} t={t} />
        <details className="delivery-auxiliary"><summary>{zh ? "分析结果与运行配置" : "Analysis and runtime configuration"}</summary>
        <div className="flex flex-wrap gap-2 py-3"><Button variant="outline" disabled={busy} onClick={() => void draftUpload(selection.id)}>{t("draftManifest")}</Button></div>
        <UploadResultPanel key={`result:${selection.id}`} upload={selection} result={result} busy={busy} onSaveManifest={(manifest, values) => saveManifest(selection.id, manifest, values)} t={t} />
        </details>
      </>}
    </div>
    <footer className="delivery-focus-footer">
      <Button variant="outline" disabled={!selection || busy} onClick={() => void requestSelection(null)}>{zh ? "上一步" : "Previous"}</Button>
      <div className="delivery-focus-summary"><strong>{selection?.filename || selectedFile?.name || (sourceMode === "git" ? (zh ? "检查 Git 来源" : "Inspect Git source") : (zh ? "选择 ZIP 项目" : "Select a ZIP project"))}</strong>{selection && <span>{selection.id}</span>}</div>
      <div ref={setActionContainer} className="flex flex-wrap gap-2" />
    </footer>
    <Drawer zIndex={40} open={historyOpen} title={zh ? "上传记录" : "Upload history"} size={760} onClose={() => setHistoryOpen(false)}>
      <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ${t("uploads")}`} resultCount={visibleUploads.length} resultLabel={t("uploads")} clearLabel={t("clearSearch")} />
      <UploadList uploads={visibleUploads} builds={builds} deployments={deployments} selectedId={selectedUploadId} busy={busy} loading={loading} failed={Boolean(loadError)} filtered={Boolean(query.trim())} onSelect={id => void requestSelection(uploads.find(upload => upload.id === id) || null)} onDraft={id => void draftUpload(id)} onCreateBuild={id => { const upload = uploads.find(item => item.id === id); if (upload) void requestSelection(upload).then(allowed => { if (allowed) void buildProject(id, { run_install: true, run_build: true, project_root: "." }) }) }} onDelete={id => void deleteUpload(id)} t={t} />
    </Drawer>
    {confirmDialog}
  </div>
}

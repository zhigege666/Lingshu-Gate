import { useEffect, useMemo, useRef, useState } from "react"
import { buildApi, type BuildRecord, type DeploymentRecord, type ProjectUpload } from "@/api/builds"
import { api } from "@/api/client"
import { useConfirm } from "@/components/confirm-dialog"
import { usePageRefresh } from "@/components/page-refresh"
import { PageHeader, PageToolbar, WorkflowSteps } from "@/components/page-shell"
import { UploadForm } from "@/components/uploads/upload-form"
import { UploadList } from "@/components/uploads/upload-list"
import { UploadResultPanel } from "@/components/uploads/upload-result-panel"
import { ProjectDetailPanel } from "@/components/uploads/project-detail-panel"
import { uploadCopy } from "@/components/uploads/upload-copy"
import { asRecord, completeUploadAction, resultForUpload, type UploadAction, type UploadResults } from "@/components/uploads/upload-state"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"
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
  const [busy, setBusy] = useState(false)
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

  useEffect(() => {
    mounted.current = true
    void loadUploads()
    return () => { mounted.current = false; loadRequest.current += 1 }
  }, [])
  usePageRefresh(loadUploads, loading || busy)

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
    selectUpload(upload)
    await run(uploadId, "draft", () => requestJson(`/v1/projects/uploads/${encodeURIComponent(uploadId)}/draft-manifest`, { method: "POST" }))
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
    const saved = await run(uploadId, "save", () => api.createConfig(manifest, false, false, credentialValues), { manifest, throwOnError: true })
    if (!saved) throw new Error(t("failed"))
  }

  async function buildProject(uploadId: string, options: { run_install: boolean; run_build: boolean; project_root: string }) {
    const build = await run(uploadId, "build", () => buildApi.createBuild(uploadId, { ...options, timeout_seconds: 300 }))
    if (build && mounted.current) window.location.hash = `#/builds/${encodeURIComponent(build.id)}`
  }

  async function deployProject(buildId: string, options: { server_id?: string; start: boolean; overwrite: boolean }) {
    const build = builds.find(item => item.id === buildId)
    if (!build || running.current) return
    const target = resolveDeploymentTarget(options.server_id, build.manifest?.id, tx("unavailableTarget"))
    const summary = formatDeploymentSummary(target, options, {
      target: tx("deploymentTarget"), overwrite: tx("overwriteExisting"), start: tx("startAfterDeploy"),
      yes: tx("enabledChoice"), no: tx("disabledChoice"), unresolved: tx("unavailableTarget"),
    })
    if (!(await confirm({ title: tx("confirmDeploymentTitle"), description: summary }))) return
    const deployment = await run(build.upload_id, "deploy", () => buildApi.deployBuild(buildId, options))
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

  return <div className="flex min-w-0 flex-col gap-4">
    <PageHeader eyebrow={t("projectDelivery")} title={t("uploads")} description={t("uploadDesc")} helpLabel={t("pageHelp")}
      toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ${t("uploads")}`} resultCount={visibleUploads.length} resultLabel={t("uploads")} clearLabel={t("clearSearch")} />} />
    {loadError && <Alert variant="destructive" role="alert"><AlertDescription className="flex flex-wrap items-center justify-between gap-2"><span>{c.loadingFailed}: {loadError}</span><Button size="sm" variant="outline" disabled={loading} onClick={() => void loadUploads()}>{t("retry")}</Button></AlertDescription></Alert>}
    {visibleActionError && <Alert variant="destructive" role="alert"><AlertDescription>{visibleActionError}</AlertDescription></Alert>}
    <div className={`grid min-w-0 items-start gap-4 ${selection ? "xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]" : ""}`}>
      <div className="flex min-w-0 flex-col gap-4">
        <UploadForm busy={busy} selectedFile={selectedFile} onFileChange={setSelectedFile} onUpload={() => void uploadZip()} t={t} />
        <UploadList uploads={visibleUploads} builds={builds} deployments={deployments} selectedId={selectedUploadId} busy={busy} loading={loading} failed={Boolean(loadError)} filtered={Boolean(query.trim())} onSelect={id => selectUpload(uploads.find(upload => upload.id === id) || null)} onDraft={id => void draftUpload(id)} onCreateBuild={id => { const upload = uploads.find(item => item.id === id); if (upload) selectUpload(upload); void buildProject(id, { run_install: true, run_build: true, project_root: "." }) }} onDelete={id => void deleteUpload(id)} t={t} />
        {!selection && uploads.length > 0 && <p className="text-sm text-muted-foreground">{c.choose}</p>}
      </div>
      {selection && <div className="flex min-w-0 flex-col gap-4">
        {!loading && !loadError && !uploads.some(upload => upload.id === selection.id) && <Alert><AlertDescription>{c.removed}</AlertDescription></Alert>}
        <WorkflowSteps ariaLabel={t("workflowProgress")} steps={[
          { label: t("selectUpload"), state: "done" },
          { label: t("createBuild"), state: selectedBuild?.status === "success" ? "done" : "current" },
          { label: t("deployBuild"), state: selectedDeployment?.status === "success" ? "done" : selectedBuild?.status === "success" ? "current" : "next" },
        ]} />
        <ProjectDetailPanel key={`project:${selection.id}`} upload={selection} build={selectedBuild} deployment={selectedDeployment} busy={busy} onBuild={options => void buildProject(selection.id, options)} onDeploy={(id, options) => void deployProject(id, options)} t={t} />
        <UploadResultPanel key={`result:${selection.id}`} upload={selection} result={result} busy={busy} onSaveManifest={(manifest, values) => saveManifest(selection.id, manifest, values)} t={t} />
      </div>}
    </div>
    {confirmDialog}
  </div>
}

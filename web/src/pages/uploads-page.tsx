import { useEffect, useMemo, useState } from "react"
import { buildApi, type BuildRecord, type DeploymentRecord, type ProjectUpload } from "@/api/builds"
import { api } from "@/api/client"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader, PageToolbar, WorkflowSteps } from "@/components/page-shell"
import { UploadForm } from "@/components/uploads/upload-form"
import { UploadList } from "@/components/uploads/upload-list"
import { UploadResultPanel } from "@/components/uploads/upload-result-panel"
import { ProjectDetailPanel } from "@/components/uploads/project-detail-panel"
import type { UploadItem } from "@/components/uploads/upload-types"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"
import { buildPageText } from "@/pages/builds-page-text"
import { formatDeploymentSummary, resolveDeploymentTarget } from "@/features/deployment-options"

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json", ...(init?.headers || {}) }, ...init })
  const text = await response.text()
  const data = text ? JSON.parse(text) : {}
  if (!response.ok) throw new Error(data?.detail || `${response.status} ${response.statusText}`)
  return data as T
}

export function UploadsPage({ t }: { t: TFunction }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [builds, setBuilds] = useState<BuildRecord[]>([])
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([])
  const [selectedUploadId, setSelectedUploadId] = useState("")
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [result, setResult] = useState<unknown>(t("waiting"))
  const [query, setQuery] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)
  const tx = (key: string) => buildPageText(t, key)

  useEffect(() => { void loadUploads() }, [])

  async function run<T>(task: () => Promise<T>, onDone?: (value: T) => void) {
    setBusy(true)
    setError(null)
    try {
      const value = await task()
      onDone?.(value)
      setResult(value)
      return value
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return null
    } finally {
      setBusy(false)
    }
  }

  async function loadUploads() {
    await run(async () => {
      const [uploadData, buildData, deploymentData] = await Promise.all([requestJson<{ uploads: UploadItem[] }>("/v1/projects/uploads"), buildApi.builds(), buildApi.deployments()])
      return { ...uploadData, builds: buildData.builds, deployments: deploymentData.deployments }
    }, (value) => { setUploads(value.uploads); setBuilds(value.builds); setDeployments(value.deployments); if (!selectedUploadId && value.uploads[0]) setSelectedUploadId(value.uploads[0].id) })
  }

  async function uploadZip() {
    if (!selectedFile) return
    const body = new FormData()
    body.append("file", selectedFile)
    await run(() => requestJson("/v1/projects/upload", { method: "POST", body }))
    await loadUploads()
  }

  async function draftUpload(uploadId: string) {
    await run(() => requestJson(`/v1/projects/uploads/${encodeURIComponent(uploadId)}/draft-manifest`, { method: "POST" }))
  }

  async function deleteUpload(uploadId: string) {
    if (!(await confirm({ title: t("confirmDeleteUploadTitle"), description: t("confirmDeleteUploadDesc"), destructive: true }))) return
    await run(() => requestJson(`/v1/projects/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE" }), async () => { await loadUploads() })
  }

  async function saveManifest(manifest: Record<string, unknown>) {
    await run(() => api.createConfig(manifest, false, false))
  }

  async function buildProject(uploadId: string, options: { run_install: boolean; run_build: boolean; project_root: string }) {
    const build = await run(() => buildApi.createBuild(uploadId, { ...options, timeout_seconds: 300 }))
    if (build && (build as BuildRecord).id) window.location.hash = `#/builds/${encodeURIComponent((build as BuildRecord).id)}`
    await loadUploads()
  }

  async function deployProject(buildId: string, options: { server_id?: string; start: boolean; overwrite: boolean }) {
    const build = builds.find((item) => item.id === buildId)
    const target = resolveDeploymentTarget(options.server_id, build?.manifest?.id, tx("unavailableTarget"))
    const summary = formatDeploymentSummary(target, options, {
      target: tx("deploymentTarget"),
      overwrite: tx("overwriteExisting"),
      start: tx("startAfterDeploy"),
      yes: tx("enabledChoice"),
      no: tx("disabledChoice"),
      unresolved: tx("unavailableTarget"),
    })
    if (!(await confirm({ title: tx("confirmDeploymentTitle"), description: summary }))) return
    await run(() => buildApi.deployBuild(buildId, options))
    await loadUploads()
  }

  const selectedUpload = uploads.find((upload) => upload.id === selectedUploadId)
  const selectedBuild = builds.filter((build) => build.upload_id === selectedUploadId).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0] || null
  const selectedDeployment = selectedBuild ? deployments.find((deployment) => deployment.build_id === selectedBuild.id) || null : null
  const visibleUploads = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return uploads
    return uploads.filter((upload) => [upload.id, upload.filename, upload.detected_runtime, upload.status].some((value) => value?.toLowerCase().includes(keyword)))
  }, [query, uploads])

  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div className="xl:col-span-2">
        <PageHeader
          eyebrow={t("projectDelivery")}
          title={t("uploads")}
          description={t("uploadDesc")}
          actions={<Button variant="outline" disabled={busy} onClick={loadUploads}>{t("refresh")}</Button>}
          stats={[
            { label: t("uploads"), value: uploads.length },
            { label: t("buildRecords"), value: builds.length },
            { label: t("deploymentRecords"), value: deployments.length },
            { label: t("status"), value: selectedDeployment?.status || selectedBuild?.status || selectedUpload?.status || "-", tone: selectedDeployment?.status === "success" ? "success" : "default" },
          ]}
        />
      </div>
      <div className="xl:col-span-2">
        <WorkflowSteps ariaLabel={t("workflowProgress")} steps={[
          { label: t("uploadZip"), state: uploads.length > 0 ? "done" : "current" },
          { label: t("selectUpload"), state: selectedUpload ? "done" : "next" },
          { label: t("createBuild"), state: selectedBuild ? "done" : selectedUpload ? "current" : "next" },
          { label: t("deployBuild"), state: selectedDeployment ? "done" : selectedBuild?.status === "success" ? "current" : "next" },
        ]} />
      </div>
      <div className="xl:col-span-2">
        <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ${t("uploads")}`} resultCount={visibleUploads.length} resultLabel={t("uploads")} clearLabel={t("clearSearch")} />
      </div>
      {error && <Alert variant="destructive" className="xl:col-span-2"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="flex min-w-0 flex-col gap-4">
        <UploadForm busy={busy} selectedFile={selectedFile} onFileChange={setSelectedFile} onUpload={uploadZip} onRefresh={loadUploads} t={t} />
        <UploadList uploads={visibleUploads} builds={builds} deployments={deployments} selectedId={selectedUploadId} busy={busy} onSelect={setSelectedUploadId} onDraft={draftUpload} onCreateBuild={(uploadId) => { setSelectedUploadId(uploadId); void buildProject(uploadId, { run_install: true, run_build: true, project_root: "." }) }} onDelete={deleteUpload} t={t} />
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        {selectedUpload && <ProjectDetailPanel key={selectedUpload.id} upload={selectedUpload as unknown as ProjectUpload} build={selectedBuild} deployment={selectedDeployment} busy={busy} onBuild={(options) => void buildProject(selectedUpload.id, options)} onDeploy={(buildId, options) => void deployProject(buildId, options)} t={t} />}
        <UploadResultPanel result={result} onSaveManifest={saveManifest} t={t} />
      </div>
      {confirmDialog}
    </div>
  )
}

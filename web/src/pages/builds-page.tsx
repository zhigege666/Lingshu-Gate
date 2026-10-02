import { BuildLogWorkbench } from "@/components/builds/build-log-workbench"
import { BUILD_LOG_WINDOW, mergeBuildLogWindow } from "@/features/build-log-window"
import { replaceConsoleRouteHash } from "@/routing/use-console-route"
import { rollbackResultError, rollbackStartFor } from "./builds-page-state"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { deliveryDraftRequest, manifestPatch, mergeManifestPatch } from "@/features/servers/delivery-draft"
import { DeliveryConfigEditor } from "@/features/servers/delivery-config-editor"
import { Select as SearchSelect } from "antd"
import { useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { BuildApiError, buildApi, type BuildBlockedDetail, type BuildLog, type BuildPlan, type BuildPreflightResult, type BuildPreflightTool, type BuildRecord, type DeploymentRecord, type DeliveryDraft, type ProjectUpload } from "@/api/builds"
import { BuildDetailCard } from "@/components/builds/build-detail-card"
import { BuildHintCard } from "@/components/builds/build-hint-card"
import { BuildLogsTable, type LogFilter } from "@/components/builds/build-logs-table"
import { BuildOutputPanels } from "@/components/builds/build-output-panels"
import { BuildRecordsTable } from "@/components/builds/build-records-table"
import { BuildTimelineCard } from "@/components/builds/build-timeline-card"
import { DeploymentRecordsTable } from "@/components/builds/deployment-records-table"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { usePageRefresh } from "@/components/page-refresh"
import { uploadCopy } from "@/components/uploads/upload-copy"
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
import { formatDeploymentSummary, formatRollbackSummary } from "@/features/deployment-options"
import { buildPageText } from "@/pages/builds-page-text"

const ACTIVE_BUILD_STATUSES = new Set(["queued", "running", "cancel_requested"])
const STOP_REQUESTABLE_BUILD_STATUSES = new Set(["queued", "running"])
const MANUAL_RUNTIME_REQUIRED = new Set(["unknown", "ambiguous", "docker"])
type WorkspaceSection = "workspace" | "builds" | "deployments" | "logs"

export function BuildsPage({ t, initialBuildId = "" }: { t: TFunction; initialBuildId?: string }) {
  const [deliveryDraft, setDeliveryDraft] = useState<DeliveryDraft | null>(null)
  const latestDeliveryDraft = useRef<DeliveryDraft | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  const deploymentPending = useRef(false)
  const buildPending = useRef(false)
  const [editingBuildId, setEditingBuildId] = useState<string | null>(null)
  const [configDrafts, setConfigDrafts] = useState<Record<string, Record<string, unknown>>>({})
  const [uploads, setUploads] = useState<ProjectUpload[]>([])
  const [builds, setBuilds] = useState<BuildRecord[]>([])
  const [buildLogs, setBuildLogs] = useState<BuildLog[]>([])
  const [followLogs, setFollowLogs] = useState(true)
  const [logWindowBusy, setLogWindowBusy] = useState(false)
  const [logBounds, setLogBounds] = useState({ earlier: false, later: false })
  const [deployments, setDeployments] = useState<DeploymentRecord[]>([])
  const [selectedUploadId, setSelectedUploadIdState] = useState("")
  const [selectedBuildId, setSelectedBuildIdState] = useState(initialBuildId)
  const [selectedDeploymentId, setSelectedDeploymentId] = useState("")
  const [activeSection, setActiveSection] = useState<WorkspaceSection>("workspace")
  const [serverId, setServerId] = useState("")
  const [deployOverwrite, setDeployOverwrite] = useState(false)
  const [deployStart, setDeployStart] = useState(false)
  const [rollbackOption, setRollbackOption] = useState({ deploymentId: "", start: false })
  const [projectRoot, setProjectRoot] = useState(".")
  const [runtimeOverride, setRuntimeOverride] = useState("auto")
  const [preflight, setPreflight] = useState<BuildPreflightResult | null>(null)
  const [plan, setPlan] = useState<BuildPlan | null>(null)
  const [detailDialog, setDetailDialog] = useState<{ title: string; body: string } | null>(null)
  const [toast, setToast] = useState<ToastState>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [logFilter, setLogFilter] = useState<LogFilter>("all")
  const [liveTail, setLiveTail] = useState(false)
  const { confirm, confirmDialog } = useConfirm(t)
  const mounted = useRef(true)
  const refreshRequest = useRef(0)
  const logRequest = useRef(0)
  const selectionRevision = useRef(0)
  const analysisRequest = useRef(0)
  const appliedRouteBuild = useRef<string | null>(null)
  const selectedUploadRef = useRef(selectedUploadId)
  const selectedBuildRef = useRef(selectedBuildId)
  function setSelectedUploadId(id: string) {
    if (selectedUploadRef.current !== id) {
      selectionRevision.current += 1
      latestDeliveryDraft.current = null
      setDeliveryDraft(null); setDraftError(null)
      setProjectRoot("."); setRuntimeOverride("auto"); setServerId("")
      setDeployOverwrite(false); setDeployStart(false); setPreflight(null); setPlan(null)
    }
    selectedUploadRef.current = id; setSelectedUploadIdState(id)
  }
  function setSelectedBuildId(id: string) {
    if (selectedBuildRef.current !== id) { setBuildLogs([]); setFollowLogs(true); setLogBounds({ earlier: false, later: false }); selectionRevision.current += 1; setSelectedDeploymentId(""); setRollbackOption({ deploymentId: "", start: false }) }
    selectedBuildRef.current = id; setSelectedBuildIdState(id)
  }
  const c = uploadCopy(t)

  const selectedUpload = uploads.find((upload) => upload.id === selectedUploadId) || null
  const selectedBuild = builds.find((build) => build.id === selectedBuildId) || null
  const latestDeployment = deployments.find((deployment) => deployment.build_id === selectedBuildId) || null
  const selectedDeployment = deployments.find(deployment => deployment.id === selectedDeploymentId) || null
  const rollbackStart = rollbackStartFor(rollbackOption, selectedDeployment?.id || "")
  const selectedBuildLog = buildLogs[buildLogs.length - 1] || null
  const polling = Boolean(selectedBuild && ACTIVE_BUILD_STATUSES.has(selectedBuild.status))
  const preflightReady = preflight?.status === "ok" || preflight?.status === "warning"
  const runtimeOverrideValue = runtimeOverride === "auto" ? null : runtimeOverride
  const tx = (key: string) => buildPageText(t, key)
  const notify = (message: string, tone: ToastTone = "info") => { if (mounted.current) setToast({ message, tone }) }
  const notifyError = (err: unknown) => notify(err instanceof Error ? err.message : String(err), "error")
  const registerExit = useContext(EditorNavigationContext)
  const settingsDirty = Boolean(deliveryDraft && deliveryDraft.upload_id === selectedUploadId && (
    serverId !== (deliveryDraft.server_id || "") || deployStart !== deliveryDraft.start || deployOverwrite !== deliveryDraft.overwrite
    || projectRoot !== (deliveryDraft.project_root || ".") || runtimeOverride !== (deliveryDraft.runtime_override || "auto")))
  useEffect(() => registerExit?.({ dirty: settingsDirty, pending: busy }), [registerExit, settingsDirty, busy])


  useEffect(() => { mounted.current = true; void refresh(initialBuildId); return () => { mounted.current = false; refreshRequest.current += 1; logRequest.current += 1 } }, [])
  usePageRefresh(() => refresh(), loading || busy)
  useEffect(() => {
    let active = true
    const uploadOwner = selectedUploadId
    setDeliveryDraft(null); setDraftError(null)
    if (selectedUploadId) void buildApi.deliveryDraft(selectedUploadId).then(draft => {
      if (!active || selectedUploadRef.current !== uploadOwner) return
      adoptDeliveryDraft(draft)
    }).catch(error => { if (active) setDraftError(String(error)) })
    return () => { active = false }
  }, [selectedUploadId])

  // A successful revision is both the persisted baseline and the form snapshot.
  // In particular, deployment resolves an empty target to the actual server ID.
  // Keep the two in sync, without allowing an old task's response to own this form.
  function adoptDeliveryDraft(draft: DeliveryDraft) {
    if (!mounted.current || selectedUploadRef.current !== draft.upload_id) return
    const previous = latestDeliveryDraft.current
    if (previous?.upload_id === draft.upload_id && previous.revision > draft.revision) return
    latestDeliveryDraft.current = draft
    setDeliveryDraft(draft)
    setServerId(draft.server_id || "")
    setDeployStart(draft.start)
    setDeployOverwrite(draft.overwrite)
    setProjectRoot(draft.project_root || ".")
    setRuntimeOverride(draft.runtime_override || "auto")
    if (draft.build_id) setConfigDrafts(previous => ({ ...previous, [draft.build_id!]: draft.manifest_patch }))
  }

  async function saveDeliveryConfiguration(buildId: string, manifest: Record<string, unknown>) {
    if (!deliveryDraft || deliveryDraft.upload_id !== selectedUploadId) throw new Error("Delivery draft is unavailable. Reload before saving.")
    const base = builds.find(item => item.id === buildId)?.manifest
    if (!base) throw new Error("Build manifest is unavailable")
    const patch = manifestPatch(base, manifest)
    const draft = await buildApi.saveDeliveryDraft(selectedUploadId, { expected_revision: deliveryDraft.revision,
      manifest_patch: patch, server_id: serverId || null, build_id: buildId, deployment_id: selectedDeploymentId || null,
      start: deployStart, overwrite: deployOverwrite, project_root: projectRoot, runtime_override: runtimeOverrideValue,
    })
    adoptDeliveryDraft(draft)
  }


  useEffect(() => {
    if (!initialBuildId) { appliedRouteBuild.current = null; return }
    if (appliedRouteBuild.current === initialBuildId) return
    const nextBuild = builds.find((build) => build.id === initialBuildId)
    if (!nextBuild) return
    appliedRouteBuild.current = initialBuildId
    setSelectedUploadId(nextBuild.upload_id)
    setSelectedBuildId(initialBuildId)
    void loadBuildLogs(initialBuildId)
  }, [initialBuildId, builds])

  useEffect(() => {
    if (!selectedBuildId || !polling || !followLogs) return undefined
    setLiveTail(false)
    const source = new EventSource(`/v1/builds/${encodeURIComponent(selectedBuildId)}/logs/stream?tail=true`)
    source.onopen = () => { if (selectedBuildRef.current === selectedBuildId) setLiveTail(true) }
    let pendingLogs: BuildLog[] = []
    let frame = 0
    const flush = () => {
      frame = 0
      if (selectedBuildRef.current !== selectedBuildId || !pendingLogs.length) return
      const batch = pendingLogs; pendingLogs = []
      setBuildLogs(previous => mergeBuildLogWindow(previous, batch))
      setLogBounds(previous => !previous.earlier && batch.some(log => log.sequence > BUILD_LOG_WINDOW) ? { ...previous, earlier: true } : previous)
    }
    source.addEventListener("log", (event) => {
      if (selectedBuildRef.current !== selectedBuildId) return
      const log = JSON.parse((event as MessageEvent).data) as BuildLog
      pendingLogs.push(log)
      // A background tab may suspend animation frames. Bound that queue as well.
      if (pendingLogs.length >= BUILD_LOG_WINDOW) { cancelAnimationFrame(frame); flush() }
      if (!frame) frame = requestAnimationFrame(flush)
    })
    source.addEventListener("status", (event) => {
      if (selectedBuildRef.current !== selectedBuildId) return
      const status = JSON.parse((event as MessageEvent).data) as { status?: string }
      if (status.status && !ACTIVE_BUILD_STATUSES.has(status.status)) {
        cancelAnimationFrame(frame); flush()
        source.close()
        setLiveTail(false)
        void refresh(selectedBuildId)
      }
    })
    source.onerror = () => { cancelAnimationFrame(frame); flush(); source.close(); setLiveTail(false) }
    return () => { cancelAnimationFrame(frame); pendingLogs = []; source.close(); setLiveTail(false) }
  }, [selectedBuildId, polling, followLogs])

  async function loadBuildLogs(buildId: string, cursor: { tail?: boolean; before_sequence?: number; after_sequence?: number } = { tail: true }) {
    if (!buildId) return
    const requestId = ++logRequest.current
    setLogWindowBusy(true)
    setFollowLogs(Boolean(cursor.tail))
    try {
      const response = await buildApi.buildLogs(buildId, BUILD_LOG_WINDOW, cursor)
      if (mounted.current && requestId === logRequest.current && selectedBuildRef.current === buildId) {
        setBuildLogs(previous => cursor.tail ? mergeBuildLogWindow(previous.filter(item => item.build_id === buildId), response.logs) : response.logs)
        setLogBounds(previous => ({ earlier: Boolean(response.has_earlier) || Boolean(cursor.tail && previous.earlier), later: Boolean(response.has_later) }))
      }
    } catch (err) {
      if (mounted.current && requestId === logRequest.current && selectedBuildRef.current === buildId) {
        notifyError(err)
      }
    } finally { if (mounted.current && requestId === logRequest.current) setLogWindowBusy(false) }
  }

  async function refresh(preferredBuildId?: string, preferredUploadId?: string) {
    if (!mounted.current) return
    const requestId = ++refreshRequest.current
    const owner = selectionRevision.current
    setLoading(true)
    setLoadError(null)
    try {
      const [uploadData, buildData, deploymentData] = await Promise.all([buildApi.uploads(), buildApi.builds(), buildApi.deployments()])
      if (!mounted.current || requestId !== refreshRequest.current) return
      setUploads(uploadData.uploads)
      setBuilds(buildData.builds)
      setDeployments(deploymentData.deployments)
      if (owner !== selectionRevision.current) return
      const preferredBuild = buildData.builds.find(build => build.id === (preferredBuildId ?? selectedBuildRef.current))
      const uploadId = preferredUploadId ?? selectedUploadRef.current
      const nextUploadId = preferredBuild?.upload_id || (uploadData.uploads.some(upload => upload.id === uploadId) ? uploadId : "")
      const nextBuild = preferredBuild || buildData.builds.find(build => build.upload_id === nextUploadId) || null
      const nextDeployment = deploymentData.deployments.find(deployment => deployment.id === selectedDeploymentId && deployment.build_id === nextBuild?.id)
        || deploymentData.deployments.find(deployment => deployment.build_id === nextBuild?.id) || null
      setSelectedUploadId(nextUploadId)
      setSelectedBuildId(nextBuild?.id || "")
      setSelectedDeploymentId(nextDeployment?.id || "")
      if (nextBuild) {
        writeBuildHash(nextBuild.id, true)
        await loadBuildLogs(nextBuild.id)
      } else {
        logRequest.current += 1
        setBuildLogs([])
        writeBuildHash("", true)
      }
    } catch (err) {
      if (mounted.current && requestId === refreshRequest.current) setLoadError(err instanceof Error ? err.message : String(err))
    } finally {
      if (mounted.current && requestId === refreshRequest.current) setLoading(false)
    }
  }

  async function runPreflight(uploadId = selectedUploadId, refresh = false) {
    if (!uploadId || busy) return null
    const owner = selectionRevision.current
    const requestId = ++analysisRequest.current
    const ownsResult = () => mounted.current && owner === selectionRevision.current && requestId === analysisRequest.current
    setBusy(true)
    try {
      const response = await buildApi.preflightBuild(uploadId, { runtime_override: runtimeOverrideValue, project_root: projectRoot || ".", refresh })
      if (!ownsResult()) return null
      setPreflight(response)
      notify(`${tx("buildPreflight")}: ${response.status} · ${response.runtime}`, response.status === "error" ? "error" : "success")
      return response
    } catch (err) {
      if (ownsResult()) notifyError(err)
      return null
    } finally {
      if (mounted.current && requestId === analysisRequest.current) setBusy(false)
    }
  }

  async function previewPlan(uploadId = selectedUploadId, refresh = false) {
    if (!uploadId || busy) return null
    const owner = selectionRevision.current
    const requestId = ++analysisRequest.current
    const ownsResult = () => mounted.current && owner === selectionRevision.current && requestId === analysisRequest.current
    setBusy(true)
    try {
      const response = await buildApi.planBuild(uploadId, { runtime_override: runtimeOverrideValue, project_root: projectRoot || ".", refresh })
      if (!ownsResult()) return null
      setPreflight(response.preflight)
      setPlan(response.plan)
      notify(`${tx("buildPlan")}: ${response.plan.buildable ? tx("buildable") : tx("notBuildable")} · ${(response.plan.steps || []).length} ${tx("planSteps")}`, response.plan.buildable ? "success" : "error")
      return response
    } catch (err) {
      if (ownsResult()) notifyError(err)
      return null
    } finally {
      if (mounted.current && requestId === analysisRequest.current) setBusy(false)
    }
  }

  async function createBuild(uploadId = selectedUploadId, options: { runtimeOverride?: string | null; projectRoot?: string } = {}) {
    if (!uploadId || busy || buildPending.current) return
    const nextRuntimeOverride = options.runtimeOverride === undefined ? runtimeOverrideValue : options.runtimeOverride
    const nextProjectRoot = options.projectRoot || projectRoot || "."
    const owner = selectionRevision.current
    let createdBuild: BuildRecord | null = null
    buildPending.current = true
    setBusy(true)
    try {
      // A row retry can have just switched uploads. Read that upload's draft,
      // never copy the previous form's target or side-effect options into it.
      const currentForm = uploadId === selectedUploadId
      const sourceDraft = currentForm ? deliveryDraft : await buildApi.deliveryDraft(uploadId)
      if (!sourceDraft || sourceDraft.upload_id !== uploadId) throw new Error("Delivery draft is unavailable. Reload before creating a build.")
      const draftRequest = deliveryDraftRequest(sourceDraft, {
        ...(currentForm ? { server_id: serverId.trim() || null, start: deployStart, overwrite: deployOverwrite } : {}),
        project_root: nextProjectRoot, runtime_override: nextRuntimeOverride,
      })
      const preflightResult = await buildApi.preflightBuild(uploadId, { runtime_override: nextRuntimeOverride, project_root: nextProjectRoot })
      if (!mounted.current || owner !== selectionRevision.current) return
      setPreflight(preflightResult)
      if (preflightResult.status === "error") {
        notify(tx("preflightBlocked"), "error")
        return
      }
      if (!nextRuntimeOverride && MANUAL_RUNTIME_REQUIRED.has(preflightResult.runtime)) {
        notify(tx("preflightManualRuntimeRequired"), "error")
        return
      }
      // Persist the submitted form snapshot before dispatching any build. A
      // revision conflict leaves the local inputs intact and creates no task.
      const preparedDraft = await buildApi.saveDeliveryDraft(uploadId, draftRequest)
      if (!mounted.current || owner !== selectionRevision.current) return
      adoptDeliveryDraft(preparedDraft)
      const build = await buildApi.createBuild(uploadId, { run_install: true, run_build: true, timeout_seconds: 300, runtime_override: nextRuntimeOverride, project_root: nextProjectRoot })
      createdBuild = build
      const updatedDraft = await buildApi.saveDeliveryDraft(uploadId, deliveryDraftRequest(preparedDraft, { build_id: build.id, deployment_id: null }))
        .catch(error => { throw new Error(`Build ${build.id} was created, but its task context could not be saved. Refresh before retrying. ${String(error)}`) })
      if (mounted.current && owner === selectionRevision.current) adoptDeliveryDraft(updatedDraft)
      if (!mounted.current) return
      if (owner !== selectionRevision.current) { await refresh(); return }
      setSelectedBuildId(build.id)
      writeBuildHash(build.id, true)
      notify(`${t("createBuild")}: ${build.status} · ${build.id.slice(0, 8)}`, ["failed", "blocked", "cancelled"].includes(build.status) ? "error" : "success")
      await refresh(build.id)
      await loadBuildLogs(build.id)
    } catch (err) {
      if (!mounted.current || owner !== selectionRevision.current) return
      // The build is already dispatched even if linking the draft failed.
      // Retain its ID and record; never silently submit another build to recover.
      if (createdBuild) {
        setBuilds(previous => [createdBuild!, ...previous.filter(build => build.id !== createdBuild!.id)])
        setSelectedBuildId(createdBuild.id)
        writeBuildHash(createdBuild.id, true)
      }
      const detail = err instanceof BuildApiError ? err.detail : undefined
      if (detail && typeof detail === "object") {
        const blocked = detail as BuildBlockedDetail
        if (blocked.preflight) setPreflight(blocked.preflight)
        notify(`${tx("buildBlocked")} [${blocked.code}]: ${blocked.message}`, "error")
      } else {
        notifyError(err)
      }
    } finally {
      buildPending.current = false
      setBusy(false)
    }
  }

  async function requestStopBuild(buildId = selectedBuildId) {
    if (!buildId) return
    if (!(await confirm({ title: t("requestStopBuild"), description: t("requestStopConfirm") }))) return
    const owner = selectionRevision.current
    setBusy(true)
    try {
      const build = await buildApi.cancelBuild(buildId)
      if (!mounted.current) return
      if (owner !== selectionRevision.current || selectedBuildRef.current !== buildId) { await refresh(); return }
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
    if (!buildId || busy || deploymentPending.current) return
    const build = builds.find(item => item.id === buildId)
    if (buildId !== selectedBuildId && build) { await showBuild(build); return }
    if (!deliveryDraft) return
    const owner = selectionRevision.current
    deploymentPending.current = true
    setBusy(true)
    try {
      const options = { server_id: serverId.trim() || undefined, start: deployStart, overwrite: deployOverwrite, manifest_patch: configDrafts[buildId] || deliveryDraft.manifest_patch }
      const preview = await buildApi.previewDeployment(buildId, options)
      const summary = formatDeploymentSummary(preview.server_id, options, {
        target: tx("deploymentTarget"), overwrite: tx("overwriteExisting"), start: tx("startAfterDeploy"),
        yes: tx("enabledChoice"), no: tx("disabledChoice"), unresolved: tx("unavailableTarget"),
      })
      if (!(await confirm({ title: tx("confirmDeploymentTitle"), description: `${summary}\n${preview.changed_fields.join(", ")}\n${preview.config_digest}`, details: <JsonPanel copyLabel={t("copy")} data={{ build_id: preview.build_id, credential_state: preview.credential_state, interrupts_existing_service: preview.interrupts_existing_service, manifest: preview.manifest }} /> }))) return
      const deployment = await buildApi.deployBuild(buildId, { ...options,
        expected_config_digest: preview.config_digest,
        expected_previous_config_digest: preview.expected_previous_config_digest,
        expected_credential_binding_digest: preview.expected_credential_binding_digest,
      })
      const savedDraft = await buildApi.saveDeliveryDraft(build!.upload_id, deliveryDraftRequest(deliveryDraft, {
        manifest_patch: options.manifest_patch || {}, build_id: buildId, deployment_id: deployment.id,
        server_id: deployment.server_id, start: deployStart, overwrite: deployOverwrite, project_root: projectRoot, runtime_override: runtimeOverrideValue,
      })).catch(error => { throw new Error(`Deployment ${deployment.id}: ${deployment.status}. Task context could not be saved; refresh before retrying. ${String(error)}`) })
      if (mounted.current && owner === selectionRevision.current) adoptDeliveryDraft(savedDraft)
      notify(`${t("deployBuild")}: ${deployment.status} · ${deployment.server_id}`, deployment.status === "success" ? "success" : "error")
      await refresh(selectedBuildRef.current === buildId ? buildId : undefined)
    } catch (err) { notifyError(err) }
    finally { deploymentPending.current = false; setBusy(false) }
  }

  async function rollback(deploymentId: string) {
    const deployment = deployments.find((item) => item.id === deploymentId)
    if (!deployment?.rollback_available || busy) return
    const start = rollbackStartFor(rollbackOption, deploymentId)
    const summary = formatRollbackSummary(deployment.server_id, start, {
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
      const response = await buildApi.rollback(deploymentId, start)
      const outcomeError = rollbackResultError(response.server, deployment.server_id, start)
      if (response.deployment.id !== deploymentId || outcomeError) throw new Error(outcomeError || "Rollback deployment did not match the confirmed target.")
      notify(response.message || t("rollback"), "success")
      await refresh()
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
      if (!mounted.current) return
      notify(tx("deleteSuccess"), "success")
      if (selectedUploadRef.current === upload.id) {
        setSelectedUploadId(""); setSelectedBuildId(""); setSelectedDeploymentId("")
        writeBuildHash("", true)
      }
      await refresh()
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
      if (!mounted.current) return
      notify(tx("deleteSuccess"), "success")
      if (selectedBuildRef.current === build.id) {
        setSelectedBuildId(""); setSelectedDeploymentId("")
        writeBuildHash("", true)
      }
      await refresh()
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
      if (!mounted.current) return
      notify(tx("deleteSuccess"), "success")
      setSelectedDeploymentId(current => current === deployment.id ? "" : current)
      await refresh()
    } catch (err) {
      notifyError(err)
    } finally {
      setBusy(false)
    }
  }

  async function retryBuild(build: BuildRecord) {
    if (!(await showBuild(build, "workspace", true))) return
    const retryRuntime = build.runtime === "node" || build.runtime === "python" ? build.runtime : null
    void createBuild(build.upload_id, { runtimeOverride: retryRuntime, projectRoot: build.plan?.project_root_dir || "." })
  }

  async function showBuild(build: BuildRecord, section: WorkspaceSection = "workspace", replaceRoute = false) {
    if (busy) return false
    if (build.upload_id !== selectedUploadRef.current && settingsDirty && !(await confirm({ title: t("uploads") === "项目上传" ? "放弃未保存的交付选项？" : "Discard unsaved delivery options?", destructive: true }))) return false
    if (build.upload_id !== selectedUploadRef.current) {
      setProjectRoot("."); setRuntimeOverride("auto"); setServerId(""); setDeployOverwrite(false); setDeployStart(false); setPreflight(null); setPlan(null)
    }
    setSelectedUploadId(build.upload_id)
    setSelectedBuildId(build.id)
    setActiveSection(section)
    writeBuildHash(build.id, replaceRoute)
    void loadBuildLogs(build.id)
    return true
  }

  async function showDeployment(deployment: DeploymentRecord, detail = false) {
    if (busy) return
    const build = builds.find((item) => item.id === deployment.build_id)
    if (build && !(await showBuild(build, activeSection))) return
    setSelectedDeploymentId(deployment.id)
    if (detail) setDetailDialog({ title: `${t("deploymentRecords")} · ${deployment.server_id}`, body: JSON.stringify(deployment, null, 2) })
  }

  function canRequestStop(build: BuildRecord) {
    return STOP_REQUESTABLE_BUILD_STATUSES.has(build.status)
  }

  function onCopied(message: string) {
    notify(`${t("copied")}: ${message}`, "success")
  }

  async function changeSelectedUpload(uploadId: string) {
    if (uploadId === selectedUploadRef.current || busy) return
    if (settingsDirty && !(await confirm({ title: t("uploads") === "项目上传" ? "放弃未保存的交付选项？" : "Discard unsaved delivery options?", destructive: true }))) return
    setSelectedUploadId(uploadId)
    const nextBuild = builds.find((build) => build.upload_id === uploadId) || null
    setSelectedBuildId(nextBuild?.id || "")
    setSelectedDeploymentId(nextBuild ? deployments.find((deployment) => deployment.build_id === nextBuild.id)?.id || "" : "")
    setBuildLogs([])
    if (nextBuild) {
      writeBuildHash(nextBuild.id, true)
      void loadBuildLogs(nextBuild.id)
    } else writeBuildHash("", true)
    setRuntimeOverride("auto")
    setProjectRoot(".")
    setServerId("")
    setDeployOverwrite(false)
    setDeployStart(false)
    setPreflight(null)
    setPlan(null)
  }

  return <div className="flex flex-col gap-4">
    <PageHeader closeLabel={t("close")}
      eyebrow={t("projectPipeline")}
      title={t("builds")}
      actions={<Button asChild><a href="#/uploads">{c.uploadProject}</a></Button>}
      description={t("buildDeployDesc")}
      helpLabel={t("pageHelp")}
      helpContent={<><p>{tx("projectContextDesc")}</p><p>{t("longBuildHint")}</p></>}
      toolbar={<div role="tablist" aria-label={tx("workspaceNavigation")} className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
        {(["workspace", "builds", "deployments", "logs"] as WorkspaceSection[]).map((section) => <Button key={section} type="button" role="tab" aria-selected={activeSection === section} variant={activeSection === section ? "secondary" : "ghost"} onClick={() => setActiveSection(section)}>{tx(`${section}Tab`)}{section === "builds" ? ` (${builds.length})` : section === "deployments" ? ` (${deployments.length})` : ""}</Button>)}
      </div>}
    />

    {loadError && <Alert variant="destructive" role="alert"><AlertDescription className="flex flex-wrap items-center justify-between gap-2"><span>{c.listFailed}: {loadError}</span><Button size="sm" variant="outline" disabled={loading} onClick={() => void refresh()}>{t("retry")}</Button></AlertDescription></Alert>}
    {draftError && <Alert variant="destructive"><AlertDescription>{draftError}</AlertDescription></Alert>}
    {loading && <p role="status" className="text-sm text-muted-foreground">{c.refreshing}</p>}

    {activeSection === "workspace" ? <>
    {selectedUpload && <WorkflowSteps ariaLabel={t("workflowProgress")} steps={[
      { label: t("selectUpload"), state: "done" },
      { label: t("createBuild"), state: selectedBuild?.status === "success" ? "done" : "current" },
      { label: t("manifest"), state: latestDeployment?.status === "success" || Boolean(configDrafts[selectedBuildId]) ? "done" : selectedBuild?.status === "success" ? "current" : "next" },
      { label: t("deployBuild"), state: latestDeployment?.status === "success" ? "done" : selectedBuild?.status === "success" ? "current" : "next" },
      { label: t("start"), state: latestDeployment?.started ? "done" : latestDeployment?.status === "success" ? "current" : "next" },
    ]} />}
    <Card>
      {selectedUpload && <CardHeader className="gap-3 md:flex-row md:items-start md:justify-between">
        <CardTitle className="break-words text-base">{selectedUpload.filename}</CardTitle>
        <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => void deleteUpload(selectedUpload)} disabled={busy}>{tx("deleteUpload")}</Button>
      </CardHeader>}
      <CardContent className={`flex flex-col gap-4 ${selectedUpload ? "" : "pt-6"}`}>
        {uploads.length > 0 && <Field label={t("selectUpload")}>
          <SearchSelect showSearch virtual style={{ width: "100%" }} disabled={busy} value={selectedUploadId || undefined} onChange={changeSelectedUpload}
            aria-label={t("selectUpload")} placeholder={t("selectUpload")} optionFilterProp="label"
            options={uploads.map(upload => ({ value: upload.id, label: `${upload.filename} · ${upload.id} · ${upload.status}` }))} />
        </Field>}
        {!selectedUpload ? <div className="flex flex-wrap items-center gap-3">
          {!loading && !loadError && <p className="text-sm text-muted-foreground">{uploads.length ? c.selectProject : c.noProjects}</p>}
          <Button variant="outline" asChild><a href="#/uploads">{c.uploadProject}</a></Button>
        </div> : <>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-xs text-muted-foreground">{tx("latestBuild")}</dt><dd>{selectedBuild ? `${localizeStatus(t, selectedBuild.status)} · ${selectedBuild.runtime}` : tx("noBuild")}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{tx("latestDeployment")}</dt><dd>{latestDeployment ? `${localizeStatus(t, latestDeployment.status)} · ${latestDeployment.server_id}` : tx("notDeployed")}</dd></div>
          </dl>
          <details><summary className="cursor-pointer text-sm font-medium">{tx("advancedSettings")}</summary><fieldset disabled={busy || !deliveryDraft} className="mt-3 grid gap-3 md:grid-cols-3">
            <Field label={t("runtimeType")}><Select disabled={busy} value={runtimeOverride} onValueChange={value => { setRuntimeOverride(value); setPreflight(null); setPlan(null) }}><SelectTrigger aria-label={t("runtimeType")}><SelectValue placeholder={t("runtimeType")} /></SelectTrigger><SelectContent><SelectItem value="auto">{tx("runtimeAuto")}</SelectItem><SelectItem value="node">{tx("runtimeNode")}</SelectItem><SelectItem value="python">{tx("runtimePython")}</SelectItem></SelectContent></Select></Field>
            <Field label={tx("projectRoot")}><Input aria-label={tx("projectRoot")} placeholder={tx("projectRootPlaceholder")} value={projectRoot} onChange={event => { setProjectRoot(event.target.value); setPreflight(null); setPlan(null) }} /></Field>
            <Field label={t("overrideServerId")}><Input aria-label={t("overrideServerId")} placeholder={t("overrideServerId")} value={serverId} onChange={event => setServerId(event.target.value)} /></Field>
          </fieldset></details>
          {selectedBuild?.status === "success" && <fieldset disabled={busy || !deliveryDraft} className="border-t pt-3">
            <legend className="mb-3 text-sm font-medium">{tx("deploymentOptions")}</legend>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="text-sm"><div className="text-xs text-muted-foreground">{tx("deploymentTarget")}</div><div className="break-all font-mono">{serverId.trim() || (typeof selectedBuild.manifest?.id === "string" ? selectedBuild.manifest.id : tx("unavailableTarget"))}</div></div>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={deployOverwrite} onChange={event => setDeployOverwrite(event.target.checked)} /><span><span className="font-medium">{tx("overwriteExisting")}</span><span className="block text-xs text-muted-foreground">{tx("overwriteExistingDesc")}</span></span></label>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={deployStart} onChange={event => setDeployStart(event.target.checked)} /><span><span className="font-medium">{tx("startAfterDeploy")}</span><span className="block text-xs text-muted-foreground">{tx("startAfterDeployDesc")}</span></span></label>
            </div>
          </fieldset>}
          {settingsDirty && <Button variant="outline" disabled={busy || !selectedBuild} onClick={() => {
            if (!selectedBuild) return
            setBusy(true)
            void saveDeliveryConfiguration(selectedBuild.id, mergeManifestPatch(selectedBuild.manifest || {}, configDrafts[selectedBuild.id] || deliveryDraft?.manifest_patch || {})).catch(notifyError).finally(() => setBusy(false))
          }}>{t("uploads") === "项目上传" ? "保存交付选项" : "Save delivery options"}</Button>}
          <div className="delivery-task-actions flex flex-wrap items-center gap-2 border-t pt-3">
            <Button variant="secondary" onClick={() => void runPreflight()} disabled={busy}>{tx("runPreflight")}</Button>
            {preflight && <Button variant="outline" onClick={() => void runPreflight(selectedUploadId, true)} disabled={busy}>{tx("forceRefresh")}</Button>}
            <Button variant="secondary" onClick={() => void previewPlan()} disabled={busy}>{tx("previewPlan")}</Button>
            <Button onClick={() => void createBuild()} disabled={busy}>{t("createBuild")}</Button>
            {selectedBuild?.status === "success" && <Button variant="outline" disabled={busy} onClick={() => setEditingBuildId(selectedBuild.id)}>{t("edit")} · {t("manifest")}</Button>}
            {latestDeployment?.status === "success" && <Button asChild variant="outline"><a href={`#/servers/${encodeURIComponent(latestDeployment.server_id)}`}>{t("viewServerDetail")}</a></Button>}
            {selectedBuild?.status === "success" && <Button variant="secondary" onClick={() => void deployBuild()} disabled={busy}>{t("deployBuild")}</Button>}
            {selectedBuild && canRequestStop(selectedBuild) && <Button variant="outline" onClick={() => void requestStopBuild()} disabled={busy}>{t("requestStopBuild")}</Button>}
          </div>
        </>}
      </CardContent>
    </Card>
    {selectedUpload && preflight ? <PreflightCard preflight={preflight} t={t} /> : null}
    {selectedUpload && plan ? <BuildPlanCard plan={plan} t={t} /> : null}
    {selectedBuild && <>
      <BuildHintCard build={selectedBuild} t={t} />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <BuildDetailCard build={selectedBuild} logs={buildLogs} streamConnected={liveTail} t={t} onCopied={onCopied} />
        <BuildTimelineCard build={selectedBuild} logs={buildLogs} t={t} />
      </div>
    </>}

    </> : null}

    {activeSection === "builds" ? <BuildRecordsTable builds={builds} busy={busy} selectedBuildId={selectedBuildId} canRequestStop={canRequestStop} onShowBuild={(build) => showBuild(build, "workspace")} onLoadLogs={(build) => showBuild(build, "logs")} onRequestStop={(id) => void requestStopBuild(id)} onDeploy={(id) => void deployBuild(id)} onRetry={retryBuild} onDelete={(build) => void deleteBuild(build)} t={t} /> : null}
    {activeSection === "deployments" ? <>
      {selectedDeployment && <Card>
        <CardHeader><CardTitle>{tx("rollbackSummary")}</CardTitle><CardDescription>{tx("startAfterRollbackDesc")}</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="rounded-md bg-muted/30 px-3 py-2 text-sm"><div className="text-xs text-muted-foreground">{tx("deploymentTarget")}</div><div className="break-all font-mono">{selectedDeployment.server_id}</div></div>
          <div className="rounded-md bg-muted/30 px-3 py-2 text-sm"><div className="text-xs text-muted-foreground">{tx("restoresSnapshot")}</div><div>{tx("enabledChoice")}</div></div>
          <label className="flex items-start gap-2 rounded-md border px-3 py-2 text-sm"><input type="checkbox" className="mt-1" checked={rollbackStart} disabled={busy || !selectedDeployment.rollback_available} onChange={(event) => setRollbackOption({ deploymentId: selectedDeployment.id, start: event.target.checked })} /><span><span className="font-medium">{tx("startAfterRollback")}</span><span className="block text-xs text-muted-foreground">{tx("startAfterRollbackDesc")}</span></span></label>
        </CardContent>
      </Card>}
      <DeploymentRecordsTable deployments={deployments} busy={busy} selectedDeploymentId={selectedDeploymentId} onSelect={(deployment) => showDeployment(deployment)} onDetail={(deployment) => showDeployment(deployment, true)} onRollback={(id) => void rollback(id)} onDelete={(deployment) => void deleteDeployment(deployment)} t={t} />
    </> : null}
    {activeSection === "logs" ? selectedBuild ? <BuildLogWorkbench><BuildLogsTable logs={buildLogs} filter={logFilter} onFilterChange={setLogFilter} selectedBuildLabel={`${selectedBuild.id} · ${localizeStatus(t, selectedBuild.status)} · ${buildLogs.length}`} live={liveTail} t={t} windowNavigation={{ busy: logWindowBusy, following: followLogs, earlier: logBounds.earlier, later: logBounds.later, onEarlier: () => void loadBuildLogs(selectedBuildId, { before_sequence: buildLogs[0]?.sequence }), onLater: () => void loadBuildLogs(selectedBuildId, { after_sequence: buildLogs.at(-1)?.sequence }), onLatest: () => void loadBuildLogs(selectedBuildId), onPause: () => setFollowLogs(false) }} /><BuildOutputPanels build={selectedBuild} log={selectedBuildLog} t={t} /></BuildLogWorkbench> : <div className="flex flex-wrap items-center gap-3"><p className="text-sm text-muted-foreground">{c.selectBuild}</p><Button variant="outline" onClick={() => setActiveSection("builds")}>{tx("buildsTab")}</Button></div> : null}

    <Toaster toast={toast} onClose={() => setToast(null)} />
    {editingBuildId && <DeliveryConfigEditor manifest={mergeManifestPatch(builds.find(item => item.id === editingBuildId)?.manifest || {}, configDrafts[editingBuildId] || deliveryDraft?.manifest_patch || {})} locale={t("uploads") === "项目上传" ? "zh-CN" : "en-US"} t={t} onClose={() => setEditingBuildId(null)} onSave={manifest => saveDeliveryConfiguration(editingBuildId, manifest)} />}
    {confirmDialog}

    <Dialog open={detailDialog !== null} onOpenChange={(open) => { if (!open) setDetailDialog(null) }}>
      <DialogContent closeLabel={t("close")} className="max-w-4xl">
        <DialogHeader><DialogTitle>{detailDialog?.title || ""}</DialogTitle></DialogHeader>
        <DialogBody><JsonPanel copyLabel={t("copy")} text={detailDialog?.body} maxHeight="max-h-[60vh]" /></DialogBody>
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
  return buildId ? `#/builds/${encodeURIComponent(buildId)}` : "#/builds"
}

function writeBuildHash(buildId: string, replace = false) {
  const hash = buildHash(buildId)
  if (replace) {
    replaceConsoleRouteHash(hash)
    return
  }
  if (window.location.hash !== hash) window.location.hash = hash
}

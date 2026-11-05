import { createPortal } from "react-dom"
import { useContext, useEffect, useId, useRef, useState } from "react"
import { Select } from "antd"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { networkApi, type GitImport, type GitPlan, type GitSource, type NetworkProfile } from "@/api/network"
import type { ProjectUpload } from "@/api/builds"
import { useAuth } from "@/components/auth-gate"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { FormDialog } from "@/components/form-dialog"
import { FilterRadio } from "@/components/filter-radio"
import { FieldLabel } from "@/components/field-help"
import { NetworkSettingsPanel } from "./network-settings-panel"
import { networkPermission, selectionFromKey, selectionKey, selectionOptions } from "./model"
import type { TFunction } from "@/i18n"
import "./network-settings.css"

const initial: GitSource = { repository_url: "", ref_type: "branch", ref: "main", project_root: ".", credential_ref: null, git_network: { mode: "inherit" }, install_network: { mode: "inherit" }, runtime_template: "node" }

export function GitImportForm({ t, onImported, onState, actionContainer }: { actionContainer?: HTMLElement | null; t: TFunction; onImported: (upload: ProjectUpload) => void; onState?: (state: { dirty: boolean; pending: boolean }) => void }) {
  const fieldId = useId()
  const { user } = useAuth()
  const zh = t("uploads") === "项目上传"
  const copy = (cn: string, en: string) => zh ? cn : en
  const { confirm, confirmDialog } = useConfirm(t, true)
  const [source, setSource] = useState<GitSource>(initial)
  const [profiles, setProfiles] = useState<NetworkProfile[]>([])
  const [plan, setPlan] = useState<GitPlan | null>(null)
  const [task, setTask] = useState<GitImport | null>(null)
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<"inspect" | "acquire" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsState, setSettingsState] = useState({ dirty: false, pending: false })
  const mounted = useRef(true)
  const pending = useRef(false)
  const settingsTrigger = useRef<HTMLElement | null>(null)
  const operationKey = useRef("")
  const published = useRef("")
  const registerExit = useContext(EditorNavigationContext)
  const active = Boolean(task && !task.terminal)
  const uncertain = Boolean(operationKey.current && !task && !busy)
  const sourceLocked = busy || active || uncertain || Boolean(task?.requires_reconciliation)
  const canUse = networkPermission(user, "network.use") && networkPermission(user, "operations.manage")
  const canWrite = canUse && networkPermission(user, "tools.invoke")
  const canManage = networkPermission(user, "system_settings.manage")
  useEffect(() => registerExit?.({ dirty: source.repository_url.length > 0, pending: sourceLocked }), [registerExit, source.repository_url, sourceLocked])
  useEffect(() => { onState?.({ dirty: source.repository_url.length > 0, pending: sourceLocked }) }, [onState, source.repository_url, sourceLocked])
  useEffect(() => { mounted.current = true; if (canUse) void loadProfiles(); return () => { mounted.current = false } }, [canUse])
  useEffect(() => {
    if (!task || task.terminal) return
    let disposed = false
    const timer = window.setTimeout(() => {
      void networkApi.status(task.import_id).then(next => { if (!disposed) { setTask(next); setError(null) } }).catch(err => { if (!disposed) setError(String(err)) })
    }, 1000)
    return () => { disposed = true; window.clearTimeout(timer) }
  }, [task])
  useEffect(() => {
    if (task?.status !== "success" || !task.upload_id || published.current === task.upload_id) return
    const uploadId = task.upload_id
    published.current = uploadId
    void networkApi.upload(uploadId).then(upload => { if (mounted.current) onImported(upload) }).catch(err => { if (mounted.current) { published.current = ""; setError(String(err)) } })
  }, [task, onImported])

  async function loadProfiles() {
    try { const value = await networkApi.options(); if (mounted.current) setProfiles(value.profiles || []) }
    catch (err) { if (mounted.current) setError(String(err)) }
  }
  function update(patch: Partial<GitSource>) { if (sourceLocked) return; setSource({ ...source, ...patch }); setPlan(null); setTask(null); operationKey.current = "" }
  async function run(action: () => Promise<void>) {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(null)
    try { await action() }
    catch (err) { if (mounted.current) setError(String(err)) }
    finally { pending.current = false; if (mounted.current) { setBusy(false); setPhase(null) } }
  }
  async function preview() {
    await run(async () => {
      setPhase("inspect")
      const value = await networkApi.plan(source)
      if (mounted.current) { setPlan(value); operationKey.current = "" }
    })
  }
  async function acquire() {
    if (!canWrite || active || task?.requires_reconciliation) return
    await run(async () => {
      setPhase("inspect")
      // A lost acquire response must retry the same pinned plan and key. A known
      // terminal task can start a fresh, explicit import; unknown tasks cannot.
      const reusable = !task && plan && (operationKey.current || (plan.status === "ready" && plan.validation.ok && (!plan.expires_at || Date.parse(plan.expires_at) > Date.now())))
      const selected = reusable ? plan : await networkApi.plan(source)
      if (!mounted.current) return
      setPlan(selected)
      if (selected.status !== "ready") return
      if (!selected.validation.ok) throw new Error(copy("来源校验未通过，请检查来源后重试。", "Source validation failed. Check the source and retry."))
      if (task?.terminal) { operationKey.current = ""; setTask(null) }
      operationKey.current ||= `git-import-${crypto.randomUUID()}`
      setPhase("acquire")
      const created = await networkApi.acquire(selected, operationKey.current)
      if (mounted.current) setTask(created)
    })
  }
  async function closeSettings() {
    if (settingsState.pending || (settingsState.dirty && !(await confirm({ title: copy("放弃未保存的设置？", "Discard unsaved settings?"), destructive: true })))) return
    setSettingsOpen(false); setSettingsState({ dirty: false, pending: false }); void loadProfiles()
  }

  const actions = <div className="network-settings-actions">
    <Button disabled={!canWrite || busy || active || Boolean(task?.requires_reconciliation) || !source.repository_url.trim() || !source.ref.trim()} onClick={() => void acquire()}>
      {phase === "inspect" ? copy("正在检查来源…", "Checking source…") : phase === "acquire" || active ? copy("正在导入…", "Importing…") : task?.terminal ? copy("重新导入", "Import again") : copy("导入项目", "Import project")}
    </Button>
    <Button variant="outline" disabled={!canUse || sourceLocked || !source.repository_url.trim() || !source.ref.trim()} onClick={() => void preview()}>{copy("检查来源", "Check source")}</Button>
  </div>

  return <Card>
    <CardHeader><CardTitle>{copy("从 Git 仓库导入", "Import from a Git repository")}</CardTitle></CardHeader>
    <CardContent className="flex flex-col gap-4">
    {!canUse && <Alert><AlertDescription>{copy("需要 network.use 权限才能访问交付网络。", "The network.use permission is required to access delivery networking.")}</AlertDescription></Alert>}
    {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}{uncertain && <p>{copy("导入响应未确认。再次导入会恢复同一个请求，不会创建重复任务。", "The import response is unconfirmed. Retrying resumes the same request without creating a duplicate task.")}</p>}</AlertDescription></Alert>}
    <div className="git-source-form">
      <label className="network-settings-field gate-form-row git-source-full" htmlFor={`${fieldId}-repository`}><FieldLabel className="gate-form-label" label={copy("仓库地址", "Repository")} zh={zh} helpId={`${fieldId}-repository-help`} help={copy("支持 HTTPS。导入时自动校验并固定 commit；SSH、submodule 和 LFS 不自动拉取。", "Use HTTPS. Import validates and pins the commit automatically; SSH, submodules and LFS are not fetched automatically.")} /><span className="gate-form-control"><Input id={`${fieldId}-repository`} aria-label={copy("仓库 URL（HTTPS）", "Repository URL (HTTPS)")} aria-describedby={`${fieldId}-repository-help`} disabled={sourceLocked} autoComplete="off" placeholder="https://git.example.invalid/team/mcp-server.git" value={source.repository_url} onChange={event => update({ repository_url: event.target.value })} /></span></label>
      <div className="network-settings-field gate-form-row git-source-full"><span className="gate-form-label">{copy("来源类型", "Ref type")}</span><div className="gate-form-control"><FilterRadio label={copy("来源类型", "Ref type")} hideLabel disabled={sourceLocked} value={source.ref_type} options={[{ value: "branch", label: copy("分支", "Branch") }, { value: "tag", label: "Tag" }, { value: "commit", label: "Commit SHA" }]} onChange={ref_type => update({ ref_type: ref_type as GitSource["ref_type"] })} /></div></div>
      <label className="network-settings-field gate-form-row"><span className="gate-form-label">{source.ref_type === "commit" ? "Commit SHA" : copy("分支 / tag", "Branch / tag")}</span><span className="gate-form-control"><Input disabled={sourceLocked} autoComplete="off" value={source.ref} onChange={event => update({ ref: event.target.value })} /></span></label>
      <label className="network-settings-field gate-form-row"><span className="gate-form-label">{copy("项目子目录", "Subdirectory")}</span><span className="gate-form-control"><Input aria-label={copy("项目子目录", "Project subdirectory")} disabled={sourceLocked} value={source.project_root} onChange={event => update({ project_root: event.target.value })} /></span></label>
      <details className="git-source-full delivery-auxiliary"><summary>{copy("凭据与网络设置", "Credentials and networking")}</summary><div className="git-source-form mt-4">
      <label className="network-settings-field gate-form-row git-source-full"><span className="gate-form-label">{copy("私有库凭据 ID", "Credential ID")}</span><span className="gate-form-control"><Input aria-label={copy("私有库凭据引用 ID（可选）", "Private repository credential reference ID (optional)")} placeholder={copy("可选", "Optional")} disabled={sourceLocked} autoComplete="off" value={source.credential_ref || ""} onChange={event => update({ credential_ref: event.target.value || null })} /></span></label>
      {(["git_network", "install_network"] as const).map(phase => <label className="network-settings-field gate-form-row" key={phase}><span className="gate-form-label">{phase === "git_network" ? copy("Git 拉取网络", "Git network") : copy("依赖安装网络", "Install network")}</span><span className="gate-form-control"><Select getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} aria-label={phase === "git_network" ? copy("Git 拉取网络", "Git acquisition network") : copy("依赖安装网络", "Dependency installation network")} disabled={sourceLocked} value={selectionKey(source[phase])} options={selectionOptions(profiles, zh)} onChange={key => update({ [phase]: selectionFromKey(key) })} /></span></label>)}
      {canManage && <div className="git-source-full"><Button variant="outline" disabled={sourceLocked} onClick={event => { settingsTrigger.current = event.currentTarget; setSettingsOpen(true) }}>{copy("管理网络设置", "Manage network settings")}</Button></div>}
      </div></details>
      <div className="network-settings-field gate-form-row git-source-full"><span className="gate-form-label">{copy("运行模板", "Runtime template")}</span><div className="gate-form-control"><FilterRadio label={copy("运行模板", "Runtime template")} hideLabel disabled={sourceLocked} value={source.runtime_template} options={[{ value: "node", label: "Node.js · stdio" }, { value: "python", label: "Python · stdio" }]} onChange={runtime_template => update({ runtime_template: runtime_template as GitSource["runtime_template"] })} /></div></div>
      {plan?.status === "blocked" && <Alert className="git-source-full"><AlertDescription><strong>{copy("无法导入此来源", "This source cannot be imported")}</strong><p>{plan.error?.message}</p><p>{plan.error?.next_action}</p><code className="text-xs">{plan.error?.code}</code></AlertDescription></Alert>}
      {plan?.status === "ready" && <details className="git-source-full delivery-auxiliary">
        <summary>{copy("已校验来源", "Validated source")} · <code>{plan.plan?.commit_sha?.slice(0, 12)}</code></summary>
        <div className="pt-3"><JsonPanel copyLabel={t("copy")} data={{ ...plan.plan, plan_digest: plan.plan_digest, expires_at: plan.expires_at }} /></div>
      </details>}
      {task && <div className="git-source-review git-source-full" role="status">
        <div className="flex flex-wrap items-center gap-2"><Badge variant={task.status === "success" ? "success" : task.error_code ? "danger" : "outline"}>{task.status}</Badge><code className="text-xs">{task.import_id}</code></div>
        <p className="my-2 text-sm">{task.progress.map(step => `${step.phase}: ${step.status}`).join(" → ")}</p>
        {task.requires_reconciliation && <Alert><AlertDescription><strong>{copy("执行结果未知，需核实原任务", "Execution outcome unknown; inspect the existing task")}</strong><p>{copy("尚未确认执行终止。请查询现有任务状态后再处理，不要重复导入。", "Execution termination is unconfirmed. Check the existing task before continuing.")}</p></AlertDescription></Alert>}
        {task.error_code && <Alert variant="destructive"><AlertDescription>{task.error_code}</AlertDescription></Alert>}
        <div className="network-settings-actions mt-3">
          <Button variant="outline" disabled={busy} onClick={() => void run(async () => setTask(await networkApi.status(task.import_id)))}>{copy("刷新任务状态", "Refresh task status")}</Button>
          {active && <Button variant="outline" className="text-destructive" disabled={busy} onClick={() => void run(async () => { if (!(await confirm({ title: copy("取消源码拉取？", "Cancel source acquisition?"), destructive: true }))) return; setTask(await networkApi.cancel(task.import_id, `git-cancel-${crypto.randomUUID()}`)) })}>{copy("取消拉取", "Cancel acquisition")}</Button>}
        </div>
      </div>}
    </div>
    {actionContainer ? createPortal(actions, actionContainer) : <div className="git-source-actions">{actions}</div>}
    <FormDialog className="max-w-[1200px] gate-network-dialog" bodyClassName="network-settings-dialog" title={copy("系统设置 · 网络与依赖", "System settings · Network and dependencies")} closeLabel={t("close")} open={settingsOpen} onClose={() => void closeSettings()} dirty={settingsState.dirty} pending={settingsState.pending}
      onCloseAutoFocus={event => { if (settingsTrigger.current?.isConnected) { event.preventDefault(); settingsTrigger.current.focus() } }}
      footer={<Button disabled={settingsState.pending} onClick={() => void closeSettings()}>{copy("返回导入", "Back to import")}</Button>}>
      {settingsOpen && <NetworkSettingsPanel t={t} onState={setSettingsState} onSaved={() => { void loadProfiles(); setPlan(null); operationKey.current = "" }} />}
    </FormDialog>
    {confirmDialog}
    </CardContent>
  </Card>
}

import { useContext, useEffect, useRef, useState } from "react"
import { Alert, Button, Card, Drawer, Input, Select, Tag } from "antd"
import { networkApi, type GitImport, type GitPlan, type GitSource, type NetworkProfile } from "@/api/network"
import type { ProjectUpload } from "@/api/builds"
import { useAuth } from "@/components/auth-gate"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { NetworkSettingsPanel } from "./network-settings-panel"
import { networkPermission, selectionFromKey, selectionKey, selectionOptions } from "./model"
import type { TFunction } from "@/i18n"
import "./network-settings.css"

const initial: GitSource = { repository_url: "", ref_type: "branch", ref: "main", project_root: ".", credential_ref: null, git_network: { mode: "inherit" }, install_network: { mode: "inherit" }, runtime_template: "node" }

export function GitImportForm({ t, onImported, onState }: { t: TFunction; onImported: (upload: ProjectUpload) => void; onState?: (state: { dirty: boolean; pending: boolean }) => void }) {
  const { user } = useAuth()
  const zh = t("uploads") === "项目上传"
  const copy = (cn: string, en: string) => zh ? cn : en
  const { confirm, confirmDialog } = useConfirm(t)
  const [source, setSource] = useState<GitSource>(initial)
  const [profiles, setProfiles] = useState<NetworkProfile[]>([])
  const [plan, setPlan] = useState<GitPlan | null>(null)
  const [task, setTask] = useState<GitImport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsState, setSettingsState] = useState({ dirty: false, pending: false })
  const mounted = useRef(true)
  const pending = useRef(false)
  const operationKey = useRef("")
  const published = useRef("")
  const registerExit = useContext(EditorNavigationContext)
  const active = Boolean(task && !task.terminal)
  const canUse = networkPermission(user, "network.use") && networkPermission(user, "operations.manage")
  const canWrite = canUse && networkPermission(user, "tools.invoke")
  const canManage = networkPermission(user, "system_settings.manage")
  useEffect(() => registerExit?.({ dirty: source.repository_url.length > 0, pending: busy || active }), [registerExit, source.repository_url, busy, active])
  useEffect(() => { onState?.({ dirty: source.repository_url.length > 0, pending: busy || active }) }, [onState, source.repository_url, busy, active])
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
  function update(patch: Partial<GitSource>) { setSource({ ...source, ...patch }); setPlan(null); setTask(null); operationKey.current = "" }
  async function run(action: () => Promise<void>) {
    if (pending.current) return
    pending.current = true; setBusy(true); setError(null)
    try { await action() }
    catch (err) { if (mounted.current) setError(String(err)) }
    finally { pending.current = false; if (mounted.current) setBusy(false) }
  }
  async function preview() { await run(async () => { const value = await networkApi.plan(source); if (mounted.current) { setPlan(value); operationKey.current = "" } }) }
  async function acquire() {
    if (!plan?.validation.ok || plan.status !== "ready") return
    const selected = plan
    await run(async () => {
      if (!(await confirm({ title: copy("确认拉取此 commit？", "Confirm acquisition of this commit?"), description: copy("仅导入源码快照。安装、部署和启动需要后续确认。", "Imports the source snapshot. Installation, deployment and startup require later confirmation."), details: <JsonPanel copyLabel={t("copy")} data={selected.plan} /> }))) return
      operationKey.current ||= `git-import-${crypto.randomUUID()}`
      const created = await networkApi.acquire(selected, operationKey.current)
      if (mounted.current) setTask(created)
    })
  }
  async function closeSettings() {
    if (settingsState.pending || (settingsState.dirty && !(await confirm({ title: copy("放弃未保存的设置？", "Discard unsaved settings?"), destructive: true })))) return
    setSettingsOpen(false); setSettingsState({ dirty: false, pending: false }); void loadProfiles()
  }

  return <Card title={copy("从 Git 仓库导入", "Import from a Git repository")} extra={canManage && <Button disabled={busy || active} onClick={() => setSettingsOpen(true)}>{copy("网络设置", "Network settings")}</Button>}>
    {!canUse && <Alert type="warning" showIcon title={copy("需要独立的 network.use 权限才能调用交付网络", "The separate network.use permission is required to invoke delivery networking")} />}
    {error && <Alert className="mb-3" type="error" showIcon title={error} />}
    <div className="git-source-form">
      <label className="network-settings-field git-source-full"><span>{copy("仓库 URL（HTTPS）", "Repository URL (HTTPS)")}</span><Input disabled={busy || active} autoComplete="off" placeholder="https://git.example.invalid/team/mcp-server.git" value={source.repository_url} onChange={event => update({ repository_url: event.target.value })} /></label>
      <label className="network-settings-field"><span>{copy("来源类型", "Ref type")}</span><Select disabled={busy || active} value={source.ref_type} options={[{ value: "branch", label: copy("分支", "Branch") }, { value: "tag", label: "Tag" }, { value: "commit", label: "Commit SHA" }]} onChange={ref_type => update({ ref_type })} /></label>
      <label className="network-settings-field"><span>{source.ref_type === "commit" ? "Commit SHA" : copy("分支 / tag", "Branch / tag")}</span><Input disabled={busy || active} autoComplete="off" value={source.ref} onChange={event => update({ ref: event.target.value })} /></label>
      <label className="network-settings-field"><span>{copy("项目子目录", "Project subdirectory")}</span><Input disabled={busy || active} value={source.project_root} onChange={event => update({ project_root: event.target.value })} /></label>
      <label className="network-settings-field"><span>{copy("私有库凭据引用 ID（可选）", "Private repository credential reference ID (optional)")}</span><Input disabled={busy || active} autoComplete="off" value={source.credential_ref || ""} onChange={event => update({ credential_ref: event.target.value || null })} /></label>
      {(["git_network", "install_network"] as const).map(phase => <label className="network-settings-field" key={phase}><span>{phase === "git_network" ? copy("Git 拉取网络", "Git acquisition network") : copy("依赖安装网络", "Dependency installation network")}</span><Select aria-label={phase === "git_network" ? copy("Git 拉取网络", "Git acquisition network") : copy("依赖安装网络", "Dependency installation network")} disabled={busy || active} value={selectionKey(source[phase])} options={selectionOptions(profiles, zh)} onChange={key => update({ [phase]: selectionFromKey(key) })} /></label>)}
      <label className="network-settings-field"><span>{copy("运行模板", "Runtime template")}</span><Select aria-label={copy("运行模板", "Runtime template")} disabled={busy || active} value={source.runtime_template} options={[{ value: "node", label: "Node.js · stdio" }, { value: "python", label: "Python · stdio" }]} onChange={runtime_template => update({ runtime_template })} /></label>
      <div className="network-settings-actions self-end"><Button type="primary" loading={busy} disabled={!canUse || active || !source.repository_url.trim() || !source.ref.trim()} onClick={() => void preview()}>{copy("检查并生成计划", "Inspect and plan")}</Button></div>
      <p className="git-source-full text-xs text-muted-foreground">{copy("计划固定 commit 与配置版本；HTTPS 重定向、SSH、submodule 和 LFS 均不自动执行，不预置 SSH 密钥。示例主机需管理员显式配置。", "Plans pin commit and configuration versions. HTTPS redirects, SSH, submodules and LFS are not automatically executed; no SSH keys are provisioned. Example hosts require explicit administrator configuration.")}</p>
      {plan?.status === "blocked" && <Alert className="git-source-full" type="warning" showIcon title={copy("导入被执行边界阻断", "Import blocked by the execution boundary")} description={`${plan.error?.code}: ${plan.error?.message} · ${plan.error?.next_action}`} />}
      {plan?.status === "ready" && <div className="git-source-review git-source-full">
        <dl><dt>Commit</dt><dd><code>{plan.plan?.commit_sha}</code></dd><dt>{copy("计划摘要", "Plan digest")}</dt><dd><code>{plan.plan_digest}</code></dd><dt>{copy("截止时间", "Expires")}</dt><dd>{plan.expires_at}</dd></dl>
        <details className="my-3"><summary>{copy("精确来源与网络版本", "Exact source and network versions")}</summary><JsonPanel copyLabel={t("copy")} data={plan.plan} /></details>
        <Button type="primary" disabled={!canWrite || busy || active || Boolean(task)} onClick={() => void acquire()}>{copy("确认并拉取快照", "Confirm and acquire snapshot")}</Button>
      </div>}
      {task && <div className="git-source-review git-source-full" role="status"><Tag>{task.status}</Tag><code>{task.import_id}</code><p>{task.progress.map(step => `${step.phase}: ${step.status}`).join(" → ")}</p>{task.requires_reconciliation && <Alert type="warning" title={copy("执行结果未知，需对账", "Execution outcome unknown; reconciliation required")} description={copy("协调器队列容量已释放，但没有确认执行已终止。请核实原任务，勿盲目重放或视为取消成功。", "The coordinator queue slot was released, but execution termination is unconfirmed. Inspect the original operation; do not replay it or assume cancellation succeeded.")} />}{task.error_code && <Alert type="error" title={task.error_code} />}<div className="network-settings-actions">
        {active && <Button danger disabled={busy} onClick={() => void run(async () => { if (!(await confirm({ title: copy("取消源码拉取？", "Cancel source acquisition?"), destructive: true }))) return; setTask(await networkApi.cancel(task.import_id, `git-cancel-${crypto.randomUUID()}`)) })}>{copy("取消拉取", "Cancel acquisition")}</Button>}
        <Button disabled={busy} onClick={() => void run(async () => setTask(await networkApi.status(task.import_id)))}>{copy("查询现有任务", "Check existing task")}</Button>
      </div></div>}
    </div>
    <Drawer className="network-settings-drawer" size={960} title={copy("系统设置 · 网络与依赖", "System settings · Network and dependencies")} open={settingsOpen} onClose={() => void closeSettings()} maskClosable={!settingsState.pending} keyboard={!settingsState.pending} closable={!settingsState.pending}>
      {settingsOpen && <NetworkSettingsPanel t={t} onState={setSettingsState} onSaved={() => { void loadProfiles(); setPlan(null); operationKey.current = "" }} />}
    </Drawer>
    {confirmDialog}
  </Card>
}

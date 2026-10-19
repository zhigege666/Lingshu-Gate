import { useContext, useEffect, useId, useRef, useState } from "react"
import { Alert, Button, Card, Empty, Input, Select, Switch, Table, Tag } from "antd"
import { useAuth } from "@/components/auth-gate"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { usePageRefresh } from "@/components/page-refresh"
import { FilterRadio } from "@/components/filter-radio"
import { FieldLabel } from "@/components/field-help"
import { FormDialog } from "@/components/form-dialog"
import { networkApi, type NetworkDefaults, type NetworkProfile, type NetworkSettings } from "@/api/network"
import { executorNextAction, networkPermission, selectionFromKey, selectionKey, selectionOptions } from "./model"
import type { TFunction } from "@/i18n"
import "./network-settings.css"

type ProfileDraft = { id?: string; name: string; endpoint: string; credential_ref: string; enabled: boolean; expected_version: number }
const blank: ProfileDraft = { name: "", endpoint: "", credential_ref: "", enabled: true, expected_version: 0 }

export function NetworkSettingsPanel({ t, onSaved, onState }: { t: TFunction; onSaved?: () => void; onState?: (state: { dirty: boolean; pending: boolean }) => void }) {
  const fieldId = useId()
  const { user } = useAuth()
  const zh = t("uploads") === "项目上传"
  const { confirm, confirmDialog } = useConfirm(t, true)
  const [settings, setSettings] = useState<NetworkSettings | null>(null)
  const [defaults, setDefaults] = useState<NetworkDefaults | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [draft, setDraft] = useState<ProfileDraft | null>(null)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [target, setTarget] = useState<"github" | "npm" | "python">("github")
  const [references, setReferences] = useState<Array<{ version: number; resource_type: string; resource_id: string }> | null>(null)
  const [hostPolicy, setHostPolicy] = useState("")
  const [executorHelp, setExecutorHelp] = useState(false)
  const baseline = useRef("")
  const requestId = useRef(0)
  const mounted = useRef(true)
  const running = useRef(false)
  const panel = useRef<HTMLDivElement | null>(null)
  const profileTrigger = useRef<HTMLElement | null>(null)
  const profileReturnScope = useRef<HTMLElement | null>(null)
  const referencesTrigger = useRef<HTMLElement | null>(null)
  const executorTrigger = useRef<HTMLElement | null>(null)
  const registerExit = useContext(EditorNavigationContext)
  const dirty = Boolean(draft && JSON.stringify(draft) !== baseline.current) || Boolean(defaults && settings && (JSON.stringify(defaults) !== JSON.stringify(settings.defaults) || hostPolicy !== JSON.stringify(settings.defaults.git_hosts, null, 2)))
  useEffect(() => registerExit?.({ dirty, pending: busy }), [registerExit, dirty, busy])
  useEffect(() => { onState?.({ dirty, pending: busy }) }, [onState, dirty, busy])
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false; requestId.current += 1 } }, [])
  usePageRefresh(() => load(true), loading || busy)
  const canTest = networkPermission(user, "network.use") && networkPermission(user, "operations.manage") && networkPermission(user, "tools.invoke")

  async function load(preserve = false) {
    const id = ++requestId.current
    setLoading(true)
    try {
      const data = await networkApi.settings()
      if (id !== requestId.current || !mounted.current) return
      // Refresh must never erase a pending default/editor draft.
      setSettings(previous => preserve && defaults && previous ? { ...data, defaults: previous.defaults, revision: previous.revision } : data)
      if (!preserve) { setDefaults(data.defaults); setHostPolicy(JSON.stringify(data.defaults.git_hosts, null, 2)) }
      setError(null)
    } catch (err) { if (mounted.current) setError(String(err)) }
    finally { if (mounted.current && id === requestId.current) setLoading(false) }
  }

  async function run(action: () => Promise<unknown>, edit = false) {
    if (running.current) return
    running.current = true; setBusy(true); setError(null); setDraftError(null); setResult(null)
    try { await action() }
    catch (err) { if (mounted.current) { if (edit) setDraftError(String(err)); else setError(String(err)) } }
    finally { running.current = false; if (mounted.current) setBusy(false) }
  }

  function edit(profile?: NetworkProfile) {
    profileTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    profileReturnScope.current = profileTrigger.current?.closest<HTMLElement>('[role="dialog"]') || null
    const value = profile ? { id: profile.id, name: profile.name, endpoint: "", credential_ref: profile.credential_ref || "", enabled: profile.enabled, expected_version: profile.version } : { ...blank }
    baseline.current = JSON.stringify(value); setDraft(value); setDraftError(null)
  }
  async function closeDraft() {
    if (busy || (draft && JSON.stringify(draft) !== baseline.current && !(await confirm({ title: zh ? "放弃未保存的网络配置？" : "Discard unsaved network configuration?", destructive: true })))) return
    setDraft(null); setDraftError(null)
  }
  async function saveProfile() {
    if (!draft) return
    const current = draft
    let saved = false
    await run(async () => {
      await networkApi.saveProfile({ name: current.name.trim(), endpoint: current.endpoint || null, credential_ref: current.credential_ref.trim() || null, enabled: current.enabled, expected_version: current.expected_version }, current.id)
      saved = true
      setResult(zh ? "配置已保存为新版本" : "Saved as a new configuration version"); await load(true); onSaved?.()
    }, true)
    // The return trigger is disabled until run settles, including its refresh.
    if (saved && mounted.current) setDraft(null)
  }

  const profiles = settings?.profiles || []
  const copy = (cn: string, en: string) => zh ? cn : en
  return <div ref={panel} className="flex flex-col gap-4" aria-busy={busy || loading}>
    {!settings && loading && <p role="status">{t("loadingData")}</p>}
    {error && <Alert type="error" showIcon title={error} action={<Button disabled={busy} onClick={() => void load(true)}>{t("retry")}</Button>} />}
    {result && <Alert type="success" showIcon title={result} closable onClose={() => setResult(null)} />}
    {settings && defaults && <>
      {!settings.executor.available && <Alert type="warning" showIcon title={copy("安全网络执行器尚未就绪", "Safe network executor is not ready")} description={<div className="flex flex-col gap-2">
        <p>{copy("Git 拉取、代理测试和使用指定网络的依赖安装需执行器就绪后才能执行。网络配置仍可先保存。", "Git acquisition, proxy tests and dependency installation with configured networking require a ready executor. You can still save network configuration.")}</p>
        <p>{executorNextAction(settings.executor.missing, zh)}</p>
        <div className="network-settings-actions">
          <Button onClick={event => { executorTrigger.current = event.currentTarget; setExecutorHelp(true) }}>{copy("查看配置指引", "View setup guide")}</Button>
          <Button disabled={busy || loading} loading={loading} onClick={() => void load(true)}>{copy("重新检查", "Check again")}</Button>
        </div>
      </div>} />}
      <div className="network-settings-grid">
        <Card title={copy("代理配置", "Proxy profiles")} extra={<Button type="primary" data-network-new-profile disabled={busy} onClick={() => edit()}>{copy("新增配置", "New profile")}</Button>}>
          <div className="gate-form-row mb-3"><span className="gate-form-label">{copy("受控测试目标", "Test target")}</span><div className="gate-form-control"><FilterRadio id="network-test-target" label={copy("受控测试目标", "Controlled test target")} hideLabel value={target} disabled={busy} onChange={value => setTarget(value as typeof target)} options={[{ value: "github", label: "GitHub" }, { value: "npm", label: "npm registry" }, { value: "python", label: "Python index" }]} /></div></div>
          <Table<NetworkProfile> rowKey="id" size="small" loading={loading} scroll={{ x: 720, y: 360 }} pagination={false} dataSource={profiles} locale={{ emptyText: <Empty description={copy("直连不需要代理配置", "Direct access needs no proxy profile")} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} columns={[
            { title: copy("名称", "Name"), dataIndex: "name", ellipsis: true },
            { title: copy("版本 / 协议", "Version / scheme"), render: (_, row) => `v${row.version} · ${row.scheme}` },
            { title: copy("状态", "State"), render: (_, row) => <Tag color={!row.enabled || !row.credential_configured ? "warning" : "success"}>{!row.enabled ? copy("已停用", "Disabled") : row.credential_configured ? copy("已配置", "Configured") : copy("凭据需更新", "Credential changed")}</Tag> },
            { title: copy("操作", "Actions"), width: 320, render: (_, row) => <div className="network-settings-actions">
              <Button size="small" disabled={busy} onClick={() => edit(row)}>{t("edit")}</Button>
              <Button size="small" disabled={busy} onClick={event => { referencesTrigger.current = event.currentTarget; void run(async () => setReferences((await networkApi.references(row.id)).references)) }}>{copy("引用", "References")}</Button>
              <Button size="small" disabled={busy || !canTest || !row.enabled} onClick={() => void run(async () => { if (!(await confirm({ title: copy("从执行环境测试网络？", "Test from the execution environment?"), description: `${target} · HEAD · 5s · 4 KiB` }))) return; const tested = await networkApi.test(row, target); setResult(`${target}: ${tested.status}`) })}>{copy("测试", "Test")}</Button>
              <Button size="small" disabled={busy} onClick={() => void run(async () => { if (!(await confirm({ title: row.enabled ? copy("停用此配置？", "Disable this profile?") : copy("启用此配置？", "Enable this profile?"), description: copy("已排队任务仍固定原版本。", "Queued tasks retain their pinned version.") }))) return; await networkApi.saveProfile({ name: row.name, credential_ref: row.credential_ref, enabled: !row.enabled, expected_version: row.version }, row.id); await load(true); onSaved?.() })}>{row.enabled ? copy("停用", "Disable") : copy("启用", "Enable")}</Button>
              <Button size="small" danger disabled={busy} onClick={event => { referencesTrigger.current = event.currentTarget; void run(async () => { const refs = await networkApi.references(row.id); if (refs.references.length) { setReferences(refs.references); throw new Error(copy("配置仍被引用，可停用但不能删除。", "Profile is referenced; disable it instead of deleting.")) } if (!(await confirm({ title: copy("删除此配置？", "Delete this profile?"), destructive: true }))) return; await networkApi.deleteProfile(row.id, row.version); await load(true); onSaved?.() }) }}>{t("delete")}</Button>
            </div> },
          ]} />
        </Card>
        <Card title={copy("默认网络与依赖源", "Default network and dependency sources")}>
          <div className="network-settings-fields">
            {(["git", "install"] as const).map(phase => <label className="network-settings-field gate-form-row network-settings-full" key={phase} htmlFor={`${fieldId}-${phase}-default`}><FieldLabel className="gate-form-label" label={phase === "git" ? copy("Git 拉取默认", "Git default") : copy("依赖安装默认", "Install default")} zh={zh} helpId={`${fieldId}-${phase}-default-help`} help={copy("项目继承在计划时固定；失败不会静默直连，网络配置不传入运行时 MCP。", "Inheritance is pinned at planning. Failures never fall back to direct; settings are not passed to runtime MCP.")} /><span className="gate-form-control"><Select id={`${fieldId}-${phase}-default`} getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} aria-label={phase === "git" ? copy("Git 拉取默认", "Git acquisition default") : copy("依赖安装默认", "Dependency installation default")} aria-describedby={`${fieldId}-${phase}-default-help`} disabled={busy} value={selectionKey(defaults[phase])} options={selectionOptions(profiles, zh, false)} onChange={key => setDefaults({ ...defaults, [phase]: selectionFromKey(key) })} /></span></label>)}
            {(["npm", "python"] as const).map(phase => <div key={phase} className="network-settings-field network-settings-full">
              <label className="network-settings-field gate-form-row"><span className="gate-form-label">{phase === "npm" ? "npm registry" : "Python index"}</span><span className="gate-form-control"><Input disabled={busy} value={phase === "npm" ? defaults.npm_registry : defaults.python_index} onChange={event => setDefaults({ ...defaults, [phase === "npm" ? "npm_registry" : "python_index"]: event.target.value })} /></span></label>
              <label className="network-settings-field gate-form-row"><span className="gate-form-label">{copy("凭据引用 ID", "Credential ID")}</span><span className="gate-form-control"><Input autoComplete="off" placeholder={copy("可选", "Optional")} disabled={busy} value={defaults[`${phase}_credential_ref`] || ""} onChange={event => setDefaults({ ...defaults, [`${phase}_credential_ref`]: event.target.value || null })} /></span></label>
            </div>)}
            <details className="network-settings-full"><summary aria-label={copy("管理员 Git 主机策略", "Administrator Git host policy")}><FieldLabel label={copy("管理员 Git 主机策略", "Administrator Git host policy")} zh={zh} helpId={`${fieldId}-host-policy-help`} help={copy("精确主机/端口；内网须指定 private_cidrs，仍拒绝环回和元数据地址。", "Exact hosts/ports; internal Git requires private_cidrs. Loopback and metadata remain denied.")} /></summary><Input.TextArea rows={4} aria-label={copy("Git 主机策略 JSON", "Git host policy JSON")} aria-describedby={`${fieldId}-host-policy-help`} disabled={busy} value={hostPolicy} onChange={event => setHostPolicy(event.target.value)} /></details>
            <Button className="network-settings-full" type="primary" disabled={busy || (JSON.stringify(defaults) === JSON.stringify(settings.defaults) && hostPolicy === JSON.stringify(settings.defaults.git_hosts, null, 2))} loading={busy} onClick={() => void run(async () => { const git_hosts: unknown = JSON.parse(hostPolicy); if (!Array.isArray(git_hosts)) throw new Error(copy("策略必须是 JSON 数组", "Policy must be a JSON array")); const saved = await networkApi.saveDefaults({ ...defaults, git_hosts }, settings.revision); setSettings({ ...saved, profiles }); setDefaults(saved.defaults); setHostPolicy(JSON.stringify(saved.defaults.git_hosts, null, 2)); setResult(copy("默认配置已保存", "Defaults saved")); onSaved?.() })}>{copy("保存默认配置", "Save defaults")}</Button>
          </div>
        </Card>
      </div>
    </>}
    <FormDialog title={draft?.id ? copy("编辑代理配置", "Edit proxy profile") : copy("新增代理配置", "New proxy profile")} open={Boolean(draft)} className="max-w-3xl gate-network-profile-dialog" closeLabel={t("close")} onClose={() => void closeDraft()} dirty={Boolean(draft && JSON.stringify(draft) !== baseline.current)} pending={busy} error={draftError}
      onCloseAutoFocus={event => {
        const target = [profileTrigger.current, profileReturnScope.current, panel.current?.querySelector<HTMLElement>('[data-network-new-profile]')]
          .find(element => element?.isConnected && !element.matches(':disabled') && element.getAttribute('aria-disabled') !== 'true')
        if (target) { event.preventDefault(); target.focus() }
      }}
      footer={<><Button disabled={busy} onClick={() => void closeDraft()}>{t("cancel")}</Button><Button type="primary" loading={busy} disabled={!draft?.name.trim() || (!draft?.id && !draft?.endpoint)} onClick={() => void saveProfile()}>{t("save")}</Button></>}>
      {draft && <div className="flex flex-col gap-4">
        <label className="network-settings-field gate-form-row"><span className="gate-form-label">{copy("配置名称", "Profile name")}</span><span className="gate-form-control"><Input disabled={busy} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></span></label>
        <label className="network-settings-field gate-form-row" htmlFor={`${fieldId}-endpoint`}><FieldLabel className="gate-form-label" label={copy("代理地址", "Proxy URL")} zh={zh} helpId={`${fieldId}-endpoint-help`} help={copy("代理地址仅写入，保存后始终脱敏，不返回完整地址；编辑时留空保留原地址。地址不能包含用户名/密码。HTTP(S)/SOCKS5 支持按阶段由执行器验证；HTTP 代理不提供 Git SSH。", "The proxy endpoint is write only and remains masked after saving; its full value is not returned. Leave it blank when editing to retain the endpoint. URLs cannot contain userinfo. The executor validates HTTP(S)/SOCKS5 support per phase; HTTP proxies do not provide Git SSH.")} /><span className="gate-form-control"><Input.Password id={`${fieldId}-endpoint`} aria-label={copy("代理地址", "Proxy endpoint")} aria-describedby={`${fieldId}-endpoint-help`} autoComplete="new-password" disabled={busy} value={draft.endpoint} placeholder={draft.id ? copy("留空保留原地址", "Leave blank to retain endpoint") : "http://proxy.example.invalid:8080"} onChange={event => setDraft({ ...draft, endpoint: event.target.value })} /></span></label>
        <label className="network-settings-field gate-form-row" htmlFor={`${fieldId}-credential`}><FieldLabel className="gate-form-label" label={copy("认证凭据 ID", "Credential ID")} zh={zh} helpId={`${fieldId}-credential-help`} help={copy("凭据仅引用共享加密存储；保存后生成新版本。", "Credentials reference shared encrypted storage; saving creates a new version.")} /><span className="gate-form-control"><Input id={`${fieldId}-credential`} aria-label={copy("认证凭据 ID", "Credential ID")} aria-describedby={`${fieldId}-credential-help`} autoComplete="off" placeholder={copy("可选", "Optional")} disabled={busy} value={draft.credential_ref} onChange={event => setDraft({ ...draft, credential_ref: event.target.value })} /></span></label>
        <div className="gate-form-row"><span className="gate-form-label">{copy("启用", "Enabled")}</span><div className="gate-form-control"><Switch aria-label={copy("启用", "Enabled")} disabled={busy} checked={draft.enabled} onChange={enabled => setDraft({ ...draft, enabled })} /></div></div>
      </div>}
    </FormDialog>
    <FormDialog open={references !== null} title={copy("配置引用", "Configuration references")} className="max-w-3xl" closeLabel={t("close")} onClose={() => setReferences(null)} footer={null} onCloseAutoFocus={event => { if (referencesTrigger.current?.isConnected) { event.preventDefault(); referencesTrigger.current.focus() } }}>
      <Table size="small" rowKey={row => `${row.resource_type}:${row.resource_id}:${row.version}`} dataSource={references || []} pagination={{ pageSize: 5 }} columns={[{ title: copy("版本", "Version"), dataIndex: "version" }, { title: copy("类型", "Type"), dataIndex: "resource_type" }, { title: "ID", dataIndex: "resource_id", ellipsis: true }]} />
    </FormDialog>
    <FormDialog open={executorHelp} className="max-w-3xl" title={copy("安全网络执行器配置指引", "Safe network executor setup guide")} closeLabel={t("close")} onClose={() => setExecutorHelp(false)} footer={null} onCloseAutoFocus={event => { if (executorTrigger.current?.isConnected) { event.preventDefault(); executorTrigger.current.focus() } }}>
      <div className="flex flex-col gap-3">
        <p>{copy("以下步骤由 Gate 部署管理员在服务器上完成。保存本页的代理配置不会自动启用执行器。", "A Gate deployment administrator must complete these steps on the server. Saving proxy settings on this page does not enable the executor automatically.")}</p>
        <ol className="list-decimal pl-5 space-y-3">
          <li>{copy("确认部署环境：当前执行器仅支持 Linux Native，由专用非 root 账户运行 rootless Podman。Windows、macOS 和 Docker Core 实例需要在受支持的 Linux Native 环境中完成这些交付操作。", "Verify the deployment environment: the executor supports Linux Native with rootless Podman under a dedicated non-root account. Windows, macOS and Docker Core instances require a supported Linux Native environment for these delivery operations.")}</li>
          <li>{copy("准备隔离资源：执行器根目录与 Gate 数据、配置、项目目录分离；根目录及 workspaces 目录由 Gate 账户拥有，无符号链接，权限为 0700。workspaces 使用独立 tmpfs 挂载，启用 nodev、nosuid，总容量不超过 2 GiB。配置 cgroup v2 及已委派的 CPU、memory、pids 控制器。", "Provision isolation resources: keep the executor root separate from Gate data, configuration and project directories; the root and workspaces directories must be owned by the Gate account, have no symlinks and use mode 0700. Mount workspaces as a separate tmpfs with nodev, nosuid and a maximum capacity of 2 GiB. Configure cgroup v2 with delegated CPU, memory and pids controllers.")}</li>
          <li>{copy("准备受审镜像和 Podman：管理员安装并配置 rootless Podman，使用受审的绝对可执行路径。预加载包含 /usr/bin/python3、具备 SHA-1 碰撞检测的 /usr/bin/git 和 /usr/local/bin/node 的执行器镜像，并使用完整 @sha256 摘要固定镜像。", "Prepare reviewed image and Podman: an administrator installs and configures rootless Podman using a reviewed absolute executable path. Preload an executor image with /usr/bin/python3, /usr/bin/git with SHA-1 collision detection and /usr/local/bin/node, and pin its full @sha256 digest.")}</li>
          <li>
            <span>{copy("配置 Gate 启动环境：", "Configure the Gate startup environment:")}</span>
            <p><code className="break-all">LINGSHU_GATE_RUNTIME_ROLE=local</code></p>
            <p><code className="break-all">LINGSHU_GATE_NATIVE_EXECUTOR</code>{copy(" 设置为 JSON 对象，enabled=true，填写 root、image、podman_bin；使用代理时配置受审的 proxy_hosts。以下占位符须替换为真实的受审目录和镜像摘要。", " must be a JSON object with enabled=true, root, image and podman_bin; configure reviewed proxy_hosts when using a proxy. Replace the following placeholders with the actual reviewed directory and image digest.")}</p>
            <pre className="whitespace-pre-wrap break-all rounded bg-muted p-3 text-xs">{JSON.stringify({ enabled: true, root: "/var/lib/lingshu-gate-executor", image: "registry.example.invalid/gate-executor@sha256:<reviewed-64-hex-digest>", podman_bin: "/usr/bin/podman", proxy_hosts: [] }, null, 2)}</pre>
          </li>
          <li>{copy("重启 Gate 并等待启动隔离自检完成，然后点击“重新检查”读取最新状态。全部就绪检查通过后，再尝试 Git 拉取或代理测试；依赖安装仍须满足对应项目计划的支持条件。", "Restart Gate and wait for its startup isolation self-test to finish, then use Check again to read the latest status. Retry Git acquisition or proxy tests after all readiness checks pass; dependency installation must also satisfy the project plan's support conditions.")}</li>
        </ol>
        {Boolean(settings?.executor.missing?.length) && <details>
          <summary>{copy("查看当前阻塞项（供管理员排查）", "View current blockers (for administrator diagnosis)")}</summary>
          <ul className="mt-2 list-disc pl-5">{settings?.executor.missing?.map(reason => <li key={reason}><code className="break-all">{reason}</code></li>)}</ul>
        </details>}
      </div>
    </FormDialog>
    {confirmDialog}
  </div>
}

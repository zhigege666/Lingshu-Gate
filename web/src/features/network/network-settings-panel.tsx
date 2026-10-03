import { useContext, useEffect, useRef, useState } from "react"
import { Alert, Button, Card, Drawer, Empty, Input, Modal, Select, Switch, Table, Tag } from "antd"
import { useAuth } from "@/components/auth-gate"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { usePageRefresh } from "@/components/page-refresh"
import { networkApi, type NetworkDefaults, type NetworkProfile, type NetworkSettings } from "@/api/network"
import { networkPermission, selectionFromKey, selectionKey, selectionOptions } from "./model"
import type { TFunction } from "@/i18n"
import "./network-settings.css"

type ProfileDraft = { id?: string; name: string; endpoint: string; credential_ref: string; enabled: boolean; expected_version: number }
const blank: ProfileDraft = { name: "", endpoint: "", credential_ref: "", enabled: true, expected_version: 0 }

export function NetworkSettingsPanel({ t, onSaved, onState }: { t: TFunction; onSaved?: () => void; onState?: (state: { dirty: boolean; pending: boolean }) => void }) {
  const { user } = useAuth()
  const zh = t("uploads") === "项目上传"
  const { confirm, confirmDialog } = useConfirm(t)
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
  const baseline = useRef("")
  const requestId = useRef(0)
  const mounted = useRef(true)
  const running = useRef(false)
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
    await run(async () => {
      await networkApi.saveProfile({ name: current.name.trim(), endpoint: current.endpoint || null, credential_ref: current.credential_ref.trim() || null, enabled: current.enabled, expected_version: current.expected_version }, current.id)
      setDraft(null); setResult(zh ? "配置已保存为新版本" : "Saved as a new configuration version"); await load(true); onSaved?.()
    }, true)
  }

  const profiles = settings?.profiles || []
  const copy = (cn: string, en: string) => zh ? cn : en
  return <div className="flex flex-col gap-4" aria-busy={busy || loading}>
    {!settings && loading && <p role="status">{t("loadingData")}</p>}
    {error && <Alert type="error" showIcon title={error} action={<Button disabled={busy} onClick={() => void load(true)}>{t("retry")}</Button>} />}
    {result && <Alert type="success" showIcon title={result} closable onClose={() => setResult(null)} />}
    {settings && defaults && <>
      {!settings.executor.available && <Alert type="warning" showIcon title={copy("安全网络执行器未安装：Git 拉取、代理测试和指定网络安装暂不可执行", "Safe network executor is unavailable: Git acquisition, proxy tests and configured installation are blocked")} />}
      <div className="network-settings-grid">
        <Card title={copy("代理配置", "Proxy profiles")} extra={<Button type="primary" disabled={busy} onClick={() => edit()}>{copy("新增配置", "New profile")}</Button>}>
          <div className="network-settings-actions mb-3"><label htmlFor="network-test-target">{copy("受控测试目标", "Controlled test target")}</label><Select id="network-test-target" aria-label={copy("受控测试目标", "Controlled test target")} value={target} onChange={setTarget} options={[{ value: "github", label: "GitHub" }, { value: "npm", label: "npm registry" }, { value: "python", label: "Python index" }]} /></div>
          <Table<NetworkProfile> rowKey="id" size="small" loading={loading} scroll={{ x: 720, y: 360 }} pagination={false} dataSource={profiles} locale={{ emptyText: <Empty description={copy("直连不需要代理配置", "Direct access needs no proxy profile")} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }} columns={[
            { title: copy("名称", "Name"), dataIndex: "name", ellipsis: true },
            { title: copy("版本 / 协议", "Version / scheme"), render: (_, row) => `v${row.version} · ${row.scheme}` },
            { title: copy("状态", "State"), render: (_, row) => <Tag color={!row.enabled || !row.credential_configured ? "warning" : "success"}>{!row.enabled ? copy("已停用", "Disabled") : row.credential_configured ? copy("已配置", "Configured") : copy("凭据需更新", "Credential changed")}</Tag> },
            { title: copy("操作", "Actions"), width: 320, render: (_, row) => <div className="network-settings-actions">
              <Button size="small" disabled={busy} onClick={() => edit(row)}>{t("edit")}</Button>
              <Button size="small" disabled={busy} onClick={() => void run(async () => setReferences((await networkApi.references(row.id)).references))}>{copy("引用", "References")}</Button>
              <Button size="small" disabled={busy || !canTest || !row.enabled} onClick={() => void run(async () => { if (!(await confirm({ title: copy("从执行环境测试网络？", "Test from the execution environment?"), description: `${target} · HEAD · 5s · 4 KiB` }))) return; const tested = await networkApi.test(row, target); setResult(`${target}: ${tested.status}`) })}>{copy("测试", "Test")}</Button>
              <Button size="small" disabled={busy} onClick={() => void run(async () => { if (!(await confirm({ title: row.enabled ? copy("停用此配置？", "Disable this profile?") : copy("启用此配置？", "Enable this profile?"), description: copy("已排队任务仍固定原版本。", "Queued tasks retain their pinned version.") }))) return; await networkApi.saveProfile({ name: row.name, credential_ref: row.credential_ref, enabled: !row.enabled, expected_version: row.version }, row.id); await load(true); onSaved?.() })}>{row.enabled ? copy("停用", "Disable") : copy("启用", "Enable")}</Button>
              <Button size="small" danger disabled={busy} onClick={() => void run(async () => { const refs = await networkApi.references(row.id); if (refs.references.length) { setReferences(refs.references); throw new Error(copy("配置仍被引用，可停用但不能删除。", "Profile is referenced; disable it instead of deleting.")) } if (!(await confirm({ title: copy("删除此配置？", "Delete this profile?"), destructive: true }))) return; await networkApi.deleteProfile(row.id, row.version); await load(true); onSaved?.() })}>{t("delete")}</Button>
            </div> },
          ]} />
          <p className="mt-3 text-xs text-muted-foreground">{copy("代理地址始终脱敏。HTTP(S)/SOCKS5 支持按阶段由执行器验证；HTTP 代理不提供 Git SSH。", "Endpoints remain masked. The executor validates HTTP(S)/SOCKS5 support per phase; HTTP proxies do not provide Git SSH.")}</p>
        </Card>
        <Card title={copy("默认网络与依赖源", "Default network and dependency sources")}>
          <div className="network-settings-fields">
            {(["git", "install"] as const).map(phase => <label className="network-settings-field" key={phase}><span>{phase === "git" ? copy("Git 拉取默认", "Git acquisition default") : copy("依赖安装默认", "Dependency installation default")}</span><Select aria-label={phase === "git" ? copy("Git 拉取默认", "Git acquisition default") : copy("依赖安装默认", "Dependency installation default")} disabled={busy} value={selectionKey(defaults[phase])} options={selectionOptions(profiles, zh, false)} onChange={key => setDefaults({ ...defaults, [phase]: selectionFromKey(key) })} /></label>)}
            {(["npm", "python"] as const).map(phase => <div key={phase} className="network-settings-field network-settings-full">
              <label className="network-settings-field"><span>{phase === "npm" ? "npm registry" : "Python index"}</span><Input disabled={busy} value={phase === "npm" ? defaults.npm_registry : defaults.python_index} onChange={event => setDefaults({ ...defaults, [phase === "npm" ? "npm_registry" : "python_index"]: event.target.value })} /></label>
              <label className="network-settings-field"><span>{copy("凭据引用 ID（可选）", "Credential reference ID (optional)")}</span><Input autoComplete="off" disabled={busy} value={defaults[`${phase}_credential_ref`] || ""} onChange={event => setDefaults({ ...defaults, [`${phase}_credential_ref`]: event.target.value || null })} /></label>
            </div>)}
            <details className="network-settings-full"><summary>{copy("管理员 Git 主机策略", "Administrator Git host policy")}</summary><p className="text-xs my-2">{copy("精确主机/端口；内网须指定 private_cidrs，仍拒绝环回和元数据地址。", "Exact hosts/ports; internal Git requires private_cidrs. Loopback and metadata remain denied.")}</p><Input.TextArea rows={4} aria-label={copy("Git 主机策略 JSON", "Git host policy JSON")} disabled={busy} value={hostPolicy} onChange={event => setHostPolicy(event.target.value)} /></details>
            <Button className="network-settings-full" type="primary" disabled={busy || (JSON.stringify(defaults) === JSON.stringify(settings.defaults) && hostPolicy === JSON.stringify(settings.defaults.git_hosts, null, 2))} loading={busy} onClick={() => void run(async () => { const git_hosts: unknown = JSON.parse(hostPolicy); if (!Array.isArray(git_hosts)) throw new Error(copy("策略必须是 JSON 数组", "Policy must be a JSON array")); const saved = await networkApi.saveDefaults({ ...defaults, git_hosts }, settings.revision); setSettings({ ...saved, profiles }); setDefaults(saved.defaults); setHostPolicy(JSON.stringify(saved.defaults.git_hosts, null, 2)); setResult(copy("默认配置已保存", "Defaults saved")); onSaved?.() })}>{copy("保存默认配置", "Save defaults")}</Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">{copy("项目继承在计划时固定；失败不会静默直连，网络配置不传入运行时 MCP。", "Inheritance is pinned at planning. Failures never fall back to direct; settings are not passed to runtime MCP.")}</p>
        </Card>
      </div>
    </>}
    <Drawer title={draft?.id ? copy("编辑代理配置", "Edit proxy profile") : copy("新增代理配置", "New proxy profile")} open={Boolean(draft)} size={480} onClose={() => void closeDraft()} maskClosable={!busy} keyboard={!busy} closable={!busy} extra={<Button type="primary" loading={busy} disabled={!draft?.name.trim() || (!draft?.id && !draft?.endpoint)} onClick={() => void saveProfile()}>{t("save")}</Button>}>
      {draft && <div className="flex flex-col gap-4">
        {draftError && <Alert type="error" title={draftError} showIcon />}
        <label className="network-settings-field"><span>{copy("配置名称", "Profile name")}</span><Input disabled={busy} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
        <label className="network-settings-field"><span>{copy("代理地址（仅写入）", "Proxy endpoint (write only)")}</span><Input.Password autoComplete="new-password" disabled={busy} value={draft.endpoint} placeholder={draft.id ? copy("留空保留原地址", "Leave blank to retain endpoint") : "http://proxy.example.invalid:8080"} onChange={event => setDraft({ ...draft, endpoint: event.target.value })} /></label>
        <label className="network-settings-field"><span>{copy("认证凭据引用 ID（可选）", "Authentication credential reference ID (optional)")}</span><Input autoComplete="off" disabled={busy} value={draft.credential_ref} onChange={event => setDraft({ ...draft, credential_ref: event.target.value })} /></label>
        <label className="network-settings-actions"><Switch disabled={busy} checked={draft.enabled} onChange={enabled => setDraft({ ...draft, enabled })} /><span>{copy("启用", "Enabled")}</span></label>
        <p className="text-xs text-muted-foreground">{copy("地址不能包含用户名/密码。凭据仅引用共享加密存储；保存后生成新版本。", "URLs cannot contain userinfo. Credentials reference shared encrypted storage; saving creates a new version.")}</p>
      </div>}
    </Drawer>
    <Modal open={references !== null} title={copy("配置引用", "Configuration references")} onCancel={() => setReferences(null)} footer={<Button onClick={() => setReferences(null)}>{t("close")}</Button>}>
      <Table size="small" rowKey={row => `${row.resource_type}:${row.resource_id}:${row.version}`} dataSource={references || []} pagination={{ pageSize: 5 }} columns={[{ title: copy("版本", "Version"), dataIndex: "version" }, { title: copy("类型", "Type"), dataIndex: "resource_type" }, { title: "ID", dataIndex: "resource_id", ellipsis: true }]} />
    </Modal>
    {confirmDialog}
  </div>
}

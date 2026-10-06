import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { Alert, Button, Checkbox, Form, Input, Radio, Switch, Table, Tag, Tooltip } from "antd"
import { CopyOutlined } from "@ant-design/icons"
import { PageHeader } from "@/components/page-shell"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { usePageRefresh } from "@/components/page-refresh"
import { Toaster } from "@/components/ui/toast"
import { OAuthRequestError, oauthError, oauthRequest, type OAuthClient, type OAuthConfig } from "@/features/external-connections/oauth-api"
import { canEnableOAuth, editOAuthIssuer, showOAuthSetupSteps, signingKeyState, type OAuthConfigDraft, type SigningKeyState } from "@/features/external-connections/oauth-config-form"
import { OAuthConnectionGuide } from "@/features/external-connections/oauth-connection-guide"
import { OAuthManagementResource } from "@/features/external-connections/oauth-management-resource"
import type { Locale, TFunction } from "@/i18n"
import "@/features/external-connections/oauth.css"

type Props = { locale: Locale; t: TFunction }
type ClientDraft = { name: string; redirect_uris: string[]; scopes: string[]; resources: string[]; enabled: boolean }
const newClient = (): ClientDraft => ({ name: "", redirect_uris: [""], scopes: ["tools.read"], resources: ["business"], enabled: true })

export function BuiltinOAuthInfrastructure({ locale, t }: Props) {
  const zh = locale === "zh-CN"
  const [config, setConfig] = useState<OAuthConfig | null>(null)
  const [clients, setClients] = useState<OAuthClient[]>([])
  const [draft, setDraft] = useState<OAuthConfigDraft>({ issuer: "", resource: "", enabled: false })
  const [keys, setKeys] = useState<SigningKeyState>({ phase: "loading" })
  const [clientsState, setClientsState] = useState<"loading" | "ready" | "error">("loading")
  const automaticResource = useRef<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [managementBusy, setManagementBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const toast = useMemo(() => notice ? { message: notice, tone: "success" as const } : null, [notice])
  const dismissToast = useCallback(() => setNotice(""), [])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<OAuthClient | null>(null)
  const [clientDraft, setClientDraft] = useState<ClientDraft>(newClient)
  const [formError, setFormError] = useState("")
  const [oneTime, setOneTime] = useState<{ client: OAuthClient; client_secret: string } | null>(null)
  const [clientQuery, setClientQuery] = useState("")
  const [guideOpen, setGuideOpen] = useState(false)
  const [viewingClient, setViewingClient] = useState<OAuthClient | null>(null)
  const [idCopyError, setIdCopyError] = useState("")
  const guideTrigger = useRef<HTMLButtonElement>(null)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const [copied, setCopied] = useState(false)
  const secretClosePending = useRef(false)
  const lock = useRef(false)
  const generation = useRef(0)
  const baseline = useRef(JSON.stringify(newClient()))
  const { confirm, confirmDialog } = useConfirm(t)
  const close = useDraftCloseGuard({ dirty: JSON.stringify(clientDraft) !== baseline.current, pending: busy, locale, confirm, onClose: () => { setOpen(false); setFormError("") } })
  async function load() {
    const current = ++generation.current
    setBusy(true); setError(""); setNotice(""); setKeys({ phase: "loading" }); setClientsState("loading")
    const results = await Promise.allSettled([oauthRequest<OAuthConfig>("/v1/auth/oauth/config"), oauthRequest<{ clients: OAuthClient[] }>("/v1/auth/oauth/clients")])
    if (current !== generation.current) return
    const failures = results.filter(result => result.status === "rejected")
    if (failures.length) setError(failures.map(result => oauthError((result as PromiseRejectedResult).reason, zh)).join(" · "))
    if (results[0].status === "fulfilled") { setConfig(results[0].value); setDraft({ issuer: results[0].value.issuer, resource: results[0].value.resource, enabled: results[0].value.enabled }); automaticResource.current = null; setKeys(signingKeyState(results[0].value.signing_keys)) }
    else setKeys({ phase: "error" })
    if (results[1].status === "fulfilled") { setClients(results[1].value.clients); setClientsState("ready") }
    else setClientsState("error")
    setBusy(false)
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [])
  const configDirty = config !== null && (draft.issuer !== config.issuer || draft.resource !== config.resource || draft.enabled !== config.enabled)
  const registerExit = useContext(EditorNavigationContext)
  useEffect(() => registerExit?.({ dirty: configDirty, pending: busy || managementBusy || Boolean(oneTime) }), [registerExit, configDirty, busy, managementBusy, oneTime])
  usePageRefresh(load, busy || managementBusy || open || Boolean(oneTime) || configDirty)

  async function mutate(action: () => Promise<void>, form = false) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(""); setFormError(""); setNotice("")
    try { await action() }
    catch (cause) { (form ? setFormError : setError)(oauthError(cause, zh)) }
    finally { lock.current = false; setBusy(false) }
  }
  async function saveConfig() {
    if (!config) return
    if (draft.enabled && !config.enabled && !canEnableOAuth(keys)) { setError(zh ? "先读取并确认活动签名密钥，再启用 OAuth。" : "Read and confirm an active signing key before enabling OAuth."); return }
    if (draft.enabled && !config.enabled && !(await confirm({ title: zh ? "启用内置 OAuth？" : "Enable built-in OAuth?", description: zh ? `将为 ${draft.resource} 启用授权服务。请先登记客户端、核对公开路径和 TLS。此操作不验证 ChatGPT 连接。` : `Enable the authorization server for ${draft.resource}. Register clients and review public paths and TLS first. This does not verify the ChatGPT connection.`, confirmText: zh ? "启用" : "Enable", cancelText: t("cancel") }))) return
    if (!draft.enabled && config.enabled && !(await confirm({ title: zh ? "关闭内置 OAuth？" : "Disable built-in OAuth?", description: zh ? "现有令牌族将撤销，下一次请求被拒绝；重新启用后需要重新授权。" : "Existing token families will be revoked and their next request denied. New authorization is required after re-enabling.", confirmText: zh ? "关闭 OAuth" : "Disable OAuth", cancelText: t("cancel"), destructive: true }))) return
    await mutate(async () => { const next = await oauthRequest<OAuthConfig>("/v1/auth/oauth/config", { ...draft, expected_revision: config.revision }, "PUT"); setConfig(next); setDraft({ issuer: next.issuer, resource: next.resource, enabled: next.enabled }); automaticResource.current = null; setKeys(signingKeyState(next.signing_keys)); setNotice(zh ? "配置已保存；连接尚未验证。" : "Configuration saved; connectivity has not been verified.") })
  }
  async function refreshKeys() {
    if (!config) return
    await mutate(async () => {
      setKeys({ phase: "loading" })
      try {
        const next = await oauthRequest<OAuthConfig>("/v1/auth/oauth/config")
        // A key retry must not rebase or overwrite the current configuration draft.
        if (next.revision !== config.revision || next.issuer !== config.issuer || next.resource !== config.resource || next.enabled !== config.enabled) throw new OAuthRequestError("revision_conflict", 409)
        setKeys(signingKeyState(next.signing_keys))
      } catch (cause) { setKeys({ phase: "error" }); throw cause }
    })
  }
  async function rotateKey() {
    if (!(await confirm({ title: zh ? "生成或轮换签名密钥？" : "Generate or rotate signing key?", description: zh ? "新私钥将加密保存。旧公钥保留 10 分钟以验证已有访问令牌；不会输出私钥。" : "The new private key is encrypted at rest. Old public keys remain for 10 minutes to validate existing access tokens. Private keys are never returned.", confirmText: zh ? "生成密钥" : "Generate key", cancelText: t("cancel") }))) return
    await mutate(async () => {
      setKeys({ phase: "loading" })
      try {
        await oauthRequest<OAuthConfig>("/v1/auth/oauth/keys/rotate", {})
        const next = await oauthRequest<OAuthConfig>("/v1/auth/oauth/config")
        if (!config || next.revision !== config.revision || next.issuer !== config.issuer || next.resource !== config.resource || next.enabled !== config.enabled) throw new OAuthRequestError("revision_conflict", 409)
        setKeys(signingKeyState(next.signing_keys))
        setNotice(zh ? "签名密钥操作已完成；已重新读取服务器状态。" : "Signing key operation completed; server state was read again.")
      } catch (cause) { setKeys({ phase: "error" }); throw cause }
    })
  }
  function edit(client: OAuthClient | null = null) {
    const next = client ? { name: client.name, redirect_uris: [...client.redirect_uris], scopes: [...client.scopes], resources: [...(client.resources || ["business"])], enabled: client.enabled } : newClient()
    setNotice(""); setEditing(client); setClientDraft(next); baseline.current = JSON.stringify(next); setFormError(""); setOpen(true)
  }
  async function saveClient() {
    await mutate(async () => {
      const result = await oauthRequest<{ client: OAuthClient; client_secret?: string }>(editing ? `/v1/auth/oauth/clients/${editing.id}` : "/v1/auth/oauth/clients", editing ? { ...clientDraft, expected_revision: editing.revision } : { name: clientDraft.name, redirect_uris: clientDraft.redirect_uris, scopes: clientDraft.scopes, resources: clientDraft.resources }, editing ? "PATCH" : "POST")
      setClients(current => [result.client, ...current.filter(client => client.id !== result.client.id)]); setOpen(false)
      if (result.client_secret) { setOneTime({ client: result.client, client_secret: result.client_secret }); setCopied(false) }
      setNotice(zh ? "客户端已保存。" : "Client saved.")
    }, true)
  }
  async function clientAction(client: OAuthClient, rotate: boolean) {
    if (!(await confirm({ title: rotate ? zh ? "轮换客户端密钥？" : "Rotate client secret?" : client.enabled ? zh ? "停用客户端？" : "Disable client?" : zh ? "启用客户端？" : "Enable client?", description: `${client.name} (${client.id}) — ${rotate ? zh ? "旧密钥立即失效，已有令牌族撤销，需要重新连接。" : "The old secret stops working immediately and existing token families are revoked. Reconnect the client." : zh ? "停用时下一次请求即拒绝；重新启用不恢复已撤销的令牌族。" : "Disabling denies the next request; enabling does not restore revoked token families."}`, confirmText: rotate ? zh ? "轮换密钥" : "Rotate secret" : client.enabled ? zh ? "停用" : "Disable" : zh ? "启用" : "Enable", cancelText: t("cancel"), destructive: rotate || client.enabled }))) return
    await mutate(async () => { const result = await oauthRequest<{ client: OAuthClient; client_secret?: string }>(`/v1/auth/oauth/clients/${client.id}`, { name: client.name, redirect_uris: client.redirect_uris, scopes: client.scopes, enabled: rotate ? client.enabled : !client.enabled, expected_revision: client.revision, rotate_secret: rotate }, "PATCH"); setClients(current => current.map(item => item.id === client.id ? result.client : item)); if (result.client_secret) { setOneTime({ client: result.client, client_secret: result.client_secret }); setCopied(false) } })
  }
  function closeSavedSecret() { setOneTime(null); setCopied(false); setFormError("") }
  async function requestSecretClose() {
    if (!oneTime || secretClosePending.current) return
    secretClosePending.current = true
    try {
      if (await confirm({ title: zh ? "关闭后无法再次查看密钥" : "The secret cannot be viewed after closing", description: zh ? "请先保存到客户端的安全秘密配置中。复制到剪贴板不代表已安全保存；继续关闭后只能通过轮换获得新密钥。" : "Store it in the client's secure secret configuration first. Copying to the clipboard is not confirmation of safe storage. After closing, only rotation can provide a new secret.", confirmText: zh ? "已安全保存，关闭" : "Stored safely, close", cancelText: zh ? "保留密钥窗口" : "Keep secret open" })) closeSavedSecret()
    } finally { secretClosePending.current = false }
  }
  async function copyClientId(client: OAuthClient) {
    const current = generation.current
    setIdCopyError("")
    try { await navigator.clipboard.writeText(client.id); if (current === generation.current) setNotice(zh ? "客户端 ID 已复制。" : "Client ID copied.") }
    catch { if (current === generation.current) setIdCopyError(zh ? "复制失败；打开客户端详情后手动复制 ID。" : "Copy failed; open client details and copy the ID manually.") }
  }
  return <div className="space-y-4 oauth-infrastructure">
    <PageHeader title={zh ? "内置 OAuth 授权服务" : "Built-in OAuth authorization server"} closeLabel={t("close")} actions={<>
      <Button ref={guideTrigger} disabled={open || Boolean(oneTime)} onClick={() => setGuideOpen(true)}>{zh ? "接入指引" : "Connection guide"}</Button>
      <Button disabled={busy || managementBusy || configDirty || open || Boolean(oneTime)} onClick={() => void load()}>{t("refresh")}</Button>
      <Button type="primary" disabled={busy || Boolean(error)} onClick={() => edit()}>{zh ? "登记客户端" : "Register client"}</Button>
    </>} />
    <div className="oauth-infrastructure-status" role="status">
      <span>OAuth <Tag color={config?.enabled ? "green" : undefined}>{config ? config.enabled ? zh ? "已启用" : "Enabled" : zh ? "已关闭" : "Disabled" : zh ? "状态未知" : "Unknown"}</Tag></span>
      <span>{zh ? "签名密钥" : "Signing keys"} <Tag color={keys.phase !== "ready" || !keys.count ? "orange" : undefined}>{keys.phase === "ready" ? zh ? `${keys.count} 个活动密钥` : `${keys.count} active` : keys.phase === "loading" ? zh ? "读取中" : "Loading" : zh ? "状态未知" : "Unknown"}</Tag></span>
      <span>{clientsState === "ready" ? zh ? `客户端 ${clients.length}` : `${clients.length} clients` : clientsState === "loading" ? zh ? "客户端读取中" : "Loading clients" : zh ? "客户端读取失败" : "Clients unavailable"}</span>
      <span className="oauth-muted">{zh ? "外部连接需单独验收" : "Verify external connectivity separately"}</span>
    </div>
    {showOAuthSetupSteps(config, keys, clientsState === "ready", clients) && <ol className="oauth-setup-steps" aria-label={zh ? "配置前置条件" : "Setup prerequisites"}>
      <li><strong>{zh ? "1. 保存地址" : "1. Save URLs"}</strong><span>{config?.issuer && config.resource ? zh ? "已保存" : "Saved" : busy ? zh ? "读取中" : "Loading" : zh ? "待保存" : "Save needed"}</span></li>
      <li><strong>{zh ? "2. 签名密钥" : "2. Signing key"}</strong><span>{keys.phase === "loading" ? zh ? "读取中" : "Loading" : keys.phase === "error" ? zh ? "未知，请重试" : "Unknown; retry" : keys.count > 0 ? zh ? "已就绪" : "Ready" : zh ? "待生成" : "Generate needed"}</span></li>
      <li><strong>{zh ? "3. 登记客户端" : "3. Register client"}</strong><span>{clientsState !== "ready" ? zh ? "尚未读取" : "Not read" : clients.some(client => client.enabled) ? zh ? "已就绪" : "Ready" : zh ? "待登记" : "Register needed"}</span></li>
      <li><strong>{zh ? "4. 启用" : "4. Enable"}</strong><span>{config?.enabled ? zh ? "已启用" : "Enabled" : zh ? "待启用" : "Enable needed"}</span></li>
    </ol>}
    {error && <Alert type="error" showIcon title={error} action={<Button disabled={busy || configDirty} onClick={() => void load()}>{t("retry")}</Button>} />}
    <div className="oauth-admin-layout">
      <section className="oauth-admin-panel" aria-label={zh ? "连接配置" : "Connection configuration"}>
        <h2>{zh ? "连接配置" : "Connection configuration"}</h2>
        <Form layout="horizontal" className="oauth-inline-form oauth-config-form" onFinish={() => void saveConfig()}>
          <Form.Item label={zh ? "签发地址" : "Issuer"} htmlFor="oauth-issuer"><Input id="oauth-issuer" placeholder="https://gate.example.test" required type="url" maxLength={2048} disabled={busy || Boolean(config?.enabled)} value={draft.issuer} onChange={event => { const next = editOAuthIssuer(draft, event.target.value, automaticResource.current); automaticResource.current = next.automaticResource; setDraft(next.draft) }} /></Form.Item>
          <Form.Item label={zh ? "MCP 地址" : "MCP resource"} htmlFor="oauth-resource"><Input id="oauth-resource" placeholder="https://gate.example.test/mcp" required type="url" maxLength={2048} disabled={busy || Boolean(config?.enabled)} value={draft.resource} onChange={event => { automaticResource.current = null; setDraft(current => ({ ...current, resource: event.target.value })) }} /></Form.Item>
          <Form.Item label={zh ? "启用 OAuth" : "Enable OAuth"} extra={<div id="oauth-enable-help">{keys.phase === "loading" ? zh ? "正在读取密钥状态；确认前不能启用。" : "Reading key status; enablement awaits confirmation." : keys.phase === "error" ? <>{zh ? "密钥状态未知，不能新启用；已启用时仍可明确关闭。" : "Key status is unknown; new enablement is blocked. An enabled service can still be disabled."} <Button size="small" disabled={busy || !config} onClick={() => void refreshKeys()}>{zh ? "重试密钥状态" : "Retry key status"}</Button></> : !canEnableOAuth(keys) ? <>{zh ? "先保存地址，再生成签名密钥，才能启用。" : "Save URLs, then generate a signing key before enabling."} <Button size="small" disabled={busy || !config || configDirty} onClick={() => { const button = document.getElementById("oauth-generate-key"); button?.scrollIntoView({ block: "nearest" }); button?.focus() }}>{zh ? "前往生成密钥" : "Go to generate key"}</Button></> : zh ? "启用需保存并确认。" : "Save and confirm enablement."}</div>}><Switch aria-label={zh ? "启用内置 OAuth" : "Enable built-in OAuth"} aria-describedby="oauth-enable-help" checked={draft.enabled} disabled={busy || !config || (!config.enabled && !draft.enabled && !canEnableOAuth(keys))} onChange={value => setDraft(current => ({ ...current, enabled: value }))} /></Form.Item>
          <div className="oauth-actions oauth-config-actions"><Button disabled={busy || !config || !configDirty} onClick={() => { if (config) { automaticResource.current = null; setDraft({ issuer: config.issuer, resource: config.resource, enabled: config.enabled }) } }}>{zh ? "放弃配置修改" : "Discard configuration edits"}</Button><Button type="primary" htmlType="submit" aria-label={t("save")} aria-busy={busy} loading={busy} disabled={!config || !configDirty}>{t("save")}</Button></div>
        </Form>
        <div className="oauth-signing-controls"><span role="status">{keys.phase === "ready" ? zh ? `当前有 ${keys.count} 个活动签名密钥。` : `${keys.count} active signing keys.` : keys.phase === "loading" ? zh ? "正在读取签名密钥状态…" : "Reading signing key status…" : zh ? "密钥状态读取失败；请重试读取，勿重复生成。" : "Key read failed; retry the read before repeating generation."}</span><Button id="oauth-generate-key" disabled={busy || !config || configDirty} onClick={() => void rotateKey()}>{zh ? "生成 / 轮换签名密钥" : "Generate / rotate signing key"}</Button></div>
      </section>
      <section className="oauth-admin-panel" aria-label={zh ? "静态客户端" : "Static clients"}>
        <h2>{zh ? "静态客户端" : "Static clients"}</h2>
        <Input className="oauth-client-search" aria-label={zh ? "搜索客户端" : "Search clients"} placeholder={zh ? "搜索客户端名称或 ID" : "Search client name or ID"} allowClear value={clientQuery} onChange={event => setClientQuery(event.target.value)} />
        {idCopyError && !viewingClient && <Alert type="error" title={idCopyError} />}
        <Table<OAuthClient> className="oauth-client-table" rowKey="id" size="small" tableLayout="fixed" loading={clientsState === "loading"} scroll={{ x: 640, y: "clamp(160px, calc(100dvh - 680px), 460px)" }} dataSource={clients.filter(client => `${client.name} ${client.id}`.toLowerCase().includes(clientQuery.toLowerCase()))} pagination={{ pageSize: 25, showSizeChanger: false, showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}` }} locale={{ emptyText: clientsState === "error" ? zh ? "读取失败，请重试。" : "Load failed; retry." : clientsState === "loading" ? zh ? "正在读取客户端…" : "Loading clients…" : clients.length === 0 ? zh ? "尚未登记客户端。" : "No clients registered." : <div><p>{zh ? "没有匹配的客户端。" : "No matching clients."}</p><Button disabled={busy} onClick={() => setClientQuery("")}>{zh ? "清除筛选" : "Clear filter"}</Button></div> }} columns={[
          { title: zh ? "客户端" : "Client", dataIndex: "name", ellipsis: true, render: (_, client) => <Button className="oauth-client-name" type="link" size="small" disabled={busy} onClick={() => edit(client)} title={client.name}>{client.name}</Button> },
          { title: "Client ID", width: 180, render: (_, client) => <div className="oauth-client-id"><span title={client.id}>{client.id.length > 20 ? `${client.id.slice(0, 6)}…${client.id.slice(-6)}` : client.id}</span><Tooltip trigger={["hover", "focus"]} title={client.id}><Button type="text" size="small" aria-label={`${zh ? "复制客户端 ID" : "Copy client ID"} ${client.id}`} icon={<CopyOutlined aria-hidden />} onClick={() => void copyClientId(client)} /></Tooltip></div> },
          { title: zh ? "状态" : "State", width: 80, render: (_, client) => <Tag>{client.enabled ? zh ? "可用" : "Enabled" : zh ? "停用" : "Disabled"}</Tag> },
          { title: t("actions"), width: 270, render: (_, client) => <div className="oauth-actions"><Button size="small" disabled={busy} onClick={event => { detailTrigger.current = event.currentTarget; setViewingClient(client) }}>{zh ? "详情" : "Details"}</Button><Button size="small" disabled={busy} onClick={() => void clientAction(client, true)}>{zh ? "轮换密钥" : "Rotate secret"}</Button><Button size="small" danger={client.enabled} disabled={busy} onClick={() => void clientAction(client, false)}>{client.enabled ? zh ? "停用" : "Disable" : zh ? "启用" : "Enable"}</Button></div> },
        ]} />
      </section>
    </div>
    <OAuthConnectionGuide open={guideOpen} onClose={() => setGuideOpen(false)} config={config} zh={zh} trigger={guideTrigger} />
    <FormDialog open={Boolean(viewingClient)} error={idCopyError} title={zh ? "客户端详情" : "Client details"} closeLabel={t("close")} onClose={() => setViewingClient(null)} className="oauth-client-dialog" onCloseAutoFocus={event => { if (detailTrigger.current?.isConnected) { event.preventDefault(); detailTrigger.current.focus({ preventScroll: true }) } }} footer={<Button onClick={() => setViewingClient(null)}>{t("close")}</Button>}>
      {viewingClient && <dl className="oauth-identity-fields"><div><dt>{zh ? "客户端" : "Client"}</dt><dd>{viewingClient.name}</dd></div><div><dt>Client ID</dt><dd><Input readOnly aria-label="Client ID" value={viewingClient.id} /><Button onClick={() => void copyClientId(viewingClient)}>{zh ? "复制 ID" : "Copy ID"}</Button></dd></div><div><dt>{zh ? "允许范围" : "Allowed scopes"}</dt><dd>{viewingClient.scopes.join(" · ")}</dd></div><div><dt>{zh ? "允许资源" : "Resources"}</dt><dd>{(viewingClient.resources || ["business"]).join(" · ")}</dd></div><div><dt>{zh ? "HTTPS 回调" : "HTTPS callbacks"}</dt><dd>{viewingClient.redirect_uris.map(uri => <p key={uri}>{uri}</p>)}</dd></div></dl>}
    </FormDialog>
    <OAuthManagementResource businessReady={Boolean(config?.enabled)} keysReady={canEnableOAuth(keys)} zh={zh} t={t} onNotice={setNotice} onPendingChange={setManagementBusy} />
    <FormDialog open={open} className="oauth-client-dialog" title={editing ? zh ? "编辑客户端" : "Edit client" : zh ? "登记客户端" : "Register client"} closeLabel={t("close")} onClose={() => void close()} dirty={JSON.stringify(clientDraft) !== baseline.current} pending={busy} error={formError} footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" htmlType="submit" form="oauth-client-form" loading={busy}>{t("save")}</Button></>}>
      <Form id="oauth-client-form" className="oauth-inline-form" layout="horizontal" onFinish={() => void saveClient()}>
        <Form.Item label={zh ? "客户端名称" : "Client name"} htmlFor="oauth-client-name"><Input id="oauth-client-name" required maxLength={100} disabled={busy} value={clientDraft.name} onChange={event => setClientDraft(current => ({ ...current, name: event.target.value }))} /></Form.Item>
        <Form.Item label={zh ? "HTTPS 回调" : "HTTPS callbacks"} htmlFor="oauth-client-redirect-0">
          {clientDraft.redirect_uris.map((uri, index) => <div key={index} className="oauth-redirect-row"><Input id={`oauth-client-redirect-${index}`} aria-label={zh ? `回调地址 ${index + 1}` : `Redirect URI ${index + 1}`} required type="url" maxLength={2048} value={uri} disabled={busy} onChange={event => setClientDraft(current => ({ ...current, redirect_uris: current.redirect_uris.map((item, i) => i === index ? event.target.value : item) }))} /><Button aria-label={zh ? `删除回调 ${index + 1}` : `Remove redirect ${index + 1}`} disabled={busy || clientDraft.redirect_uris.length === 1} onClick={() => setClientDraft(current => ({ ...current, redirect_uris: current.redirect_uris.filter((_, i) => i !== index) }))}>{zh ? "删除" : "Remove"}</Button></div>)}
          <Button disabled={busy || clientDraft.redirect_uris.length >= 10} onClick={() => setClientDraft(current => ({ ...current, redirect_uris: [...current.redirect_uris, ""] }))}>{zh ? "添加回调" : "Add redirect"}</Button>
        </Form.Item>
        <Form.Item label={zh ? "允许的资源" : "Allowed resources"} extra={zh ? "管理资源必须请求 operations.manage，并重新同意管理员工具与精确目标。修改客户端不会升级已有业务授权或令牌族。" : "Management requires operations.manage and fresh consent for administrator tools and exact targets. Client edits do not upgrade existing business grants or token families."}>
          <Radio.Group aria-label={zh ? "允许的资源" : "Allowed resources"} disabled={busy} value={clientDraft.resources.length === 2 ? "both" : clientDraft.resources[0]} options={[{ value: "business", label: zh ? "业务 /mcp" : "Business /mcp" }, { value: "management", label: zh ? "管理 /mcp/manage" : "Management /mcp/manage" }, { value: "both", label: zh ? "两个资源" : "Both resources" }]} onChange={event => { const resources = event.target.value === "both" ? ["business", "management"] : [String(event.target.value)]; setClientDraft(current => { const scopes = current.scopes.filter(scope => scope === "tools.invoke" || (scope === "tools.read" && resources.includes("business"))); if (resources.includes("management")) scopes.push("operations.manage"); if (!scopes.length) scopes.push("tools.read"); return { ...current, resources, scopes } }) }} />
        </Form.Item>
        <Form.Item label={zh ? "允许的 OAuth 范围" : "Allowed OAuth scopes"}>
          <Checkbox.Group disabled={busy} value={clientDraft.scopes} options={[...(clientDraft.resources.includes("business") ? [{ value: "tools.read", label: zh ? "只读工具 (tools.read)" : "Read tools (tools.read)" }] : []), ...(clientDraft.resources.includes("management") ? [{ value: "operations.manage", label: zh ? "管理权限 (operations.manage)" : "Management (operations.manage)", disabled: true }] : []), { value: "tools.invoke", label: zh ? "写入工具 (tools.invoke)" : "Write tools (tools.invoke)" }]} onChange={values => setClientDraft(current => ({ ...current, scopes: values.map(String) }))} />
        </Form.Item>
        {editing && <Form.Item label={zh ? "客户端可用" : "Client enabled"}><Switch aria-label={zh ? "客户端可用" : "Client enabled"} disabled={busy} checked={clientDraft.enabled} onChange={enabled => setClientDraft(current => ({ ...current, enabled }))} /></Form.Item>}
      </Form>
    </FormDialog>
    <FormDialog open={Boolean(oneTime)} className="oauth-client-dialog oauth-secret-dialog" title={zh ? "仅展示一次的客户端密钥" : "One-time client secret"} closeLabel={t("close")} onClose={() => void requestSecretClose()} dirty={true} pending={false} error={formError} footer={<Button type="primary" onClick={closeSavedSecret}>{zh ? "已保存，关闭" : "Saved, close"}</Button>}>
      {oneTime && <div className="space-y-4"><Alert type="warning" title={zh ? "关闭后无法再次查看。请保存到客户端的秘密配置中。" : "This secret cannot be viewed after closing. Store it in the client's secret configuration."} description={zh ? "复制到剪贴板不代表已安全保存。" : "Copying to the clipboard is not confirmation of safe storage."} /><label className="oauth-secret-field">Client ID<Input readOnly value={oneTime.client.id} /></label><label className="oauth-secret-field">Client Secret<Input.Password readOnly autoComplete="off" value={oneTime.client_secret} /></label><Button onClick={async () => { try { await navigator.clipboard.writeText(oneTime.client_secret); setCopied(true) } catch { setCopied(false); setFormError(zh ? "复制失败，请手工保存密钥。" : "Copy failed; save the secret manually.") } }}>{copied ? zh ? "已复制" : "Copied" : zh ? "复制密钥" : "Copy secret"}</Button></div>}
    </FormDialog>{confirmDialog}<Toaster toast={toast} onClose={dismissToast} closeLabel={t("close")} />
  </div>
}

export { BuiltinOAuthGrants } from "./oauth-grants"

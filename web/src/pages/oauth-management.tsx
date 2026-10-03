import { useContext, useEffect, useRef, useState } from "react"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { Alert, Button, Checkbox, Form, Input, InputNumber, Switch, Table, Tag } from "antd"
import { PageHeader } from "@/components/page-shell"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { usePageRefresh } from "@/components/page-refresh"
import { OAuthToolPicker } from "@/features/external-connections/oauth-tool-picker"
import { oauthError, oauthRequest, type OAuthClient, type OAuthConfig, type OAuthGrant } from "@/features/external-connections/oauth-api"
import type { Locale, TFunction } from "@/i18n"
import "@/features/external-connections/oauth.css"

type Props = { locale: Locale; t: TFunction }
type ClientDraft = { name: string; redirect_uris: string[]; scopes: string[]; enabled: boolean }
const newClient = (): ClientDraft => ({ name: "", redirect_uris: [""], scopes: ["tools.read"], enabled: true })
function localTime(seconds: number, locale: Locale) { return new Date(seconds * 1000).toLocaleString(locale) }

export function BuiltinOAuthInfrastructure({ locale, t }: Props) {
  const zh = locale === "zh-CN"
  const [config, setConfig] = useState<OAuthConfig | null>(null)
  const [clients, setClients] = useState<OAuthClient[]>([])
  const [draft, setDraft] = useState({ issuer: "", resource: "", enabled: false })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<OAuthClient | null>(null)
  const [clientDraft, setClientDraft] = useState<ClientDraft>(newClient)
  const [formError, setFormError] = useState("")
  const [oneTime, setOneTime] = useState<{ client: OAuthClient; client_secret: string } | null>(null)
  const [clientQuery, setClientQuery] = useState("")
  const [copied, setCopied] = useState(false)
  const secretClosePending = useRef(false)
  const lock = useRef(false)
  const generation = useRef(0)
  const baseline = useRef(JSON.stringify(newClient()))
  const { confirm, confirmDialog } = useConfirm(t)
  const close = useDraftCloseGuard({ dirty: JSON.stringify(clientDraft) !== baseline.current, pending: busy, locale, confirm, onClose: () => { setOpen(false); setFormError("") } })
  async function load() {
    const current = ++generation.current
    setBusy(true); setError("")
    const results = await Promise.allSettled([oauthRequest<OAuthConfig>("/v1/auth/oauth/config"), oauthRequest<{ clients: OAuthClient[] }>("/v1/auth/oauth/clients")])
    if (current !== generation.current) return
    const failures = results.filter(result => result.status === "rejected")
    if (failures.length) setError(failures.map(result => oauthError((result as PromiseRejectedResult).reason, zh)).join(" · "))
    if (results[0].status === "fulfilled") { setConfig(results[0].value); setDraft({ issuer: results[0].value.issuer, resource: results[0].value.resource, enabled: results[0].value.enabled }) }
    if (results[1].status === "fulfilled") setClients(results[1].value.clients)
    setBusy(false)
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [])
  const configDirty = config !== null && (draft.issuer !== config.issuer || draft.resource !== config.resource || draft.enabled !== config.enabled)
  const registerExit = useContext(EditorNavigationContext)
  useEffect(() => registerExit?.({ dirty: configDirty, pending: busy || Boolean(oneTime) }), [registerExit, configDirty, busy, oneTime])
  usePageRefresh(load, busy || open || Boolean(oneTime) || configDirty)

  async function mutate(action: () => Promise<void>, form = false) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(""); setFormError(""); setNotice("")
    try { await action() }
    catch (cause) { (form ? setFormError : setError)(oauthError(cause, zh)) }
    finally { lock.current = false; setBusy(false) }
  }
  async function saveConfig() {
    if (!config) return
    if (draft.enabled && !config.enabled && !(await confirm({ title: zh ? "启用内置 OAuth？" : "Enable built-in OAuth?", description: zh ? `将为 ${draft.resource} 启用授权服务。请先登记客户端、核对公开路径和 TLS。此操作不验证 ChatGPT 连接。` : `Enable the authorization server for ${draft.resource}. Register clients and review public paths and TLS first. This does not verify the ChatGPT connection.`, confirmText: zh ? "启用" : "Enable", cancelText: t("cancel") }))) return
    if (!draft.enabled && config.enabled && !(await confirm({ title: zh ? "关闭内置 OAuth？" : "Disable built-in OAuth?", description: zh ? "现有令牌族将撤销，下一次请求被拒绝；重新启用后需要重新授权。" : "Existing token families will be revoked and their next request denied. New authorization is required after re-enabling.", confirmText: zh ? "关闭 OAuth" : "Disable OAuth", cancelText: t("cancel"), destructive: true }))) return
    await mutate(async () => { const next = await oauthRequest<OAuthConfig>("/v1/auth/oauth/config", { ...draft, expected_revision: config.revision }, "PUT"); setConfig(next); setNotice(zh ? "配置已保存；连接尚未验证。" : "Configuration saved; connectivity has not been verified.") })
  }
  async function rotateKey() {
    if (!(await confirm({ title: zh ? "生成或轮换签名密钥？" : "Generate or rotate signing key?", description: zh ? "新私钥将加密保存。旧公钥保留 10 分钟以验证已有访问令牌；不会输出私钥。" : "The new private key is encrypted at rest. Old public keys remain for 10 minutes to validate existing access tokens. Private keys are never returned.", confirmText: zh ? "生成密钥" : "Generate key", cancelText: t("cancel") }))) return
    await mutate(async () => { setConfig(await oauthRequest<OAuthConfig>("/v1/auth/oauth/keys/rotate", {})); setNotice(zh ? "签名密钥已保存。" : "Signing key saved.") })
  }
  function edit(client: OAuthClient | null = null) {
    const next = client ? { name: client.name, redirect_uris: [...client.redirect_uris], scopes: [...client.scopes], enabled: client.enabled } : newClient()
    setEditing(client); setClientDraft(next); baseline.current = JSON.stringify(next); setFormError(""); setOpen(true)
  }
  async function saveClient() {
    await mutate(async () => {
      const result = await oauthRequest<{ client: OAuthClient; client_secret?: string }>(editing ? `/v1/auth/oauth/clients/${editing.id}` : "/v1/auth/oauth/clients", editing ? { ...clientDraft, expected_revision: editing.revision } : { name: clientDraft.name, redirect_uris: clientDraft.redirect_uris, scopes: clientDraft.scopes }, editing ? "PATCH" : "POST")
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
  return <div className="space-y-4">
    <PageHeader title={zh ? "内置 OAuth 授权服务" : "Built-in OAuth authorization server"} closeLabel={t("close")} actions={<Button disabled={busy || configDirty || open || Boolean(oneTime)} onClick={() => void load()}>{t("refresh")}</Button>} />
    <Alert type="info" showIcon title={zh ? "使用现有 Gate 用户，默认关闭" : "Uses existing Gate users; disabled by default"} description={zh ? "依次保存固定 HTTPS 地址、生成加密签名密钥、登记客户端并启用。管理员不代用户同意授权；不需要手工绑定 subject。" : "Save fixed HTTPS URLs, generate an encrypted signing key, register the client, then enable. Administrators cannot consent for users; no manual subject binding is needed."} />
    {error && <Alert type="error" showIcon title={error} action={<Button disabled={busy || configDirty} onClick={() => void load()}>{t("retry")}</Button>} />}{notice && <Alert type="success" title={notice} />}
    <div className="oauth-admin-layout"><section className="oauth-admin-panel"><h2>{zh ? "1. 可信地址与签名" : "1. Trusted URLs and signing"}</h2><Form layout="vertical" onFinish={() => void saveConfig()}>
      <Form.Item label={zh ? "授权服务 HTTPS 域名（Issuer）" : "Authorization server HTTPS origin (issuer)"} htmlFor="oauth-issuer" extra={zh ? "例如 https://gate.example.com，无路径或末尾斜线。" : "For example https://gate.example.com, with no path or trailing slash."}><Input id="oauth-issuer" required type="url" maxLength={2048} disabled={busy || Boolean(config?.enabled)} value={draft.issuer} onChange={event => setDraft(current => ({ ...current, issuer: event.target.value }))} /></Form.Item>
      <Form.Item label={zh ? "固定 MCP 资源 URL" : "Fixed MCP resource URL"} htmlFor="oauth-resource"><Input id="oauth-resource" required type="url" maxLength={2048} disabled={busy || Boolean(config?.enabled)} value={draft.resource} onChange={event => setDraft(current => ({ ...current, resource: event.target.value }))} /></Form.Item>
      <Form.Item label={zh ? "启用内置 OAuth" : "Enable built-in OAuth"}><Switch aria-label={zh ? "启用内置 OAuth" : "Enable built-in OAuth"} checked={draft.enabled} disabled={busy || !config} onChange={value => setDraft(current => ({ ...current, enabled: value }))} /></Form.Item><div className="oauth-actions"><Button disabled={busy || !config || !configDirty} onClick={() => { if (config) setDraft({ issuer: config.issuer, resource: config.resource, enabled: config.enabled }) }}>{zh ? "放弃配置修改" : "Discard configuration edits"}</Button><Button type="primary" htmlType="submit" loading={busy} disabled={!config || !configDirty}>{t("save")}</Button></div>
    </Form><dl className="oauth-endpoints">{config && [["Issuer", config.issuer], [zh ? "受保护资源" : "Protected resource", config.resource], ["Discovery", config.metadata_url], ["Authorize", config.authorization_endpoint], ["Token", config.token_endpoint], ["JWKS", config.jwks_uri]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "—"}</dd></div>)}</dl><p className="text-sm">{zh ? `当前有 ${config?.signing_keys.filter(key => key.active).length ?? 0} 个活动签名密钥。` : `${config?.signing_keys.filter(key => key.active).length ?? 0} active signing keys.`}</p><Button disabled={busy || !config || configDirty} onClick={() => void rotateKey()}>{zh ? "生成 / 轮换签名密钥" : "Generate / rotate signing key"}</Button></section>
      <section className="oauth-admin-panel"><div className="oauth-actions"><h2>{zh ? "2. 静态客户端" : "2. Static clients"}</h2><Button type="primary" disabled={busy || Boolean(error)} onClick={() => edit()}>{zh ? "登记客户端" : "Register client"}</Button></div><Input aria-label={zh ? "搜索客户端" : "Search clients"} placeholder={zh ? "搜索客户端名称或 ID" : "Search client name or ID"} allowClear value={clientQuery} onChange={event => setClientQuery(event.target.value)} /><Table<OAuthClient> rowKey="id" size="small" scroll={{ x: 660 }} dataSource={clients.filter(client => `${client.name} ${client.id}`.toLowerCase().includes(clientQuery.toLowerCase()))} pagination={{ pageSize: 10, showSizeChanger: false }} locale={{ emptyText: error ? zh ? "读取失败，请重试。" : "Load failed; retry." : clients.length === 0 ? zh ? "尚未登记客户端。" : "No clients registered." : <div><p>{zh ? "没有匹配的客户端。" : "No matching clients."}</p><Button disabled={busy} onClick={() => setClientQuery("")}>{zh ? "清除筛选" : "Clear filter"}</Button></div> }} columns={[{ title: zh ? "客户端" : "Client", dataIndex: "name", render: (_, client) => <><Button type="link" disabled={busy} onClick={() => edit(client)}>{client.name}</Button><div className="oauth-muted oauth-wrap">{client.id}</div><div>{client.scopes.join(" · ")}</div></> }, { title: zh ? "状态" : "State", width: 90, render: (_, client) => <Tag>{client.enabled ? zh ? "可用" : "Enabled" : zh ? "停用" : "Disabled"}</Tag> }, { title: t("actions"), width: 230, render: (_, client) => <div className="flex flex-wrap gap-2"><Button size="small" disabled={busy} onClick={() => void clientAction(client, true)}>{zh ? "轮换密钥" : "Rotate secret"}</Button><Button size="small" danger={client.enabled} disabled={busy} onClick={() => void clientAction(client, false)}>{client.enabled ? zh ? "停用" : "Disable" : zh ? "启用" : "Enable"}</Button></div> }]} /><p className="text-sm">{zh ? "从 ChatGPT 连接管理页复制精确回调；在支持预定义客户端的配置入口填写 Client ID 和密钥。无需 CIMD 或匿名注册。" : "Copy the exact callback from ChatGPT connection settings; enter Client ID and secret in the setup that supports predefined clients. CIMD and anonymous registration are not used."}</p><a href="https://github.com/zhigege666/Lingshu-Gate/blob/main/docs/builtin-oauth.md" target="_blank" rel="noreferrer">{zh ? "内置 OAuth 配置说明" : "Built-in OAuth setup"}</a><h2 className="mt-5">{zh ? "3. 公开路径与连接检查" : "3. Public paths and connection checks"}</h2><p>{zh ? "代理仅放行 /mcp、OAuth 发现路径及 /oauth/ 下的授权页面、资源和协议端点。Console 与 /v1 继续只供内部管理使用。" : "Allow only /mcp, OAuth discovery and the authorization pages, assets and protocol endpoints under /oauth/. Keep Console and /v1 private."}</p><p className="text-sm">{zh ? "连接时每个用户用自己的 Gate 账号登录并选择工具。请另行验证只读调用、拒绝范围、到期和撤权。本页保存不是 OAuth 验收。" : "Each user signs in with their Gate account and selects tools. Separately verify read calls, denied scope, expiry and revocation. Saving this page is not OAuth acceptance."}</p></section>
    </div>
    <FormDialog open={open} title={editing ? zh ? "编辑客户端" : "Edit client" : zh ? "登记客户端" : "Register client"} closeLabel={t("close")} onClose={() => void close()} dirty={JSON.stringify(clientDraft) !== baseline.current} pending={busy} error={formError} footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" htmlType="submit" form="oauth-client-form" loading={busy}>{t("save")}</Button></>}>
      <form id="oauth-client-form" className="space-y-4" onSubmit={event => { event.preventDefault(); void saveClient() }}><label className="block">{zh ? "客户端名称" : "Client name"}<Input required maxLength={100} disabled={busy} value={clientDraft.name} onChange={event => setClientDraft(current => ({ ...current, name: event.target.value }))} /></label><fieldset><legend>{zh ? "精确 HTTPS 回调地址" : "Exact HTTPS redirect URIs"}</legend>{clientDraft.redirect_uris.map((uri, index) => <div key={index} className="oauth-redirect-row"><Input aria-label={zh ? `回调地址 ${index + 1}` : `Redirect URI ${index + 1}`} required type="url" maxLength={2048} value={uri} disabled={busy} onChange={event => setClientDraft(current => ({ ...current, redirect_uris: current.redirect_uris.map((item, i) => i === index ? event.target.value : item) }))} /><Button aria-label={zh ? `删除回调 ${index + 1}` : `Remove redirect ${index + 1}`} disabled={busy || clientDraft.redirect_uris.length === 1} onClick={() => setClientDraft(current => ({ ...current, redirect_uris: current.redirect_uris.filter((_, i) => i !== index) }))}>{zh ? "删除" : "Remove"}</Button></div>)}<Button disabled={busy || clientDraft.redirect_uris.length >= 10} onClick={() => setClientDraft(current => ({ ...current, redirect_uris: [...current.redirect_uris, ""] }))}>{zh ? "添加回调" : "Add redirect"}</Button></fieldset><fieldset><legend>{zh ? "允许的 OAuth 范围" : "Allowed OAuth scopes"}</legend><Checkbox.Group disabled={busy} value={clientDraft.scopes} options={[{ value: "tools.read", label: zh ? "只读工具 (tools.read)" : "Read tools (tools.read)" }, { value: "tools.invoke", label: zh ? "写入工具 (tools.invoke)" : "Write tools (tools.invoke)" }]} onChange={values => setClientDraft(current => ({ ...current, scopes: values.map(String) }))} /></fieldset>{editing && <label className="flex items-center gap-2"><Switch disabled={busy} checked={clientDraft.enabled} onChange={enabled => setClientDraft(current => ({ ...current, enabled }))} />{zh ? "客户端可用" : "Client enabled"}</label>}</form>
    </FormDialog>
    <FormDialog open={Boolean(oneTime)} title={zh ? "仅展示一次的客户端密钥" : "One-time client secret"} closeLabel={t("close")} onClose={() => void requestSecretClose()} dirty={true} pending={false} error={formError} footer={<Button type="primary" onClick={closeSavedSecret}>{zh ? "已保存，关闭" : "Saved, close"}</Button>}>
      {oneTime && <div className="space-y-4"><Alert type="warning" title={zh ? "关闭后无法再次查看。请保存到客户端的秘密配置中。" : "This secret cannot be viewed after closing. Store it in the client's secret configuration."} description={zh ? "复制到剪贴板不代表已安全保存。" : "Copying to the clipboard is not confirmation of safe storage."} /><label className="block">Client ID<Input readOnly value={oneTime.client.id} /></label><label className="block">Client Secret<Input.Password readOnly autoComplete="off" value={oneTime.client_secret} /></label><Button onClick={async () => { try { await navigator.clipboard.writeText(oneTime.client_secret); setCopied(true) } catch { setCopied(false); setFormError(zh ? "复制失败，请手工保存密钥。" : "Copy failed; save the secret manually.") } }}>{copied ? zh ? "已复制" : "Copied" : zh ? "复制密钥" : "Copy secret"}</Button></div>}
    </FormDialog>{confirmDialog}
  </div>
}

export function BuiltinOAuthGrants({ locale, t }: Props) {
  const zh = locale === "zh-CN"
  const [grants, setGrants] = useState<OAuthGrant[]>([])
  const [query, setQuery] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const [editing, setEditing] = useState<OAuthGrant | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [expiry, setExpiry] = useState(0)
  const [rate, setRate] = useState(30)
  const [concurrency, setConcurrency] = useState(1)
  const lock = useRef(false)
  const version = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const dirty = Boolean(editing && (JSON.stringify(selected) !== JSON.stringify(editing.tools.map(tool => tool.id)) || expiry !== editing.expires_at || rate !== editing.rate_per_minute || concurrency !== editing.concurrency))
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: () => setEditing(null) })
  async function load() {
    const current = ++version.current
    setBusy(true); setError("")
    try { const result = await oauthRequest<{ grants: OAuthGrant[] }>("/v1/auth/oauth/grants"); if (current === version.current) setGrants(result.grants) }
    catch (cause) { if (current === version.current) setError(oauthError(cause, zh)) }
    finally { if (current === version.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { version.current++ } }, [])
  usePageRefresh(load, busy || Boolean(editing))
  function edit(grant: OAuthGrant) { setEditing(grant); setSelected(grant.tools.map(tool => tool.id)); setExpiry(grant.expires_at); setRate(grant.rate_per_minute); setConcurrency(grant.concurrency); setFormError("") }
  async function save() {
    if (lock.current || !editing) return
    lock.current = true; setBusy(true); setFormError("")
    try { const next = await oauthRequest<OAuthGrant>(`/v1/auth/oauth/grants/${editing.id}`, { expected_revision: editing.revision, tool_ids: selected, expires_at: expiry, rate_per_minute: rate, concurrency }, "PATCH"); setGrants(current => current.map(grant => grant.id === next.id ? next : grant)); setEditing(null) }
    catch (cause) { setFormError(oauthError(cause, zh)) }
    finally { lock.current = false; setBusy(false) }
  }
  async function revoke(grant: OAuthGrant) {
    if (lock.current || !(await confirm({ title: zh ? "撤销授权？" : "Revoke authorization?", description: `${grant.client_name} — ${zh ? "所有相关令牌族将撤销，下一次请求立即拒绝。" : "All related token families will be revoked; their next request is denied."}`, confirmText: zh ? "撤销授权" : "Revoke grant", cancelText: t("cancel"), destructive: true }))) return
    lock.current = true; setBusy(true); setError("")
    try { const next = await oauthRequest<OAuthGrant>(`/v1/auth/oauth/grants/${grant.id}/revoke`, { expected_revision: grant.revision }); setGrants(current => current.map(item => item.id === grant.id ? next : item)) }
    catch (cause) { setError(oauthError(cause, zh)) }
    finally { lock.current = false; setBusy(false) }
  }
  return <div className="space-y-4"><PageHeader title={zh ? "我的 OAuth 授权" : "My OAuth grants"} closeLabel={t("close")} actions={<Button disabled={busy || Boolean(editing)} onClick={() => void load()}>{t("refresh")}</Button>} /><p>{zh ? "在客户端发起连接并同意后，授权显示在这里。可缩小工具、到期时间和配额，或撤销；新增工具与扩大范围需要重新授权。" : "Grants appear after you connect and consent from the client. Reduce tools, expiry and quotas, or revoke. New tools and expanded access require new authorization."}</p>{error && <Alert type="error" title={error} action={<Button disabled={busy} onClick={() => void load()}>{t("retry")}</Button>} />}<Input aria-label={zh ? "搜索我的授权" : "Search my grants"} placeholder={zh ? "搜索客户端、MCP 或工具" : "Search client, MCP or tool"} allowClear value={query} onChange={event => setQuery(event.target.value)} /><Table<OAuthGrant> rowKey="id" size="small" loading={busy && !grants.length} scroll={{ x: 760 }} dataSource={grants.filter(grant => `${grant.client_name} ${grant.client_id} ${grant.tools.map(tool => `${tool.name} ${tool.id} ${tool.server_name || ""} ${tool.server_id}`).join(" ")}`.toLowerCase().includes(query.toLowerCase()))} pagination={{ pageSize: 15, showSizeChanger: false }} locale={{ emptyText: error ? zh ? "读取失败，请重试。" : "Load failed; retry." : zh ? "没有匹配授权。请从客户端连接，或清除筛选。" : "No matching grants. Connect from the client or clear filters." }} columns={[{ title: zh ? "客户端" : "Client", dataIndex: "client_name", render: (_, grant) => <><Button type="link" disabled={busy} onClick={() => edit(grant)}>{grant.client_name}</Button><div className="oauth-muted oauth-wrap">{grant.client_id}</div></> }, { title: zh ? "工具范围与到期时间" : "Tool scope and expiry", render: (_, grant) => <><span>{grant.tools.length} {zh ? "个工具" : "tools"} · {new Set(grant.tools.map(tool => tool.server_id)).size} MCP · {grant.tools.some(tool => tool.access === "write") ? zh ? "含写入" : "Includes write" : zh ? "只读" : "Read only"}</span><div>{localTime(grant.expires_at, locale)}</div><div className="oauth-muted">{grant.rate_per_minute}/min · {grant.concurrency} {zh ? "并发" : "concurrent"}</div></> }, { title: zh ? "状态" : "State", width: 110, render: (_, grant) => <Tag>{zh ? ({ active: "有效", revoked: "已撤销", expired: "已过期", disabled: "已关闭" }[grant.state] || grant.state) : grant.state}</Tag> }, { title: t("actions"), width: 210, render: (_, grant) => <div className="flex gap-2"><Button size="small" disabled={busy || grant.state === "revoked" || grant.state === "expired"} onClick={() => edit(grant)}>{zh ? "缩小范围" : "Reduce scope"}</Button><Button size="small" danger disabled={busy || grant.state === "revoked"} onClick={() => void revoke(grant)}>{zh ? "撤销" : "Revoke"}</Button></div> }]} />
    <FormDialog open={Boolean(editing)} title={zh ? "查看 / 缩小授权" : "View / reduce grant"} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={formError} className="max-w-5xl" footer={<><Button disabled={busy} onClick={() => void close()}>{t("close")}</Button><Button type="primary" disabled={busy || !selected.length || editing?.state === "revoked" || editing?.state === "expired"} onClick={() => void save()}>{zh ? "保存缩小后的授权" : "Save reduced grant"}</Button></>}>
      {editing && <><p className="oauth-wrap">{editing.client_name} · {editing.resource}</p>{!editing.scope_currently_authorized && <Alert type="warning" title={zh ? `当前只有 ${editing.effective_tool_count} 个工具仍获准。保存范围不会恢复已失去的权限。` : `Only ${editing.effective_tool_count} tools are currently authorized. Saving scope does not restore lost permissions.`} />}<OAuthToolPicker tools={editing.tools} selected={selected} onChange={setSelected} zh={zh} disabled={busy || ["revoked", "expired"].includes(editing.state)} /><div className="grid gap-4 sm:grid-cols-3"><label>{zh ? "到期时间（UTC）" : "Expiry (UTC)"}<Input type="datetime-local" disabled={busy} max={new Date(editing.expires_at * 1000).toISOString().slice(0, 16)} value={new Date(expiry * 1000).toISOString().slice(0, 16)} onChange={event => { const next = Date.parse(`${event.target.value}:00Z`); if (Number.isFinite(next)) setExpiry(Math.floor(next / 1000)) }} /></label><label>{zh ? "每分钟调用上限" : "Calls per minute"}<InputNumber disabled={busy} min={1} max={editing.rate_per_minute} precision={0} value={rate} onChange={value => setRate(value ?? 1)} /></label><label>{zh ? "并发上限" : "Concurrent calls"}<InputNumber disabled={busy} min={1} max={editing.concurrency} precision={0} value={concurrency} onChange={value => setConcurrency(value ?? 1)} /></label></div></>}
    </FormDialog>{confirmDialog}</div>
}

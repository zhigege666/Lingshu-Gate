import { ConnectionGuide, ConnectionGuideChecks } from "@/features/external-connections/connection-guide"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useContext, useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Input, InputNumber, Select, Switch, Tag } from "antd"
import { api, type ToolDefinition } from "@/api/client"
import { externalRequest as request, activationReason, externalError } from "@/features/external-connections/api"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { RemainingList, ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { usePageRefresh } from "@/components/page-refresh"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { transportLabel, connectionGuideStepErrors, connectionDraft, connectionError, connectionReadiness, emptyConnection, eligibleTools, grantError, type ConnectionSnapshot, type Grant, type GrantDraft, type GrantList } from "@/features/external-connections/model"
import { ExternalSubjectLinks } from "@/pages/external-subject-links"
import type { Locale, TFunction } from "@/i18n"

type Props = { locale: Locale; t: TFunction }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="flex flex-col gap-2 text-sm"><span>{label}</span>{children}</label> }
function QuotaNotice({ zh }: { zh: boolean }) { return <p className="text-sm text-muted-foreground">{zh ? "调用配额仅在单 Core 进程内存中计数，重启后重置；多个进程或实例不共享配额。" : "Call quotas are counted in one Core process's memory and reset on restart; multiple processes or instances do not share quotas."}</p> }
function ConnectionNotice({ zh }: { zh: boolean }) { return <Alert type="info" showIcon title={zh ? "Gate OAuth 令牌验证与个人授权" : "Gate OAuth token verification and personal grants"} description={<>{zh ? "默认关闭。启用后仅接受受信签发方已签发且验证通过的令牌；不会自动注册 OAuth 客户端、启动隧道或完成 ChatGPT 登录。外部提供方的注册与授权须另行完成。" : "Disabled by default. Enabling accepts already-issued tokens only after verification. It does not register an OAuth client, start a tunnel or complete ChatGPT sign-in. Provider registration and authorization are separate steps."}<QuotaNotice zh={zh} /></>} /> }
function statusLabel(state: string, zh: boolean) { return zh ? ({ enabled: "已启用", active: "已启用", disabled: "已关闭", expired: "已过期", revoked: "已撤销" }[state] ?? state) : state }


export function ConnectionInfrastructurePage({ locale, t }: Props) {
  const zh = locale === "zh-CN"
  const [snapshot, setSnapshot] = useState<ConnectionSnapshot | null>(null)
  const [draft, setDraft] = useState(emptyConnection)
  const [open, setOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [guideStep, setGuideStep] = useState(() => { try { const value = Number(sessionStorage.getItem("gate-connection-guide-step") || 0); return Number.isInteger(value) && value >= 0 && value <= 3 ? value : 0 } catch { return 0 } })
  const registerExit = useContext(EditorNavigationContext)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const [message, setMessage] = useState("")
  const pending = useRef(false)
  const generation = useRef(0)
  const baseline = useRef("")
  const dirty = JSON.stringify(draft) !== baseline.current
  const { confirm, confirmDialog } = useConfirm(t)
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: () => setOpen(false) })
  const closeGuide = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: () => { setGuideOpen(false); if(snapshot) setDraft(connectionDraft(snapshot)) } })
  useEffect(() => { if (guideOpen) return registerExit?.({dirty,pending:busy}) }, [guideOpen, dirty, busy, registerExit])
  function changeGuideStep(next: number) { setGuideStep(next); try { sessionStorage.setItem("gate-connection-guide-step", String(next)) } catch { /* optional progress preference */ } }
  function beginGuide() { if (!snapshot) return; const next=connectionDraft(snapshot); setDraft(next); baseline.current=JSON.stringify(next); setFormError(""); setGuideOpen(true) }
  async function load() {
    const revision = ++generation.current
    setBusy(true); setError("")
    try { const result = await request<ConnectionSnapshot>("/v1/auth/external-connection/config"); if (revision === generation.current) setSnapshot(result) }
    catch (cause) { if (revision === generation.current) setError(externalError(cause, zh)) }
    finally { if (revision === generation.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [])
  usePageRefresh(load, busy || open || guideOpen)
  function edit() { if (!snapshot) return; const next = connectionDraft(snapshot); setDraft(next); baseline.current = JSON.stringify(next); setFormError(""); setOpen(true) }
  async function save() {
    if (pending.current || !snapshot) return
    setMessage("")
    const invalid = connectionError(draft)
    if (invalid) { setFormError(externalError(new Error(invalid), zh)); return }
    if (draft.enabled && connectionReadiness(draft).length) { setFormError((zh ? "尚未配置完成：" : "Configuration incomplete: ") + connectionReadiness(draft).map(reason => activationReason(reason, zh)).join(" · ")); return }
    pending.current = true; setBusy(true); setFormError("")
    try {
      if (draft.enabled && !(await confirm({ title: zh ? "启用外部令牌验证配置？" : "Enable external token verification?", description: zh ? "此设置将立即控制受信令牌的接受范围。它不会完成外部 OAuth 登录或启动隧道。" : "This immediately controls which trusted tokens Gate accepts. It does not complete OAuth sign-in or launch a tunnel." }))) return
      const result = await request<ConnectionSnapshot>("/v1/auth/external-connection/config", { method: "PUT", body: JSON.stringify({ ...draft, expected_revision: snapshot.revision }) })
      if (result.enabled !== draft.enabled) throw new Error("Unexpected enablement state")
      setSnapshot(result); baseline.current = JSON.stringify(draft); setOpen(false); setMessage(zh ? "配置已保存；未执行外部 OAuth 登录。" : "Configuration saved; no external OAuth sign-in was performed."); return true
    } catch (cause) { setFormError(externalError(cause, zh)) }
    finally { pending.current = false; setBusy(false) }
  }
  const configurationForm = (<form id="connection-draft" className="grid min-w-0 grid-cols-1 items-start gap-6 lg:grid-cols-2" onSubmit={event => { event.preventDefault(); void save() }}>
        {(!guideOpen || guideStep === 0) && <fieldset className="min-w-0 space-y-4"><legend className="mb-3 font-medium">{zh ? "连通配置" : "Connectivity"}</legend>
        <Field label={zh ? "传输方式" : "Transport mode"}><Select getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} aria-label={zh ? "计划传输方式" : "Planned transport"} value={draft.mode} disabled={busy} onChange={mode => setDraft(current => ({ ...current, mode }))} options={[{ value: "disabled", label: zh ? "关闭" : "Disabled" }, { value: "direct", label: transportLabel("direct", zh) }, { value: "secure_mcp_tunnel", label: transportLabel("secure_mcp_tunnel", zh) }]} /></Field>
        {(!guideOpen || draft.mode === "direct") && <Field label={zh ? "HTTPS 接入地址" : "HTTPS endpoint"}><Input disabled={busy} value={draft.endpoint ?? ""} onChange={event => setDraft(current => ({ ...current, endpoint: event.target.value || null }))} /></Field>}
        {(!guideOpen || draft.mode !== "disabled") && <Field label={zh ? "Gate 规范资源 URL（空白时使用接入地址）" : "Gate canonical resource URL (defaults to endpoint)"}><Input disabled={busy} value={draft.canonical_resource_url ?? ""} onChange={event => setDraft(current => ({ ...current, canonical_resource_url: event.target.value || null }))} /></Field>}
        {(!guideOpen || draft.mode === "secure_mcp_tunnel") && <Field label={zh ? "隧道引用（tunnel:ID）" : "Tunnel reference (tunnel:ID)"}><Input disabled={busy} value={draft.tunnel_reference ?? ""} onChange={event => setDraft(current => ({ ...current, tunnel_reference: event.target.value || null }))} /></Field>}
        {(!guideOpen || draft.mode === "secure_mcp_tunnel") && <Field label={zh ? "运行秘密引用（credential:ID，勿填秘密）" : "Runtime secret reference (credential:ID, never the secret)"}><Input disabled={busy} autoComplete="off" value={draft.runtime_secret_reference ?? ""} onChange={event => setDraft(current => ({ ...current, runtime_secret_reference: event.target.value || null }))} /></Field>}
        </fieldset>}
        {(!guideOpen || guideStep === 1) && <fieldset className="min-w-0 space-y-4"><legend className="mb-3 font-medium">{zh ? "令牌信任" : "Token trust"}</legend>
        <Field label={zh ? "接受已签发的受信 OAuth 令牌" : "Accept already-issued trusted OAuth tokens"}><Switch className="self-start shrink-0" aria-label={zh ? "启用令牌验证" : "Enable token verification"} checked={draft.enabled} disabled={busy || (!draft.enabled && connectionReadiness(draft).length > 0)} onChange={enabled => setDraft(current => ({ ...current, enabled }))} /></Field>
        <Field label={zh ? "受信 issuer（每行一个 HTTPS URL）" : "Trusted issuers (one HTTPS URL per line)"}><Input.TextArea disabled={busy} rows={3} value={draft.trusted_issuers.join("\n")} onChange={event => setDraft(current => ({ ...current, trusted_issuers: event.target.value ? event.target.value.split("\n") : [] }))} /></Field>
        <Field label={zh ? "允许的客户端 ID（每行一个；匹配 client_id / azp）" : "Allowed client IDs (one per line; client_id / azp)"}><Input.TextArea disabled={busy} value={draft.client_allowlist.join("\n")} onChange={event => setDraft(current => ({ ...current, client_allowlist: event.target.value ? event.target.value.split("\n") : [] }))} /></Field>
        {connectionReadiness(draft).length > 0 && <Alert type="warning" title={zh ? "启用前须完成配置" : "Complete configuration before enabling"} description={connectionReadiness(draft).map(reason => activationReason(reason, zh)).join(" · ")} />}
        </fieldset>}
        {(!guideOpen || guideStep === 1) && <fieldset className="min-w-0 space-y-3 lg:col-span-2"><legend>{zh ? "受信 issuer → 固定 JWKS URL（仅 RS256）" : "Trusted issuer → fixed JWKS URL (RS256 only)"}</legend>
          {draft.issuer_jwks.map((pair, index) => <div className="flex min-w-0 flex-col gap-2 rounded border p-3" key={index}>{pair.map((value, part) => <Input key={part} aria-label={`${part === 0 ? "Issuer" : "JWKS URL"} ${index + 1}`} disabled={busy} value={value} onChange={event => setDraft(current => ({ ...current, issuer_jwks: current.issuer_jwks.map((item, row) => row === index ? item.map((entry, column) => column === part ? event.target.value : entry) as [string, string] : item) }))} />)}<Button className="self-end" disabled={busy} onClick={() => setDraft(current => ({ ...current, issuer_jwks: current.issuer_jwks.filter((_, row) => row !== index) }))}>{t("delete")}</Button></div>)}
          <Button disabled={busy || draft.issuer_jwks.length >= 20} onClick={() => setDraft(current => ({ ...current, issuer_jwks: [...current.issuer_jwks, ["", ""]] }))}>{zh ? "添加签发方 JWKS" : "Add issuer JWKS"}</Button>
        </fieldset>}
        {(!guideOpen || guideStep === 1) && <fieldset className="min-w-0 space-y-3 lg:col-span-2"><legend>{zh ? "外部 audience → canonical resource 精确映射" : "Exact external audience → canonical resource mappings"}</legend>
          {draft.resource_mappings.map((pair, index) => <div className="flex min-w-0 flex-col gap-2 rounded border p-3" key={index}>{pair.map((value, part) => <Input key={part} aria-label={`${part === 0 ? "External audience" : "Canonical resource"} ${index + 1}`} disabled={busy} value={value} onChange={event => setDraft(current => ({ ...current, resource_mappings: current.resource_mappings.map((item, row) => row === index ? item.map((entry, column) => column === part ? event.target.value : entry) as [string, string] : item) }))} />)}<Button className="self-end" disabled={busy} onClick={() => setDraft(current => ({ ...current, resource_mappings: current.resource_mappings.filter((_, row) => row !== index) }))}>{t("delete")}</Button></div>)}
          <Button disabled={busy || draft.resource_mappings.length >= 20} onClick={() => setDraft(current => ({ ...current, resource_mappings: [...current.resource_mappings, ["", ""]] }))}>{zh ? "添加映射" : "Add mapping"}</Button>
        </fieldset>}
      </form>)
  if (guideOpen) return <div className="space-y-4">
    <PageHeader variant="detail" title={zh ? "外部接入引导" : "External connection setup"} closeLabel={t("close")} actions={<Button disabled={busy} onClick={() => void closeGuide()}>{zh ? "返回总览" : "Back to overview"}</Button>} />
    <p className="text-sm text-muted-foreground">{zh ? "可返回任意步骤。步骤位置会保留；未保存的输入离开前会提示，已保存配置可继续编辑。" : "Revisit any step. Your step position is retained; leaving warns about unsaved input, and saved configuration can be resumed."}</p>
    <ConnectionGuide zh={zh} mode={draft.mode} step={guideStep} onStep={changeGuideStep} disabled={busy}>
      {guideStep < 2 && configurationForm}
      {guideStep === 2 && <div className="space-y-4"><ExternalSubjectLinks locale={locale} t={t} issuers={snapshot?.trusted_issuers ?? []} /><p>{zh ? "用户在“我的连接”设置自己的授权；管理员不能替用户自动同意 OAuth。" : "Users configure their own grants in My connections; administrators cannot automatically consent on their behalf."}</p><a href="#/myConnections" className="underline">{zh ? "打开我的连接" : "Open My connections"}</a></div>}
      {guideStep === 3 && <><ConnectionGuideChecks draft={connectionDraft(snapshot || {revision:0})} zh={zh} />{dirty && <p className="text-sm text-amber-600">{zh ? "检查针对已保存配置；前面步骤还有未保存修改。" : "Checks use saved configuration; previous steps contain unsaved edits."}</p>}<Button className="mt-3" disabled={busy} onClick={() => void load()}>{zh ? "重新读取配置状态" : "Reload configuration status"}</Button></>}
      {formError && <Alert className="mt-4" type="error" title={formError} />}
      {message && <Alert className="mt-4" type="success" title={message} />}
    </ConnectionGuide>
    <div className="connection-guide-footer">{guideStep < 2 && <Button disabled={busy} onClick={() => void save()}>{draft.enabled ? (zh ? "保存配置" : "Save configuration") : (zh ? "保存草稿" : "Save draft")}</Button>}<Button disabled={busy || guideStep === 0} onClick={() => changeGuideStep(guideStep-1)}>{zh ? "上一步" : "Previous"}</Button>
      {guideStep < 2 ? <Button type="primary" loading={busy} onClick={async () => { const missing=connectionGuideStepErrors(draft,guideStep); if(missing.length){setMessage("");setFormError(missing.map(reason=>activationReason(reason,zh)).join(" · "));return} if (await save()) changeGuideStep(guideStep+1) }}>{zh ? "保存配置并继续" : "Save configuration and continue"}</Button> : guideStep === 2 ? <Button type="primary" disabled={busy} onClick={() => changeGuideStep(3)}>{zh ? "检查与验证" : "Check and verify"}</Button> : <Button disabled={busy} onClick={() => void closeGuide()}>{zh ? "返回总览" : "Back to overview"}</Button>}
    </div>{confirmDialog}
  </div>
  return <div className="space-y-4">
    <PageHeader closeLabel={t("close")} title={zh ? "连接基础设施" : "Connection infrastructure"} actions={<><Button type="primary" disabled={busy || !snapshot || Boolean(error)} onClick={beginGuide}>{zh ? "接入引导" : "Setup guide"}</Button><Button disabled={busy || !snapshot || Boolean(error)} onClick={edit}>{zh ? "编辑验证配置" : "Edit verification configuration"}</Button></>} />
    <ConnectionNotice zh={zh} />
    {error && <Alert type="error" title={error} action={<Button onClick={() => void load()}>{t("retry")}</Button>} />}
    {message && <Alert type="success" title={message} />}
    {snapshot && <div className="rounded border p-4"><p>{zh ? "配置修订" : "Configuration revision"}: {snapshot.revision} · {transportLabel(snapshot.mode ?? "disabled", zh)} · {statusLabel(snapshot.enabled ? "enabled" : "disabled", zh)}</p><p>{zh ? "JWT 请求验证：" : "JWT request verification: "}{snapshot.enabled && snapshot.oauth_verifier_ready ? (zh ? "接受符合策略的已签发 JWT" : "accepts already-issued JWTs that satisfy policy") : (zh ? "尚未启用或配置不完整" : "disabled or incomplete")}</p><p>{zh ? "外部提供方连通验证：" : "External provider connectivity: "}{snapshot.provider_verified ? (zh ? "服务端报告已验证" : "reported verified by the server") : (zh ? "尚未验证；未完成 OAuth 登录或客户端注册" : "not verified; no OAuth sign-in or client registration completed")}</p><p>{zh ? "待完成本地配置检查（不进行网络探测）" : "Outstanding local configuration checks (no network probe)"}</p><ul className="mt-2 grid list-disc gap-x-8 pl-5 text-sm xl:grid-cols-2">{snapshot.validation_errors?.map(item => <li key={item} title={item}>{activationReason(item, zh)}</li>)}</ul></div>}
    <FormDialog open={open} title={zh ? "外部接入验证配置" : "External access verification configuration"} description={zh ? "部署级传输与令牌信任规则；每位用户仍需独立身份绑定及个人授权。" : "Deployment transport and token trust rules; each user still needs an individual identity binding and grant."} className="max-w-[1120px]" closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={formError} footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" htmlType="submit" form="connection-draft" loading={busy}>{zh ? "保存配置" : "Save configuration"}</Button></>}>
      {configurationForm}
    </FormDialog>{confirmDialog}
    <ExternalSubjectLinks locale={locale} t={t} issuers={snapshot?.trusted_issuers ?? []} />
  </div>
}

const newGrant = (): GrantDraft => ({ enabled: false, client_id: "", server_allowlist: [], tool_allowlist: [], access: ["read"], expires_at: "", rate_per_minute: 30, concurrency: 1 })
export function ExternalGrantsPage({ locale, t }: Props) {
  const zh = locale === "zh-CN"
  const [grants, setGrants] = useState<Grant[]>([])
  const [readiness, setReadiness] = useState({ connection_ready: false, activation_errors: [] as string[], allowed_client_ids: [] as string[] })
  const [tools, setTools] = useState<ToolDefinition[]>([])
  const [toolError, setToolError] = useState("")
  const [query, setQuery] = useState("")
  const [toolQuery, setToolQuery] = useState("")
  const [server, setServer] = useState("")
  const [accessFilter, setAccessFilter] = useState<"read" | "write">("read")
  const [draft, setDraft] = useState<GrantDraft>(newGrant)
  const [editing, setEditing] = useState<Grant | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const [message, setMessage] = useState("")
  const pending = useRef(false)
  const generation = useRef(0)
  const baseline = useRef("")
  const { confirm, confirmDialog } = useConfirm(t)
  const dirty = JSON.stringify(draft) !== baseline.current
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: () => setOpen(false) })
  async function load() {
    const revision = ++generation.current
    setBusy(true); setError("")
    try {
      const [result, visible] = await Promise.allSettled([request<GrantList>("/v1/auth/external-grants"), api.tools()])
      if (revision !== generation.current) return
      if (result.status === "rejected") throw result.reason
      setGrants(result.value.grants); setReadiness({ connection_ready: result.value.connection_ready === true, activation_errors: result.value.activation_errors ?? [], allowed_client_ids: result.value.allowed_client_ids ?? [] })
      if (visible.status === "fulfilled") { setTools(visible.value); setToolError("") }
      else { setTools([]); setToolError(externalError(visible.reason, zh)) }
    } catch (cause) { if (revision === generation.current) setError(externalError(cause, zh)) }
    finally { if (revision === generation.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [])
  usePageRefresh(load, busy || open)
  const paging = useListPage(grants.filter(item => `${item.client_id} ${item.id} ${item.state}`.toLowerCase().includes(query.toLowerCase())), query)
  const eligible = useMemo(() => eligibleTools(tools, accessFilter), [tools, accessFilter])
  const toolPaging = useListPage(eligible.filter(tool => (!server || tool.metadata.server_id === server) && `${tool.name} ${tool.id}`.toLowerCase().includes(toolQuery.toLowerCase())), JSON.stringify([toolQuery, server, accessFilter]))
  const selected = new Set(draft.tool_allowlist)
  const activationBlockers = [...readiness.activation_errors, ...(!readiness.allowed_client_ids.includes(draft.client_id) ? ["client_not_allowed"] : [])]

  function edit(item?: Grant) {
    const next = item ? { enabled: item.enabled, client_id: item.client_id, server_allowlist: item.server_allowlist, tool_allowlist: item.tool_allowlist, access: item.access, expires_at: item.expires_at, rate_per_minute: item.rate_per_minute, concurrency: item.concurrency } : newGrant()
    setEditing(item ?? null); setAccessFilter(next.access[0] ?? "read"); setDraft(next); baseline.current = JSON.stringify(next); setToolQuery(""); setServer(""); setFormError(""); setOpen(true)
  }
  function selectTool(id: string, checked: boolean) {
    setDraft(current => {
      const ids = checked ? [...new Set([...current.tool_allowlist, id])] : current.tool_allowlist.filter(item => item !== id)
      const serverIds = [...new Set(ids.map(toolId => tools.find(tool => tool.id === toolId)?.metadata.server_id).filter((value): value is string => typeof value === "string"))]
      const access = [...new Set(ids.map(toolId => (tools.find(tool => tool.id === toolId)?.metadata.gate_access as { required_access?: "read" | "write" } | undefined)?.required_access).filter((value): value is "read" | "write" => value === "read" || value === "write"))]
      return { ...current, tool_allowlist: ids, server_allowlist: serverIds, access }
    })
  }
  async function save() {
    if (pending.current) return
    const invalid = grantError(draft, tools)
    if (invalid) { setFormError(externalError(new Error(invalid), zh)); return }
    if (draft.enabled && (!readiness.connection_ready || activationBlockers.length)) { setFormError(activationBlockers.map(code => activationReason(code, zh)).join(" · ") || (zh ? "外部验证配置尚未启用" : "External verification is not enabled")); return }
    pending.current = true; setBusy(true); setFormError("")
    try {
      if (draft.enabled && !(await confirm({ title: zh ? "启用此个人授权范围？" : "Enable this personal grant scope?", description: `${draft.client_id} · ${draft.tool_allowlist.length} ${zh ? "个工具" : "tools"} · ${draft.expires_at}` }))) return
      const result = await request<Grant>(`/v1/auth/external-grants${editing ? `/${encodeURIComponent(editing.id)}` : ""}`, { method: editing ? "PATCH" : "POST", body: JSON.stringify({ ...draft, ...(editing ? { expected_revision: editing.revision } : {}) }) })
      if (result.enabled !== draft.enabled) throw new Error("Unexpected enablement state")
      setGrants(current => editing ? current.map(item => item.id === result.id ? result : item) : [result, ...current]); setOpen(false); setMessage(zh ? "个人授权设置已保存；未执行外部 OAuth 登录。" : "Personal grant saved; no external OAuth sign-in was performed.")
    } catch (cause) { setFormError(externalError(cause, zh)) }
    finally { pending.current = false; setBusy(false) }
  }
  async function disable(item: Grant) {
    if (pending.current) return
    pending.current = true; setBusy(true); setError("")
    try {
      const result = await request<Grant>(`/v1/auth/external-grants/${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ enabled: false, expected_revision: item.revision }) })
      if (result.enabled !== false) throw new Error("Disable state unknown")
      setGrants(current => current.map(grant => grant.id === result.id ? result : grant))
    } catch (cause) { setError(externalError(cause, zh)) }
    finally { pending.current = false; setBusy(false) }
  }
  async function revoke(item: Grant) {
    if (pending.current) return
    pending.current = true
    try {
      if (!(await confirm({ title: zh ? "撤销个人授权？" : "Revoke personal grant?", description: `${item.client_id} · ${item.id}`, destructive: true }))) return
      setBusy(true); setError("")
      const result = await request<Grant>(`/v1/auth/external-grants/${encodeURIComponent(item.id)}`, { method: "DELETE" })
      if (result.state !== "revoked") throw new Error("Revocation state unknown")
      setGrants(current => current.map(grant => grant.id === item.id ? result : grant))
    } catch (cause) { setError(externalError(cause, zh)) }
    finally { pending.current = false; setBusy(false) }
  }
  return <div className="space-y-4">
    <PageHeader closeLabel={t("close")} title={zh ? "我的连接" : "My connections"} toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={zh ? "搜索本人授权" : "Search your grants"} clearLabel={t("clearSearch")} />} actions={<Button disabled={busy || Boolean(error) || Boolean(toolError)} onClick={() => edit()}>{zh ? "新建个人授权" : "New personal grant"}</Button>} />
    <ConnectionNotice zh={zh} />
    {error && <Alert type="error" title={error} action={<Button onClick={() => void load()}>{t("retry")}</Button>} />}
    {toolError && <Alert type="warning" title={zh ? "工具目录不可用；仍可关闭或撤销已有授权。" : "Tool catalog unavailable; existing grants can still be disabled or revoked."} description={toolError} />}
    {message && <Alert type="success" title={message} />}
    <RemainingList>
    <ListViewport viewport={paging.viewport} label={zh ? "本人授权" : "Your grants"}><Table><TableHeader><TableRow><TableHead>Client ID</TableHead><TableHead>{zh ? "范围 / 有效期" : "Scope / expiry"}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader><TableBody>{paging.items.map(item => <TableRow key={item.id}><TableCell>{item.client_id}<div className="text-xs">{item.id}</div></TableCell><TableCell>{item.tool_allowlist.length} {zh ? "个工具" : "tools"} · {item.access.join(" / ")}<div>{item.expires_at}</div></TableCell><TableCell><Tag>{statusLabel(item.state, zh)}</Tag>{item.activation_errors?.length ? <p className="text-xs">{item.activation_errors.map(reason => activationReason(reason, zh)).join(" · ")}</p> : null}{!item.scope_currently_authorized && <p>{zh ? "范围已不获准" : "Scope no longer authorized"}</p>}</TableCell><TableCell><div className="flex gap-2">{item.enabled && <Button size="small" disabled={busy} onClick={() => void disable(item)}>{zh ? "关闭" : "Disable"}</Button>}<Button size="small" disabled={busy || Boolean(toolError) || item.state === "revoked"} onClick={() => edit(item)}>{t("edit")}</Button><Button size="small" danger disabled={busy || item.state === "revoked"} onClick={() => void revoke(item)}>{zh ? "撤销" : "Revoke"}</Button></div></TableCell></TableRow>)}</TableBody></Table></ListViewport>
    {!busy && !paging.total && !error && <p>{query.trim() && grants.length ? t("noMatchingRecords") : zh ? "还没有个人授权。" : "No personal grants yet."}</p>}<ListPagination paging={paging} t={t} />
    </RemainingList>
    <FormDialog open={open} title={zh ? "个人授权范围" : "Personal grant scope"} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={formError} className="max-w-3xl" footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" htmlType="submit" form="external-grant-draft" loading={busy}>{zh ? "保存个人授权" : "Save personal grant"}</Button></>}>
      <form id="external-grant-draft" className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); void save() }}>
        <Field label={zh ? "启用本人授权" : "Enable my grant"}><Switch aria-label={zh ? "启用本人授权" : "Enable my grant"} checked={draft.enabled} disabled={busy || (!draft.enabled && (!readiness.connection_ready || activationBlockers.length > 0))} onChange={enabled => setDraft(current => ({ ...current, enabled }))} /></Field>
        {(!readiness.connection_ready || activationBlockers.length > 0) && <Alert type="warning" title={zh ? "当前不能启用：检查配置、身份绑定和客户端" : "Cannot enable: check infrastructure, identity binding and client"} description={activationBlockers.map(reason => activationReason(reason, zh)).join(" · ")} />}
        <Field label={zh ? "每分钟调用上限" : "Calls per minute"}><InputNumber disabled={busy} min={1} max={10000} value={draft.rate_per_minute} onChange={value => setDraft(current => ({ ...current, rate_per_minute: value ?? 1 }))} /></Field>
        <Field label={zh ? "并发上限" : "Concurrent calls"}><InputNumber disabled={busy} min={1} max={100} value={draft.concurrency} onChange={value => setDraft(current => ({ ...current, concurrency: value ?? 1 }))} /></Field>
        <QuotaNotice zh={zh} />
        <Field label="Client ID"><Input list="external-allowed-clients" disabled={busy} value={draft.client_id} onChange={event => setDraft(current => ({ ...current, client_id: event.target.value }))} /><datalist id="external-allowed-clients">{readiness.allowed_client_ids.map(id => <option key={id} value={id} />)}</datalist></Field>
        <Field label={zh ? "到期时间（UTC）" : "Expiry (UTC)"}><Input type="datetime-local" disabled={busy} value={draft.expires_at ? new Date(draft.expires_at).toISOString().slice(0, 16) : ""} onChange={event => setDraft(current => ({ ...current, expires_at: event.target.value ? `${event.target.value}:00Z` : "" }))} /></Field>
        <Field label={zh ? "筛选已获准的工具类型" : "Filter authorized tool access"}><Select aria-label={zh ? "工具访问类型" : "Tool access type"} disabled={busy} value={accessFilter} options={[{ value: "read", label: zh ? "已获准的只读工具" : "Authorized read tools" }, { value: "write", label: zh ? "已获准的写工具" : "Authorized write tools" }]} onChange={setAccessFilter} /></Field>
        <p>{zh ? "可跨页选择只读及写工具；只记录所选工具所需的级别，不会扩大原有角色或资源权限。调用仍受现有角色、资源授权、令牌 scope 与下方限制共同约束。" : "Select read and write tools across pages. Access follows the selected tools and does not expand existing permissions. Calls remain subject to role, resource, token scope and the limits below."} ({draft.rate_per_minute}/min · {draft.concurrency})</p>
        <div className="flex flex-wrap gap-2"><Input aria-label={zh ? "搜索获准工具" : "Search authorized tools"} value={toolQuery} onChange={event => setToolQuery(event.target.value)} /><Select className="min-w-48" aria-label={zh ? "筛选获准 MCP" : "Filter authorized MCP"} showSearch optionFilterProp="label" value={server} onChange={setServer} options={[{ value: "", label: zh ? "所有获准 MCP" : "All authorized MCP" }, ...[...new Set(eligible.map(tool => String(tool.metadata.server_id)))].map(id => ({ value: id, label: id }))]} /></div>
        <div className="flex items-center justify-between"><span>{zh ? `跨页已选 ${selected.size} 项` : `${selected.size} selected across pages`}</span><Button disabled={busy || !selected.size} onClick={() => setDraft(current => ({ ...current, tool_allowlist: [], server_allowlist: [], access: [] }))}>{zh ? "清空选择" : "Clear selection"}</Button></div>
        <ListViewport actions={false} viewport={toolPaging.viewport} label={zh ? "已发布且获准工具" : "Published authorized tools"}><Table><TableHeader><TableRow><TableHead>{zh ? "选择" : "Select"}</TableHead><TableHead>{zh ? "MCP / 工具" : "MCP / tool"}</TableHead></TableRow></TableHeader><TableBody>{toolPaging.items.map(tool => <TableRow key={tool.id}><TableCell><input type="checkbox" aria-label={tool.id} checked={selected.has(tool.id)} disabled={busy} onChange={event => selectTool(tool.id, event.target.checked)} /></TableCell><TableCell>{String(tool.metadata.server_id)} · {tool.name}<div className="text-xs">{tool.id}</div></TableCell></TableRow>)}</TableBody></Table></ListViewport><ListPagination paging={toolPaging} t={t} />
      </form>
    </FormDialog>{confirmDialog}
  </div>
}

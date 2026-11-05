import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { Button, Input, Radio, Tabs } from "antd"
import { ReloadOutlined } from "@ant-design/icons"
import { useAuth } from "@/components/auth-gate"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { getAvailableTokenScopes, getDefaultTokenScopes, getTokenScopeOptions } from "@/features/personal-token-scopes"
import { TokenScopeSelector } from "@/features/external-connections/token-scope-controls"
import type { PersonalToken } from "@/api/client"
import type { Locale, TFunction } from "@/i18n"
import { oauthError, oauthRequest, OAuthRequestError, type OAuthScopeGroup, type OAuthTool } from "./oauth-api"
import { QuotaFields, validQuotas, type McpServerPolicy, type McpAuthorizationMode } from "./mcp-authorization-editor"
import { TokenMcpScopeEditor } from "./token-mcp-scope-editor"
import { TokenAuthorizationReview } from "./token-authorization-review"
import { expandsTokenAccess } from "./authorization-changes"
import { changeTokenMcpChoice, completeTokenMcpPermissions, mergeTokenMcpTools, retainTokenTools, tokenMcpSignature, tokenMcpPermissionConflicts, type TokenMcpChoice, type TokenMcpSnapshot } from "./token-mcp-scope-model"
import "./authorization-editor.css"

type TokenOptions = { scope_editable?: boolean; catalog_complete?: boolean; revision: number; mode: "account" | "independent"; scopes: string[]; tool_ids: string[]; server_policies: McpServerPolicy[]; rate_per_minute: number | null; concurrency: number | null; csrf: string; catalog_revision: string; tools: OAuthTool[]; selected_tools?: OAuthTool[]; servers: { server_id: string; server_name: string | null; server_binding?: string; tool_count: number }[] }
type TokenPreview = { confirmation: string; scopes: string[]; tool_ids: string[]; server_policies: McpServerPolicy[]; rate_per_minute: number; concurrency: number; added: string[]; removed: string[] }
type TokenWrite = { expected_revision: number; catalog_revision: string; mode: "account" | "independent"; scopes: string[]; tool_ids: string[]; server_policies: McpServerPolicy[]; rate_per_minute: number | null; concurrency: number | null; name?: string; expires_at?: string | null }
type Review = { preview: TokenPreview; body: TokenWrite; before: TokenOptions }

function draftSignature(value: { name: string; expiresAt: string; scopes: string[]; selected: string[]; policies: McpServerPolicy[]; mode: string; rate: number | null; concurrency: number | null }) {
  return JSON.stringify({ ...value, scopes: [...value.scopes].sort(), selected: [...value.selected].sort(), policies: [...value.policies].sort((a, b) => a.server_id.localeCompare(b.server_id)).map(policy => [policy.server_id, policy.mode, policy.access, policy.server_binding ?? null]) })
}

export function TokenAuthorizationDialog({ target, create, locale, t, onClose, onSaved, returnFocusState = "ready" }: { target: PersonalToken | null; create: boolean; locale: Locale; t: TFunction; onClose: () => void; onSaved: () => void; returnFocusState?: "pending" | "ready" | "error" }) {
  const zh = locale === "zh-CN"
  let user: any = undefined
  try { user = useAuth().user } catch { /* Isolated component rendering has no auth provider. */ }
  const [options, setOptions] = useState<TokenOptions | null>(null)
  const [mode, setMode] = useState<"account" | "independent">("independent")
  const [name, setName] = useState("MCP Client"), [expiresAt, setExpiresAt] = useState("")
  const [scopes, setScopes] = useState<string[]>([]), [selected, setSelected] = useState<string[]>([])
  const [policies, setPolicies] = useState<McpServerPolicy[]>([]), [modes, setModes] = useState<Record<string, McpAuthorizationMode>>({})
  const [rememberedTools, setRememberedTools] = useState<OAuthTool[]>([])
  const [rate, setRate] = useState<number | null>(6000), [concurrency, setConcurrency] = useState<number | null>(100)
  const [busy, setBusy] = useState(false), [refreshing, setRefreshing] = useState(false), [error, setError] = useState("")
  const [secret, setSecret] = useState(""), [copied, setCopied] = useState(false), [uncertain, setUncertain] = useState(false)
  const [section, setSection] = useState("mcp"), [review, setReview] = useState<Review | null>(null)
  const generation = useRef(0), baseline = useRef(""), locked = useRef(false)
  const initialScope = useRef<TokenMcpSnapshot>({ selected: [], policies: [] })
  const reviewButton = useRef<HTMLButtonElement>(null), reviewRegion = useRef<HTMLDivElement>(null)
  const editTrigger = useRef<HTMLElement | null>(null), editFocusPending = useRef(false), wasOpen = useRef(false)
  const editReturnScope = useRef<HTMLElement | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)
  const open = create || Boolean(target)
  const path = target ? `/v1/auth/tokens/${encodeURIComponent(target.id)}` : "/v1/auth/tokens"
  // Account mode retains the independent draft locally, but never submits it.
  const activeSelected = mode === "independent" ? selected : []
  const activePolicies = mode === "independent" ? policies : []
  const draft = draftSignature({ name, expiresAt, scopes, selected: activeSelected, policies: activePolicies, mode, rate, concurrency })
  const dirty = open && !secret && Boolean(options) && baseline.current !== draft
  const availableScopes = user ? getAvailableTokenScopes(user) : []
  const mcpDraft = { selected, policies, modes }
  const groups: OAuthScopeGroup[] = useMemo(() => {
    const result = new Map<string, OAuthScopeGroup>((options?.servers || []).map(server => [server.server_id, { ...server, read_count: 0, write_count: 0 }]))
    for (const tool of rememberedTools) if (!result.has(tool.server_id)) result.set(tool.server_id, { server_id: tool.server_id, server_name: tool.server_name || null, tool_count: 0, read_count: 0, write_count: 0 })
    for (const policy of [...policies, ...initialScope.current.policies]) if (!result.has(policy.server_id)) result.set(policy.server_id, { server_id: policy.server_id, server_name: null, tool_count: 0, read_count: 0, write_count: 0 })
    return [...result.values()]
  }, [options, rememberedTools, policies])
  const changedMcpCount = groups.filter(group => tokenMcpSignature(group.server_id, { selected: activeSelected, policies: activePolicies }, rememberedTools) !== tokenMcpSignature(group.server_id, initialScope.current, rememberedTools)).length
  // Quota-only writes preserve saved classification snapshots on the API.
  const quotaOnly = Boolean(target && options && draftSignature({ name: "", expiresAt: "", scopes, selected: activeSelected, policies: activePolicies, mode, rate: null, concurrency: null }) === draftSignature({ name: "", expiresAt: "", scopes: options.scopes, selected: options.tool_ids, policies: options.server_policies, mode: options.mode, rate: null, concurrency: null }))
  const permissionTools = quotaOnly ? [...new Map([...rememberedTools, ...(options?.selected_tools || [])].map(tool => [tool.id, tool])).values()] : rememberedTools
  const permissionConflicts = tokenMcpPermissionConflicts({ selected: activeSelected, policies: activePolicies }, permissionTools, scopes)
  const completedScopes = completeTokenMcpPermissions({ selected: activeSelected, policies: activePolicies }, permissionTools, scopes, availableScopes)
  const saveHint = !options ? busy ? zh ? "正在读取授权" : "Loading authorization" : zh ? "请先读取授权范围" : "Load the authorization scope first"
    : uncertain ? zh ? "请先读取实际保存结果" : "Read the saved state before retrying"
    : permissionConflicts.length ? zh ? "MCP 范围与功能权限不一致" : "MCP scope conflicts with functional permissions"
    : !validQuotas(rate, concurrency) ? zh ? "请检查调用限制" : "Check call limits"
    : !scopes.length ? zh ? "请至少选择一项功能权限" : "Select at least one functional permission"
    : !target && !name.trim() ? zh ? "请填写授权名称" : "Enter an authorization name"
    : changedMcpCount ? zh ? `已修改 ${changedMcpCount} 个 MCP，尚未保存` : `${changedMcpCount} MCPs changed; not saved`
    : dirty ? zh ? "有未保存的修改" : "You have unsaved changes"
    : zh ? "尚未修改" : "No changes"
  const saveDisabled = busy || !options || uncertain || Boolean(permissionConflicts.length) || !validQuotas(rate, concurrency) || !scopes.length || (!target && !name.trim()) || (Boolean(target) && !dirty)
  const restoreEditFocus = useCallback(() => {
    if (returnFocusState === "pending") return
    const trigger = editTrigger.current, scope = editReturnScope.current
    const focusTarget = [trigger, scope?.querySelector<HTMLElement>('[data-authorization-retry]'), scope?.querySelector<HTMLElement>('[data-authorization-create]')]
      .find(element => element?.isConnected && !element.matches(':disabled, [aria-disabled="true"]') && !element.closest('[inert], [aria-hidden="true"]') && element.getClientRects().length > 0)
    editFocusPending.current = false
    focusTarget?.focus({ preventScroll: focusTarget === trigger })
  }, [returnFocusState])
  useLayoutEffect(() => {
    if (open && !wasOpen.current) {
      editTrigger.current = document.querySelector<HTMLElement>(".ant-dropdown-trigger.ant-dropdown-open") || (document.activeElement instanceof HTMLElement ? document.activeElement : null)
      editReturnScope.current = editTrigger.current?.closest<HTMLElement>('[data-authorization-page]') || null
      editFocusPending.current = false
    }
    wasOpen.current = open
  }, [open])
  useEffect(() => { if (!open && editFocusPending.current) restoreEditFocus() }, [open, restoreEditFocus])
  useEffect(() => { if (review) reviewRegion.current?.focus() }, [review])
  function finishClose() { generation.current++; setSecret(""); onClose() }
  const closeDraft = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: finishClose })
  async function close() {
    if (busy) return
    if (!secret) { await closeDraft(); return }
    if (copied) { finishClose(); return }
    if (await confirm({ title: zh ? "令牌已创建" : "Token created", description: zh ? "关闭后无法再次查看明文，请确认已保存。" : "The secret cannot be viewed again after closing. Confirm that you have saved it.", confirmText: zh ? "已保存，关闭" : "Saved; close", cancelText: zh ? "返回保存" : "Return to save" })) finishClose()
  }
  async function load(reconcile = false) {
    const current = ++generation.current
    setBusy(true); setRefreshing(reconcile); setError(""); setReview(null)
    try {
      const next = await oauthRequest<TokenOptions>(`${path}/authorization-options`)
      if (current !== generation.current) return
      setOptions(next); setUncertain(reconcile && create && uncertain)
      setRememberedTools(previous => retainTokenTools(reconcile ? previous : [], next.tools, next.selected_tools || [], reconcile ? [...selected, ...initialScope.current.selected, ...next.tool_ids] : next.tool_ids))
      if (reconcile && create && uncertain) { onSaved(); setError(zh ? "已刷新授权列表。请关闭后核对创建结果；令牌明文无法再次读取，请勿重复创建。" : "Authorization list refreshed. Close and review the creation result. Token secrets cannot be recovered; do not create a duplicate.") }
      if (!reconcile) {
        const initialScopes = target ? next.scopes : getDefaultTokenScopes(getAvailableTokenScopes(user), user)
        const nextRate = next.rate_per_minute ?? 6000, nextConcurrency = next.concurrency ?? 100
        initialScope.current = { selected: next.tool_ids, policies: next.server_policies }
        setScopes(initialScopes); setSelected(next.tool_ids); setPolicies(next.server_policies); setMode(next.mode); setRate(nextRate); setConcurrency(nextConcurrency)
        setModes(Object.fromEntries([...next.tools, ...(next.selected_tools || [])].filter(tool => next.tool_ids.includes(tool.id)).map(tool => [tool.server_id, "selected"])))
        setName(target?.name || "MCP Client"); setExpiresAt(""); setSecret(""); setCopied(false); setSection("mcp")
        baseline.current = draftSignature({ name: target?.name || "MCP Client", expiresAt: "", scopes: initialScopes, selected: next.tool_ids, policies: next.server_policies, mode: next.mode, rate: nextRate, concurrency: nextConcurrency })
      }
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { if (current === generation.current) { setBusy(false); setRefreshing(false) } }
  }
  useEffect(() => { if (open) { setOptions(null); setRememberedTools([]); setUncertain(false); setReview(null); void load() } return () => { generation.current++ } }, [target?.id, create])
  function changeChoice(server: string, choice: TokenMcpChoice) {
    const next = changeTokenMcpChoice(server, choice, mcpDraft, rememberedTools, options?.servers.find(item => item.server_id === server)?.server_binding)
    setModes(next.modes); setPolicies(next.policies); setSelected(next.selected)
    const nextScopes = completeTokenMcpPermissions(next, rememberedTools, scopes, availableScopes)
    if (nextScopes) setScopes(nextScopes)
  }
  function changeTools(server: string, ids: string[]) {
    const next = mergeTokenMcpTools(server, selected, ids, rememberedTools)
    setSelected(next)
    const nextScopes = completeTokenMcpPermissions({ selected: next, policies }, rememberedTools, scopes, availableScopes)
    if (nextScopes) setScopes(nextScopes)
  }
  async function writeAuthorization(value: Review, current: number) {
    const result = await oauthRequest<PersonalToken & { token?: string }>(`${path}/authorization`, { ...value.body, confirmation: value.preview.confirmation })
    if (current !== generation.current) return
    if (!result?.id || (target ? result.id !== target.id : typeof result.token !== "string" || !result.token)) throw new OAuthRequestError("invalid_response", 200)
    onSaved(); setReview(null)
    if (result.token) setSecret(result.token)
    else { generation.current++; onClose() }
  }
  async function prepareReview() {
    if (locked.current || saveDisabled || !options) return
    const current = generation.current
    locked.current = true; setBusy(true); setError("")
    let writeAttempted = false
    try {
      const body: TokenWrite = { expected_revision: options.revision, catalog_revision: options.catalog_revision, mode, scopes, tool_ids: activeSelected, server_policies: activePolicies, rate_per_minute: rate, concurrency, ...(!target ? { name, expires_at: expiresAt ? new Date(expiresAt).toISOString() : null } : {}) }
      const preview = await oauthRequest<TokenPreview>(`${path}/authorization-preview`, { ...body, csrf: options.csrf })
      if (current !== generation.current) return
      const value = { preview, body, before: options }
      if (target && expandsTokenAccess(options, body, preview.added)) setReview(value)
      else { writeAttempted = true; await writeAuthorization(value, current) }
    } catch (cause) { if (current === generation.current) {
      if (writeAttempted && (!(cause instanceof OAuthRequestError) || !cause.status || cause.status >= 500 || cause.code === "invalid_response")) setUncertain(true)
      setError(oauthError(cause, zh))
    } }
    finally { locked.current = false; if (current === generation.current) setBusy(false) }
  }
  function returnToEditing() { setReview(null); requestAnimationFrame(() => reviewButton.current?.focus()) }
  async function saveReviewed() {
    if (locked.current || busy || !review) return
    const current = generation.current
    locked.current = true; setBusy(true); setError("")
    try {
      await writeAuthorization(review, current)
    } catch (cause) {
      if (current === generation.current) {
        if (!(cause instanceof OAuthRequestError) || !cause.status || cause.status >= 500 || cause.code === "invalid_response") setUncertain(true)
        setReview(null); setError(oauthError(cause, zh))
      }
    } finally { locked.current = false; if (current === generation.current) setBusy(false) }
  }
  const editable = !busy && options?.scope_editable !== false
  const saveLabel = target ? zh ? "保存授权" : "Save authorization" : zh ? "创建令牌" : "Create token"
  const readSavedLabel = zh ? "读取实际记录" : "Read saved state"
  const saving = busy && Boolean(options) && !refreshing
  return <><FormDialog
    onCloseAutoFocus={event => { event.preventDefault(); editFocusPending.current = true; restoreEditFocus() }}
    open={open}
    title={review ? zh ? "检查授权变更" : "Review authorization changes" : target ? zh ? "调整授权" : "Adjust authorization" : zh ? "创建 API 令牌" : "Create API token"}
    description={target ? target.name : undefined}
    closeLabel={t("close")}
    className="token-authorization-dialog"
    pending={busy}
    dirty={dirty || Boolean(secret)}
    error={error}
    onClose={() => void close()}
    footer={secret ? <>
      <Button onClick={() => void close()}>{t("close")}</Button>
      <Button type="primary" onClick={async () => { try { await navigator.clipboard.writeText(secret); setCopied(true) } catch { setError(zh ? "复制失败，请手动复制。" : "Copy failed. Copy manually.") } }}>{copied ? zh ? "已复制" : "Copied" : zh ? "复制令牌" : "Copy token"}</Button>
    </> : review ? <>
      <Button disabled={busy} onClick={returnToEditing}>{zh ? "返回编辑" : "Back to editing"}</Button>
      <Button type="primary" loading={busy} disabled={busy} onClick={() => void saveReviewed()}>{zh ? "确认扩大授权" : "Confirm expanded access"}</Button>
    </> : <>
      <span className="token-authorization-save-hint" role="status">{saveHint}{permissionConflicts.length > 0 && <Button type="link" size="small" onClick={() => setSection("permissions")}>{zh ? "调整功能权限" : "Edit permissions"}</Button>}{options && !validQuotas(rate, concurrency) && <Button type="link" size="small" onClick={() => setSection("quota")}>{zh ? "前往修改" : "Edit call limits"}</Button>}{options && !scopes.length && <Button type="link" size="small" onClick={() => setSection("permissions")}>{zh ? "选择功能权限" : "Choose permissions"}</Button>}</span>
      <Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button>
      <Button ref={reviewButton} type="primary" aria-label={saveLabel} aria-busy={saving} loading={saving} disabled={saveDisabled} onClick={() => void prepareReview()}>{saveLabel}</Button>
    </>}
  >
    {secret ? <div><p>{zh ? "令牌明文只显示一次，请保存。" : "This token is shown only once. Save it now."}</p><code className="block break-all rounded border p-3">{secret}</code></div> : <>
      {review && <div ref={reviewRegion} tabIndex={-1} className="token-review-focus"><TokenAuthorizationReview before={review.before} after={review.preview} mode={review.body.mode} tools={rememberedTools} groups={groups} zh={zh} create={!target} name={review.body.name || name} expiry={review.body.expires_at || ""} /></div>}
      <div className="token-authorization-sections" style={review ? { display: "none" } : undefined} aria-hidden={review ? true : undefined}>
        {!options && <Button loading={busy} onClick={() => void load()}>{zh ? "读取授权范围" : "Load authorization scope"}</Button>}
        {uncertain && <div className="token-authorization-notice" role="alert">{zh ? "保存结果未知。草稿已保留，请先读取实际记录；不要重复创建令牌。" : "Save result unknown. Your draft is retained. Read the saved state before retrying; do not create another token."}<Button aria-label={readSavedLabel} aria-busy={refreshing} disabled={busy} loading={refreshing} onClick={() => void load(true)}>{readSavedLabel}</Button></div>}
        {options && <>
          {options.scope_editable === false && <div className="token-authorization-notice" role="alert">{zh ? "候选目录超出当前支持上限，仅可调整配额。" : "The candidate catalog exceeds current limits; only call limits can be edited."}</div>}
          {!target && <div className="token-authorization-metadata">
            <div className="authorization-field"><label htmlFor="authorization-token-name">{zh ? "授权名称" : "Authorization name"}</label><Input id="authorization-token-name" value={name} disabled={busy} onChange={event => setName(event.target.value)} /></div>
            <div className="authorization-field"><label htmlFor="authorization-token-expiry">{zh ? "到期时间" : "Expires at"}</label><div className="authorization-field-control"><Input id="authorization-token-expiry" type="datetime-local" value={expiresAt} disabled={busy} onChange={event => setExpiresAt(event.target.value)} /><p className="text-muted-foreground">{zh ? "留空表示永不过期" : "Leave empty for no expiry"}</p></div></div>
          </div>}
          {permissionConflicts.length > 0 && <div className="token-authorization-conflict" role="alert"><p>{zh ? "以下 MCP 的范围需要对应功能权限。可在此补齐所需权限，或调整 MCP 范围。" : "These MCPs require matching functional permissions. Add the required permissions here or edit their MCP scope."}</p><ul>{permissionConflicts.map(conflict => <li key={conflict.server_id}>{groups.find(group => group.server_id === conflict.server_id)?.server_name || conflict.server_id}: {conflict.required.map(scope => scope === "tools.read" ? zh ? "只读工具 (tools.read)" : "Read-only tools (tools.read)" : zh ? "写入工具 (tools.invoke)" : "Write tools (tools.invoke)").join("、")}</li>)}</ul><Button disabled={!editable || completedScopes === null} onClick={() => { if (completedScopes) setScopes(completedScopes) }}>{zh ? "补齐上述功能权限" : "Add these required permissions"}</Button>{completedScopes === null && <p>{zh ? "当前账号无权授予其中的权限，请调整 MCP 范围。" : "Your account cannot grant one of these permissions. Adjust the MCP scope."}</p>}</div>}
          <Tabs className="token-authorization-tabs" activeKey={section} onChange={setSection}
            items={[
              { key: "mcp", label: zh ? "MCP 范围" : "MCP scope", children: <section className="token-authorization-scope">
                {<div className="token-authorization-mode"><div className="authorization-field">
                  <span className="token-authorization-label" id="token-scope-mode-label">{zh ? "范围模式" : "Scope mode"}</span>
                  <div className="authorization-field-control"><Radio.Group aria-labelledby="token-scope-mode-label" value={mode} disabled={!editable} onChange={event => setMode(event.target.value)}>
                    <Radio value="account">{zh ? "跟随账号权限" : "Follow account access"}</Radio><Radio value="independent">{zh ? "独立 MCP 范围" : "Independent MCP scope"}</Radio>
                  </Radio.Group>
                  <p className="text-muted-foreground">{mode === "account" ? zh ? "MCP 和工具随账号资源权限动态变化，仍受此令牌的功能权限和调用限制约束。" : "MCPs and tools follow changes to account access, within this token’s functional permissions and call limits." : zh ? "只开放下方指定的 MCP 或工具。" : "Allows only the MCPs or tools specified below."}</p>
                  </div>
                </div></div>}
                {mode === "independent" ? <TokenMcpScopeEditor groups={groups} tools={rememberedTools} draft={mcpDraft} baseline={initialScope.current} canRead={availableScopes.includes("tools.read")} canWrite={availableScopes.includes("tools.invoke")} disabled={!editable} pending={busy} refreshing={refreshing} zh={zh}
                  onChoice={changeChoice} onTools={changeTools} onRefresh={() => void load(true)} onPermissions={() => setSection("permissions")}
                  onReconfirm={server => setPolicies(current => current.map(policy => policy.server_id === server ? { ...policy, server_binding: options.servers.find(item => item.server_id === server)?.server_binding } : policy))} onClearTools={() => setSelected([])} />
                  : <Button className="token-account-refresh" icon={<ReloadOutlined aria-hidden />} disabled={busy} loading={refreshing} onClick={() => void load(true)}>{zh ? "刷新可授权范围" : "Refresh available scope"}</Button>}
              </section> },
              { key: "permissions", label: zh ? "功能权限" : "Functional permissions", children: <TokenScopeSelector options={getTokenScopeOptions(getAvailableTokenScopes(user), target?.scopes)} selected={scopes} locale={locale} disabled={!editable} onChange={setScopes} /> },
              { key: "quota", label: zh ? "调用限制" : "Call limits", children: <section className="token-authorization-quotas" aria-label={zh ? "调用限制" : "Call limits"}>
                {target && (options.rate_per_minute === null || options.concurrency === null) && <p className="text-muted-foreground">{zh ? `当前：${options.rate_per_minute ?? "未设置"} 次/分钟 · 并发 ${options.concurrency ?? "未设置"}；保存后使用下方限制。` : `Current: ${options.rate_per_minute ?? "not set"}/min · ${options.concurrency ?? "not set"} concurrent. Saving applies the limits below.`}</p>}
                <QuotaFields rate={rate} concurrency={concurrency} onRate={setRate} onConcurrency={setConcurrency} disabled={busy} zh={zh} />
              </section> },
            ]} />
        </>}
      </div>
    </>}
  </FormDialog>{confirmDialog}</>
}

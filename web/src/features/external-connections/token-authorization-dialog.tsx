import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { Button, Collapse, Input, Radio } from "antd"
import { useAuth } from "@/components/auth-gate"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { getAvailableTokenScopes, getDefaultTokenScopes, getTokenScopeOptions } from "@/features/personal-token-scopes"
import { TokenScopeSelector } from "@/pages/personal-tokens-page"
import type { PersonalToken } from "@/api/client"
import type { Locale, TFunction } from "@/i18n"
import { oauthError, oauthRequest, OAuthRequestError, type OAuthScopeGroup, type OAuthTool } from "./oauth-api"
import { OAuthToolPicker } from "./oauth-tool-picker"
import { McpAuthorizationEditor, McpPolicyDifference, QuotaSettings, validQuotas, type McpServerPolicy, type McpAuthorizationMode } from "./mcp-authorization-editor"
import "./authorization-editor.css"

type TokenOptions = { scope_editable?: boolean; catalog_complete?: boolean; revision: number; mode: "account" | "independent"; scopes: string[]; tool_ids: string[]; server_policies: McpServerPolicy[]; rate_per_minute: number | null; concurrency: number | null; csrf: string; catalog_revision: string; tools: OAuthTool[]; selected_tools?: OAuthTool[]; servers: { server_id: string; server_name: string | null; server_binding?: string; tool_count: number }[] }
type TokenPreview = { confirmation: string; scopes: string[]; tool_ids: string[]; server_policies: McpServerPolicy[]; rate_per_minute: number; concurrency: number; added: string[]; removed: string[] }
export function TokenAuthorizationDialog({ target, create, locale, t, onClose, onSaved, returnFocusState = "ready" }: { target: PersonalToken | null; create: boolean; locale: Locale; t: TFunction; onClose: () => void; onSaved: () => void; returnFocusState?: "pending" | "ready" | "error" }) {
  const zh = locale === "zh-CN"
  let user: any = undefined
  try {
    user = useAuth().user
  } catch {
    // Safe fallback for isolated components or static markup rendering
  }
  const [options, setOptions] = useState<TokenOptions | null>(null)
  const [mode, setMode] = useState<"account" | "independent">("independent")
  const [name, setName] = useState("MCP Client"), [expiresAt, setExpiresAt] = useState("")
  const [scopes, setScopes] = useState<string[]>([]), [selected, setSelected] = useState<string[]>([])
  const [policies, setPolicies] = useState<McpServerPolicy[]>([]), [modes, setModes] = useState<Record<string, McpAuthorizationMode>>({})
  const [rate, setRate] = useState<number | null>(6000), [concurrency, setConcurrency] = useState<number | null>(100)
  const [busy, setBusy] = useState(false), [error, setError] = useState("")
  const [secret, setSecret] = useState(""), [copied, setCopied] = useState(false), [uncertain, setUncertain] = useState(false)
  const generation = useRef(0), baseline = useRef(""), locked = useRef(false)
  const editTrigger = useRef<HTMLElement | null>(null), editFocusPending = useRef(false), wasOpen = useRef(false)
  const editReturnScope = useRef<HTMLElement | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)
  const open = create || Boolean(target)
  const path = target ? `/v1/auth/tokens/${encodeURIComponent(target.id)}` : "/v1/auth/tokens"
  const draft = JSON.stringify({ name, expiresAt, scopes, selected, policies, mode, rate, concurrency })
  const dirty = open && !secret && Boolean(options) && baseline.current !== draft
  const restoreEditFocus = useCallback(() => {
    if (returnFocusState === "pending") return
    const trigger = editTrigger.current
    const scope = editReturnScope.current
    const target = [trigger, scope?.querySelector<HTMLElement>('[data-authorization-retry]'), scope?.querySelector<HTMLElement>('[data-authorization-create]')]
      .find(element => element?.isConnected && !element.matches(':disabled, [aria-disabled="true"]') && !element.closest('[inert], [aria-hidden="true"]') && element.getClientRects().length > 0)
    editFocusPending.current = false
    target?.focus({ preventScroll: target === trigger })
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
  function finishClose() { generation.current++; setSecret(""); onClose() }
  const closeDraft = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: finishClose })
  async function close() {
    if (busy) return
    if (!secret) { await closeDraft(); return }
    if (await confirm({ title: zh ? "令牌已创建" : "Token created", description: zh ? "关闭后无法再次查看明文，请确认已保存。" : "The secret cannot be viewed again after closing. Confirm that you have saved it.", confirmText: zh ? "已保存，关闭" : "Saved; close", cancelText: zh ? "返回保存" : "Return to save" })) finishClose()
  }
  async function load(reconcile = false) {
    const current = ++generation.current
    setBusy(true); setError("")
    try {
      const next = await oauthRequest<TokenOptions>(`${path}/authorization-options`)
      if (current !== generation.current) return
      setOptions(next); setUncertain(reconcile && create && uncertain)
      if (reconcile && create && uncertain) { onSaved(); setError(zh ? "已刷新授权列表。请关闭后核对创建结果；令牌明文无法再次读取，请勿重复创建。" : "Authorization list refreshed. Close and review the creation result. Token secrets cannot be recovered; do not create a duplicate.") }
      if (!reconcile) {
        const initialScopes = target ? next.scopes : getDefaultTokenScopes(getAvailableTokenScopes(user), user)
        const nextRate = next.rate_per_minute ?? 6000, nextConcurrency = next.concurrency ?? 100
        setScopes(initialScopes); setSelected(next.tool_ids); setPolicies(next.server_policies); setMode(next.mode); setRate(nextRate); setConcurrency(nextConcurrency)
        setModes(Object.fromEntries([...next.tools, ...(next.selected_tools || [])].filter(tool => next.tool_ids.includes(tool.id)).map(tool => [tool.server_id, "selected"])))
        setName(target?.name || "MCP Client"); setExpiresAt(""); setSecret(""); setCopied(false)
        baseline.current = JSON.stringify({ name: target?.name || "MCP Client", expiresAt: "", scopes: initialScopes, selected: next.tool_ids, policies: next.server_policies, mode: next.mode, rate: nextRate, concurrency: nextConcurrency })
      }
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { if (current === generation.current) setBusy(false) }
  }
  useEffect(() => { if (open) { setOptions(null); setUncertain(false); void load() } return () => { generation.current++ } }, [target?.id, create])
  const groups: OAuthScopeGroup[] = useMemo(() => {
    const result = new Map((options?.servers || []).map(server => [server.server_id, { ...server, read_count: 0, write_count: 0 }]))
    for (const tool of options?.selected_tools || []) if (!result.has(tool.server_id)) result.set(tool.server_id, { server_id: tool.server_id, server_name: tool.server_name || null, tool_count: 0, read_count: 0, write_count: 0 })
    for (const policy of policies) if (!result.has(policy.server_id)) result.set(policy.server_id, { server_id: policy.server_id, server_name: null, tool_count: 0, read_count: 0, write_count: 0 })
    return [...result.values()]
  }, [options, policies])
  function changeMode(server: string, next: McpAuthorizationMode) {
    setModes(current => ({ ...current, [server]: next }))
    setPolicies(current => [...current.filter(policy => policy.server_id !== server), ...(next === "continuous" ? [{ server_id: server, server_binding: options?.servers.find(item => item.server_id === server)?.server_binding, mode: "continuous" as const, access: "read" as const }] : [])])
    if (next !== "selected") setSelected(current => current.filter(id => [...(options?.tools || []), ...(options?.selected_tools || [])].find(tool => tool.id === id)?.server_id !== server))
  }
  async function save() {
    if (locked.current || !options || uncertain || !validQuotas(rate, concurrency) || !scopes.length || (!target && !name.trim())) return
    const current = generation.current
    const body = { expected_revision: options.revision, catalog_revision: options.catalog_revision, mode, scopes, tool_ids: selected, server_policies: policies, rate_per_minute: rate, concurrency, ...(!target ? { name, expires_at: expiresAt ? new Date(expiresAt).toISOString() : null } : {}) }
    locked.current = true; setBusy(true); setError("")
    let attempted = false
    try {
      const preview = await oauthRequest<TokenPreview>(`${path}/authorization-preview`, { ...body, csrf: options.csrf })
      if (current !== generation.current) return
      if (!(await confirm({ title: zh ? "确认保存授权？" : "Save authorization?", description: target?.name || name,
        details: <div className="space-y-2"><p>{zh ? "每分钟" : "Per minute"} {options.rate_per_minute ?? (zh ? "未设置" : "Not set")} → {preview.rate_per_minute} · {zh ? "并发" : "Concurrent"} {options.concurrency ?? (zh ? "未设置" : "Not set")} → {preview.concurrency}</p>{options.mode !== mode && <p>{zh ? "MCP 范围" : "MCP scope"}: {options.mode === "account" ? zh ? "跟随账号资源权限" : "Follows account resource access" : zh ? "独立 MCP 范围" : "Independent MCP scope"} → {mode === "account" ? zh ? "跟随账号资源权限" : "Follows account resource access" : zh ? "独立 MCP 范围" : "Independent MCP scope"}</p>}{[...options.scopes].sort().join(",") !== [...preview.scopes].sort().join(",") && <p>{zh ? "功能权限" : "Functional permissions"}: {options.scopes.join(", ")} → {preview.scopes.join(", ")}</p>}{(preview.added.length > 0 || preview.removed.length > 0) && <p>{zh ? "新增工具" : "Added tools"} {preview.added.length} · {zh ? "移除工具" : "Removed tools"} {preview.removed.length}</p>}<McpPolicyDifference before={options.server_policies} after={preview.server_policies} beforeSelected={[...(options.selected_tools || [])].map(tool => tool.server_id)} afterSelected={Object.keys(modes).filter(id => modes[id] === "selected")} zh={zh} /></div>, confirmText: zh ? "确认保存" : "Confirm", cancelText: t("cancel") }))) return
      if (current !== generation.current) return
      attempted = true
      const result = await oauthRequest<PersonalToken & { token?: string }>(`${path}/authorization`, { ...body, confirmation: preview.confirmation })
      if (current !== generation.current) return
      onSaved()
      if (result.token) setSecret(result.token)
      else { generation.current++; onClose() }
    } catch (cause) { if (current === generation.current) {
      if (attempted && (!(cause instanceof OAuthRequestError) || !cause.status || cause.status >= 500)) setUncertain(true)
      setError(oauthError(cause, zh))
    } } finally { locked.current = false; if (current === generation.current) setBusy(false) }
  }
  return <><FormDialog onCloseAutoFocus={event => { event.preventDefault(); editFocusPending.current = true; restoreEditFocus() }} open={open} title={target ? zh ? "调整授权" : "Adjust authorization" : zh ? "创建 API 令牌" : "Create API token"} description={target ? `${target.name} · ${target.token_prefix}` : undefined} closeLabel={t("close")} className="max-w-6xl" pending={busy} dirty={dirty || Boolean(secret)} error={error} onClose={() => void close()} footer={secret ? <><Button onClick={() => void close()}>{t("close")}</Button><Button type="primary" onClick={async () => { try { await navigator.clipboard.writeText(secret); setCopied(true) } catch { setError(zh ? "复制失败，请手动复制。" : "Copy failed. Copy manually.") } }}>{copied ? zh ? "已复制" : "Copied" : zh ? "复制令牌" : "Copy token"}</Button></> : <><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" disabled={busy || !options || uncertain || !validQuotas(rate, concurrency) || !scopes.length || (!target && !name.trim()) || (Boolean(target) && !dirty)} onClick={() => void save()}>{zh ? "保存授权" : "Save authorization"}</Button></>}>
    {secret ? <div><p>{zh ? "令牌明文只显示一次，请保存。" : "This token is shown only once. Save it now."}</p><code className="block break-all rounded border p-3">{secret}</code></div> : <div className="space-y-4">
      {!options && <Button loading={busy} onClick={() => void load()}>{zh ? "读取授权范围" : "Load authorization scope"}</Button>}
      {uncertain && <div role="alert">{zh ? "保存结果未知。草稿已保留，请先读取实际记录；不要重复创建令牌。" : "Save result unknown. Your draft is retained. Read the saved state before retrying; do not create another token."}<Button onClick={() => void load(true)}>{zh ? "读取实际记录" : "Read saved state"}</Button></div>}
      {options && <>
        {options.scope_editable === false && <div role="alert">{zh ? "候选目录超出当前支持上限，仅可调整配额。" : "The candidate catalog exceeds current limits; only call limits can be edited."}</div>}
        {!target && <><div className="authorization-field"><label htmlFor="authorization-token-name">{zh ? "授权名称" : "Authorization name"}</label><Input id="authorization-token-name" value={name} disabled={busy} onChange={event => setName(event.target.value)} /></div><div className="authorization-field"><label htmlFor="authorization-token-expiry">{zh ? "到期时间" : "Expires at"}</label><Input id="authorization-token-expiry" type="datetime-local" value={expiresAt} disabled={busy} onChange={event => setExpiresAt(event.target.value)} /></div></>}
        <Button disabled={busy} onClick={() => void load(true)}>{zh ? "刷新可授权范围" : "Refresh available scope"}</Button>
        <QuotaSettings rate={rate} concurrency={concurrency} onRate={setRate} onConcurrency={setConcurrency} disabled={busy} zh={zh} />
        <Collapse items={[{ key: "scopes", label: zh ? "功能权限" : "Functional permissions", children: <TokenScopeSelector options={getTokenScopeOptions(getAvailableTokenScopes(user), target?.scopes)} selected={scopes} locale={locale} disabled={busy || options.scope_editable === false} onChange={setScopes} /> }]} />
        {mode === "account" ? <div className="authorization-field"><span>{zh ? "跟随账号资源权限（现有模式）" : "Follows account resource access (existing mode)"}</span><Button disabled={busy || options.scope_editable === false} onClick={() => setMode("independent")}>{zh ? "改为独立 MCP 范围" : "Use independent MCP scope"}</Button></div> : <>
          <McpAuthorizationEditor groups={groups} policies={policies} modes={modes} onMode={changeMode} onAccess={(server, access) => setPolicies(current => current.map(policy => policy.server_id === server ? { ...policy, access } : policy))} canWrite={scopes.includes("tools.invoke") || scopes.includes("*")} disabled={busy || options.scope_editable === false} zh={zh} />
          {Object.values(modes).includes("selected") && <OAuthToolPicker tools={[...new Map([...(options.selected_tools || []).map(tool => ({ ...tool, currently_authorized: false })), ...options.tools].map(tool => [tool.id, tool])).values()].filter(tool => modes[tool.server_id] === "selected")} eligibleTools={options.tools.filter(tool => modes[tool.server_id] === "selected")} selected={selected} onChange={setSelected} zh={zh} disabled={busy || options.scope_editable === false} />}
          {!selected.length && !policies.length && <Radio checked>{zh ? "仅控制功能，不开放业务 MCP" : "Control functions only; no business MCP access"}</Radio>}
        </>}
      </>}
    </div>}
  </FormDialog>{confirmDialog}</>
}

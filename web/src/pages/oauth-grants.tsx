import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Input, InputNumber, Segmented, Table, Tag } from "antd"
import { PageHeader } from "@/components/page-shell"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { usePageRefresh } from "@/components/page-refresh"
import { Toaster } from "@/components/ui/toast"
import { ManagementTargetsDialog } from "@/features/external-connections/management-targets-dialog"
import { ManagementTargetsEditor } from "@/features/external-connections/management-targets-editor"
import { managementTargetRows } from "@/features/external-connections/management-targets-model"
import { OAuthToolPicker } from "@/features/external-connections/oauth-tool-picker"
import { scopeEditorTools } from "@/features/external-connections/oauth-tool-selection"
import { ScopeAvailability } from "@/features/external-connections/oauth-scope-availability"
import { ScopeDifference, scopeDifference } from "@/features/external-connections/oauth-scope-difference"
import { oauthError, oauthRequest, OAuthRequestError, type OAuthGrant, type OAuthScopeOptions, type OAuthScopePreview, type OAuthTool } from "@/features/external-connections/oauth-api"
import { filterGrants, grantRemaining, grantState, utcGrantTime, type GrantFilter } from "@/features/external-connections/oauth-grants-model"
import type { Locale, TFunction } from "@/i18n"
import "@/features/external-connections/oauth.css"

export function BuiltinOAuthGrants({ locale, t }: { locale: Locale; t: TFunction }) {
  const zh = locale === "zh-CN"
  const [grants, setGrants] = useState<OAuthGrant[]>([])
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<GrantFilter>("active")
  const [page, setPage] = useState(1)
  const [snapshotAt, setSnapshotAt] = useState(() => Math.floor(Date.now() / 1000))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const [viewing, setViewing] = useState<OAuthGrant | null>(null)
  const viewingGeneration = useRef(0)
  const viewTrigger = useRef<HTMLElement | null>(null)
  const targetTrigger = useRef<HTMLElement | null>(null)
  const [copyMessage, setCopyMessage] = useState("")
  const [targetEditing, setTargetEditing] = useState<OAuthGrant | null>(null)
  const [editing, setEditing] = useState<OAuthGrant | null>(null)
  const [scopeOptions, setScopeOptions] = useState<OAuthScopeOptions | null>(null)
  const [rememberedTools, setRememberedTools] = useState<OAuthTool[]>([])
  const [scopeLoading, setScopeLoading] = useState(false)
  const scopeGeneration = useRef(0)
  const [notice, setNotice] = useState("")
  const toast = useMemo(() => notice ? { message: notice, tone: "success" as const } : null, [notice])
  const dismissToast = useCallback(() => setNotice(""), [])
  const [selected, setSelected] = useState<string[]>([])
  const [expiry, setExpiry] = useState(0)
  const [rate, setRate] = useState(30)
  const [concurrency, setConcurrency] = useState(1)
  const lock = useRef(false)
  const version = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const editorTools = useMemo(() => scopeEditorTools(rememberedTools, scopeOptions?.tools ?? null, selected), [rememberedTools, scopeOptions, selected])
  const availableIds = useMemo(() => new Set(scopeOptions?.tools.map(tool => tool.id) || []), [scopeOptions])
  const unavailableSelected = scopeOptions ? selected.filter(id => !availableIds.has(id)) : []
  const changes = useMemo(() => scopeDifference(editing?.tools || [], selected, editorTools), [editing, selected, editorTools])
  const dirty = Boolean(editing && (changes.added.length || changes.removed.length || expiry !== editing.expires_at || rate !== editing.rate_per_minute || concurrency !== editing.concurrency))
  function closeEditor() { scopeGeneration.current++; setEditing(null); setScopeOptions(null); setRememberedTools([]); setScopeLoading(false) }
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: closeEditor })
  async function load() {
    const current = ++version.current
    setBusy(true); setError(""); setNotice("")
    try {
      const result = await oauthRequest<{ grants: OAuthGrant[] }>("/v1/auth/oauth/grants")
      if (current === version.current) {
        const now = Math.floor(Date.now() / 1000)
        setGrants(result.grants); setSnapshotAt(now)
      }
    } catch (cause) { if (current === version.current) setError(oauthError(cause, zh)) }
    finally { if (current === version.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { version.current++; viewingGeneration.current++; scopeGeneration.current++ } }, [])
  usePageRefresh(load, busy || Boolean(editing) || Boolean(viewing) || Boolean(targetEditing))
  const filtered = useMemo(() => filterGrants(grants, filter, query, snapshotAt), [grants, filter, query, snapshotAt])
  const shownPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / 15)))
  function stateLabel(state: string) { return zh ? ({ active: "有效", revoked: "已撤销", expired: "已过期", disabled: "已关闭" }[state] || state) : ({ active: "Active", revoked: "Revoked", expired: "Expired", disabled: "Disabled" }[state] || state) }
  function view(grant: OAuthGrant) { viewingGeneration.current++; viewTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setViewing(grant); setCopyMessage("") }
  function editTargets(grant: OAuthGrant) { targetTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setNotice(""); setTargetEditing(grant) }
  function closeView() { viewingGeneration.current++; setViewing(null); setCopyMessage("") }
  function edit(grant: OAuthGrant) {
    if (grantState(grant, Math.floor(Date.now() / 1000)) !== "active") return
    setEditing(grant); setSelected(grant.tools.map(tool => tool.id)); setExpiry(grant.expires_at); setRate(grant.rate_per_minute); setConcurrency(grant.concurrency); setFormError("")
    setScopeOptions(null); setRememberedTools(grant.tools); void readScopeOptions(grant)
  }
  async function readScopeOptions(target: OAuthGrant) {
    const generation = ++scopeGeneration.current
    setScopeLoading(true); setFormError("")
    try {
      const next = await oauthRequest<OAuthScopeOptions>(`/v1/auth/oauth/grants/${target.id}/scope-options`)
      if (generation !== scopeGeneration.current) return
      if (next.grant_revision !== target.revision) throw new OAuthRequestError("revision_conflict", 409)
      setRememberedTools(previous => [...new Map([...previous, ...next.tools].map(tool => [tool.id, tool])).values()])
      setScopeOptions(next)
    } catch (cause) { if (generation === scopeGeneration.current) { setScopeOptions(null); setFormError(oauthError(cause, zh)) } }
    finally { if (generation === scopeGeneration.current) setScopeLoading(false) }
  }
  async function save() {
    if (lock.current || !editing || scopeLoading || !scopeOptions || !selected.length || unavailableSelected.length) return
    const target = editing, current = version.current, generation = scopeGeneration.current
    const body = { expected_revision: target.revision, tool_ids: [...selected], expires_at: expiry, rate_per_minute: rate, concurrency }
    lock.current = true; setBusy(true); setFormError(""); setNotice("")
    try {
      const preview = await oauthRequest<OAuthScopePreview>(`/v1/auth/oauth/grants/${target.id}/scope-preview`, { ...body, csrf: scopeOptions.csrf })
      if (current !== version.current || generation !== scopeGeneration.current) return
      if (!(await confirm({ title: zh ? "确认更新当前连接？" : "Update this connection?",
        description: `${target.client_name} — ${zh ? "在 Gate 内确认即可更新此授权的工具范围，无需客户端再次 OAuth。新增、重新确认及删除会作用于此授权；每个令牌仍受原有 scope 限制。客户端缓存的工具列表可能需要刷新。" : "Confirm in Gate to update this grant's tools without another client OAuth flow. Additions, reconfirmations and removals affect this grant; each token keeps its existing scope limits. The client's cached tool list may need refreshing."}`,
        details: <><ScopeDifference before={preview.previous_tools} selected={preview.tool_ids} catalog={preview.tools} zh={zh} /><p className="oauth-muted">{zh ? "到期（UTC）：" : "Expiry (UTC): "}{utcGrantTime(preview.expires_at)} · {preview.rate_per_minute} / min · {preview.concurrency} {zh ? "并发" : "concurrent"}</p></>,
        confirmText: zh ? "确认并更新" : "Confirm update", cancelText: t("cancel") }))) return
      if (current !== version.current || generation !== scopeGeneration.current) return
      const next = await oauthRequest<OAuthGrant>(`/v1/auth/oauth/grants/${target.id}/scope`, { ...body, confirmation: preview.confirmation })
      if (current === version.current && generation === scopeGeneration.current) {
        setGrants(items => items.map(grant => grant.id === next.id ? next : grant)); setSnapshotAt(Math.floor(Date.now() / 1000)); closeEditor()
        setNotice(zh ? "连接工具范围已更新；下一次请求按新范围检查。" : "Connection tools updated; the next request uses the new scope.")
      }
    } catch (cause) { if (current === version.current && generation === scopeGeneration.current) setFormError(oauthError(cause, zh)) }
    finally { lock.current = false; if (current === version.current) setBusy(false) }
  }
  async function revoke(grant: OAuthGrant) {
    if (lock.current) return
    const current = version.current
    lock.current = true; setBusy(true); setError("")
    try {
      if (!(await confirm({ title: zh ? "撤销授权？" : "Revoke authorization?", description: `${grant.client_name} — ${zh ? "所有相关令牌族将撤销，下一次请求立即拒绝。" : "All related token families will be revoked; their next request is denied."}`, confirmText: zh ? "撤销授权" : "Revoke grant", cancelText: t("cancel"), destructive: true }))) return
      if (current !== version.current) return
      const next = await oauthRequest<OAuthGrant>(`/v1/auth/oauth/grants/${grant.id}/revoke`, { expected_revision: grant.revision })
      if (current === version.current) { setGrants(items => items.map(item => item.id === next.id ? next : item)); setSnapshotAt(Math.floor(Date.now() / 1000)) }
    } catch (cause) { if (current === version.current) setError(oauthError(cause, zh)) }
    finally { lock.current = false; if (current === version.current) setBusy(false) }
  }
  async function copyId(value: string) {
    const current = viewingGeneration.current
    try { await navigator.clipboard.writeText(value); if (current === viewingGeneration.current) setCopyMessage(zh ? "标识已复制。" : "Identifier copied.") }
    catch { if (current === viewingGeneration.current) setCopyMessage(zh ? "复制失败，请从只读字段手动复制。" : "Copy failed; copy from the read-only field.") }
  }
  return <div className="space-y-4">
    <PageHeader title={zh ? "我的 OAuth 授权" : "My OAuth grants"} closeLabel={t("close")} actions={<Button disabled={busy || Boolean(editing) || Boolean(viewing) || Boolean(targetEditing)} onClick={() => void load()}>{t("refresh")}</Button>} />
    <p>{zh ? "这里只展示本人的授权。在 Gate 内明确确认即可增加或减少现有 OAuth scope 内的 MCP 和工具，无需客户端再次 OAuth；可随时撤销。" : "Only your own grants appear here. Explicit confirmation in Gate adds or removes MCPs and tools within existing OAuth scopes, without another client OAuth flow. You can revoke at any time."}</p>
    {error && <Alert type="error" title={error} action={<Button disabled={busy} onClick={() => void load()}>{t("retry")}</Button>} />}
    <div className="oauth-grants-toolbar"><Segmented aria-label={zh ? "授权状态" : "Grant state"} value={filter} onChange={value => { setFilter(value as GrantFilter); setPage(1); setSnapshotAt(Math.floor(Date.now() / 1000)) }} options={[{ value: "active", label: zh ? "有效" : "Active" }, { value: "expired", label: zh ? "已过期" : "Expired" }, { value: "revoked", label: zh ? "已撤销" : "Revoked" }, { value: "all", label: zh ? "全部" : "All" }]} /><Input aria-label={zh ? "搜索我的授权" : "Search my grants"} placeholder={zh ? "搜索客户端、MCP 或工具" : "Search client, MCP or tool"} allowClear value={query} onChange={event => { setQuery(event.target.value); setPage(1); setSnapshotAt(Math.floor(Date.now() / 1000)) }} /></div>
    <p className="oauth-muted" role="status">{zh ? `匹配 ${filtered.length} / 已读取 ${grants.length} 条本人授权；到期时间为 UTC，剩余时间按本次读取或筛选计算。` : `${filtered.length} matching / ${grants.length} loaded personal grants; expiry is UTC, remaining time reflects the latest read or filter.`}</p>
    <Table<OAuthGrant> rowKey="id" size="small" loading={busy && !grants.length} scroll={{ x: 1160 }} dataSource={filtered}
      pagination={{ current: shownPage, pageSize: 15, showSizeChanger: false, onChange: setPage, showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}` }}
      locale={{ emptyText: error ? zh ? "读取失败，请重试。" : "Load failed; retry." : grants.length === 0 ? zh ? "尚无授权。请从客户端连接并同意工具范围。" : "No grants yet. Connect from a client and consent to tool scope." : <div><p>{zh ? "没有匹配授权。" : "No matching grants."}</p><Button onClick={() => { setFilter("all"); setQuery(""); setPage(1) }}>{zh ? "查看全部授权" : "Show all grants"}</Button></div> }}
      columns={[
        { title: zh ? "客户端 / 授权时间" : "Client / authorized", width: 220, render: (_, grant) => <><Button type="link" disabled={busy} onClick={() => view(grant)}>{grant.client_name}</Button>{utcGrantTime(grant.created_at) && <div className="oauth-muted">{utcGrantTime(grant.created_at)}</div>}<div className="oauth-muted">{zh ? "授权" : "Grant"} …{grant.id.slice(-8)}</div></> },
        { title: zh ? "工具范围" : "Tool scope", width: 200, render: (_, grant) => <><div><Button type="link" disabled={busy} onClick={() => view(grant)}>{zh ? `${grant.tools.length} 个工具` : `${grant.tools.length} tools`}</Button> · {new Set(grant.tools.map(tool => tool.server_id)).size} MCP</div><Tag color={grant.tools.some(tool => tool.access === "write") ? "orange" : "blue"}>{grant.tools.some(tool => tool.access === "write") ? zh ? "含写入" : "Includes write" : zh ? "只读" : "Read only"}</Tag></> },
        { title: zh ? "到期 / 剩余" : "Expiry / remaining", width: 215, render: (_, grant) => <><div>{utcGrantTime(grant.expires_at) || "—"}</div>{grantState(grant, snapshotAt) === "active" && <div className="oauth-muted">{grantRemaining(grant.expires_at, snapshotAt, zh)}</div>}</> },
        { title: zh ? "调用配额" : "Call limits", width: 135, render: (_, grant) => <><div>{grant.rate_per_minute} / min</div><div className="oauth-muted">{grant.concurrency} {zh ? "并发" : "concurrent"}</div></> },
        { title: zh ? "状态" : "State", width: 100, render: (_, grant) => <Tag color={grantState(grant, snapshotAt) === "active" ? "green" : undefined}>{stateLabel(grantState(grant, snapshotAt))}</Tag> },
        { title: t("actions"), width: 290, render: (_, grant) => <div className="flex flex-wrap gap-2"><Button size="small" disabled={busy} onClick={() => view(grant)}>{zh ? "详情" : "Details"}</Button>{grantState(grant, snapshotAt) === "active" && <><Button size="small" disabled={busy} onClick={() => grant.resource_kind === "management" ? editTargets(grant) : edit(grant)}>{grant.resource_kind === "management" ? zh ? "调整管理目标" : "Adjust targets" : zh ? "调整授权范围" : "Adjust scope"}</Button><Button size="small" danger disabled={busy} onClick={() => void revoke(grant)}>{zh ? "撤销" : "Revoke"}</Button></>}</div> },
      ]} />
    <FormDialog open={Boolean(viewing)} title={zh ? "授权详情" : "Grant details"} closeLabel={t("close")} onClose={closeView} onCloseAutoFocus={event => { event.preventDefault(); if (viewTrigger.current && document.contains(viewTrigger.current)) viewTrigger.current.focus() }} className="oauth-grant-scope-dialog" bodyClassName={viewing?.resource_kind === "management" ? "oauth-management-target-body" : "oauth-grant-scope-body oauth-grant-details-body"} footer={<Button onClick={closeView}>{t("close")}</Button>}>
      {viewing && <><p>{viewing.client_name} · {stateLabel(grantState(viewing, snapshotAt))}</p><p className="oauth-wrap">{viewing.resource}</p><div className="oauth-grant-identifiers"><label>Grant ID<Input readOnly value={viewing.id} /></label><Button onClick={() => void copyId(viewing.id)}>{zh ? "复制授权 ID" : "Copy grant ID"}</Button><label>Client ID<Input readOnly value={viewing.client_id} /></label><Button onClick={() => void copyId(viewing.client_id)}>{zh ? "复制客户端 ID" : "Copy client ID"}</Button></div>{copyMessage && <p role="status">{copyMessage}</p>}<p className="text-sm">{zh ? "这是已保存的工具范围；历史记录不代表当前仍获准调用。" : "This is recorded tool scope; historical records do not establish current invocation permission."}</p>{viewing.resource_kind === "management" && <ManagementTargetsEditor rows={managementTargetRows(viewing.management_targets || {})} onChange={() => undefined} zh={zh} readOnly />}<OAuthToolPicker key={viewing.id} tools={viewing.tools} selected={[]} onChange={() => undefined} zh={zh} readOnly fillViewport={viewing.resource_kind !== "management"} /></>}
    </FormDialog>
    <ManagementTargetsDialog grant={targetEditing} locale={locale} t={t} onCloseAutoFocus={event => { if (targetTrigger.current?.isConnected) { event.preventDefault(); targetTrigger.current.focus() } }} onClose={() => setTargetEditing(null)} onSaved={next => { setGrants(items => items.map(item => item.id === next.id ? next : item)); setSnapshotAt(Math.floor(Date.now() / 1000)); setNotice(zh ? "管理目标已更新；旧计划失效，权限上限未改变。" : "Management targets updated; old plans are stale and scope ceilings unchanged.") }} />
    <FormDialog open={Boolean(editing)} title={zh ? "调整授权范围" : "Adjust authorization scope"} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={formError} className="oauth-grant-scope-dialog" bodyClassName="oauth-grant-scope-body" footer={<>{editing && <Button aria-label={zh ? "刷新可授权范围" : "Refresh available scope"} aria-busy={scopeLoading} loading={scopeLoading} disabled={busy || scopeLoading} onClick={() => void readScopeOptions(editing)}>{zh ? "刷新可授权范围" : "Refresh available scope"}</Button>}<Button disabled={busy} onClick={() => void close()}>{t("close")}</Button><Button type="primary" disabled={busy || scopeLoading || !dirty || !selected.length || unavailableSelected.length > 0 || !editing || !scopeOptions || grantState(editing, Math.floor(Date.now() / 1000)) !== "active"} onClick={() => void save()}>{zh ? "核对并更新连接" : "Review connection update"}</Button></>}>
      {editing && <><p className="oauth-wrap">{editing.client_name} · {editing.resource}</p>{!editing.scope_currently_authorized && <Alert type="warning" title={zh ? `当前只有 ${editing.effective_tool_count} 个原工具仍获准。只有本人当前获准的工具才可确认更新。` : `Only ${editing.effective_tool_count} original tools remain authorized. Only tools you currently have permission to use can be confirmed.`} />}
        {scopeLoading && <p role="status">{zh ? "正在读取本人可授权范围…" : "Loading your available scope…"}</p>}
        {scopeOptions && <div className="oauth-muted" role="status"><p>{zh ? "现有 OAuth scope 上限：" : "Existing OAuth scope ceiling: "}{scopeOptions.scopes.join(" · ") || "—"}{scopeOptions.effective_scopes.join(" ") !== scopeOptions.scopes.join(" ") && <span>{zh ? "；当前客户端允许：" : "; currently allowed by client: "}{scopeOptions.effective_scopes.join(" · ") || "—"}</span>}</p><p>{zh ? "各令牌族仍受自己的 scope 上限约束；仅有 tools.read 的令牌不能调用新增写工具。" : "Each token family keeps its own scope ceiling; a tools.read-only token cannot invoke newly added write tools."}{scopeOptions.family_scope_limits.length > 0 && <> {scopeOptions.family_scope_limits.map(limit => `${limit.count} × ${limit.scopes.join(" + ") || "—"}`).join("; ")}</>}</p></div>}
        {scopeOptions && <ScopeAvailability options={scopeOptions} zh={zh} />}
        {unavailableSelected.length > 0 && <Alert type="warning" title={zh ? `草稿保留了 ${unavailableSelected.length} 个当前不可授权选择。移除这些选择后才能保存。` : `Your draft retains ${unavailableSelected.length} currently unavailable selections. Remove them before saving.`} action={<Button disabled={busy || scopeLoading} onClick={() => setSelected(ids => ids.filter(id => availableIds.has(id)))}>{zh ? "移除不可授权选择" : "Remove unavailable selections"}</Button>} />}
        <p className="oauth-muted" role="status">{zh ? `新增 / 重新确认 ${changes.added.length} 个工具（写入 ${changes.added.filter(tool => tool.access === "write").length}）；从当前连接移除 ${changes.removed.length} 个。` : `${changes.added.length} added / reconfirmed tools (${changes.added.filter(tool => tool.access === "write").length} write); ${changes.removed.length} removed from this connection.`}</p>
        <div className="oauth-grant-limits"><label>{zh ? "到期时间（UTC）" : "Expiry (UTC)"}<Input type="datetime-local" aria-label={zh ? "到期时间（UTC）" : "Expiry (UTC)"} disabled={busy} max={new Date(editing.expires_at * 1000).toISOString().slice(0, 16)} value={new Date(expiry * 1000).toISOString().slice(0, 16)} onChange={event => { const next = Date.parse(`${event.target.value}:00Z`); if (Number.isFinite(next)) setExpiry(Math.floor(next / 1000)) }} /></label><label>{zh ? "每分钟调用上限" : "Calls per minute"}<InputNumber aria-label={zh ? "每分钟调用上限" : "Calls per minute"} disabled={busy} min={1} max={editing.rate_per_minute} precision={0} value={rate} onChange={value => setRate(value ?? 1)} /></label><label>{zh ? "并发上限" : "Concurrent calls"}<InputNumber aria-label={zh ? "并发上限" : "Concurrent calls"} disabled={busy} min={1} max={editing.concurrency} precision={0} value={concurrency} onChange={value => setConcurrency(value ?? 1)} /></label></div><OAuthToolPicker tools={editorTools} eligibleTools={scopeOptions?.tools ?? null} selected={selected} onChange={setSelected} zh={zh} disabled={busy || scopeLoading || !scopeOptions} fillViewport bulkActions /></>}
    </FormDialog>{confirmDialog}<Toaster toast={toast} onClose={dismissToast} closeLabel={t("close")} />
  </div>
}

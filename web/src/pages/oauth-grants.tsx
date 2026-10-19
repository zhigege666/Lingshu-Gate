import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Input, Select, Segmented, Table, Tag } from "antd"
import { McpAuthorizationEditor, McpPolicyDifference, QuotaSettings, validQuotas, policyGroups, type McpServerPolicy, type McpAuthorizationMode } from "@/features/external-connections/mcp-authorization-editor"
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
import { OAuthPagedToolPicker, type ScopeSelectionOperation } from "@/features/external-connections/oauth-paged-tool-picker"
import { scopeEditorTools } from "@/features/external-connections/oauth-tool-selection"
import { ScopeAvailability } from "@/features/external-connections/oauth-scope-availability"
import { preventOAuthMcpPopupDismiss } from "@/features/external-connections/oauth-mcp-filter"
import { ScopeRules } from "@/features/external-connections/oauth-scope-rules"
import { ScopeDifference, scopeDifference } from "@/features/external-connections/oauth-scope-difference"
import { oauthError, oauthRequest, OAuthRequestError, type OAuthGrant, type OAuthScopeGroup, type OAuthScopeCatalog, type OAuthScopeOptions, type OAuthScopePreview, type OAuthScopeSelection, type OAuthTool } from "@/features/external-connections/oauth-api"
import { filterGrants, grantRemaining, grantState, isOAuthQuotaOnlyChange, utcGrantTime, type GrantFilter } from "@/features/external-connections/oauth-grants-model"
import type { Locale, TFunction } from "@/i18n"
import "@/features/external-connections/oauth.css"
import "@/features/external-connections/authorization-editor.css"

export type OAuthGrantAction = { grant: OAuthGrant; action: "edit" | "view" | "revoke"; nonce: number }
export function BuiltinOAuthGrants({ locale, t, embedded = false, action, onChanged, returnFocusState = "ready" }: { locale: Locale; t: TFunction; embedded?: boolean; action?: OAuthGrantAction; onChanged?: () => void; returnFocusState?: "pending" | "ready" | "error" }) {
  const zh = locale === "zh-CN"
  const [grants, setGrants] = useState<OAuthGrant[]>([])
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<GrantFilter>("active")
  const [page, setPage] = useState(1)
  const [snapshotAt, setSnapshotAt] = useState(() => Math.floor(Date.now() / 1000))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const [saveUncertain, setSaveUncertain] = useState(false)
  const [scopeReadNotice, setScopeReadNotice] = useState("")
  const [viewing, setViewing] = useState<OAuthGrant | null>(null)
  const viewingGeneration = useRef(0)
  const viewTrigger = useRef<HTMLElement | null>(null)
  const targetTrigger = useRef<HTMLElement | null>(null)
  const editTrigger = useRef<HTMLElement | null>(null)
  const editReturnScope = useRef<HTMLElement | null>(null)
  const editFocusPending = useRef(false)
  const [copyMessage, setCopyMessage] = useState("")
  const [targetEditing, setTargetEditing] = useState<OAuthGrant | null>(null)
  const [editing, setEditing] = useState<OAuthGrant | null>(null)
  const [scopeOptions, setScopeOptions] = useState<OAuthScopeOptions | null>(null)
  const [toolServer, setToolServer] = useState("")
  const [serverGroups, setServerGroups] = useState<OAuthScopeGroup[]>([])
  const [scopeCatalog, setScopeCatalog] = useState<OAuthScopeCatalog | null>(null)
  const [scopeSelection, setScopeSelection] = useState<OAuthScopeSelection | null>(null)
  const [scopeRefreshKey, setScopeRefreshKey] = useState(0)
  const [rememberedTools, setRememberedTools] = useState<OAuthTool[]>([])
  const [scopeLoading, setScopeLoading] = useState(false)
  const [scopeInfoOpen, setScopeInfoOpen] = useState(false)
  const scopeGeneration = useRef(0)
  const selectionLock = useRef(false)
  const [notice, setNotice] = useState("")
  const toast = useMemo(() => notice ? { message: notice, tone: "success" as const } : null, [notice])
  const dismissToast = useCallback(() => setNotice(""), [])
  const [selected, setSelected] = useState<string[]>([])
  const [expiry, setExpiry] = useState(0)
  const [rate, setRate] = useState<number | null>(6000)
  const [concurrency, setConcurrency] = useState<number | null>(100)
  const [policies, setPolicies] = useState<McpServerPolicy[]>([])
  const [modes, setModes] = useState<Record<string, McpAuthorizationMode>>({})
  const lock = useRef(false)
  const version = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const editorTools = useMemo(() => scopeEditorTools(rememberedTools, scopeOptions?.tools ?? null, selected), [rememberedTools, scopeOptions, selected])
  const eligibleScopeTools = useMemo(() => scopeOptions?.tools.filter(tool => modes[tool.server_id] === "selected") ?? null, [scopeOptions?.tools, modes])
  const activeOptions = scopeCatalog || scopeOptions
  const paged = editing?.scope_catalog_mode === "paged"
  const availableIds = useMemo(() => new Set(paged ? scopeSelection?.available_ids || [] : scopeOptions?.tools.map(tool => tool.id) || []), [paged, scopeSelection, scopeOptions])
  const unavailableSelected = activeOptions ? selected.filter(id => !availableIds.has(id)) : []
  const changes = useMemo(() => scopeDifference(editing?.tools || [], selected, editorTools), [editing, selected, editorTools])
  const addedCount = paged ? scopeSelection?.difference_summary.added || 0 : changes.added.length
  const addedWriteCount = paged ? scopeSelection?.difference_summary.added_write || 0 : changes.added.filter(tool => tool.access === "write").length
  const removedCount = paged ? scopeSelection?.difference_summary.removed || 0 : changes.removed.length
  const originalIds = useMemo(() => new Set(editing?.tools.map(tool => tool.id) || []), [editing])
  const changedIds = Boolean(editing && (selected.length !== originalIds.size || selected.some(id => !originalIds.has(id))))
  const quotaOnly = isOAuthQuotaOnlyChange(editing, { toolIds: selected, policies, expiresAt: expiry, rate, concurrency })
  const dirty = Boolean(editing && (JSON.stringify(policies) !== JSON.stringify(editing.server_policies || []) || saveUncertain || addedCount || removedCount || changedIds || expiry !== editing.expires_at || rate !== editing.rate_per_minute || concurrency !== editing.concurrency))
  const unknownSaveMessage = zh ? "保存结果未知；草稿已保留。请刷新可授权范围，读取实际已保存状态后再决定是否更新。" : "Save result is unknown; your draft is retained. Refresh available scope to read the saved state before deciding whether to update."
  function closeEditor() { scopeGeneration.current++; setEditing(null); setScopeOptions(null); setScopeCatalog(null); setScopeSelection(null); setRememberedTools([]); setScopeLoading(false); setScopeInfoOpen(false); setSaveUncertain(false); setScopeReadNotice("") }
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: closeEditor })
  const restoreEditFocus = useCallback(() => {
    if (busy || returnFocusState === "pending") return
    const trigger = editTrigger.current
    const scope = editReturnScope.current
    const target = [trigger, scope?.querySelector<HTMLElement>('[data-authorization-retry]'), scope?.querySelector<HTMLElement>('[data-authorization-create]'), scope?.querySelector<HTMLElement>('[data-authorization-refresh]')]
      .find(element => element?.isConnected && !element.matches(':disabled, [aria-disabled="true"]') && !element.closest('[inert], [aria-hidden="true"]') && element.getClientRects().length > 0)
    editFocusPending.current = false
    target?.focus({ preventScroll: target === trigger })
  }, [busy, returnFocusState])
  useEffect(() => { if (!editing && editFocusPending.current) restoreEditFocus() }, [editing, restoreEditFocus])
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
  useEffect(() => { if (!embedded) void load(); return () => { version.current++; viewingGeneration.current++; scopeGeneration.current++ } }, [embedded])
  usePageRefresh(load, busy || Boolean(editing) || Boolean(viewing) || Boolean(targetEditing))
  const filtered = useMemo(() => filterGrants(grants, filter, query, snapshotAt), [grants, filter, query, snapshotAt])
  const shownPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / 15)))
  function stateLabel(state: string) { return zh ? ({ active: "有效", revoked: "已撤销", expired: "已过期", disabled: "已关闭" }[state] || state) : ({ active: "Active", revoked: "Revoked", expired: "Expired", disabled: "Disabled" }[state] || state) }
  function view(grant: OAuthGrant) { viewingGeneration.current++; viewTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setViewing(grant); setCopyMessage("") }
  function editTargets(grant: OAuthGrant) { targetTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setNotice(""); setTargetEditing(grant) }
  function closeView() { viewingGeneration.current++; setViewing(null); setCopyMessage("") }
  function edit(grant: OAuthGrant) {
    if (grantState(grant, Math.floor(Date.now() / 1000)) !== "active") return
    editTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    editReturnScope.current = editTrigger.current?.closest<HTMLElement>('[data-authorization-page]') || null
    editFocusPending.current = false
    setPolicies(grant.server_policies || []); setModes(Object.fromEntries(grant.tools.map(tool => [tool.server_id, "selected"]))); setEditing(grant); setSelected(grant.tools.map(tool => tool.id)); setExpiry(grant.expires_at); setRate(grant.rate_per_minute); setConcurrency(grant.concurrency); setFormError(""); setSaveUncertain(false); setScopeReadNotice("")
    setScopeOptions(null); setScopeCatalog(null); setScopeSelection(null); setScopeInfoOpen(false); setRememberedTools(grant.tools); void readScopeOptions(grant, grant.tools.map(tool => tool.id))
  }
  async function readScopeOptions(target: OAuthGrant, draft = selected, reconcile = false) {
    const generation = ++scopeGeneration.current
    setScopeLoading(true); setFormError("")
    try {
      if (reconcile) {
        const saved = await oauthRequest<{ grants: OAuthGrant[] }>("/v1/auth/oauth/grants")
        if (generation !== scopeGeneration.current) return
        const actual = saved.grants.find(grant => grant.id === target.id)
        if (!actual) throw new OAuthRequestError("grant_scope_unavailable", 409)
        target = actual
      }
      const applySavedState = () => {
        if (!reconcile) return
        setEditing(target); setGrants(items => items.map(grant => grant.id === target.id ? target : grant)); setSnapshotAt(Math.floor(Date.now() / 1000))
        setSaveUncertain(false)
        setScopeReadNotice(zh ? `已读取保存版本 ${target.revision}：${target.tools.length} 个工具；草稿已保留。` : `Saved grant revision ${target.revision} read: ${target.tools.length} tools; your draft is retained.`)
      }
      if (target.scope_catalog_mode === "paged") {
        const next = await oauthRequest<OAuthScopeCatalog>(`/v1/auth/oauth/grants/${target.id}/scope-catalog`)
        if (generation !== scopeGeneration.current) return
        if (next.complete !== false || next.grant_revision !== target.revision) throw new OAuthRequestError("revision_conflict", 409)
        const checked = await oauthRequest<OAuthScopeSelection>(`/v1/auth/oauth/grants/${target.id}/scope-selection`, {
          csrf: next.csrf, expected_revision: target.revision, catalog_revision: next.catalog_revision, mode: "ids", tool_ids: draft,
        })
        if (generation !== scopeGeneration.current) return
        const groups: OAuthScopeGroup[] = []
        let cursor = ""
        do {
          const params = new URLSearchParams({ view: "groups", limit: "100", catalog_revision: next.catalog_revision })
          if (cursor) params.set("cursor", cursor)
          const page = await oauthRequest<OAuthScopeCatalog>(`/v1/auth/oauth/grants/${target.id}/scope-catalog?${params}`)
          if (generation !== scopeGeneration.current) return
          groups.push(...page.items as OAuthScopeGroup[]); cursor = page.next_cursor || ""
        } while (cursor)
        for (const policy of target.server_policies || []) if (!groups.some(group => group.server_id === policy.server_id)) groups.push({ server_id: policy.server_id, server_name: null, tool_count: 0, read_count: 0, write_count: 0 })
        setServerGroups(groups)
        setScopeCatalog(next); setScopeSelection(checked); setScopeOptions(null); setScopeRefreshKey(key => key + 1)
        setRememberedTools(previous => [...new Map([...previous.filter(tool => draft.includes(tool.id)), ...checked.tools].map(tool => [tool.id, tool])).values()])
        applySavedState()
        return
      }
      const next = await oauthRequest<OAuthScopeOptions>(`/v1/auth/oauth/grants/${target.id}/scope-options`)
      if (generation !== scopeGeneration.current) return
      if (next.grant_revision !== target.revision) throw new OAuthRequestError("revision_conflict", 409)
      setRememberedTools(previous => [...new Map([...previous, ...next.tools].map(tool => [tool.id, tool])).values()])
      setScopeOptions(next)
      applySavedState()
    } catch (cause) { if (generation === scopeGeneration.current) { setScopeOptions(null); setScopeCatalog(null); setFormError(oauthError(cause, zh)) } }
    finally { if (generation === scopeGeneration.current) setScopeLoading(false) }
  }
  async function resolveSelection(operation: ScopeSelectionOperation): Promise<OAuthScopeSelection | null> {
    if (selectionLock.current || scopeLoading || busy || !editing || !scopeCatalog) return null
    const generation = scopeGeneration.current, target = editing
    selectionLock.current = true; setScopeLoading(true); setFormError("")
    try {
      const next = await oauthRequest<OAuthScopeSelection>(`/v1/auth/oauth/grants/${target.id}/scope-selection`, {
        csrf: scopeCatalog.csrf, expected_revision: target.revision, catalog_revision: scopeCatalog.catalog_revision,
        tool_ids: selected, ...operation,
      })
      if (generation !== scopeGeneration.current) return null
      setSelected(next.tool_ids); setScopeSelection(next)
      setRememberedTools(previous => [...new Map([...previous.filter(tool => next.tool_ids.includes(tool.id)), ...next.tools].map(tool => [tool.id, tool])).values()])
      return next
    } catch (cause) { if (generation === scopeGeneration.current) {
      setFormError(oauthError(cause, zh))
      if (cause instanceof OAuthRequestError && ["tool_scope_changed", "revision_conflict", "invalid_csrf"].includes(cause.code)) setScopeCatalog(null)
    }; return null }
    finally { selectionLock.current = false; if (generation === scopeGeneration.current) setScopeLoading(false) }
  }
  async function changeServerMode(server: string, mode: McpAuthorizationMode) {
    if (busy || scopeLoading) return
    if (mode !== "selected") {
      if (paged) { const result = await resolveSelection({ mode: "groups", server_ids: [server], checked: false }); if (!result) return }
      else setSelected(ids => ids.filter(id => !editorTools.some(tool => tool.id === id && tool.server_id === server)))
    }
    setModes(current => ({ ...current, [server]: mode })); if (mode === "selected") setToolServer(server)
    setPolicies(current => [...current.filter(policy => policy.server_id !== server), ...(mode === "continuous" ? [{ server_id: server, server_binding: (paged ? serverGroups : scopeOptions?.servers || []).find(group => group.server_id === server)?.server_binding || undefined, mode: "continuous" as const, access: "read" as const }] : [])])
  }
  async function save() {
    if (lock.current || saveUncertain || !editing || scopeLoading || !activeOptions || !validQuotas(rate, concurrency) || (!selected.length && !policies.length) || (unavailableSelected.length > 0 && !quotaOnly)) return
    const target = editing, current = version.current, generation = scopeGeneration.current
    const body = { expected_revision: target.revision, tool_ids: [...selected], server_policies: policies, expires_at: expiry, rate_per_minute: rate, concurrency, ...(scopeCatalog ? { catalog_revision: scopeCatalog.catalog_revision } : {}) }
    lock.current = true; setBusy(true); setFormError(""); setNotice("")
    let writeAttempted = false
    try {
      const preview = await oauthRequest<OAuthScopePreview>(`/v1/auth/oauth/grants/${target.id}/scope-preview`, { ...body, csrf: activeOptions.csrf })
      if (current !== version.current || generation !== scopeGeneration.current) return
      if (!(await confirm({ title: zh ? "确认更新当前连接？" : "Update this connection?",
        description: target.client_name,
        details: <><ScopeDifference before={preview.difference_summary ? target.tools : preview.previous_tools} selected={preview.tool_ids} catalog={preview.tools} zh={zh} summary={preview.difference_summary} addedIds={preview.added} removedIds={preview.removed} /><McpPolicyDifference before={target.server_policies || []} after={preview.server_policies || policies} beforeSelected={target.tools.map(tool => tool.server_id)} afterSelected={Object.keys(modes).filter(id => modes[id] === "selected")} zh={zh} /><p>{zh ? "每分钟" : "Per minute"} {target.rate_per_minute} → {preview.rate_per_minute} · {zh ? "并发" : "Concurrent"} {target.concurrency} → {preview.concurrency}</p><p className="oauth-muted">{zh ? "到期（UTC）：" : "Expiry (UTC): "}{utcGrantTime(preview.expires_at)} · {preview.rate_per_minute} / min · {preview.concurrency} {zh ? "并发" : "concurrent"}</p></>,
        confirmText: zh ? "确认并更新" : "Confirm update", cancelText: t("cancel") }))) return
      if (current !== version.current || generation !== scopeGeneration.current) return
      writeAttempted = true
      const next = await oauthRequest<OAuthGrant>(`/v1/auth/oauth/grants/${target.id}/scope`, { ...body, confirmation: preview.confirmation })
      if (current === version.current && generation === scopeGeneration.current) {
        setGrants(items => items.map(grant => grant.id === next.id ? next : grant)); setSnapshotAt(Math.floor(Date.now() / 1000)); closeEditor()
        setNotice(zh ? "授权已更新" : "Authorization updated"); onChanged?.()
      }
    } catch (cause) { if (current === version.current && generation === scopeGeneration.current) {
      if (writeAttempted && (!(cause instanceof OAuthRequestError) || cause.status === 0 || cause.status >= 500 || cause.code === "invalid_response")) {
        setSaveUncertain(true); setScopeOptions(null); setScopeCatalog(null); setScopeReadNotice(""); setFormError("")
      } else setFormError(oauthError(cause, zh))
    } }
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
      if (current === version.current) { setGrants(items => items.map(item => item.id === next.id ? next : item)); setSnapshotAt(Math.floor(Date.now() / 1000)); onChanged?.() }
    } catch (cause) { if (current === version.current) setError(oauthError(cause, zh)) }
    finally { lock.current = false; if (current === version.current) setBusy(false) }
  }
  useEffect(() => { if (!action) return; if (action.action === "view") view(action.grant); else if (action.action === "revoke") void revoke(action.grant); else if (action.grant.resource_kind === "management") editTargets(action.grant); else edit(action.grant) }, [action?.nonce])
  async function copyId(value: string) {
    const current = viewingGeneration.current
    try { await navigator.clipboard.writeText(value); if (current === viewingGeneration.current) setCopyMessage(zh ? "标识已复制。" : "Identifier copied.") }
    catch { if (current === viewingGeneration.current) setCopyMessage(zh ? "复制失败，请从只读字段手动复制。" : "Copy failed; copy from the read-only field.") }
  }
  return <div className="space-y-4" data-authorization-page={!embedded ? "" : undefined}>
    {!embedded && <>
    <PageHeader title={zh ? "我的 OAuth 授权" : "My OAuth grants"} closeLabel={t("close")} actions={<Button data-authorization-refresh disabled={busy || Boolean(editing) || Boolean(viewing) || Boolean(targetEditing)} onClick={() => void load()}>{t("refresh")}</Button>} />
    <p>{zh ? "这里只展示本人的授权。在 Gate 内明确确认即可增加或减少现有 OAuth scope 内的 MCP 和工具，无需客户端再次 OAuth；可随时撤销。" : "Only your own grants appear here. Explicit confirmation in Gate adds or removes MCPs and tools within existing OAuth scopes, without another client OAuth flow. You can revoke at any time."}</p>
    {error && <Alert type="error" title={error} action={<Button data-authorization-retry disabled={busy} onClick={() => void load()}>{t("retry")}</Button>} />}
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
    </>}
    {embedded && error && <Alert type="error" title={error} />}
    <FormDialog open={Boolean(viewing)} title={zh ? "授权详情" : "Grant details"} closeLabel={t("close")} onClose={closeView} onEscapeKeyDown={preventOAuthMcpPopupDismiss} onCloseAutoFocus={event => { event.preventDefault(); if (viewTrigger.current && document.contains(viewTrigger.current)) viewTrigger.current.focus() }} className="oauth-grant-scope-dialog" bodyClassName={viewing?.resource_kind === "management" ? "oauth-management-target-body" : "oauth-grant-scope-body oauth-grant-details-body"} footer={<Button onClick={closeView}>{t("close")}</Button>}>
      {viewing && <><p>{viewing.client_name} · {stateLabel(grantState(viewing, snapshotAt))}</p><p className="oauth-wrap">{viewing.resource}</p><div className="oauth-grant-identifiers"><label>Grant ID<Input readOnly value={viewing.id} /></label><Button onClick={() => void copyId(viewing.id)}>{zh ? "复制授权 ID" : "Copy grant ID"}</Button><label>Client ID<Input readOnly value={viewing.client_id} /></label><Button onClick={() => void copyId(viewing.client_id)}>{zh ? "复制客户端 ID" : "Copy client ID"}</Button></div>{copyMessage && <p role="status">{copyMessage}</p>}<p className="text-sm">{zh ? "这是已保存的工具范围；历史记录不代表当前仍获准调用。" : "This is recorded tool scope; historical records do not establish current invocation permission."}</p>{viewing.resource_kind === "management" && <ManagementTargetsEditor rows={managementTargetRows(viewing.management_targets || {})} onChange={() => undefined} zh={zh} readOnly />}<OAuthToolPicker key={viewing.id} tools={viewing.tools} selected={[]} onChange={() => undefined} zh={zh} readOnly fillViewport={viewing.resource_kind !== "management"} /></>}
    </FormDialog>
    <ManagementTargetsDialog grant={targetEditing} locale={locale} t={t} onCloseAutoFocus={event => { if (targetTrigger.current?.isConnected) { event.preventDefault(); targetTrigger.current.focus() } }} onClose={() => setTargetEditing(null)} onSaved={next => { onChanged?.(); setGrants(items => items.map(item => item.id === next.id ? next : item)); setSnapshotAt(Math.floor(Date.now() / 1000)); setNotice(zh ? "管理目标已更新；旧计划失效，权限上限未改变。" : "Management targets updated; old plans are stale and scope ceilings unchanged.") }} />
    <FormDialog onCloseAutoFocus={event => { event.preventDefault(); editFocusPending.current = true; restoreEditFocus() }} open={Boolean(editing)} title={zh ? "调整授权范围" : "Adjust authorization scope"} description={editing?.client_name} closeLabel={t("close")} onClose={() => void close()} onEscapeKeyDown={event => { preventOAuthMcpPopupDismiss(event); if (!event.defaultPrevented && scopeInfoOpen) { event.preventDefault(); setScopeInfoOpen(false) } }} dirty={dirty} pending={busy} error={saveUncertain ? [unknownSaveMessage, formError].filter(Boolean).join(" ") : formError} className="oauth-grant-scope-dialog oauth-grant-edit-dialog" bodyClassName="oauth-grant-scope-body oauth-grant-edit-body" footer={<><span className="oauth-grant-delta" role="status">{zh ? `新增 ${addedCount} · 移除 ${removedCount} · 新增写入 ${addedWriteCount}` : `${addedCount} added · ${removedCount} removed · ${addedWriteCount} added write`}</span><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" disabled={busy || saveUncertain || scopeLoading || !dirty || !validQuotas(rate, concurrency) || (!selected.length && !policies.length) || (unavailableSelected.length > 0 && !quotaOnly) || !editing || !activeOptions || grantState(editing, Math.floor(Date.now() / 1000)) !== "active"} onClick={() => void save()}>{zh ? "保存授权" : "Save authorization"}</Button></>}>
      {editing && <>{scopeReadNotice && <p className="oauth-muted oauth-scope-refresh-status" role="status">{scopeReadNotice}</p>}<div className="oauth-grant-context"><ScopeRules summary={stateLabel(grantState(editing, Math.floor(Date.now() / 1000)))} options={activeOptions} grant={editing} loading={scopeLoading} added={addedCount} addedWrite={addedWriteCount} removed={removedCount} zh={zh} open={scopeInfoOpen} onOpenChange={setScopeInfoOpen} />
        {activeOptions && <ScopeAvailability options={activeOptions} grantId={paged ? editing.id : undefined} zh={zh} />}</div>
        {unavailableSelected.length > 0 && <Alert className="oauth-unavailable-selection" type="warning" title={quotaOnly ? zh ? `${unavailableSelected.length} 项当前不可授权；本次仅调整配额，保留原快照，不恢复访问。` : `${unavailableSelected.length} selections are unavailable. This update changes quotas only and preserves original snapshots without restoring access.` : zh ? `${unavailableSelected.length} 项当前不可授权；调整范围前须移除，仅改配额可保留原范围。` : `${unavailableSelected.length} selections are unavailable. Remove them before changing scope; quota-only changes can retain the original scope.`} action={<Button type="link" size="small" disabled={busy || scopeLoading} onClick={() => { if (paged) void resolveSelection({ mode: "ids", tool_ids: selected.filter(id => availableIds.has(id)) }); else setSelected(ids => ids.filter(id => availableIds.has(id))) }}>{zh ? "移除不可授权选择" : "Remove unavailable selections"}</Button>} />}
        <div className="authorization-field"><label>{zh ? "到期时间（UTC）" : "Expiry (UTC)"}</label><Input type="datetime-local" aria-label={zh ? "到期时间（UTC）" : "Expiry (UTC)"} disabled={busy} max={new Date(editing.expires_at * 1000).toISOString().slice(0, 16)} value={new Date(expiry * 1000).toISOString().slice(0, 16)} onChange={event => { const next = Date.parse(`${event.target.value}:00Z`); if (Number.isFinite(next)) setExpiry(Math.floor(next / 1000)) }} /></div>
        <QuotaSettings rate={rate} concurrency={concurrency} onRate={setRate} onConcurrency={setConcurrency} disabled={busy} zh={zh} />
        <Button className="self-start" disabled={busy || scopeLoading} loading={scopeLoading} onClick={() => void readScopeOptions(editing, selected, saveUncertain)}>{zh ? "刷新可授权范围" : "Refresh available scope"}</Button>
        <McpAuthorizationEditor groups={paged ? serverGroups : activeOptions?.servers || policyGroups(editorTools, policies)} policies={policies} modes={modes} onMode={(server, mode) => void changeServerMode(server, mode)} onAccess={(server, access) => setPolicies(items => items.map(policy => policy.server_id === server ? { ...policy, access } : policy))} canWrite={Boolean(activeOptions?.effective_scopes.includes("tools.invoke"))} disabled={busy || scopeLoading || !activeOptions} zh={zh} />
        {Object.values(modes).includes("selected") && <Select aria-label={zh ? "选择工具所属 MCP" : "MCP for tool selection"} value={modes[toolServer] === "selected" ? toolServer : Object.keys(modes).find(id => modes[id] === "selected")} onChange={setToolServer} options={Object.keys(modes).filter(id => modes[id] === "selected").map(value => ({ value, label: serverGroups.find(group => group.server_id === value)?.server_name || value }))} />}
        {Object.values(modes).includes("selected") && (paged ? <OAuthPagedToolPicker serverId={modes[toolServer] === "selected" ? toolServer : Object.keys(modes).find(id => modes[id] === "selected")} key={`${editing.id}:${toolServer}`} grantId={editing.id} catalog={scopeCatalog} selection={scopeSelection} selected={selected} refreshKey={scopeRefreshKey} zh={zh} disabled={busy || scopeLoading} onResolve={resolveSelection} onRefresh={() => void readScopeOptions(editing, selected, saveUncertain)} onCatalog={setScopeCatalog} onLoading={setScopeLoading} onError={cause => { setScopeCatalog(null); setFormError(oauthError(cause, zh)) }} /> : <OAuthToolPicker tools={editorTools.filter(tool => modes[tool.server_id] === "selected")} eligibleTools={eligibleScopeTools} selected={selected} onChange={setSelected} zh={zh} disabled={busy || scopeLoading || !scopeOptions} fillViewport bulkActions compact quickAction={<Button type="text" aria-label={zh ? "刷新可授权范围" : "Refresh available scope"} aria-busy={scopeLoading} loading={scopeLoading} disabled={busy || scopeLoading} onClick={() => void readScopeOptions(editing, selected, saveUncertain)}>{zh ? "刷新可授权范围" : "Refresh available scope"}</Button>} />)}</>}
    </FormDialog>{confirmDialog}<Toaster toast={toast} onClose={dismissToast} closeLabel={t("close")} />
  </div>
}

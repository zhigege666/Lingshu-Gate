import { useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Input, InputNumber, Segmented, Table, Tag } from "antd"
import { PageHeader } from "@/components/page-shell"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { usePageRefresh } from "@/components/page-refresh"
import { OAuthToolPicker } from "@/features/external-connections/oauth-tool-picker"
import { oauthError, oauthRequest, type OAuthGrant } from "@/features/external-connections/oauth-api"
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
  const viewTrigger = useRef<HTMLElement | null>(null)
  const [copyMessage, setCopyMessage] = useState("")
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
    try {
      const result = await oauthRequest<{ grants: OAuthGrant[] }>("/v1/auth/oauth/grants")
      if (current === version.current) { setGrants(result.grants); setSnapshotAt(Math.floor(Date.now() / 1000)) }
    } catch (cause) { if (current === version.current) setError(oauthError(cause, zh)) }
    finally { if (current === version.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { version.current++ } }, [])
  usePageRefresh(load, busy || Boolean(editing) || Boolean(viewing))
  const filtered = useMemo(() => filterGrants(grants, filter, query, snapshotAt), [grants, filter, query, snapshotAt])
  const shownPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / 15)))
  function stateLabel(state: string) { return zh ? ({ active: "有效", revoked: "已撤销", expired: "已过期", disabled: "已关闭" }[state] || state) : ({ active: "Active", revoked: "Revoked", expired: "Expired", disabled: "Disabled" }[state] || state) }
  function view(grant: OAuthGrant) { viewTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setViewing(grant); setCopyMessage("") }
  function edit(grant: OAuthGrant) {
    if (grantState(grant, Math.floor(Date.now() / 1000)) !== "active") return
    setEditing(grant); setSelected(grant.tools.map(tool => tool.id)); setExpiry(grant.expires_at); setRate(grant.rate_per_minute); setConcurrency(grant.concurrency); setFormError("")
  }
  async function save() {
    if (lock.current || !editing) return
    const target = editing, current = version.current
    lock.current = true; setBusy(true); setFormError("")
    try {
      if (!(await confirm({ title: zh ? "保存缩小后的授权？" : "Save reduced grant?", description: `${target.client_name} — ${zh ? "只保存更小的工具范围、期限或配额；不会恢复失去的权限。扩大范围须重新授权。" : "Save only reduced tools, expiry or quotas. Lost permissions are not restored; broader access requires new consent."}`, confirmText: zh ? "保存缩小后的授权" : "Save reduced grant", cancelText: t("cancel") }))) return
      if (current !== version.current) return
      const next = await oauthRequest<OAuthGrant>(`/v1/auth/oauth/grants/${target.id}`, { expected_revision: target.revision, tool_ids: selected, expires_at: expiry, rate_per_minute: rate, concurrency }, "PATCH")
      if (current === version.current) { setGrants(items => items.map(grant => grant.id === next.id ? next : grant)); setSnapshotAt(Math.floor(Date.now() / 1000)); setEditing(null) }
    } catch (cause) { if (current === version.current) setFormError(oauthError(cause, zh)) }
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
    try { await navigator.clipboard.writeText(value); setCopyMessage(zh ? "标识已复制。" : "Identifier copied.") }
    catch { setCopyMessage(zh ? "复制失败，请从只读字段手动复制。" : "Copy failed; copy from the read-only field.") }
  }
  return <div className="space-y-4">
    <PageHeader title={zh ? "我的 OAuth 授权" : "My OAuth grants"} closeLabel={t("close")} actions={<Button disabled={busy || Boolean(editing) || Boolean(viewing)} onClick={() => void load()}>{t("refresh")}</Button>} />
    <p>{zh ? "这里只展示本人的授权。可查看已保存范围、缩小有效授权或撤销；新增工具与扩大范围需要重新授权。" : "Only your own grants appear here. Review recorded scope, reduce active grants or revoke. New tools and expanded access require new authorization."}</p>
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
        { title: t("actions"), width: 290, render: (_, grant) => <div className="flex flex-wrap gap-2"><Button size="small" disabled={busy} onClick={() => view(grant)}>{zh ? "详情" : "Details"}</Button>{grantState(grant, snapshotAt) === "active" && <><Button size="small" disabled={busy} onClick={() => edit(grant)}>{zh ? "缩小范围" : "Reduce scope"}</Button><Button size="small" danger disabled={busy} onClick={() => void revoke(grant)}>{zh ? "撤销" : "Revoke"}</Button></>}</div> },
      ]} />
    <FormDialog open={Boolean(viewing)} title={zh ? "授权详情" : "Grant details"} closeLabel={t("close")} onClose={() => setViewing(null)} onCloseAutoFocus={event => { event.preventDefault(); if (viewTrigger.current && document.contains(viewTrigger.current)) viewTrigger.current.focus() }} className="max-w-5xl" footer={<Button onClick={() => setViewing(null)}>{t("close")}</Button>}>
      {viewing && <><p>{viewing.client_name} · {stateLabel(grantState(viewing, snapshotAt))}</p><p className="oauth-wrap">{viewing.resource}</p><div className="oauth-grant-identifiers"><label>Grant ID<Input readOnly value={viewing.id} /></label><Button onClick={() => void copyId(viewing.id)}>{zh ? "复制授权 ID" : "Copy grant ID"}</Button><label>Client ID<Input readOnly value={viewing.client_id} /></label><Button onClick={() => void copyId(viewing.client_id)}>{zh ? "复制客户端 ID" : "Copy client ID"}</Button></div>{copyMessage && <p role="status">{copyMessage}</p>}<p className="text-sm">{zh ? "这是已保存的工具范围；历史记录不代表当前仍获准调用。" : "This is recorded tool scope; historical records do not establish current invocation permission."}</p><OAuthToolPicker key={viewing.id} tools={viewing.tools} selected={[]} onChange={() => undefined} zh={zh} readOnly /></>}
    </FormDialog>
    <FormDialog open={Boolean(editing)} title={zh ? "查看 / 缩小授权" : "View / reduce grant"} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={formError} className="max-w-5xl" footer={<><Button disabled={busy} onClick={() => void close()}>{t("close")}</Button><Button type="primary" disabled={busy || !dirty || !selected.length || !editing || grantState(editing, Math.floor(Date.now() / 1000)) !== "active"} onClick={() => void save()}>{zh ? "保存缩小后的授权" : "Save reduced grant"}</Button></>}>
      {editing && <><p className="oauth-wrap">{editing.client_name} · {editing.resource}</p>{!editing.scope_currently_authorized && <Alert type="warning" title={zh ? `当前只有 ${editing.effective_tool_count} 个工具仍获准。保存范围不会恢复已失去的权限。` : `Only ${editing.effective_tool_count} tools are currently authorized. Saving scope does not restore lost permissions.`} />}<OAuthToolPicker tools={editing.tools} selected={selected} onChange={setSelected} zh={zh} disabled={busy} /><div className="grid gap-4 sm:grid-cols-3"><label>{zh ? "到期时间（UTC）" : "Expiry (UTC)"}<Input type="datetime-local" disabled={busy} max={new Date(editing.expires_at * 1000).toISOString().slice(0, 16)} value={new Date(expiry * 1000).toISOString().slice(0, 16)} onChange={event => { const next = Date.parse(`${event.target.value}:00Z`); if (Number.isFinite(next)) setExpiry(Math.floor(next / 1000)) }} /></label><label>{zh ? "每分钟调用上限" : "Calls per minute"}<InputNumber aria-label={zh ? "每分钟调用上限" : "Calls per minute"} disabled={busy} min={1} max={editing.rate_per_minute} precision={0} value={rate} onChange={value => setRate(value ?? 1)} /></label><label>{zh ? "并发上限" : "Concurrent calls"}<InputNumber aria-label={zh ? "并发上限" : "Concurrent calls"} disabled={busy} min={1} max={editing.concurrency} precision={0} value={concurrency} onChange={value => setConcurrency(value ?? 1)} /></label></div></>}
    </FormDialog>{confirmDialog}
  </div>
}

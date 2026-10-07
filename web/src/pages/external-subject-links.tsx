import { TableEmptyRow } from "@/pages/page-utils"
import { ExternalUserSelector } from "@/components/external-user-selector"
import { useEffect, useRef, useState } from "react"
import { Alert, Button, Input, Select, Switch, Tag, Typography } from "antd"
import { externalRequest as request, externalError } from "@/features/external-connections/api"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { RemainingList, ListPagination, ListViewport } from "@/components/list-pagination"
import { PageToolbar } from "@/components/page-shell"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { bindingUserLabel, type BindingUser, type SubjectLink } from "@/features/external-connections/model"
import type { Locale, TFunction } from "@/i18n"

type LinkInput = { issuer: string; subject: string; user_id: string; enabled: boolean }
const empty: LinkInput = { issuer: "", subject: "", user_id: "", enabled: false }
export function ExternalSubjectLinks({ locale, t, issuers }: { locale: Locale; t: TFunction; issuers: string[] }) {
  const zh = locale === "zh-CN"
  const [links, setLinks] = useState<SubjectLink[]>([])
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [selectedUser, setSelectedUser] = useState<BindingUser | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState(empty)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const pending = useRef(false)
  const generation = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const dirty = JSON.stringify(draft) !== JSON.stringify(empty)
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: () => setOpen(false) })
  const paging = { items: links, viewport, page, pageCount: Math.max(1, Math.ceil(total / 50)), total,
    start: total ? (page - 1) * 50 + 1 : 0, end: Math.min(page * 50, total), setPage }
  async function load() {
    const version = ++generation.current
    setBusy(true); setError("")
    try { const result = await request<{ links: SubjectLink[]; total: number }>(`/v1/auth/external-subject-links?${new URLSearchParams({ q: query, offset: String((page - 1) * 50), limit: "50" })}`); if (version === generation.current) { setLinks(result.links); setTotal(result.total) } }
    catch (cause) { if (version === generation.current) setError(externalError(cause, zh)) }
    finally { if (version === generation.current) setBusy(false) }
  }
  useEffect(() => {
    generation.current++; setLinks([]); setTotal(0); setBusy(true)
    if (viewport.current) viewport.current.scrollTop = 0
    const timer = window.setTimeout(() => void load(), query ? 200 : 0)
    return () => { generation.current++; window.clearTimeout(timer) }
  }, [query, page])
  async function save() {
    if (pending.current) return
    if (!issuers.includes(draft.issuer) || !draft.subject.trim() || !draft.user_id.trim()) { setFormError(zh ? "选择受信签发方、Gate 用户并输入准确的 subject。" : "Select a trusted issuer and Gate user, and enter the exact subject."); return }
    pending.current = true; setBusy(true); setFormError("")
    try {
      if (!(await confirm({ title: zh ? "确认外部身份绑定？" : "Confirm external identity binding?", description: `${draft.issuer}\n${draft.subject} → ${bindingUserLabel(selectedUser)} · ${draft.user_id}\n${zh ? "启用后该已验证身份可在个人授权范围内作为此用户调用。请核对身份，不以电子邮箱推断 subject。" : "When enabled, this verified identity can call as this user within personal grants. Verify the identity; do not infer the subject from email."}` }))) return
      const result = await request<SubjectLink>("/v1/auth/external-subject-links", { method: "POST", body: JSON.stringify(draft) })
      if (result.enabled !== draft.enabled) throw new Error("Identity binding state unknown")
      setOpen(false); await load()
    } catch (cause) { setFormError(externalError(cause, zh)) }
    finally { pending.current = false; setBusy(false) }
  }
  async function toggle(item: SubjectLink) {
    if (pending.current) return
    pending.current = true
    try {
      if (!item.enabled && !(await confirm({ title: zh ? "启用身份绑定？" : "Enable identity binding?", description: `${item.issuer}\n${item.subject} → ${bindingUserLabel(item.user)} · ${item.user_id}` }))) return
      setBusy(true); setError("")
      const result = await request<SubjectLink>(`/v1/auth/external-subject-links/${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled, expected_revision: item.revision }) })
      if (result.enabled !== !item.enabled) throw new Error("Identity binding state unknown")
      setLinks(current => current.map(link => link.id === item.id ? result : link))
    } catch (cause) { setError(externalError(cause, zh)) }
    finally { pending.current = false; setBusy(false) }
  }
  return <section className="space-y-3" aria-label={zh ? "OAuth 身份绑定" : "OAuth identity bindings"}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{zh ? "OAuth 身份绑定" : "OAuth identity bindings"}</h2><div className="flex gap-2"><Button disabled={busy || open} onClick={() => void load()}>{t("refresh")}</Button><Button disabled={busy || !issuers.length} onClick={() => { setDraft(empty); setSelectedUser(null); setFormError(""); setOpen(true) }}>{zh ? "添加身份绑定" : "Add identity binding"}</Button></div></div>
    <p className="text-sm">{zh ? "仅绑定受信且签名验证后的 (issuer, subject) 到 Gate 用户。身份绑定不是 OAuth 提供方登录或同意授权。" : "Bind a trusted, signature-verified (issuer, subject) to a Gate user. A binding is not provider sign-in or OAuth consent."}</p>
    {!issuers.length && <Alert type="warning" title={zh ? "请先保存受信 issuer 配置。" : "Save trusted issuer configuration first."} />}
    {error && <Alert type="error" title={error} />}
    <PageToolbar query={query} onQueryChange={value => { setQuery(value); setPage(1) }} placeholder={zh ? "搜索签发方、subject、用户名称或 ID" : "Search issuer, subject, user name or ID"} clearLabel={t("clearSearch")} />
    <RemainingList standaloneSection>
    <ListViewport viewport={paging.viewport} label={zh ? "身份绑定列表" : "Identity binding list"}><Table><TableHeader><TableRow><TableHead>Issuer / subject</TableHead><TableHead>{zh ? "Gate 用户" : "Gate user"}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader><TableBody>{!links.length && <TableEmptyRow colSpan={4} title={busy ? (zh ? "正在加载…" : "Loading…") : error ? (zh ? "加载失败，请重试" : "Could not load. Please retry.") : query.trim() ? t("noMatchingRecords") : zh ? "尚无身份绑定。" : "No identity bindings yet."} />}{paging.items.map(item => <TableRow key={item.id}><TableCell><span className="break-all">{item.issuer}</span><p>{item.subject}</p></TableCell><TableCell><div className="break-words font-medium">{bindingUserLabel(item.user, zh ? "用户不可用" : "User unavailable")}</div><Typography.Text type="secondary" copyable={{ text: item.user_id, tooltips: [zh ? "复制用户 ID" : "Copy user ID", zh ? "已复制" : "Copied"] }} className="break-all text-xs">{item.user_id}</Typography.Text>{item.user && item.user.status !== "active" && <Tag>{item.user.status}</Tag>}</TableCell><TableCell><Tag>{item.enabled ? (zh ? "已启用" : "Enabled") : (zh ? "已关闭" : "Disabled")}</Tag></TableCell><TableCell><Button disabled={busy} onClick={() => void toggle(item)}>{item.enabled ? (zh ? "关闭" : "Disable") : (zh ? "启用" : "Enable")}</Button></TableCell></TableRow>)}</TableBody></Table></ListViewport><ListPagination paging={paging} t={t} />
    </RemainingList>
    <FormDialog className="overflow-visible" open={open} title={zh ? "添加外部身份绑定" : "Add external identity binding"} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={formError} footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button type="primary" htmlType="submit" form="subject-link" loading={busy}>{t("save")}</Button></>}>
      <form id="subject-link" className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); void save() }}>
        <label className="flex flex-col gap-2">Issuer<Select getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} aria-label="Issuer" disabled={busy} value={draft.issuer || undefined} options={issuers.map(issuer => ({ value: issuer, label: issuer }))} onChange={issuer => setDraft(current => ({ ...current, issuer }))} /></label>
        <label className="flex flex-col gap-2">Subject<Input disabled={busy} value={draft.subject} onChange={event => setDraft(current => ({ ...current, subject: event.target.value }))} /></label>
        {open && <ExternalUserSelector value={selectedUser} zh={zh} disabled={busy} onChange={user => { setSelectedUser(user); setDraft(current => ({ ...current, user_id: user?.id || "" })) }} />}
        <label className="flex items-center gap-3">{zh ? "启用此身份绑定" : "Enable this identity binding"}<Switch aria-label={zh ? "启用此身份绑定" : "Enable this identity binding"} disabled={busy} checked={draft.enabled} onChange={enabled => setDraft(current => ({ ...current, enabled }))} /></label>
      </form>
    </FormDialog>{confirmDialog}
  </section>
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Pencil, Settings2 } from "lucide-react"
import { api, type ToolClassification } from "@/api/client"
import { useRemainingViewport } from "@/components/use-remaining-viewport"
import { ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import { usePageRefresh } from "@/components/page-refresh"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { FormDialog } from "@/components/form-dialog"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { FilterRadio } from "@/components/filter-radio"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { Toaster } from "@/components/ui/toast"
import { JsonPanel } from "@/components/json-panel"
import { TableEmptyRow } from "@/pages/page-utils"
import { classificationOriginName } from "@/features/tool-origin"
import { effectiveToolPolicy, toolPolicyMode, saveToolPolicyBatch, type ToolPolicyMode } from "@/features/tool-policy"
import type { Locale, TFunction } from "@/i18n"
import "./tool-classifications-page.css"

export function ToolClassificationsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const zh = locale === "zh-CN"
  const workspace = useRemainingViewport()
  const [items, setItems] = useState<ToolClassification[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [server, setServer] = useState("all")
  const [filter, setFilter] = useState("all")
  const [query, setQuery] = useState("")
  const [editing, setEditing] = useState<ToolClassification[]>([])
  const [batchSession, setBatchSession] = useState(false)
  const [mode, setMode] = useState<ToolPolicyMode>("automatic")
  const [note, setNote] = useState("")
  const [destructive, setDestructive] = useState(false)
  const [idempotent, setIdempotent] = useState(false)
  const [initial, setInitial] = useState("")
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [formError, setFormError] = useState("")
  const [message, setMessage] = useState("")
  const generation = useRef(0)
  const submitting = useRef(false)
  const trigger = useRef<HTMLElement | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)
  const draft = JSON.stringify({ mode, note, destructive, idempotent })
  const close = useDraftCloseGuard({ dirty: editing.length > 0 && draft !== initial, pending: saving, locale, confirm,
    onClose: () => { setEditing([]); setFormError("") } })
  const load = useCallback(async () => {
    const request = ++generation.current
    setBusy(true); setError("")
    try {
      const result = await api.toolClassifications()
      if (generation.current !== request) return
      setItems(result.classifications)
      setSelectedIds(current => current.filter(id => result.classifications.some(item => item.id === id)))
    } catch (cause) { if (generation.current === request) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { if (generation.current === request) setBusy(false) }
  }, [])
  useEffect(() => { void load(); return () => { generation.current++ } }, [load])
  usePageRefresh(load, busy || saving || editing.length > 0)
  const editable = (item: ToolClassification) => item.policy_editable !== false && item.policy_source !== "unavailable"
  const selected = items.filter(item => selectedIds.includes(item.id) && editable(item))
  const servers = [...new Set(items.map(item => item.server_id))].sort()
  const visible = useMemo(() => items.filter(item => {
    if (server !== "all" && item.server_id !== server) return false
    if (filter !== "all" && effectiveToolPolicy(item) !== filter) return false
    return !query.trim() || `${item.tool_name} ${item.tool_id} ${item.server_id} ${classificationOriginName(item, locale) || ""}`.toLowerCase().includes(query.trim().toLowerCase())
  }).sort((a, b) => a.server_id.localeCompare(b.server_id) || a.tool_name.localeCompare(b.tool_name)), [items, server, filter, query, locale])
  const paging = useListPage(visible, JSON.stringify([query, server, filter]))
  const selectableVisible = paging.items.filter(editable)
  const selectedVisible = selectableVisible.filter(item => selectedIds.includes(item.id)).length
  const allVisible = selectableVisible.length > 0 && selectedVisible === selectableVisible.length
  function togglePage(checked: boolean) {
    const ids = selectableVisible.map(item => item.id)
    setSelectedIds(current => checked ? [...new Set([...current, ...ids])] : current.filter(id => !ids.includes(id)))
  }
  function open(targets: ToolClassification[], element: HTMLElement) {
    if (!targets.length || saving || targets.some(item => !editable(item))) return
    trigger.current = element
    setBatchSession(targets.length > 1)
    const next = targets.length === 1 ? toolPolicyMode(targets[0]) : "automatic"
    setMode(next); setNote(""); setDestructive(targets[0].destructive); setIdempotent(targets[0].idempotent)
    setInitial(JSON.stringify({ mode: next, note: "", destructive: targets[0].destructive, idempotent: targets[0].idempotent }))
    setFormError(""); setEditing(targets.map(item => ({ ...item })))
  }
  async function save() {
    if (!editing.length || submitting.current) return
    submitting.current = true; setSaving(true); setFormError("")
    try {
      const targets = !batchSession ? [{ ...editing[0], destructive, idempotent }] : editing
      const result = await saveToolPolicyBatch(targets, mode, note, api.updateToolClassification)
      const saved = new Map(result.saved.map(item => [item.id, item]))
      setItems(current => current.map(item => saved.get(item.id) || item))
      setSelectedIds(current => current.filter(id => !saved.has(id)))
      if (result.failed.length) {
        setEditing(result.failed.map(item => item.item))
        setFormError(`${zh ? "已保存" : "Saved"} ${result.saved.length}${zh ? "；" : "; "}${zh ? "未完成" : "Unfinished"} ${result.failed.length}${zh ? "。" : ". "}${result.failed.slice(0, 3).map(item => `${item.item.tool_name}: ${item.error}`).join("; ")}`)
      } else {
        setEditing([])
        setMessage(zh ? `已保存并生效 · ${result.saved.length} 个工具` : `Saved and active · ${result.saved.length} tools`)
      }
    } finally { submitting.current = false; setSaving(false) }
  }
  async function reloadUnfinished() {
    if (submitting.current) return
    submitting.current = true; setSaving(true)
    try {
      const result = await api.toolClassifications()
      const ids = new Set(editing.map(item => item.id))
      const current = result.classifications.filter(item => ids.has(item.id) && editable(item))
      setItems(result.classifications); setEditing(current)
      setFormError(zh ? "已读取最新版本，请核对后重新保存未完成项。" : "Latest versions loaded. Review and save the unfinished items again.")
      if (!current.length) { setEditing([]); setError(zh ? "未完成工具已从目录移除。" : "The unfinished tools were removed from the catalog.") }
    } catch (cause) { setFormError(cause instanceof Error ? cause.message : String(cause)) }
    finally { submitting.current = false; setSaving(false) }
  }
  const accessLabel = (access: string) => access === "read" ? (zh ? "只读" : "Read only") : access === "write" ? (zh ? "读写" : "Read and write") : (zh ? "已禁用" : "Disabled")
  const sourceLabel = (item: ToolClassification) => item.policy_constraint === "control_permission" ? (zh ? "专用管理权限" : "Control permission") : item.policy_source === "builtin_contract" ? (zh ? "内置策略" : "Built-in policy") : toolPolicyMode(item) === "automatic" ? (zh ? "自动默认" : "Automatic") : (zh ? "自定义" : "Custom")
  return <div ref={workspace} className="tool-review-workspace flex flex-col gap-4">
    <PageHeader title={zh ? "工具权限" : "Tool access"} toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={zh ? "搜索工具或服务" : "Search tools or services"} clearLabel={t("clearSearch")} resultCount={visible.length} resultLabel={zh ? "个工具" : "tools"} resetFilters={{ label: t("resetFilters"), disabled: !query && server === "all" && filter === "all", onReset: () => { setQuery(""); setServer("all"); setFilter("all") } }}>
      <Select value={server} onValueChange={setServer}><SelectTrigger className="tool-review-source-filter" aria-label={zh ? "筛选服务" : "Filter service"}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{zh ? "全部服务" : "All services"}</SelectItem>{servers.map(id => <SelectItem key={id} value={id}>{id}</SelectItem>)}</SelectContent></Select>
      <FilterRadio label={zh ? "权限" : "Access"} value={filter} onChange={setFilter} options={[{ value: "all", label: t("all") }, { value: "read", label: accessLabel("read") }, { value: "write", label: accessLabel("write") }, { value: "none", label: accessLabel("none") }]} />
    </PageToolbar>} />
    <p className="text-sm text-muted-foreground">{zh ? "工具连接后自动同步。新增外部工具默认需要读写授权；需要调整时在这里设置，保存后立即生效。" : "Tools synchronize automatically. New external tools require write access by default. Optional overrides take effect on save."}</p>
    {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription><Button variant="outline" size="sm" onClick={() => void load()}>{t("refresh")}</Button></Alert>}
    {selected.length > 0 && <div className="tool-policy-selection" role="region" aria-label={zh ? "所选工具操作" : "Selected tool actions"}>
      <span role="status">{zh ? `已选 ${selected.length} 项` : `${selected.length} selected`}{selected.length > selectedVisible ? (zh ? `（含当前页外 ${selected.length - selectedVisible} 项）` : ` (${selected.length - selectedVisible} outside this page)`) : ""}</span>
      <Button variant="ghost" size="sm" disabled={saving} onClick={() => setSelectedIds([])}>{zh ? "取消选择" : "Clear selection"}</Button>
      <Button size="sm" disabled={saving} onClick={event => open(selected, event.currentTarget)}><Settings2 />{zh ? "设置权限" : "Set access"}</Button>
    </div>}
    <div className="tool-review-card rounded-lg border">
      <div className="tool-review-content">
        <ListViewport viewport={paging.viewport} label={zh ? "工具权限" : "Tool access"}>
          <Table className="tool-review-table"><TableHeader><TableRow>
            <TableHead className="w-12"><input type="checkbox" aria-label={zh ? "选择本页工具" : "Select tools on this page"} checked={allVisible} ref={node => { if (node) node.indeterminate = selectedVisible > 0 && !allVisible }} disabled={busy || saving || !selectableVisible.length} onChange={event => togglePage(event.target.checked)} /></TableHead>
            <TableHead>{zh ? "工具" : "Tool"}</TableHead><TableHead>{zh ? "服务" : "Service"}</TableHead><TableHead>{zh ? "所需权限" : "Required access"}</TableHead><TableHead>{zh ? "策略" : "Policy"}</TableHead><TableHead>{t("actions")}</TableHead>
          </TableRow></TableHeader><TableBody>
            {paging.items.map(item => <TableRow key={item.id} data-state={selectedIds.includes(item.id) ? "selected" : undefined}>
              <TableCell>{editable(item) && <input type="checkbox" aria-label={`${zh ? "选择工具" : "Select tool"} ${item.tool_name}`} checked={selectedIds.includes(item.id)} disabled={saving} onChange={event => setSelectedIds(current => event.target.checked ? [...new Set([...current, item.id])] : current.filter(id => id !== item.id))} />}</TableCell>
              <TableCell><div className="font-medium">{item.tool_name}</div>{item.tool_id !== item.tool_name && <div className="truncate text-xs text-muted-foreground" title={item.tool_id}>{item.tool_id}</div>}</TableCell>
              <TableCell><div>{classificationOriginName(item, locale) || item.server_id}</div>{classificationOriginName(item, locale) && classificationOriginName(item, locale) !== item.server_id && <div className="truncate text-xs text-muted-foreground" title={item.server_id}>{item.server_id}</div>}</TableCell>
              <TableCell><Badge variant={effectiveToolPolicy(item) === "none" ? "secondary" : effectiveToolPolicy(item) === "read" ? "success" : "outline"}>{accessLabel(effectiveToolPolicy(item))}</Badge></TableCell>
              <TableCell className="text-muted-foreground">{sourceLabel(item)}</TableCell>
              <TableCell>{editable(item) ? <Button variant="ghost" size="sm" disabled={saving} onClick={event => open([item], event.currentTarget)} aria-label={`${zh ? "设置权限" : "Set access"} · ${item.tool_name}`}><Pencil />{zh ? "设置" : "Edit"}</Button> : <span className="text-xs text-muted-foreground">{item.policy_constraint === "control_permission" ? (zh ? "按角色管理" : "Role managed") : (zh ? "不可用" : "Unavailable")}</span>}</TableCell>
            </TableRow>)}
            {!paging.items.length && <TableEmptyRow colSpan={6} title={busy ? t("loadingData") : query || filter !== "all" || server !== "all" ? t("noMatchingRecords") : t("noData")} />}
          </TableBody></Table>
        </ListViewport>
        <ListPagination paging={paging} t={t} />
      </div>
    </div>
    <FormDialog open={editing.length > 0} title={editing.length === 1 ? `${zh ? "工具权限" : "Tool access"} · ${editing[0]?.tool_name}` : (zh ? `设置 ${editing.length} 个工具的权限` : `Set access for ${editing.length} tools`)} closeLabel={t("close")} onClose={() => void close()} dirty={draft !== initial} pending={saving}
      onCloseAutoFocus={event => { if (trigger.current?.isConnected && !trigger.current.matches(":disabled")) { event.preventDefault(); trigger.current.focus() } }}
      footer={<><Button variant="outline" disabled={saving} onClick={() => void close()}>{t("cancel")}</Button><Button disabled={saving} onClick={() => void save()}>{saving ? (zh ? "保存中…" : "Saving…") : (zh ? "保存并生效" : "Save and apply")}</Button></>}>
      <div className="gate-form-fields">
        {editing.length === 1 && <div className="text-sm"><p className="font-medium">{classificationOriginName(editing[0], locale) || editing[0].server_id}</p><p className="break-all font-mono text-xs text-muted-foreground">{editing[0].server_id} / {editing[0].tool_id}</p></div>}
        {editing.length > 1 && <details><summary className="cursor-pointer text-sm">{zh ? `查看 ${editing.length} 个目标工具` : `View ${editing.length} target tools`}</summary><ul className="mt-2 max-h-40 overflow-auto text-xs">{editing.map(item => <li className="break-all py-1" key={item.id}>{item.server_id} / {item.tool_id}</li>)}</ul></details>}
        {formError && <Alert variant="destructive"><AlertDescription>{formError}</AlertDescription><Button type="button" variant="outline" size="sm" disabled={saving} onClick={() => void reloadUnfinished()}>{zh ? "刷新未完成项" : "Refresh unfinished tools"}</Button></Alert>}
        <div className="gate-form-row"><span className="gate-form-label">{zh ? "权限策略" : "Access policy"}</span><div className="gate-form-control"><FilterRadio id="tool-policy-mode" label={zh ? "权限策略" : "Access policy"} hideLabel value={mode} onChange={value => setMode(value as ToolPolicyMode)} disabled={saving} options={[{ value: "automatic", label: zh ? "自动默认" : "Automatic default" }, { value: "read", label: zh ? "只读" : "Read only" }, { value: "write", label: zh ? "读写" : "Read and write" }, { value: "unknown", label: zh ? "禁用" : "Disabled" }]} />
          <p className="gate-form-help">{mode === "automatic" ? (zh ? "外部工具默认要求读写授权；内置工具使用自身策略。" : "External tools require write access; built-in tools use their own policy.") : mode === "read" ? (zh ? "现有只读授权将可以调用这些工具，请确认工具不会修改数据。" : "Existing read grants will be able to invoke these tools. Check that they do not change data.") : mode === "unknown" ? (zh ? "这些工具将不可调用；授权记录保留，但恢复后指定工具授权可能需要重新选择。" : "These tools cannot be invoked. Grants remain stored, but exact tool authorizations may need reselection after restoring access.") : (zh ? "只有具备读写授权的账号和客户端可以调用。" : "Invocations require write access for both the account and client.")}</p>
        </div></div>
        <div className="gate-form-row"><Label className="gate-form-label" htmlFor="tool-policy-note">{zh ? "备注" : "Note"}</Label><Textarea id="tool-policy-note" value={note} onChange={event => setNote(event.target.value)} disabled={saving} placeholder={zh ? "可选" : "Optional"} /></div>
        {!batchSession && editing.length === 1 && <details><summary className="cursor-pointer text-sm text-muted-foreground">{zh ? "高级：工具安全信息" : "Advanced: tool safety information"}</summary><div className="mt-4 gate-form-fields">
          <div className="gate-form-row"><Label className="gate-form-label" htmlFor="policy-destructive">{zh ? "会改变系统状态" : "Changes state"}</Label><Switch id="policy-destructive" checked={destructive} onCheckedChange={setDestructive} disabled={saving} /></div>
          <div className="gate-form-row"><Label className="gate-form-label" htmlFor="policy-idempotent">{zh ? "幂等" : "Idempotent"}</Label><Switch id="policy-idempotent" checked={idempotent} onCheckedChange={setIdempotent} disabled={saving} /></div>
          <p className="text-xs text-muted-foreground">{zh ? "幂等标记不允许重放写调用；自动重试仍仅限可信只读策略且合同未变。" : "Idempotency does not enable write replay. Automatic retry still requires a trusted read policy and an unchanged contract."}</p>
          <JsonPanel data={editing[0]?.evidence || {}} copyLabel={t("copy")} maxHeight="max-h-64" />
        </div></details>}
      </div>
    </FormDialog>
    {confirmDialog}<Toaster toast={message ? { message, tone: "success" } : null} onClose={() => setMessage("")} />
  </div>
}

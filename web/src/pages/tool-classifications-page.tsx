import { usePageRefresh } from "@/components/page-refresh"
import { useEffect, useMemo, useRef, useState } from "react"
import { BadgeCheck, CheckCheck, ListChecks, ScanSearch } from "lucide-react"
import { api, type ToolClassification } from "@/api/client"
import { useConfirm } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { Toaster, type ToastState } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    title: "工具读写分类",
    help: "分类说明",
    description: "先读取 MCP 工具标注并运行内部规则，最后由人工确认发布。只有已发布的只读或读写分类才进入运行时授权。",
    pending: "待审核",
    published: "已发布",
    stale: "已失效",
    unknown: "待判定",
    server: "来源",
    tool: "工具",
    suggestion: "机器建议",
    effective: "最终分类",
    confidence: "置信度",
    evidence: "证据",
    flags: "风险标记",
    source: "来源",
    analyzeRules: "运行规则分析",
    batchClassify: "批量设置",
    batchDescription: "为所选工具统一设置最终分类。每条工具已有的“会改变系统状态”和“可安全重试”标记保持不变；已发布工具更新后会回到待发布状态。",
    batchAccess: "批量分类结果",
    batchNote: "批量审核说明",
    batchNotePlaceholder: "可选：记录本次批量判断的依据",
    batchPendingHint: "选择“待判定”会把工具退回人工审核，退回后不能发布。",
    applyBatch: "应用到所选工具",
    batchSaved: "已批量更新",
    batchFailed: "条更新失败，请重试",
    saving: "正在保存…",
    confirmSelected: "批量确认",
    confirmDescription: "逐条保留每个工具已保存的人工读写结论；没有人工结论时，采纳该工具的规则建议。确认后仍需单独发布才会生效。",
    confirmSaved: "已批量确认",
    confirmSkipped: "条仍待判定，已保留选择",
    confirmAvailable: "可批量确认",
    confirmedPending: "已确认待发布",
    needsConfirmation: "待确认",
    selectVisible: "选择当前视图",
    publishSelected: "发布所选",
    publishConfirm: "发布后会立即进入 REST 与 MCP Gateway 的运行时授权判断。请确认人工分类与风险标记已经复核。",
    edit: "人工确认",
    note: "审核说明",
    destructive: "会改变系统状态",
    idempotent: "可安全重试",
    saveDecision: "保存人工判断",
    allServers: "全部 MCP 服务",
    allStatuses: "全部状态",
    search: "搜索来源或工具",
    noData: "暂无工具分类",
    selectHint: "可先批量设置或按各自机器建议批量确认，再单独发布；工具元数据变化后会自动标记为已失效并停止授权。",
    filterSource: "按 MCP 服务筛选",
    filterStatus: "按显示状态筛选",
    selectRow: "选择工具",
    selectionReady: "勾选工具后可批量分类或发布已确认记录",
    selectionActions: "所选工具操作",
    clearSelection: "取消选择",
    sourceBuiltin: "Lingshu Gate 内置",
    sourceMcp: "下游 MCP",
    readAccess: "只读",
    writeAccess: "读写",
    sourceRule: "内部规则",
    sourceAnnotation: "MCP 标注",
    sourceManual: "人工判断",
    noRiskFlag: "无",
    step1: "MCP 元数据",
    step2: "规则预判",
    step3: "人工确认",
    step4: "发布生效",
  },
  "en-US": {
    title: "Tool Read/Write Classification",
    help: "Classification help",
    description: "Start with MCP annotations and local rules, then publish a human-reviewed decision. Only published read/write results enter enforcement.",
    pending: "Pending",
    published: "Published",
    stale: "Stale",
    unknown: "Unknown",
    server: "MCP Server",
    tool: "Tool",
    suggestion: "Suggestion",
    effective: "Effective",
    confidence: "Confidence",
    evidence: "Evidence",
    flags: "Risk flags",
    source: "Source",
    analyzeRules: "Run rule analysis",
    batchClassify: "Batch set",
    batchDescription: "Apply one effective classification to the selected tools while preserving each tool's destructive and idempotent flags. Updated published tools return to pending.",
    batchAccess: "Batch classification",
    batchNote: "Batch review note",
    batchNotePlaceholder: "Optional: record the rationale for this batch decision",
    batchPendingHint: "Choosing Unknown returns tools to human review and prevents publishing.",
    applyBatch: "Apply to selected tools",
    batchSaved: "Batch updated",
    batchFailed: "updates failed; retry them",
    saving: "Saving…",
    confirmSelected: "Confirm selected",
    confirmDescription: "Keep each tool's saved human decision; when none exists, adopt that tool's rule suggestion. Confirmation stays pending until you publish it separately.",
    confirmSaved: "Batch confirmed",
    confirmSkipped: "still need a decision and remain selected",
    confirmAvailable: "Ready to confirm",
    confirmedPending: "Confirmed · pending publish",
    needsConfirmation: "Needs confirmation",
    selectVisible: "Select visible tools",
    publishSelected: "Publish selected",
    publishConfirm: "Publishing immediately affects REST and MCP Gateway enforcement. Confirm the human classification and risk flags first.",
    edit: "Human review",
    note: "Review note",
    destructive: "Changes system state",
    idempotent: "Safe to retry",
    saveDecision: "Save decision",
    allServers: "All MCP services",
    allStatuses: "All statuses",
    search: "Search source or tool",
    noData: "No tool classifications",
    selectHint: "Batch-set a decision or confirm each tool's own machine suggestion, then publish separately. Metadata changes mark classifications stale and block access.",
    filterSource: "Filter by MCP service",
    filterStatus: "Filter by displayed status",
    selectRow: "Select tool",
    selectionReady: "Select tools to classify in bulk or publish reviewed records",
    selectionActions: "Selected tool actions",
    clearSelection: "Clear selection",
    sourceBuiltin: "Lingshu Gate built-in",
    sourceMcp: "Downstream MCP",
    readAccess: "Read",
    writeAccess: "Read + write",
    sourceRule: "Local rule",
    sourceAnnotation: "MCP annotation",
    sourceManual: "Human decision",
    noRiskFlag: "None",
    step1: "MCP metadata",
    step2: "Rule suggestion",
    step3: "Human confirmation",
    step4: "Publish",
  },
} satisfies Record<Locale, Record<string, string>>

const CONFIRM_BATCH_SIZE = 500
type ClassificationViewStatus = "__all" | "needs_confirmation" | "confirmed_pending" | "stale" | "published"

export function ToolClassificationsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const [items, setItems] = useState<ToolClassification[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [serverFilter, setServerFilter] = useState("__all")
  const [statusFilter, setStatusFilter] = useState<ClassificationViewStatus>("__all")
  const [query, setQuery] = useState("")
  const [editing, setEditing] = useState<ToolClassification | null>(null)
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchAccess, setBatchAccess] = useState<"read" | "write" | "unknown">("read")
  const [batchNote, setBatchNote] = useState("")
  const [batchItems, setBatchItems] = useState<ToolClassification[]>([])
  const [reviewInitial, setReviewInitial] = useState("")
  const [access, setAccess] = useState<"read" | "write" | "unknown">("unknown")
  const [destructive, setDestructive] = useState(false)
  const [idempotent, setIdempotent] = useState(false)
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)
  const submitting = useRef(false)
  const closeBatch = useDraftCloseGuard({
    dirty: batchOpen && (batchAccess !== "read" || batchNote !== ""), pending: busy, locale, confirm,
    onClose: () => { setBatchOpen(false); setBatchItems([]); setFormError(null) },
  })
  const closeReview = useDraftCloseGuard({
    dirty: editing !== null && JSON.stringify({ access, destructive, idempotent, note }) !== reviewInitial,
    pending: busy, locale, confirm,
    onClose: () => { setEditing(null); setFormError(null) },
  })

  const servers = useMemo(() => [...new Set(items.map((item) => item.server_id))].sort(), [items])
  const visibleItems = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return items.filter((item) => {
      if (serverFilter !== "__all" && item.server_id !== serverFilter) return false
      if (statusFilter !== "__all" && classificationViewStatus(item) !== statusFilter) return false
      return !needle || `${item.server_id} ${item.tool_id} ${item.tool_name}`.toLowerCase().includes(needle)
    })
  }, [items, query, serverFilter, statusFilter])
  const selectedItems = useMemo(
    () => items.filter((item) => selectedIds.includes(item.id)),
    [items, selectedIds],
  )
  const publishableSelectedItems = useMemo(
    () => selectedItems.filter((item) => item.status !== "published" && item.effective_access !== "unknown"),
    [selectedItems],
  )
  const confirmableSelectedItems = useMemo(
    () => selectedItems.filter((item) => (
      item.status !== "published"
      && (item.effective_access !== "unknown" || item.suggested_access !== "unknown")
    )),
    [selectedItems],
  )
  const unknownSelectedItems = useMemo(
    () => selectedItems.filter((item) => (
      item.status !== "published"
      && item.effective_access === "unknown"
      && item.suggested_access === "unknown"
    )),
    [selectedItems],
  )
  const publishedSelectedCount = selectedItems.filter((item) => item.status === "published").length
  const selectableVisibleItems = visibleItems
  const selectedVisibleCount = selectableVisibleItems.filter((item) => selectedIds.includes(item.id)).length
  const allVisibleSelected = selectableVisibleItems.length > 0 && selectedVisibleCount === selectableVisibleItems.length
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected

  usePageRefresh(load, busy || batchOpen || editing !== null)
  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const classificationResult = await api.toolClassifications()
      setItems(classificationResult.classifications)
      setSelectedIds((current) => current.filter((id) => classificationResult.classifications.some((item) => item.id === id)))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function analyze() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.analyzeToolClassifications({
        server_id: serverFilter === "__all" ? null : serverFilter,
      })
      setItems(result.classifications)
      setMessage(c.analyzeRules)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function openReview(item: ToolClassification) {
    if (busy) return
    const nextAccess = item.effective_access !== "unknown" ? item.effective_access : item.suggested_access
    setEditing(item)
    setAccess(nextAccess)
    setDestructive(item.destructive)
    setIdempotent(item.idempotent)
    setNote("")
    setFormError(null)
    setReviewInitial(JSON.stringify({ access: nextAccess, destructive: item.destructive, idempotent: item.idempotent, note: "" }))
  }

  async function saveReview() {
    if (!editing || busy || submitting.current || access === "unknown") return
    const target = editing
    const payload = { access, destructive, idempotent, note }
    submitting.current = true
    setBusy(true)
    setFormError(null)
    try {
      await api.updateToolClassification(target.server_id, target.tool_id, payload)
      setMessage(`${t("saved")}: ${target.tool_id}`)
      setEditing(null)
      await load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  function openBatchReview() {
    if (!selectedItems.length || busy) return
    setBatchAccess("read")
    setBatchNote("")
    setBatchItems(selectedItems.map(item => ({ ...item })))
    setFormError(null)
    setBatchOpen(true)
  }

  async function applyBatchReview() {
    if (!batchItems.length || busy || submitting.current) return
    const targets = batchItems
    const decision = { access: batchAccess, note: batchNote }
    submitting.current = true
    setBusy(true)
    setFormError(null)
    try {
      // 限制并发写入数量，避免大批量工具同时更新 SQLite 产生写锁竞争。
      const failed: ToolClassification[] = []
      const failureDetails: string[] = []
      const savedIds = new Set<string>()
      for (let index = 0; index < targets.length; index += 6) {
        const batch = targets.slice(index, index + 6)
        const results = await Promise.allSettled(batch.map((item) => api.updateToolClassification(
          item.server_id,
          item.tool_id,
          {
            access: decision.access,
            destructive: item.destructive,
            idempotent: item.idempotent,
            note: decision.note,
          },
        )))
        results.forEach((result, position) => {
          if (result.status === "rejected") {
            failed.push(batch[position])
            if (failureDetails.length < 3) failureDetails.push(`${batch[position].tool_id}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`)
          }
          else savedIds.add(batch[position].id)
        })
      }
      setSelectedIds(current => current.filter(id => !savedIds.has(id)))
      setBatchItems(failed)
      if (!failed.length) setBatchOpen(false)
      await load()
      if (failed.length > 0) {
        setFormError(`${c.batchSaved}: ${savedIds.size}；${failed.length} ${c.batchFailed}。${failureDetails.join("; ")}`)
      } else {
        setMessage(`${c.batchSaved}: ${targets.length}`)
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  async function confirmSelected() {
    const selected = confirmableSelectedItems
    if (!selected.length) return
    const selectedSnapshotIds = new Set(selectedItems.map((item) => item.id))
    const batchCount = Math.ceil(selected.length / CONFIRM_BATCH_SIZE)
    const selectionDetail = locale === "zh-CN"
      ? `本次可确认 ${selected.length} 条；${unknownSelectedItems.length} 条仍待判定，${publishedSelectedCount} 条已发布不处理。`
      : `${selected.length} can be confirmed; ${unknownSelectedItems.length} still need a decision and ${publishedSelectedCount} published items will not change.`
    const batchDetail = batchCount > 1
      ? locale === "zh-CN"
        ? `系统会自动拆成 ${batchCount} 批，每批最多 ${CONFIRM_BATCH_SIZE} 条并保持批内原子性；若后续批次冲突，已完成批次保留，其余选择会刷新。`
        : `The system will process ${batchCount} batches of up to ${CONFIRM_BATCH_SIZE}, atomically within each batch. If a later batch conflicts, completed batches remain confirmed and the rest refresh.`
      : ""
    if (!(await confirm({
      title: `${c.confirmSelected} (${selected.length})`,
      description: `${c.confirmDescription} ${selectionDetail} ${batchDetail}`.trim(),
    }))) return

    setBusy(true)
    setError(null)
    const confirmedIds = new Set<string>()
    try {
      const remainingIds = new Set(unknownSelectedItems.map((item) => item.id))
      let confirmedCount = 0
      for (let index = 0; index < selected.length; index += CONFIRM_BATCH_SIZE) {
        const batch = selected.slice(index, index + CONFIRM_BATCH_SIZE)
        const batchItemsByKey = new Map(batch.map((item) => [`${item.server_id}\u0000${item.tool_id}`, item]))
        const result = await api.confirmToolClassifications({
          items: batch.map((item) => ({
            server_id: item.server_id,
            tool_id: item.tool_id,
            expected_fingerprint: item.fingerprint,
          })),
        })
        confirmedCount += result.confirmed_count
        for (const item of result.confirmed) confirmedIds.add(item.id)
        for (const skipped of result.skipped) {
          const item = batchItemsByKey.get(`${skipped.server_id}\u0000${skipped.tool_id}`)
          if (!item) continue
          if (skipped.reason === "unknown") remainingIds.add(item.id)
          if (skipped.reason === "published") confirmedIds.add(item.id)
        }
      }
      setSelectedIds((current) => current.filter((id) => (
        !selectedSnapshotIds.has(id) || remainingIds.has(id)
      )))
      await load()
      const remainingCount = remainingIds.size
      setMessage(remainingCount > 0
        ? `${c.confirmSaved}: ${confirmedCount}；${remainingCount} ${c.confirmSkipped}`
        : `${c.confirmSaved}: ${confirmedCount}`)
    } catch (err) {
      // 指纹冲突时刷新最新分类；已成功批次不再保留选择，其余工具可直接重新确认。
      setSelectedIds((current) => current.filter((id) => !confirmedIds.has(id)))
      let refreshed = false
      try {
        const classificationResult = await api.toolClassifications()
        setItems(classificationResult.classifications)
        setSelectedIds((current) => current.filter((id) => (
          !confirmedIds.has(id)
          && classificationResult.classifications.some((item) => item.id === id)
        )))
        refreshed = true
      } catch {
        // 原始批量确认错误优先展示；刷新失败时明确要求人工刷新，避免误报已拿到新 fingerprint。
      }
      const detail = err instanceof Error ? err.message : String(err)
      setError(refreshed
        ? locale === "zh-CN"
          ? `批量确认未全部完成，已刷新最新工具数据；未处理项仍保持选择。${detail}`
          : `Batch confirmation did not finish. Tool data was refreshed and unprocessed items remain selected. ${detail}`
        : locale === "zh-CN"
          ? `批量确认未全部完成，且最新工具数据刷新失败；未处理项仍保持选择，请先手动刷新再重试。${detail}`
          : `Batch confirmation did not finish and tool data could not be refreshed. Unprocessed items remain selected; refresh manually before retrying. ${detail}`)
    } finally {
      setBusy(false)
    }
  }

  async function publish() {
    const selected = publishableSelectedItems
    if (!selected.length) return
    if (!(await confirm({
      title: `${c.publishSelected} (${selected.length})`,
      description: c.publishConfirm,
    }))) return
    setBusy(true)
    setError(null)
    try {
      const groupedServer = new Set(selected.map((item) => item.server_id))
      if (groupedServer.size === 1) {
        await api.publishToolClassifications({ server_id: selected[0].server_id, tool_ids: selected.map((item) => item.tool_id) })
      } else {
        for (const item of selected) {
          await api.publishToolClassifications({ server_id: item.server_id, tool_ids: [item.tool_id] })
        }
      }
      setMessage(`${c.published}: ${selected.length}`)
      setSelectedIds([])
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function toggleSelected(item: ToolClassification, checked: boolean) {
    setSelectedIds((current) => checked ? [...new Set([...current, item.id])] : current.filter((id) => id !== item.id))
  }

  function toggleVisibleSelected(checked: boolean) {
    const visibleIds = selectableVisibleItems.map((item) => item.id)
    setSelectedIds((current) => checked
      ? [...new Set([...current, ...visibleIds])]
      : current.filter((id) => !visibleIds.includes(id)))
  }

  // 筛选不会清空选择；明确提示视图外的已选项，避免用户误判批量操作范围。
  const hiddenSelectedCount = selectedItems.length - selectedVisibleCount
  const selectionSummary = locale === "zh-CN"
    ? `已选 ${selectedItems.length} 项${hiddenSelectedCount > 0 ? `，其中 ${hiddenSelectedCount} 项不在当前筛选结果中` : ""}`
    : `${selectedItems.length} selected${hiddenSelectedCount > 0 ? `, including ${hiddenSelectedCount} outside the current filters` : ""}`
  const toast: ToastState = message ? { message, tone: "success" } : null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={c.title} description={c.description} helpLabel={t("pageHelp")}
        helpContent={<>
          <ol className="list-inside list-decimal space-y-1">{[c.step1, c.step2, c.step3, c.step4].map((step) => <li key={step}>{step}</li>)}</ol>
          <p>{c.selectionReady}</p>
          <p className="text-muted-foreground">{c.selectHint}</p>
        </>}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={c.search} resultCount={visibleItems.length} resultLabel={c.tool} clearLabel={t("clearSearch")}>
            <Select value={serverFilter} onValueChange={setServerFilter}><SelectTrigger aria-label={c.filterSource} className="w-full sm:w-44"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allServers}</SelectItem>{servers.map((server) => <SelectItem key={server} value={server}>{sourceOptionLabel(server, c)}</SelectItem>)}</SelectContent></Select>
            <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as ClassificationViewStatus)}><SelectTrigger aria-label={c.filterStatus} className="w-full sm:w-44"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{c.allStatuses}</SelectItem><SelectItem value="needs_confirmation">{c.needsConfirmation}</SelectItem><SelectItem value="confirmed_pending">{c.confirmedPending}</SelectItem><SelectItem value="stale">{c.stale}</SelectItem><SelectItem value="published">{c.published}</SelectItem></SelectContent></Select>
        </PageToolbar>}
        actions={<>
          <Button variant="outline" onClick={() => void analyze()} disabled={busy}><ScanSearch />{c.analyzeRules}</Button>
        </>}
      />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <Card>
        <div className="flex flex-col gap-3 p-3 md:p-4">
          {selectedItems.length > 0 && <div role="region" aria-label={c.selectionActions} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span role="status">{selectionSummary}</span>
              <Button size="sm" variant="ghost" onClick={() => setSelectedIds([])} disabled={busy}>{c.clearSelection}</Button>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button className="shrink-0" variant="outline" onClick={openBatchReview} disabled={busy}><ListChecks />{c.batchClassify} ({selectedItems.length})</Button>
              <Button className="shrink-0" variant="secondary" onClick={() => void confirmSelected()} disabled={busy || confirmableSelectedItems.length === 0}><BadgeCheck />{c.confirmSelected} ({confirmableSelectedItems.length})</Button>
              <Button className="shrink-0" onClick={() => void publish()} disabled={busy || publishableSelectedItems.length === 0}><CheckCheck />{c.publishSelected} ({publishableSelectedItems.length})</Button>
            </div>
          </div>}
          <div className="overflow-x-auto rounded-lg border">
            <Table className="min-w-[900px] [&_th]:whitespace-nowrap">
              <TableHeader><TableRow><TableHead className="w-10"><input ref={(node) => { if (node) node.indeterminate = someVisibleSelected }} className="size-4 accent-primary" type="checkbox" aria-label={c.selectVisible} title={c.selectVisible} checked={allVisibleSelected} disabled={busy || selectableVisibleItems.length === 0} onChange={(event) => toggleVisibleSelected(event.target.checked)} /></TableHead><TableHead>{c.tool}</TableHead><TableHead>{c.suggestion}</TableHead><TableHead>{c.effective}</TableHead><TableHead>{c.confidence}</TableHead><TableHead>{c.flags}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {visibleItems.length === 0 ? <TableEmptyRow colSpan={8} title={c.noData} /> : visibleItems.map((item) => <TableRow key={item.id}>
                  <TableCell><input className="size-4 accent-primary" type="checkbox" aria-label={`${c.selectRow}: ${item.tool_name}`} title={c.selectRow} checked={selectedIds.includes(item.id)} disabled={busy} onChange={(event) => toggleSelected(item, event.target.checked)} /></TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.tool_name}</span><SourceBadge serverId={item.server_id} labels={c} /></div>
                    <div className="mt-0.5 max-w-96 truncate text-xs text-foreground/65" title={`${item.server_id}/${item.tool_id}`}>{sourceDisplayName(item.server_id, c)} · {item.tool_id}</div>
                  </TableCell>
                  <TableCell><AccessBadge access={item.suggested_access} labels={c} /><div className="mt-1 text-xs text-foreground/65">{suggestionSourceLabel(item.source, c)}</div></TableCell>
                  <TableCell><AccessBadge access={item.effective_access} labels={c} /></TableCell>
                  <TableCell className="font-mono text-xs">{Math.round(item.confidence * 100)}%</TableCell>
                  <TableCell><div className="flex flex-wrap gap-1">{item.destructive && <Badge variant="danger">{c.destructive}</Badge>}{item.idempotent && <Badge variant="outline">{c.idempotent}</Badge>}{!item.destructive && !item.idempotent && <span className="text-xs text-foreground/65">{c.noRiskFlag}</span>}</div></TableCell>
                  <TableCell><StatusBadge item={item} labels={c} /></TableCell>
                  <TableCell><Button className="min-h-9" size="sm" variant="outline" disabled={busy} onClick={() => openReview(item)}>{c.edit}</Button></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </div>
        </div>
      </Card>

      <FormDialog dirty={batchAccess !== "read" || batchNote !== ""} open={batchOpen} onClose={() => void closeBatch()}
        title={`${c.batchClassify} (${batchItems.length})`} description={c.batchDescription}
        closeLabel={t("cancel")} pending={busy} className="max-w-lg" error={formError}
        footer={<><Button variant="outline" onClick={() => void closeBatch()} disabled={busy}>{t("cancel")}</Button><Button onClick={() => void applyBatchReview()} disabled={busy || batchItems.length === 0}>{busy ? c.saving : `${c.applyBatch} (${batchItems.length})`}</Button></>}>
        <div className="flex flex-col gap-4">
          <div><Label htmlFor="classification-batch-access">{c.batchAccess}</Label><Select value={batchAccess} disabled={busy} onValueChange={(value) => setBatchAccess(value as typeof batchAccess)}><SelectTrigger id="classification-batch-access" aria-label={c.batchAccess} className="mt-2"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="read">{c.readAccess}</SelectItem><SelectItem value="write">{c.writeAccess}</SelectItem><SelectItem value="unknown">{c.unknown}</SelectItem></SelectContent></Select>{batchAccess === "unknown" && <p className="mt-2 text-xs text-foreground/65">{c.batchPendingHint}</p>}</div>
          <div><Label htmlFor="classification-batch-note">{c.batchNote}</Label><Textarea id="classification-batch-note" className="mt-2 min-h-24" disabled={busy} value={batchNote} placeholder={c.batchNotePlaceholder} onChange={(event) => setBatchNote(event.target.value)} /></div>
        </div>
      </FormDialog>

      <FormDialog dirty={JSON.stringify({ access, destructive, idempotent, note }) !== reviewInitial} open={editing !== null} onClose={() => void closeReview()}
        title={c.edit} description={editing ? `${sourceDisplayName(editing.server_id, c)} · ${editing.tool_id}` : ""}
        closeLabel={t("cancel")} pending={busy} className="max-w-3xl" error={formError}
        footer={<><Button variant="outline" onClick={() => void closeReview()} disabled={busy}>{t("cancel")}</Button><Button onClick={() => void saveReview()} disabled={busy || access === "unknown"}>{busy ? c.saving : c.saveDecision}</Button></>}>
        <div className="flex flex-col gap-4">
          <div><Label htmlFor="classification-review-access">{c.effective}</Label><Select value={access} disabled={busy} onValueChange={(value) => setAccess(value as typeof access)}><SelectTrigger id="classification-review-access" aria-label={c.effective} className="mt-2"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="read">{c.readAccess}</SelectItem><SelectItem value="write">{c.writeAccess}</SelectItem><SelectItem value="unknown">{c.unknown}</SelectItem></SelectContent></Select></div>
          <div className="flex items-center justify-between gap-3"><Label htmlFor="classification-destructive">{c.destructive}</Label><Switch id="classification-destructive" disabled={busy} checked={destructive} onCheckedChange={setDestructive} /></div>
          <div className="flex items-center justify-between gap-3"><Label htmlFor="classification-idempotent">{c.idempotent}</Label><Switch id="classification-idempotent" disabled={busy} checked={idempotent} onCheckedChange={setIdempotent} /></div>
          <div><Label htmlFor="classification-review-note">{c.note}</Label><Textarea id="classification-review-note" className="mt-2 min-h-28" disabled={busy} value={note} onChange={(event) => setNote(event.target.value)} /></div>
          <details><summary className="cursor-pointer text-sm font-medium">{c.evidence}</summary><div className="mt-2"><JsonPanel data={editing?.evidence || {}} maxHeight="max-h-80" /></div></details>
        </div>
      </FormDialog>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => setMessage(null)} />
    </div>
  )
}

function AccessBadge({ access, labels }: { access: ToolClassification["effective_access"]; labels: Record<string, string> }) {
  if (access === "write") return <Badge variant="warning">{labels.writeAccess}</Badge>
  if (access === "read") return <Badge variant="success">{labels.readAccess}</Badge>
  return <Badge variant="secondary">{labels.unknown}</Badge>
}

function StatusBadge({ item, labels }: { item: ToolClassification; labels: Record<string, string> }) {
  const status = classificationViewStatus(item)
  if (status === "published") return <Badge variant="success">{labels.published}</Badge>
  if (status === "stale") return <Badge variant="danger">{labels.stale}</Badge>
  if (status === "confirmed_pending") return <Badge variant="outline">{labels.confirmedPending}</Badge>
  return <Badge variant="warning">{labels.needsConfirmation}</Badge>
}

function classificationViewStatus(item: ToolClassification): Exclude<ClassificationViewStatus, "__all"> {
  if (item.status === "published") return "published"
  if (item.status === "stale") return "stale"
  if (item.effective_access !== "unknown") return "confirmed_pending"
  return "needs_confirmation"
}

function SourceBadge({ serverId, labels }: { serverId: string; labels: Record<string, string> }) {
  if (serverId === "builtin") return <Badge variant="secondary">{labels.sourceBuiltin}</Badge>
  return <Badge variant="outline">{labels.sourceMcp}</Badge>
}

function sourceDisplayName(serverId: string, labels: Record<string, string>) {
  if (serverId === "builtin") return labels.sourceBuiltin
  return serverId
}

function sourceOptionLabel(serverId: string, labels: Record<string, string>) {
  const displayName = sourceDisplayName(serverId, labels)
  return displayName === serverId ? serverId : `${displayName} (${serverId})`
}

function suggestionSourceLabel(source: string, labels: Record<string, string>) {
  if (source === "annotation") return labels.sourceAnnotation
  if (source === "manual") return labels.sourceManual
  return labels.sourceRule
}

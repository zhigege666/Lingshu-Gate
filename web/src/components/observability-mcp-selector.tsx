import { useEffect, useId, useRef, useState } from "react"
import { Select } from "antd"
import { api, type ObservabilityMcpScope } from "@/api/client"
import { Button } from "@/components/ui/button"
import { createRequestOwner, exactScopeId, scopeOptionLabel, scopePageSize } from "@/features/observability/model"

/** Names and counts only come from the authorized observability endpoints. */
export function ObservabilityMcpSelector({ value, onChange, zh, disabled = false, serverId }: {
  value: string; onChange: (id: string) => void; zh: boolean; disabled?: boolean; serverId?: string
}) {
  const toolMode = serverId !== undefined
  const label = toolMode ? (zh ? "工具" : "Tool") : "MCP"
  const historyLabel = toolMode ? (zh ? "历史工具" : "Historical tool") : (zh ? "历史服务" : "Historical service")
  const unavailable = toolMode && !serverId
  const labelId = useId()
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const [retry, setRetry] = useState(0)
  const [scopes, setScopes] = useState<ObservabilityMcpScope[]>([])
  const [selected, setSelected] = useState<ObservabilityMcpScope | null>(null)
  const [total, setTotal] = useState(0)
  const [globalScope, setGlobalScope] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [resolveError, setResolveError] = useState(false)
  const [open, setOpen] = useState(false)
  const owner = useRef(createRequestOwner())
  useEffect(() => { setQuery(""); setOffset(0); setOpen(false) }, [serverId])
  useEffect(() => {
    const id = owner.current.next()
    const controller = new AbortController()
    setError(null); setScopes([]); setTotal(0); setGlobalScope(false)
    setLoading(!unavailable)
    if (unavailable) return () => { controller.abort(); owner.current.invalidate() }
    const timer = window.setTimeout(() => {
      const filters = { q: query.trim() || undefined, offset, limit: scopePageSize }
      const request = toolMode
        ? api.observabilityToolScopes({ ...filters, server_id: serverId! }, controller.signal).then(response => ({ ...response, capabilities: undefined }))
        : api.observabilityMcpScopes(filters, controller.signal)
      void request.then(response => {
        if (!owner.current.owns(id) || controller.signal.aborted) return
        setScopes(response.scopes); setTotal(response.total)
        setGlobalScope(response.capabilities?.all_scope === "global")
      }).catch(cause => {
        if (owner.current.owns(id) && !controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause))
      }).finally(() => { if (owner.current.owns(id) && !controller.signal.aborted) setLoading(false) })
    }, query ? 200 : 0)
    return () => { window.clearTimeout(timer); controller.abort(); owner.current.invalidate() }
  }, [query, offset, retry, serverId, toolMode, unavailable])
  useEffect(() => {
    setSelected(null); setResolveError(false)
    if (!value || unavailable) return
    let active = true
    const controller = new AbortController()
    const request = toolMode
      ? api.observabilityToolScopes({ server_id: serverId!, tool_id: value, limit: 1 }, controller.signal)
      : api.observabilityMcpScopes({ server_id: value, limit: 1 }, controller.signal)
    void request.then(response => {
      if (active) setSelected(response.scopes.find(item => item.id === value) || null)
    }).catch(() => { if (active && !controller.signal.aborted) setResolveError(true) })
    return () => { active = false; controller.abort() }
  }, [value, retry, serverId, toolMode, unavailable])
  const options = scopes.map(scope => ({ value: scope.id, label: scopeOptionLabel(scope, historyLabel) }))
  if (value && !options.some(option => option.value === value)) options.unshift({ value, label: selected?.id === value
    ? scopeOptionLabel(selected, historyLabel) : `${value} · ${zh ? "精确 ID" : "Exact ID"}` })
  options.unshift({ value: "", label: toolMode ? (unavailable ? (zh ? "请先选择 MCP" : "Select an MCP first") : (zh ? "全部工具" : "All tools"))
    : globalScope ? (zh ? "全部 MCP 与系统记录" : "All MCPs and system records") : (zh ? "全部获准 MCP" : "All authorized MCPs") })
  function choose(id: string) { onChange(id); setQuery(""); setOffset(0); setOpen(false) }
  // Exact IDs remain a narrow escape hatch for history absent from the catalog.
  const exact = toolMode ? (query.trim() && query.trim().length <= 256 && !/[\s*]/.test(query.trim()) ? query.trim() : null) : exactScopeId(query)
  return <div className="flex min-w-0 flex-col gap-1 text-xs">
    <label id={labelId} className="font-medium text-muted-foreground">{label}</label>
    <Select aria-labelledby={labelId} aria-label={label} value={value} onChange={id => choose(id ?? "")} disabled={disabled || unavailable}
      open={open} onOpenChange={setOpen}
      allowClear={{ label: toolMode ? (zh ? "清除工具筛选" : "Clear tool filter") : (zh ? "清除 MCP 筛选" : "Clear MCP filter") }}
      showSearch filterOption={false} onSearch={next => { setQuery(next); setOffset(0) }} searchValue={query}
      virtual listHeight={224} loading={loading} options={options} style={{ width: "100%" }}
      placeholder={zh ? "搜索名称或 ID" : "Search name or ID"}
      popupRender={menu => <>{menu}{!loading && !error && scopes.length === 0 && <div className="px-3 py-2 text-xs text-muted-foreground" onMouseDown={event => event.preventDefault()}>
        <p>{toolMode ? (zh ? "此范围内没有匹配工具" : "No matching tools in this scope") : (zh ? "没有获准的匹配 MCP" : "No authorized MCP matches")}</p>
        {exact && <><Button type="button" size="sm" variant="outline" className="mt-2" onClick={() => choose(exact)}>{zh ? `按精确 ID 筛选：${exact}` : `Filter exact ID: ${exact}`}</Button><p className="mt-1">{zh ? "用于已知历史 ID；不确认对象存在，查询仍受权限限制。" : "For known historical IDs. This does not confirm existence; queries remain permission-scoped."}</p></>}
      </div>}<div className="flex items-center justify-between gap-2 border-t p-2" onMouseDown={event => event.preventDefault()}>
        <Button type="button" size="sm" variant="outline" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - scopePageSize))}>{zh ? "上一页" : "Previous"}</Button>
        <span role="status">{loading ? "…" : `${total ? offset + 1 : 0}–${Math.min(offset + scopes.length, total)} / ${total}`}</span>
        <Button type="button" size="sm" variant="outline" disabled={loading || offset + scopePageSize >= total} onClick={() => setOffset(offset + scopePageSize)}>{zh ? "下一页" : "Next"}</Button>
      </div></>} />
    {(error || resolveError) && <div role="alert" className="flex flex-wrap items-center gap-2 text-destructive"><span>{error || (zh ? "无法取得此 ID 的名称；精确查询仍受权限限制。" : "Unable to resolve this ID's name. Exact queries remain permission-scoped.")}</span><Button type="button" variant="outline" size="sm" onClick={() => setRetry(current => current + 1)}>{zh ? "重试" : "Retry"}</Button></div>}
  </div>
}

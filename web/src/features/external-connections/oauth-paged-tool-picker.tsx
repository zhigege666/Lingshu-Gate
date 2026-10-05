import { useEffect, useId, useRef, useState } from "react"
import { Button, Checkbox, Input, Radio, Segmented, Table, Tag, Tooltip } from "antd"
import { InfoCircleOutlined } from "@ant-design/icons"
import { oauthRequest, type OAuthScopeCatalog, type OAuthScopeGroup, type OAuthScopeSelection, type OAuthTool } from "./oauth-api"
import type { ScopeSelectionMode } from "./oauth-tool-selection"

export type ScopeSelectionOperation = { mode: "ids" | "all" | "read" | "groups"; tool_ids?: string[]; server_ids?: string[]; checked?: boolean; metadata_ids?: string[] }
type Filters = { query: string; server_id: string; access: string; view: "tools" | "groups" }
const emptyFilters: Filters = { query: "", server_id: "", access: "", view: "tools" }

/** Pages are display data. Only the server resolver determines whole choices. */
export function OAuthPagedToolPicker({ grantId, catalog, selection, selected, refreshKey, zh, disabled, onResolve, onRefresh, onCatalog, onError, onLoading }: {
  grantId: string; catalog: OAuthScopeCatalog | null; selection: OAuthScopeSelection | null; selected: string[]; refreshKey: number; zh: boolean; disabled: boolean
  onResolve: (operation: ScopeSelectionOperation) => Promise<OAuthScopeSelection | null>; onRefresh: () => void
  onCatalog: (catalog: OAuthScopeCatalog) => void; onError: (cause: unknown) => void; onLoading: (loading: boolean) => void
}) {
  const [pageData, setPageData] = useState<OAuthScopeCatalog | null>(catalog)
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [cursors, setCursors] = useState<string[]>([""])
  const [mode, setMode] = useState<ScopeSelectionMode>("custom")
  const [loading, setLoading] = useState(false)
  const generation = useRef(0)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastRefresh = useRef(-1)
  const quickId = useId()
  useEffect(() => {
    if (catalog && lastRefresh.current !== refreshKey) {
      lastRefresh.current = refreshKey; generation.current++
      if (debounce.current) clearTimeout(debounce.current)
      setPageData(catalog); setFilters(emptyFilters); setCursors([""]); setMode("custom"); setLoading(false)
    }
  }, [catalog, refreshKey])
  useEffect(() => () => { generation.current++; if (debounce.current) clearTimeout(debounce.current) }, [])
  const blocked = disabled || loading || !catalog
  async function load(nextFilters: Filters, nextCursors = [""]) {
    if (!catalog) return
    if (debounce.current) clearTimeout(debounce.current)
    const current = ++generation.current
    setFilters(nextFilters); setLoading(true); onLoading(true)
    const params = new URLSearchParams({ ...nextFilters, limit: nextFilters.view === "groups" ? "15" : "50", catalog_revision: catalog.catalog_revision })
    const cursor = nextCursors.at(-1)
    if (cursor) params.set("cursor", cursor)
    try {
      const next = await oauthRequest<OAuthScopeCatalog>(`/v1/auth/oauth/grants/${grantId}/scope-catalog?${params}`)
      if (current !== generation.current) return
      setPageData(next); setCursors(nextCursors); onCatalog(next)
    } catch (cause) { if (current === generation.current) onError(cause) }
    finally { if (current === generation.current) { setLoading(false); onLoading(false) } }
  }
  async function choose(operation: ScopeSelectionOperation, nextMode: ScopeSelectionMode = "custom") {
    if (blocked) return
    const result = await onResolve(operation)
    if (result) setMode(nextMode)
  }
  const counts = selection?.selected_counts
  const whole = catalog?.catalog_counts
  const selectedGroups = new Map(selection?.group_selected_counts.map(group => [group.server_id, group.selected_count]) || [])
  const countText = whole ? zh ? `已选 ${counts?.tools ?? 0} / ${whole.tools} 工具 · ${counts?.mcps ?? 0} MCP · 匹配 ${pageData?.matching_counts.tools ?? 0}` : `${counts?.tools ?? 0} / ${whole.tools} selected · ${counts?.mcps ?? 0} MCPs · ${pageData?.matching_counts.tools ?? 0} matches` : zh ? `草稿保留 ${selected.length} 个工具；请刷新可授权范围。` : `${selected.length} draft selections retained; refresh available scope.`
  return <section className="oauth-tools oauth-paged-tools" aria-label={zh ? "MCP 和工具授权范围" : "MCP and tool authorization scope"} aria-busy={loading}>
    <div className="oauth-bulk-selection">
      <span className="oauth-bulk-label"><span id={quickId}>{zh ? "快捷选择" : "Quick selection"}</span><Tooltip trigger={["hover", "focus"]} title={zh ? "作用于整个当前可授权目录，跨分页和筛选；超限保留草稿。只读仅含已发布为 read 的工具，未来新增不会自动选中。" : "Applies to the entire current available catalog across pages and filters. Limits retain your draft. Read-only uses published read classifications; future additions stay unselected."}><Button type="text" size="small" className="oauth-scope-info-trigger" aria-label={zh ? "快捷选择说明" : "Quick selection details"} icon={<InfoCircleOutlined aria-hidden />} /></Tooltip></span>
      <Radio.Group aria-labelledby={quickId} value={mode} disabled={blocked} onChange={event => {
        const next = event.target.value as ScopeSelectionMode
        if (next === "custom") setMode(next)
        else void choose({ mode: next }, next)
      }} options={[{ value: "read", label: zh ? "仅选全部当前只读" : "All current read-only tools" }, { value: "all", label: zh ? "选中全部当前工具" : "All current tools" }, { value: "custom", label: zh ? "自定义" : "Custom" }]} />
      <Button type="text" loading={loading || disabled} disabled={disabled || loading} onClick={onRefresh}>{zh ? "刷新可授权范围" : "Refresh available scope"}</Button>
    </div>
    <div className="oauth-filters">
      <Input aria-label={zh ? "搜索当前范围内的工具" : "Search tools in the current scope"} placeholder={zh ? "搜索工具名称、ID 或 MCP" : "Search tool name, ID or MCP"} allowClear value={filters.query} disabled={disabled || !catalog} onChange={event => {
        const next = { ...filters, query: event.target.value }; setFilters(next)
        if (debounce.current) clearTimeout(debounce.current)
        debounce.current = setTimeout(() => void load(next), 300)
      }} />
      <Input aria-label={zh ? "按 MCP ID 筛选" : "Filter by MCP ID"} placeholder={zh ? "MCP ID（精确）" : "Exact MCP ID"} allowClear value={filters.server_id} disabled={disabled || !catalog} onChange={event => {
        const next = { ...filters, server_id: event.target.value }; setFilters(next)
        if (debounce.current) clearTimeout(debounce.current)
        debounce.current = setTimeout(() => void load(next), 300)
      }} />
      <Segmented aria-label={zh ? "按读写权限筛选" : "Filter by access"} value={filters.access} disabled={blocked} onChange={value => void load({ ...filters, access: String(value) })} options={[{ value: "", label: zh ? "全部" : "All" }, { value: "read", label: zh ? "只读" : "Read" }, { value: "write", label: zh ? "写入" : "Write" }]} />
    </div>
    <div className="oauth-selection"><span role="status" title={countText}>{countText}</span><div className="oauth-actions">
      <Radio.Group aria-label={zh ? "范围显示方式" : "Scope view"} value={filters.view} disabled={blocked} onChange={event => void load({ ...filters, view: event.target.value })} options={[{ value: "groups", label: zh ? "MCP 整组" : "MCP groups" }, { value: "tools", label: zh ? "具体工具" : "Tools" }]} />
      <Button type="text" disabled={blocked || (!filters.query && !filters.server_id && !filters.access && cursors.length === 1)} onClick={() => void load(emptyFilters)}>{zh ? "重置筛选" : "Reset filters"}</Button>
      <Button type="text" disabled={blocked || !selected.length} onClick={() => void choose({ mode: "ids", tool_ids: [] })}>{zh ? "清空选择" : "Clear selection"}</Button>
    </div></div>
    {pageData?.view === "groups" ? <Table<OAuthScopeGroup> rowKey="server_id" size="small" dataSource={pageData.items as OAuthScopeGroup[]} pagination={false} tableLayout="fixed" scroll={{ y: "100%", x: 600 }} loading={loading} columns={[
      { title: zh ? "选择" : "Select", width: 70, render: (_, group) => { const count = selectedGroups.get(group.server_id) || 0; return <Checkbox aria-label={zh ? `选择 MCP ${group.server_id} 的全部当前可授权工具` : `Select all current available tools in MCP ${group.server_id}`} disabled={blocked} checked={count === group.tool_count} indeterminate={count > 0 && count < group.tool_count} onChange={event => void choose({ mode: "groups", server_ids: [group.server_id], checked: event.target.checked })} /> } },
      { title: "MCP", render: (_, group) => <div className="oauth-wrap">{group.server_name || group.server_id}<div className="oauth-muted">{group.server_id}</div></div> },
      { title: zh ? "已选 / 可授权" : "Selected / available", width: 170, render: (_, group) => `${selectedGroups.get(group.server_id) || 0} / ${group.tool_count}` },
      { title: zh ? "权限" : "Access", width: 180, render: (_, group) => zh ? `只读 ${group.read_count} · 写入 ${group.write_count}` : `${group.read_count} read · ${group.write_count} write` },
      { title: zh ? "工具" : "Tools", width: 130, render: (_, group) => <Button type="link" size="small" disabled={blocked} onClick={() => void load({ query: "", server_id: group.server_id, access: "", view: "tools" })}>{zh ? "查看工具" : "View tools"}</Button> },
    ]} /> : <Table<OAuthTool> rowKey="id" size="small" dataSource={(pageData?.items || []) as OAuthTool[]} pagination={false} tableLayout="fixed" scroll={{ y: "100%", x: 600 }} loading={loading}
      rowSelection={{ selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: keys => void choose({ mode: "ids", tool_ids: keys.map(String) }), getCheckboxProps: () => ({ disabled: blocked }), columnTitle: node => <span aria-label={zh ? "选择本页" : "Select page"}>{node}</span> }} columns={[
        { title: "MCP", dataIndex: "server_id", width: 170, render: id => <span className="oauth-wrap">{id}</span> },
        { title: zh ? "工具" : "Tool", dataIndex: "name", render: (name, tool) => <div className="oauth-wrap">{name}<div className="oauth-muted">{tool.id}</div></div> },
        { title: zh ? "权限" : "Access", dataIndex: "access", width: 110, render: access => <Tag color={access === "write" ? "orange" : "blue"}>{access === "write" ? zh ? "写入" : "Write" : zh ? "只读" : "Read"}</Tag> },
      ]} />}
    <div className="oauth-paged-navigation"><span>{zh ? `第 ${cursors.length} 页 · 每次按需读取` : `Page ${cursors.length} · loaded on demand`}</span><div className="oauth-actions"><Button disabled={blocked || cursors.length === 1} onClick={() => void load(filters, cursors.slice(0, -1))}>{zh ? "上一页" : "Previous page"}</Button><Button disabled={blocked || !pageData?.next_cursor} onClick={() => void load(filters, [...cursors, pageData!.next_cursor!])}>{zh ? "下一页" : "Next page"}</Button></div></div>
  </section>
}

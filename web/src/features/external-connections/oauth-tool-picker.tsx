import { useEffect, useId, useMemo, useState } from "react"
import { Button, Checkbox, Input, Radio, Segmented, Select, Table, Tag } from "antd"
import { toolFilter, type OAuthTool } from "./oauth-api"
import { mcpSelectionGroups, selectCurrentTools, selectMcpTools, type OAuthMcpGroup, type ScopeSelectionMode } from "./oauth-tool-selection"

/** Consent and grant reduction share a bounded searchable scope list.
 * Callers own authorization, snapshot freshness, mutation and confirmations.
 */
export function OAuthToolPicker({ tools, selected, onChange, zh, disabled = false, readOnly = false, fillViewport = false, bulkActions = false, eligibleTools = tools }: { tools: OAuthTool[]; selected: string[]; onChange: (ids: string[]) => void; zh: boolean; disabled?: boolean; readOnly?: boolean; fillViewport?: boolean; bulkActions?: boolean; eligibleTools?: OAuthTool[] | null }) {
  const [query, setQuery] = useState("")
  const [server, setServer] = useState("")
  const [access, setAccess] = useState("")
  const [page, setPage] = useState(1)
  const [view, setView] = useState("tools")
  const [mode, setMode] = useState<ScopeSelectionMode>("custom")
  const quickSelectionId = useId()
  // A refreshed snapshot never re-applies an earlier bulk choice to new tools.
  useEffect(() => { setMode("custom") }, [eligibleTools])
  const filtered = useMemo(() => toolFilter(tools, query, server, access), [tools, query, server, access])
  const servers = useMemo(() => {
    const names = new Map<string, string | null>()
    for (const tool of tools) if (!names.get(tool.server_id)) names.set(tool.server_id, tool.server_name || null)
    return [...names].sort(([a], [b]) => a.localeCompare(b))
  }, [tools])
  const shownPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / 50)))
  const selectedIds = useMemo(() => new Set(selected), [selected])
  const currentTools = eligibleTools || []
  const selectedAvailableCount = currentTools.filter(tool => selectedIds.has(tool.id)).length
  const selectedServers = new Set(currentTools.filter(tool => selectedIds.has(tool.id)).map(tool => tool.server_id)).size
  const groups = useMemo(() => mcpSelectionGroups(eligibleTools || [], selected), [eligibleTools, selected])
  const matchingServers = new Set(filtered.map(tool => tool.server_id))
  const filteredGroups = groups.filter(group => matchingServers.has(group.id))
  const groupPage = Math.min(page, Math.max(1, Math.ceil(filteredGroups.length / 15)))
  function change(ids: string[]) { setMode("custom"); onChange(ids) }
  const tableScroll = { y: fillViewport ? "100%" : "clamp(220px, calc(100dvh - 440px), 640px)", x: 600 }
  return <section className="oauth-tools" aria-label={zh ? "MCP 和工具授权范围" : "MCP and tool authorization scope"}>
    {bulkActions && !readOnly && <div className="oauth-bulk-selection">
      <span id={quickSelectionId}>{zh ? "快捷选择" : "Quick selection"}</span>
      <div><Radio.Group aria-labelledby={quickSelectionId} value={mode} disabled={disabled} onChange={event => {
        const choice = event.target.value as ScopeSelectionMode
        setMode(choice)
        if (choice !== "custom") onChange(selectCurrentTools(currentTools, choice))
      }} options={[{ value: "read", label: zh ? "仅选全部当前只读" : "All current read-only tools" }, { value: "all", label: zh ? "选中全部当前工具" : "All current tools" }, { value: "custom", label: zh ? "自定义" : "Custom" }]} />
      <p className="oauth-muted">{zh ? "替换整个当前可授权目录的选择，跨筛选和分页；以后新增的服务不会自动选中。只读仅含已发布为 read 的工具。" : "Replaces selection across the entire current available catalog, including all filters and pages. Later services stay unselected. Read-only uses published read classifications."}</p></div>
    </div>}
    <div className="oauth-filters">
      <Input aria-label={zh ? "搜索当前范围内的工具" : "Search tools in the current scope"} placeholder={zh ? "搜索工具名称、ID 或 MCP" : "Search tool name, ID or MCP"} allowClear value={query} disabled={disabled} onChange={event => { setQuery(event.target.value); setPage(1) }} />
      <Select aria-label={zh ? "按 MCP 筛选" : "Filter by MCP"} getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} showSearch optionFilterProp="searchText" value={server} disabled={disabled} onChange={value => { setServer(value); setPage(1) }} optionRender={option => <span title={option.data.name || undefined}>{option.label}</span>} options={[{ value: "", label: zh ? "全部 MCP" : "All MCPs", name: "", searchText: zh ? "全部 MCP" : "All MCPs" }, ...servers.map(([id, name]) => ({ value: id, label: id, searchText: `${name || ""} ${id}`, name }))]} />
      <Segmented aria-label={zh ? "按读写权限筛选" : "Filter by access"} value={access} disabled={disabled} onChange={value => { setAccess(String(value)); setPage(1) }} options={[{ value: "", label: zh ? "全部" : "All" }, { value: "read", label: zh ? "只读" : "Read" }, { value: "write", label: zh ? "写入" : "Write" }]} />
    </div>
    <div className="oauth-selection"><span role="status">{readOnly ? zh ? `${tools.length} 个已记录工具，涉及 ${servers.length} 个 MCP；筛选匹配 ${filtered.length} 项。` : `${tools.length} recorded tools across ${servers.length} MCPs; ${filtered.length} filter matches.` : eligibleTools === null ? zh ? `草稿保留 ${selected.length} 个工具选择；可授权目录尚未读取。` : `${selected.length} draft tool selections retained; the available catalog has not been loaded.` : zh ? `已选 ${selectedAvailableCount} / ${currentTools.length} 个${bulkActions ? "可授权" : ""}工具，涉及 ${selectedServers} 个 MCP；筛选匹配 ${filtered.length} 项。` : `${selectedAvailableCount} / ${currentTools.length} ${bulkActions ? "available " : ""}tools selected across ${selectedServers} MCPs; ${filtered.length} filter matches.`}</span><div className="oauth-actions">{bulkActions && !readOnly && <Radio.Group aria-label={zh ? "范围显示方式" : "Scope view"} value={view} disabled={disabled} onChange={event => { setView(event.target.value); setPage(1) }} options={[{ value: "groups", label: zh ? "MCP 整组" : "MCP groups" }, { value: "tools", label: zh ? "具体工具" : "Tools" }]} />}<Button disabled={disabled || (!query && !server && !access && page === 1)} onClick={() => { setQuery(""); setServer(""); setAccess(""); setPage(1) }}>{zh ? "重置筛选" : "Reset filters"}</Button>{!readOnly && <Button disabled={disabled || !selected.length} onClick={() => change([])}>{zh ? "清空选择" : "Clear selection"}</Button>}</div></div>
    {bulkActions && !readOnly && view === "groups" ? <Table<OAuthMcpGroup> rowKey="id" size="small" dataSource={filteredGroups} tableLayout="fixed" scroll={tableScroll}
      locale={{ emptyText: eligibleTools === null ? zh ? "可授权目录尚未读取，请刷新范围。" : "The available catalog has not been loaded. Refresh the scope." : zh ? "没有匹配的可授权 MCP。" : "No matching available MCPs." }}
      pagination={{ current: groupPage, pageSize: 15, showSizeChanger: false, onChange: setPage, showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}` }}
      columns={[{ title: zh ? "选择" : "Select", width: 70, render: (_, group) => <Checkbox aria-label={zh ? `选择 MCP ${group.id} 的全部当前可授权工具` : `Select all current available tools in MCP ${group.id}`} disabled={disabled} checked={group.selectedCount === group.tools.length} indeterminate={group.selectedCount > 0 && group.selectedCount < group.tools.length} onChange={event => change(selectMcpTools(selected, group, event.target.checked, tools))} /> },
        { title: "MCP", render: (_, group) => <div className="oauth-wrap">{group.name || (zh ? "名称未提供" : "Name unavailable")}<div className="oauth-muted">{group.id}</div></div> },
        { title: zh ? "已选 / 可授权" : "Selected / available", width: 170, render: (_, group) => `${group.selectedCount} / ${group.tools.length}` },
        { title: zh ? "权限" : "Access", width: 180, render: (_, group) => <>{zh ? `只读 ${group.readCount} · 写入 ${group.writeCount}` : `${group.readCount} read · ${group.writeCount} write`}</> },
        { title: zh ? "工具" : "Tools", width: 130, render: (_, group) => <Button size="small" disabled={disabled} onClick={() => { setServer(group.id); setQuery(""); setAccess(""); setView("tools"); setPage(1) }}>{zh ? "查看工具" : "View tools"}</Button> }]} /> : <Table<OAuthTool> rowKey="id" size="small" dataSource={filtered} tableLayout="fixed" scroll={tableScroll} locale={{ emptyText: zh ? "当前范围没有匹配工具。清除筛选或重新检查权限。" : "No matching tools in this scope. Clear filters or review permissions." }}
      pagination={{ current: shownPage, pageSize: 50, showSizeChanger: false, onChange: setPage, showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}` }}
      rowSelection={readOnly ? undefined : { selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: keys => change(keys.map(String)), getCheckboxProps: tool => ({ disabled: disabled || (tool.currently_authorized === false && !selectedIds.has(tool.id)) }), columnTitle: node => <span aria-label={zh ? "选择本页" : "Select page"}>{node}</span> }}
      columns={[{ title: "MCP", dataIndex: "server_id", width: 170, render: (id, tool) => <div className="oauth-wrap">{tool.server_name || (zh ? "名称未提供" : "Name unavailable")}<div className="oauth-muted">{id}</div></div> }, { title: zh ? "工具" : "Tool", dataIndex: "name", render: (name, tool) => <div className="oauth-wrap">{name}<div className="oauth-muted">{tool.id}</div></div> }, { title: zh ? "权限" : "Access", dataIndex: "access", width: 110, render: (value, tool) => <><Tag color={value === "write" ? "orange" : "blue"}>{value === "write" ? zh ? "写入" : "Write" : zh ? "只读" : "Read"}</Tag>{tool.currently_authorized === false && <span className="oauth-muted">{zh ? "当前不可用" : "Unavailable"}</span>}</> }]} />}
  </section>
}

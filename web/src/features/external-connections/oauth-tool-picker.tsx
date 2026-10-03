import { useMemo, useState } from "react"
import { Button, Input, Segmented, Select, Table, Tag } from "antd"
import { toolFilter, type OAuthTool } from "./oauth-api"

/** Consent and grant reduction share a bounded searchable scope list.
 * Callers own authorization, snapshot freshness, mutation and confirmations.
 */
export function OAuthToolPicker({ tools, selected, onChange, zh, disabled = false, readOnly = false }: { tools: OAuthTool[]; selected: string[]; onChange: (ids: string[]) => void; zh: boolean; disabled?: boolean; readOnly?: boolean }) {
  const [query, setQuery] = useState("")
  const [server, setServer] = useState("")
  const [access, setAccess] = useState("")
  const [page, setPage] = useState(1)
  const filtered = useMemo(() => toolFilter(tools, query, server, access), [tools, query, server, access])
  const servers = useMemo(() => {
    const names = new Map<string, string | null>()
    for (const tool of tools) if (!names.get(tool.server_id)) names.set(tool.server_id, tool.server_name || null)
    return [...names].sort(([a], [b]) => a.localeCompare(b))
  }, [tools])
  const shownPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / 50)))
  const selectedIds = useMemo(() => new Set(selected), [selected])
  const selectedServers = new Set(tools.filter(tool => selectedIds.has(tool.id)).map(tool => tool.server_id)).size
  return <section className="oauth-tools" aria-label={zh ? "MCP 和工具授权范围" : "MCP and tool authorization scope"}>
    <div className="oauth-filters">
      <Input aria-label={zh ? "搜索当前范围内的工具" : "Search tools in the current scope"} placeholder={zh ? "搜索工具名称、ID 或 MCP" : "Search tool name, ID or MCP"} allowClear value={query} disabled={disabled} onChange={event => { setQuery(event.target.value); setPage(1) }} />
      <Select aria-label={zh ? "按 MCP 筛选" : "Filter by MCP"} showSearch optionFilterProp="label" value={server} disabled={disabled} onChange={value => { setServer(value); setPage(1) }} optionRender={option => <div>{option.data.name || option.label}{option.value && <div className="oauth-muted">{option.value}</div>}</div>} options={[{ value: "", label: zh ? "全部 MCP" : "All MCPs", name: "" }, ...servers.map(([id, name]) => ({ value: id, label: `${name || (zh ? "名称未提供" : "Name unavailable")} · ${id}`, name }))]} />
      <Segmented aria-label={zh ? "按读写权限筛选" : "Filter by access"} value={access} disabled={disabled} onChange={value => { setAccess(String(value)); setPage(1) }} options={[{ value: "", label: zh ? "全部" : "All" }, { value: "read", label: zh ? "只读" : "Read" }, { value: "write", label: zh ? "写入" : "Write" }]} />
    </div>
    <div className="oauth-selection" role="status"><span>{readOnly ? zh ? `${tools.length} 个已记录工具，涉及 ${servers.length} 个 MCP；筛选匹配 ${filtered.length} 项。` : `${tools.length} recorded tools across ${servers.length} MCPs; ${filtered.length} filter matches.` : zh ? `已选 ${selected.length} / ${tools.length} 个工具，涉及 ${selectedServers} 个 MCP；筛选匹配 ${filtered.length} 项。` : `${selected.length} / ${tools.length} tools selected across ${selectedServers} MCPs; ${filtered.length} filter matches.`}</span><div className="oauth-actions"><Button disabled={disabled || (!query && !server && !access && page === 1)} onClick={() => { setQuery(""); setServer(""); setAccess(""); setPage(1) }}>{zh ? "重置筛选" : "Reset filters"}</Button>{!readOnly && <Button disabled={disabled || !selected.length} onClick={() => onChange([])}>{zh ? "清空选择" : "Clear selection"}</Button>}</div></div>
    <Table<OAuthTool> rowKey="id" size="small" dataSource={filtered} tableLayout="fixed" scroll={{ y: "clamp(220px, calc(100dvh - 440px), 640px)", x: 600 }} locale={{ emptyText: zh ? "当前范围没有匹配工具。清除筛选或重新检查权限。" : "No matching tools in this scope. Clear filters or review permissions." }}
      pagination={{ current: shownPage, pageSize: 50, showSizeChanger: false, onChange: setPage, showTotal: (total, range) => `${range[0]}–${range[1]} / ${total}` }}
      rowSelection={readOnly ? undefined : { selectedRowKeys: selected, preserveSelectedRowKeys: true, onChange: keys => onChange(keys.map(String)), getCheckboxProps: () => ({ disabled }), columnTitle: node => <span aria-label={zh ? "选择本页" : "Select page"}>{node}</span> }}
      columns={[{ title: "MCP", dataIndex: "server_id", width: 170, render: (id, tool) => <div className="oauth-wrap">{tool.server_name || (zh ? "名称未提供" : "Name unavailable")}<div className="oauth-muted">{id}</div></div> }, { title: zh ? "工具" : "Tool", dataIndex: "name", render: (name, tool) => <div className="oauth-wrap">{name}<div className="oauth-muted">{tool.id}</div></div> }, { title: zh ? "权限" : "Access", dataIndex: "access", width: 110, render: (value, tool) => <><Tag color={value === "write" ? "orange" : "blue"}>{value === "write" ? zh ? "写入" : "Write" : zh ? "只读" : "Read"}</Tag>{tool.currently_authorized === false && <span className="oauth-muted">{zh ? "当前不可用" : "Unavailable"}</span>}</> }]} />
  </section>
}

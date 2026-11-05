import { useId, useMemo, useState } from "react"
import { Button, Checkbox, Dropdown, Input, Pagination, Radio, Table, Tooltip } from "antd"
import { InfoCircleOutlined, MoreOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons"
import { useListPage } from "@/components/list-pagination"
import type { OAuthScopeGroup, OAuthTool } from "./oauth-api"
import { tokenMcpChoice, tokenMcpSignature, tokenMcpTools, type TokenMcpChoice, type TokenMcpDraft, type TokenMcpSnapshot } from "./token-mcp-scope-model"

type Props = {
  groups: OAuthScopeGroup[]; tools: OAuthTool[]; draft: TokenMcpDraft; baseline: TokenMcpSnapshot
  canRead: boolean; canWrite: boolean; disabled: boolean; pending: boolean; refreshing: boolean; zh: boolean
  onChoice: (server: string, choice: TokenMcpChoice) => void
  onTools: (server: string, ids: string[]) => void
  onRefresh: () => void; onPermissions: () => void; onReconfirm: (server: string) => void; onClearTools: () => void
}

/** API-token presentation only. The dialog owns the complete draft and writes. */
export function TokenMcpScopeEditor(props: Props) {
  const { groups, tools, draft, baseline, canRead, canWrite, disabled, pending, refreshing, zh } = props
  const [query, setQuery] = useState(""), [filter, setFilter] = useState("all"), [expanded, setExpanded] = useState<string | null>(null)
  const id = useId()
  const counts = useMemo(() => new Map(groups.map(group => [group.server_id, tokenMcpTools(group.server_id, draft.selected, tools).length])), [groups, draft.selected, tools])
  const changed = useMemo(() => new Set(groups.filter(group => tokenMcpSignature(group.server_id, draft, tools) !== tokenMcpSignature(group.server_id, baseline, tools)).map(group => group.server_id)), [groups, draft, baseline, tools])
  const permitted = (server: string) => draft.policies.some(policy => policy.server_id === server) || Boolean(counts.get(server))
  const filtered = groups.filter(group => `${group.server_name || ""} ${group.server_id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (filter === "all" || (filter === "granted" ? permitted(group.server_id) : changed.has(group.server_id))))
  const paging = useListPage(filtered, `${query}:${filter}`, 10)
  const duplicateNames = new Set(groups.filter((group, index) => group.server_name && groups.findIndex(other => other.server_name === group.server_name) !== index).map(group => group.server_name))
  return <section className="token-mcp-list" aria-label={zh ? "MCP 资源范围" : "MCP resource scope"}>
    <p className="mb-3 text-sm text-muted-foreground">{zh ? "服务只读 / 读写持续包含后续同步且本人获准的工具；指定工具只开放已选工具。" : "Service read / read-write continuously includes future synced tools within your permissions. Selected tools allows only your exact selection."}</p>
    <div className="token-mcp-toolbar">
      <Input aria-label={zh ? "搜索 MCP" : "Search MCP"} placeholder={zh ? "搜索 MCP" : "Search MCP"} prefix={<SearchOutlined aria-hidden />} allowClear value={query} onChange={event => setQuery(event.target.value)} />
      <Radio.Group aria-label={zh ? "筛选 MCP" : "Filter MCPs"} value={filter} onChange={event => setFilter(event.target.value)} options={[{ value: "all", label: zh ? "全部" : "All" }, { value: "granted", label: zh ? "已授权" : "Granted" }, { value: "changed", label: zh ? "已修改" : "Changed" }]} />
      <div className="token-mcp-toolbar-actions">
        <Button type="text" icon={<ReloadOutlined aria-hidden />} loading={refreshing} disabled={pending} onClick={props.onRefresh} aria-label={zh ? "刷新可授权范围" : "Refresh available scope"}>{zh ? "刷新" : "Refresh"}</Button>
        <Dropdown menu={{ items: [{ key: "clear", label: zh ? "清空全部指定工具" : "Clear all selected tools", disabled: disabled || !draft.selected.length }], onClick: () => props.onClearTools() }}><Button type="text" icon={<MoreOutlined aria-hidden />} aria-label={zh ? "更多范围操作" : "More scope actions"} disabled={disabled} /></Dropdown>
      </div>
    </div>
    <Table<OAuthScopeGroup> className="token-mcp-table" rowKey="server_id" size="small" tableLayout="fixed" dataSource={paging.items} pagination={false} rowClassName={group => expanded === group.server_id ? "token-mcp-open" : ""}
      locale={{ emptyText: query || filter !== "all" ? zh ? "没有匹配的 MCP，可清除搜索或选择全部。" : "No matching MCPs. Clear the search or choose All." : zh ? "当前没有可授权的 MCP。" : "No MCPs are currently available." }}
      expandable={{ expandedRowKeys: expanded ? [expanded] : [], showExpandColumn: false, expandedRowClassName: () => "token-mcp-expanded-row", expandedRowRender: group => <div id={`${id}-${group.server_id}`} className="token-mcp-inline" role="region" aria-label={`${group.server_name || group.server_id} ${zh ? "授权编辑" : "authorization editor"}`}>
        {tokenMcpChoice(group.server_id, draft) === "selected" && <TokenMcpToolList server={group} tools={tools.filter(tool => tool.server_id === group.server_id)} selected={tokenMcpTools(group.server_id, draft.selected, tools)} baseline={tokenMcpTools(group.server_id, baseline.selected, tools)} disabled={disabled} zh={zh} onChange={ids => props.onTools(group.server_id, ids)} />}
      </div> }}
      columns={[
        { title: "MCP", width: "28%", render: (_, group) => {
          const policy = draft.policies.find(item => item.server_id === group.server_id)
          const changedIdentity = Boolean(policy?.server_binding && group.server_binding && policy.server_binding !== group.server_binding)
          return <div className="token-mcp-identity"><strong title={group.server_id}>{group.server_name || group.server_id}</strong>{duplicateNames.has(group.server_name) && <code>{group.server_id}</code>}{changedIdentity && <div role="status" className="token-mcp-identity-warning">{zh ? "服务身份已改变" : "Service identity changed"}<Button type="link" size="small" disabled={disabled} onClick={() => props.onReconfirm(group.server_id)}>{zh ? "重新确认服务" : "Reconfirm service"}</Button></div>}</div>
        } },
        { title: zh ? "访问范围" : "Access scope", width: "60%", render: (_, group) => <Radio.Group aria-label={`${group.server_id} ${zh ? "授权方式" : "authorization"}`} value={tokenMcpChoice(group.server_id, draft)} disabled={disabled} onChange={event => {
          props.onChoice(group.server_id, event.target.value)
          setExpanded(current => event.target.value === "selected" ? group.server_id : current === group.server_id ? null : current)
        }} options={[{ value: "none", label: zh ? "不授权" : "No access" }, { value: "read", label: zh ? "服务只读" : "Service read", disabled: disabled || !canRead }, { value: "write", label: zh ? "服务读写" : "Service read/write", disabled: disabled || !canWrite }, { value: "selected", label: zh ? "指定工具" : "Selected tools" }]} /> },
        { title: zh ? "工具" : "Tools", width: "12%", align: "right", render: (_, group) => <div className="token-mcp-summary">
          {tokenMcpChoice(group.server_id, draft) === "selected" && <Button type="link" disabled={disabled} aria-label={`${group.server_name || group.server_id} ${zh ? "选择指定工具" : "select exact tools"}`} aria-expanded={expanded === group.server_id} aria-controls={`${id}-${group.server_id}`} onClick={() => setExpanded(current => current === group.server_id ? null : group.server_id)}>{zh ? `已选 ${counts.get(group.server_id) || 0}` : `${counts.get(group.server_id) || 0} selected`}</Button>}
          {changed.has(group.server_id) && <span className="token-mcp-unsaved">{zh ? "未保存" : "Unsaved"}</span>}
        </div> },
      ]} />
    {(!canRead || !canWrite) && <p className="mt-2 token-mcp-scope-reason">{zh ? `当前账号可授予的权限未包含${!canRead && !canWrite ? "只读及写入" : !canRead ? "只读" : "写入"}。` : `Your account cannot grant ${!canRead && !canWrite ? "reads and writes" : !canRead ? "reads" : "writes"}.`}<Button type="link" size="small" onClick={props.onPermissions}>{zh ? "查看功能权限" : "View permissions"}</Button></p>}
    {paging.pageCount > 1 && <div className="token-mcp-pagination"><span>{zh ? `${filtered.length} 个 MCP` : `${filtered.length} MCPs`}</span><Pagination size="small" current={paging.page} total={paging.total} pageSize={10} showSizeChanger={false} onChange={paging.setPage} /></div>}
  </section>
}

function TokenMcpToolList({ server, tools, selected, baseline, disabled, zh, onChange }: { server: OAuthScopeGroup; tools: OAuthTool[]; selected: string[]; baseline: string[]; disabled: boolean; zh: boolean; onChange: (ids: string[]) => void }) {
  const [query, setQuery] = useState(""), [access, setAccess] = useState("all")
  const filtered = tools.filter(tool => `${tool.name} ${tool.id}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (access === "all" || access === tool.access))
  const paging = useListPage(filtered, `${query}:${access}`, 10)
  const checked = new Set(selected), original = new Set(baseline)
  const available = tools.filter(tool => tool.currently_authorized !== false)
  const eligiblePage = paging.items.filter(tool => tool.currently_authorized !== false)
  const nameCounts = new Map<string, number>()
  for (const tool of tools) nameCounts.set(tool.name, (nameCounts.get(tool.name) || 0) + 1)
  const duplicateNames = new Set([...nameCounts].filter(([, count]) => count > 1).map(([name]) => name))
  function toggle(id: string, value: boolean) { onChange(value ? [...new Set([...selected, id])] : selected.filter(item => item !== id)) }
  return <div className="token-mcp-tools">
    <div className="token-mcp-tool-toolbar"><Input aria-label={`${server.server_id} ${zh ? "搜索工具" : "search tools"}`} prefix={<SearchOutlined aria-hidden />} placeholder={zh ? `搜索${server.server_name || server.server_id}的工具` : `Search ${server.server_name || server.server_id} tools`} allowClear value={query} onChange={event => setQuery(event.target.value)} /><span role="status">{zh ? `已选 ${selected.length} 个` : `${selected.length} selected`}</span>
      <Dropdown menu={{ items: [{ key: "read", label: zh ? "选择此 MCP 当前只读工具" : "Select this MCP's current read-only tools" }, { key: "all", label: zh ? "选择此 MCP 当前全部工具" : "Select all current tools in this MCP" }, { key: "clear", label: zh ? "清空此 MCP 的指定工具" : "Clear this MCP's selected tools" }], onClick: ({ key }) => onChange(key === "clear" ? [] : available.filter(tool => key === "all" || tool.access === "read").map(tool => tool.id)) }}><Button type="text" icon={<MoreOutlined aria-hidden />} aria-label={`${server.server_id} ${zh ? "工具选择操作" : "tool selection actions"}`} disabled={disabled} /></Dropdown>
    </div>
    {tools.length > 10 && <div className="token-mcp-tool-filters"><Radio.Group aria-label={`${server.server_id} ${zh ? "工具类型" : "tool access"}`} value={access} onChange={event => setAccess(event.target.value)} options={[{ value: "all", label: zh ? "全部" : "All" }, { value: "read", label: zh ? "只读" : "Read-only" }, { value: "write", label: zh ? "写入" : "Write" }]} /><Checkbox disabled={disabled || !eligiblePage.length} checked={Boolean(eligiblePage.length) && eligiblePage.every(tool => checked.has(tool.id))} indeterminate={eligiblePage.some(tool => checked.has(tool.id)) && !eligiblePage.every(tool => checked.has(tool.id))} onChange={event => onChange(event.target.checked ? [...new Set([...selected, ...eligiblePage.map(tool => tool.id)])] : selected.filter(id => !eligiblePage.some(tool => tool.id === id)))}>{zh ? "选择本页" : "Select page"}</Checkbox></div>}
    <div className="token-mcp-tool-rows">{paging.items.map(tool => <div className="token-mcp-tool-row" key={tool.id}>
      <Checkbox aria-label={`${tool.name} (${tool.id})`} disabled={disabled || (tool.currently_authorized === false && !checked.has(tool.id))} checked={checked.has(tool.id)} onChange={event => toggle(tool.id, event.target.checked)}><span className="token-mcp-tool-name">{tool.name}</span>{duplicateNames.has(tool.name) && <code className="token-mcp-tool-id">{tool.id}</code>}</Checkbox>
      {checked.has(tool.id) && !original.has(tool.id) && <span className="token-mcp-tool-added">{zh ? "新增" : "Added"}</span>}{!checked.has(tool.id) && original.has(tool.id) && <span className="token-mcp-unsaved">{zh ? "已移除" : "Removed"}</span>}
      {tool.currently_authorized === false && <span className="token-mcp-unavailable">{zh ? "当前不可用" : "Currently unavailable"}</span>}
      <Tooltip trigger={["hover", "focus"]} title={<span>{tool.id}<br />{tool.access === "write" ? zh ? "写入工具" : "Write tool" : zh ? "只读工具" : "Read-only tool"}</span>}><Button type="text" size="small" icon={<InfoCircleOutlined aria-hidden />} aria-label={`${tool.name} ${zh ? "工具详情" : "tool details"}`} /></Tooltip>
    </div>)}</div>
    {!filtered.length && <p className="token-mcp-empty">{zh ? "没有匹配的工具。" : "No matching tools."}</p>}
    {paging.pageCount > 1 && <div className="token-mcp-tool-pagination"><span>{paging.start}–{paging.end} / {paging.total}</span><Pagination size="small" current={paging.page} total={paging.total} pageSize={10} showSizeChanger={false} onChange={paging.setPage} /></div>}
  </div>
}

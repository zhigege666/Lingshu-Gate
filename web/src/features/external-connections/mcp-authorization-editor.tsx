import { useId, useState, type ReactNode } from "react"
import { Button, Collapse, Input, InputNumber, Radio, Table } from "antd"
import { useListPage } from "@/components/list-pagination"
import type { McpServerPolicy, OAuthScopeGroup, OAuthTool } from "./oauth-api"

export type { McpServerPolicy } from "./oauth-api"
export type McpAuthorizationMode = "none" | "continuous" | "selected"
export type CurrentToolAccess = "read" | "all"

/** A batch selection is a snapshot of the offered tools, never a future-tool policy. */
export function selectCurrentTools({ tools, selected, policies, modes, access, serverId }: { tools: OAuthTool[]; selected: string[]; policies: McpServerPolicy[]; modes: Record<string, McpAuthorizationMode>; access: CurrentToolAccess; serverId?: string }) {
  const affected = new Set(serverId ? [serverId] : [...tools.map(tool => tool.server_id), ...policies.map(policy => policy.server_id), ...Object.keys(modes)])
  const current = tools.filter(tool => affected.has(tool.server_id) && tool.currently_authorized !== false && (access === "all" || tool.access === "read"))
  const affectedIds = new Set(tools.filter(tool => affected.has(tool.server_id)).map(tool => tool.id))
  const nextSelected = serverId ? selected.filter(id => !affectedIds.has(id)) : []
  const selectedServers = new Set(current.map(tool => tool.server_id))
  return {
    selected: [...new Set([...nextSelected, ...current.map(tool => tool.id)])],
    policies: policies.filter(policy => !affected.has(policy.server_id)),
    modes: { ...modes, ...Object.fromEntries([...affected].map(server => [server, selectedServers.has(server) ? "selected" as const : "none" as const])) },
  }
}

export function currentAuthorizationSummary(tools: OAuthTool[], selected: string[], policies: McpServerPolicy[]) {
  const ids = new Set(selected)
  const granted = tools.filter(tool => ids.has(tool.id) || policies.some(policy => policy.server_id === tool.server_id && (policy.access === "write" || tool.access === "read")))
  return {
    servers: new Set([...granted.map(tool => tool.server_id), ...policies.map(policy => policy.server_id)]).size,
    tools: granted.length,
    read: granted.filter(tool => tool.access === "read").length,
    write: granted.filter(tool => tool.access === "write").length,
    continuous: policies.length,
    byServer: Object.fromEntries([...new Set(tools.map(tool => tool.server_id))].map(server => [server, granted.filter(tool => tool.server_id === server).length])),
  }
}

export function validQuotas(rate: number | null, concurrency: number | null) {
  return rate !== null && concurrency !== null && Number.isInteger(rate) && rate >= 1 && rate <= 10000 && Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 100
}
type QuotaFieldsProps = { rate: number | null; concurrency: number | null; onRate: (value: number | null) => void; onConcurrency: (value: number | null) => void; disabled?: boolean; zh: boolean; singleColumn?: boolean }
export function QuotaFields({ rate, concurrency, onRate, onConcurrency, disabled, zh, singleColumn }: QuotaFieldsProps) {
  const id = useId()
  return <div className={`authorization-quota-fields${singleColumn ? " authorization-quota-fields--single" : ""}`}>
    <div className="authorization-field"><label htmlFor={`${id}-rate`}>{zh ? "每分钟调用上限" : "Calls per minute"}</label><div><InputNumber id={`${id}-rate`} disabled={disabled} min={1} max={10000} step={1} changeOnBlur={false} value={rate} status={rate === null || !Number.isInteger(rate) || rate < 1 || rate > 10000 ? "error" : undefined} onChange={onRate} />{(rate === null || !Number.isInteger(rate) || rate < 1 || rate > 10000) && <div role="alert">{zh ? "请输入 1–10000 的整数" : "Enter an integer from 1 to 10000"}</div>}</div></div>
    <div className="authorization-field"><label htmlFor={`${id}-concurrency`}>{zh ? "并发上限" : "Concurrent calls"}</label><div><InputNumber id={`${id}-concurrency`} disabled={disabled} min={1} max={100} step={1} changeOnBlur={false} value={concurrency} status={concurrency === null || !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 100 ? "error" : undefined} onChange={onConcurrency} />{(concurrency === null || !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 100) && <div role="alert">{zh ? "请输入 1–100 的整数" : "Enter an integer from 1 to 100"}</div>}</div></div>
  </div>
}
export function QuotaSettings(props: QuotaFieldsProps & { summary?: ReactNode }) {
  const [expanded, setExpanded] = useState(false)
  const { rate, concurrency, zh } = props
  const invalid = !validQuotas(rate, concurrency)
  return <Collapse className="authorization-quota-settings" activeKey={expanded || invalid ? ["quota"] : []} onChange={keys => setExpanded(keys.includes("quota"))} items={[{
    key: "quota",
    label: <span className="authorization-quota-summary"><span>{zh ? "高级 · 调用限制" : "Advanced · Call limits"}</span><span className="authorization-quota-values">{props.summary ?? (zh ? `${rate ?? "—"} 次/分钟 · 并发 ${concurrency ?? "—"}` : `${rate ?? "—"}/min · ${concurrency ?? "—"} concurrent`)}</span></span>,
    children: <QuotaFields {...props} />,
  }]} />
}
export function policyGroups(tools: OAuthTool[], policies: McpServerPolicy[] = []): OAuthScopeGroup[] {
  const groups = new Map<string, OAuthScopeGroup>()
  for (const tool of tools) {
    const group = groups.get(tool.server_id) || { server_id: tool.server_id, server_name: tool.server_name || null, tool_count: 0, read_count: 0, write_count: 0 }
    group.tool_count++; group[tool.access === "write" ? "write_count" : "read_count"]++; groups.set(tool.server_id, group)
  }
  for (const policy of policies) if (!groups.has(policy.server_id)) groups.set(policy.server_id, { server_id: policy.server_id, server_name: null, tool_count: 0, read_count: 0, write_count: 0 })
  return [...groups.values()]
}
type RemoteMcpPage = { query: string; page: number; total: number; loading: boolean; hasNext: boolean; onQuery: (value: string) => void; onPrevious: () => void; onNext: () => void }
export function McpAuthorizationEditor({ groups, policies, modes = {}, onMode, onAccess, onSelectCurrent, onEditTools, selectionCounts, canWrite, disabled, zh, remote }: { groups: OAuthScopeGroup[]; policies: McpServerPolicy[]; modes?: Record<string, McpAuthorizationMode>; onMode: (server: string, mode: McpAuthorizationMode, access?: "read" | "write") => void; onAccess: (server: string, access: "read" | "write") => void; onSelectCurrent?: (server: string, access: CurrentToolAccess) => void; onEditTools?: (server: string) => void; selectionCounts?: Record<string, number>; canWrite: boolean; disabled?: boolean; zh: boolean; remote?: RemoteMcpPage }) {
  const [query, setQuery] = useState("")
  const filtered = remote ? groups : groups.filter(group => `${group.server_id} ${group.server_name || ""}`.toLowerCase().includes(query.trim().toLowerCase()))
  const paging = useListPage(filtered, query, 10)
  const blocked = disabled || remote?.loading
  return <section className="authorization-mcp-editor" aria-label={zh ? "MCP 资源范围" : "MCP resource scope"}>
    <Input aria-label={zh ? "搜索 MCP" : "Search MCP"} value={remote?.query ?? query} onChange={event => remote ? remote.onQuery(event.target.value) : setQuery(event.target.value)} disabled={disabled} allowClear placeholder={zh ? "搜索 MCP" : "Search MCP"} />
    <p className="text-sm text-muted-foreground">{zh ? "服务只读 / 读写为持续授权，自动纳入后续同步且本人获准的工具。指定工具仅开放已选工具。" : "Service read / read-write is continuous access, including future synced tools within your permissions. Selected tools allows only your exact selection."}{!canWrite && <span> {zh ? "当前 OAuth scope 不包含写入。" : "Current OAuth scopes exclude write access."}</span>}</p>
    <Table<OAuthScopeGroup> rowKey="server_id" size="small" dataSource={filtered} loading={remote?.loading} pagination={remote ? false : { current: paging.page, onChange: paging.setPage, pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }} scroll={{ x: onSelectCurrent ? 900 : 700 }} columns={[
      { title: "MCP", render: (_, group) => { const policy = policies.find(item => item.server_id === group.server_id); const identityChanged = Boolean(policy?.server_binding && group.server_binding && policy.server_binding !== group.server_binding); return <><strong>{group.server_name || group.server_id}</strong>{group.server_name && <div className="text-xs text-muted-foreground">{group.server_id}</div>}{identityChanged && <div role="status">{zh ? "服务身份已改变" : "Service identity changed"}<Button size="small" disabled={blocked} onClick={() => onMode(group.server_id, "continuous", policy?.access || "read")}>{zh ? "重新确认服务" : "Reconfirm service"}</Button></div>}</> } },
      { title: zh ? "访问范围" : "Access scope", width: 430, render: (_, group) => {
        const policy = policies.find(item => item.server_id === group.server_id)
        return <Radio.Group aria-label={`${group.server_id} ${zh ? "授权方式" : "authorization"}`} value={policy?.access || modes[group.server_id] || "none"} disabled={blocked} onChange={event => {
          const choice = event.target.value
          if (choice === "read" || choice === "write") {
            if (policy) onAccess(group.server_id, choice)
            else onMode(group.server_id, "continuous", choice)
          } else onMode(group.server_id, choice)
        }} options={[{ value: "none", label: zh ? "不授权" : "None" }, { value: "read", label: zh ? "服务只读" : "Service read" }, { value: "write", label: zh ? "服务读写" : "Service read/write", disabled: blocked || !canWrite }, { value: "selected", label: zh ? "指定工具" : "Selected tools" }]} />
      } },
      { title: zh ? "当前工具" : "Current tools", width: onSelectCurrent ? 256 : 100, render: (_, group) => <>{onEditTools && modes[group.server_id] === "selected" && !policies.some(policy => policy.server_id === group.server_id) ? <Button type="link" size="small" disabled={blocked} aria-label={`${group.server_id} ${zh ? "选择工具" : "choose tools"}`} onClick={() => onEditTools(group.server_id)}>{zh ? "选择工具" : "Choose tools"}</Button> : <span>{selectionCounts ? `${selectionCounts[group.server_id] || 0} / ${group.tool_count}` : group.tool_count}</span>}{onSelectCurrent && <><div className="text-xs text-muted-foreground">{zh ? `只读 ${group.read_count} · 写入 ${group.write_count}` : `${group.read_count} read · ${group.write_count} write`}</div><div className="authorization-current-actions"><Button size="small" disabled={blocked || !group.read_count} aria-label={`${group.server_id} ${zh ? "选择当前只读工具" : "select current read tools"}`} onClick={() => onSelectCurrent(group.server_id, "read")}>{zh ? "当前只读" : "Current read"}</Button><Button size="small" disabled={blocked || !group.tool_count} aria-label={`${group.server_id} ${zh ? "选择当前全部工具" : "select all current tools"}`} onClick={() => onSelectCurrent(group.server_id, "all")}>{zh ? "当前全部" : "All current"}</Button></div></>}</> },
    ]} />
    {remote && <nav className="oauth-paged-navigation" aria-label={zh ? "MCP 分页" : "MCP pages"}><span>{zh ? `${remote.total} 个匹配 MCP · 第 ${remote.page} 页` : `${remote.total} matching MCPs · Page ${remote.page}`}</span><div className="oauth-actions"><Button disabled={blocked || remote.page === 1} onClick={remote.onPrevious}>{zh ? "上一页" : "Previous page"}</Button><Button disabled={blocked || !remote.hasNext} onClick={remote.onNext}>{zh ? "下一页" : "Next page"}</Button></div></nav>}
  </section>
}

export function McpPolicyDifference({ before, after, beforeSelected = [], afterSelected = [], zh }: { before: McpServerPolicy[]; after: McpServerPolicy[]; beforeSelected?: string[]; afterSelected?: string[]; zh: boolean }) {
  const servers = [...new Set([...before.map(policy => policy.server_id), ...after.map(policy => policy.server_id), ...beforeSelected, ...afterSelected])]
  function label(policies: McpServerPolicy[], selected: string[], server: string) {
    const policy = policies.find(item => item.server_id === server)
    if (policy) return policy.access === "write" ? zh ? "持续授权 · 读写（含未来写工具）" : "Continuous · read/write (includes future write tools)" : zh ? "持续授权 · 当前及未来只读工具" : "Continuous · current and future read tools"
    return selected.includes(server) ? zh ? "指定工具" : "Selected tools" : zh ? "不授权" : "None"
  }
  function identityChanged(server: string) { const previous = before.find(policy => policy.server_id === server), next = after.find(policy => policy.server_id === server); return Boolean(previous?.server_binding && next?.server_binding && previous.server_binding !== next.server_binding) }
  return <>{servers.filter(server => identityChanged(server) || label(before, beforeSelected, server) !== label(after, afterSelected, server)).map(server => <p key={server}>{server}: {label(before, beforeSelected, server)} → {label(after, afterSelected, server)}{identityChanged(server) && <strong> · {zh ? "重新绑定当前服务身份" : "Rebind to the current service identity"}</strong>}</p>)}</>
}

import { useId, useState } from "react"
import { Button, Input, InputNumber, Radio, Table } from "antd"
import type { McpServerPolicy, OAuthScopeGroup, OAuthTool } from "./oauth-api"

export type { McpServerPolicy } from "./oauth-api"
export type McpAuthorizationMode = "none" | "continuous" | "selected"
export function validQuotas(rate: number | null, concurrency: number | null) {
  return rate !== null && concurrency !== null && Number.isInteger(rate) && rate >= 1 && rate <= 10000 && Number.isInteger(concurrency) && concurrency >= 1 && concurrency <= 100
}
export function QuotaFields({ rate, concurrency, onRate, onConcurrency, disabled, zh }: { rate: number | null; concurrency: number | null; onRate: (value: number | null) => void; onConcurrency: (value: number | null) => void; disabled?: boolean; zh: boolean }) {
  const id = useId()
  return <div className="authorization-quota-fields">
    <div className="authorization-field"><label htmlFor={`${id}-rate`}>{zh ? "每分钟调用上限" : "Calls per minute"}</label><div><InputNumber id={`${id}-rate`} disabled={disabled} min={1} max={10000} step={1} changeOnBlur={false} value={rate} status={rate === null || !Number.isInteger(rate) || rate < 1 || rate > 10000 ? "error" : undefined} onChange={onRate} />{(rate === null || !Number.isInteger(rate) || rate < 1 || rate > 10000) && <div role="alert">{zh ? "请输入 1–10000 的整数" : "Enter an integer from 1 to 10000"}</div>}</div></div>
    <div className="authorization-field"><label htmlFor={`${id}-concurrency`}>{zh ? "并发上限" : "Concurrent calls"}</label><div><InputNumber id={`${id}-concurrency`} disabled={disabled} min={1} max={100} step={1} changeOnBlur={false} value={concurrency} status={concurrency === null || !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 100 ? "error" : undefined} onChange={onConcurrency} />{(concurrency === null || !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 100) && <div role="alert">{zh ? "请输入 1–100 的整数" : "Enter an integer from 1 to 100"}</div>}</div></div>
  </div>
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
export function McpAuthorizationEditor({ groups, policies, modes = {}, onMode, onAccess, canWrite, disabled, zh }: { groups: OAuthScopeGroup[]; policies: McpServerPolicy[]; modes?: Record<string, McpAuthorizationMode>; onMode: (server: string, mode: McpAuthorizationMode) => void; onAccess: (server: string, access: "read" | "write") => void; canWrite: boolean; disabled?: boolean; zh: boolean }) {
  const [query, setQuery] = useState("")
  const [help, setHelp] = useState(false)
  return <section className="authorization-mcp-editor" aria-label={zh ? "MCP 资源范围" : "MCP resource scope"}>
    <div className="flex items-center gap-2"><Input.Search aria-label={zh ? "搜索 MCP" : "Search MCP"} value={query} onChange={event => setQuery(event.target.value)} allowClear placeholder={zh ? "搜索 MCP" : "Search MCP"} /><Button aria-expanded={help} onClick={() => setHelp(value => !value)}>{zh ? "授权规则" : "Scope rules"}</Button></div>
    {help && <div role="note">{zh ? "持续授权自动纳入此 MCP 后续已发布且本人获准的工具。只读不包含写工具；读写包含未来写工具，仍受当前令牌 scope 限制。指定工具仅保存明确选择的工具。" : "Continuous authorization includes future published tools in this MCP within your permissions and token scopes. Read excludes write tools; read/write includes future write tools. Selected mode saves only explicitly chosen tools."}{!canWrite && <p>{zh ? "当前功能权限不包含写入；OAuth 需从客户端重新申请 tools.invoke。" : "Current scopes exclude write access; OAuth clients must request tools.invoke again."}</p>}</div>}
    <Table<OAuthScopeGroup> rowKey="server_id" size="small" dataSource={groups.filter(group => `${group.server_id} ${group.server_name || ""}`.toLowerCase().includes(query.toLowerCase()))} pagination={{ pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }} scroll={{ x: 720 }} columns={[
      { title: "MCP", render: (_, group) => { const policy = policies.find(item => item.server_id === group.server_id); const identityChanged = Boolean(policy?.server_binding && group.server_binding && policy.server_binding !== group.server_binding); return <><strong>{group.server_name || group.server_id}</strong>{group.server_name && <div className="text-xs text-muted-foreground">{group.server_id}</div>}{identityChanged && <div role="status">{zh ? "服务身份已改变" : "Service identity changed"}<Button size="small" disabled={disabled} onClick={() => onMode(group.server_id, "continuous")}>{zh ? "重新确认服务" : "Reconfirm service"}</Button></div>}</> } },
      { title: zh ? "授权方式" : "Authorization", width: 340, render: (_, group) => <Radio.Group aria-label={`${group.server_id} ${zh ? "授权方式" : "authorization"}`} value={policies.some(policy => policy.server_id === group.server_id) ? "continuous" : modes[group.server_id] || "none"} disabled={disabled} onChange={event => onMode(group.server_id, event.target.value)} options={[{ value: "none", label: zh ? "不授权" : "None" }, { value: "continuous", label: zh ? "持续授权" : "Continuous" }, { value: "selected", label: zh ? "指定工具" : "Selected tools" }]} /> },
      { title: zh ? "访问权限" : "Access", width: 180, render: (_, group) => { const policy = policies.find(item => item.server_id === group.server_id); return policy ? <Radio.Group aria-label={`${group.server_id} ${zh ? "访问权限" : "access"}`} value={policy.access} disabled={disabled} onChange={event => onAccess(group.server_id, event.target.value)}><Radio value="read">{zh ? "只读" : "Read"}</Radio><Radio value="write" disabled={disabled || !canWrite}>{zh ? "读写" : "Read/write"}</Radio></Radio.Group> : "—" } },
      { title: zh ? "当前工具" : "Current tools", dataIndex: "tool_count", width: 100 },
    ]} />
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

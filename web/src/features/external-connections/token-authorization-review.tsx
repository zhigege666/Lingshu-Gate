import { Pagination } from "antd"
import { useListPage } from "@/components/list-pagination"
import type { McpServerPolicy, OAuthScopeGroup, OAuthTool } from "./oauth-api"
import { tokenMcpSignature, tokenMcpTools } from "./token-mcp-scope-model"

type Scope = { tool_ids: string[]; server_policies: McpServerPolicy[]; scopes: string[]; rate_per_minute: number | null; concurrency: number | null }
type Props = { before: Scope & { mode: "account" | "independent" }; after: Scope & { added: string[]; removed: string[] }; mode: "account" | "independent"; tools: OAuthTool[]; groups: OAuthScopeGroup[]; zh: boolean; create: boolean; name: string; expiry: string }

function sameIds(left: string[], right: string[]) { return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort()) }

/** Read-only server preview. Confirmation and the frozen write body stay in the dialog. */
export function TokenAuthorizationReview({ before, after, mode, tools, groups, zh, create, name, expiry }: Props) {
  const beforeScope = { selected: before.tool_ids, policies: before.server_policies }, afterScope = { selected: after.tool_ids, policies: after.server_policies }
  const changedGroups = groups.filter(group => tokenMcpSignature(group.server_id, beforeScope, tools) !== tokenMcpSignature(group.server_id, afterScope, tools))
  const byId = new Map(tools.map(tool => [tool.id, tool]))
  const unknownAdded = after.added.filter(id => !byId.has(id)), unknownRemoved = after.removed.filter(id => !byId.has(id))
  const policyLabel = (server: string, scope: Scope, scopeMode: "account" | "independent") => {
    if (scopeMode === "account") return zh ? "跟随账号权限" : "Follow account access"
    const policy = scope.server_policies.find(item => item.server_id === server)
    if (policy) return policy.access === "write" ? zh ? "持续读写" : "Continuous read/write" : zh ? "持续只读" : "Continuous read-only"
    const count = tokenMcpTools(server, scope.tool_ids, tools).length
    return count ? zh ? `指定 ${count} 个工具` : `${count} selected tools` : zh ? "未授权" : "No access"
  }
  const changes: { label: string; before: string; after: string }[] = []
  const unset = zh ? "未设置" : "Not set"
  if (create) {
    changes.push({ label: zh ? "授权名称" : "Authorization name", before: "—", after: name })
    changes.push({ label: zh ? "到期时间" : "Expires at", before: "—", after: expiry ? new Date(expiry).toLocaleString(zh ? "zh-CN" : "en-US") : zh ? "永不过期" : "No expiry" })
  }
  if (before.mode !== mode) changes.push({ label: zh ? "MCP 范围" : "MCP scope", before: before.mode === "account" ? zh ? "跟随账号权限" : "Follow account access" : zh ? "独立范围" : "Independent scope", after: mode === "account" ? zh ? "跟随账号权限" : "Follow account access" : zh ? "独立范围" : "Independent scope" })
  if (before.rate_per_minute !== after.rate_per_minute) changes.push({ label: zh ? "每分钟调用上限" : "Calls per minute", before: String(before.rate_per_minute ?? unset), after: String(after.rate_per_minute ?? unset) })
  if (before.concurrency !== after.concurrency) changes.push({ label: zh ? "并发上限" : "Concurrent calls", before: String(before.concurrency ?? unset), after: String(after.concurrency ?? unset) })
  const scopeChanged = !sameIds(before.scopes, after.scopes)
  const scopesAdded = after.scopes.filter(scope => !before.scopes.includes(scope)), scopesRemoved = before.scopes.filter(scope => !after.scopes.includes(scope))
  return <section className="token-authorization-review" aria-label={zh ? "授权变更明细" : "Authorization changes"}>
    {changes.length > 0 && <table className="token-review-table"><thead><tr><th>{zh ? "配置项" : "Setting"}</th><th>{zh ? "修改前" : "Before"}</th><th>{zh ? "修改后" : "After"}</th></tr></thead><tbody>{changes.map(change => <tr key={change.label}><th>{change.label}</th><td>{change.before}</td><td>{change.after}</td></tr>)}</tbody></table>}
    {before.mode === "account" && mode === "independent" && <p className="token-review-important">{zh ? "保存后只开放本次指定的 MCP 或工具；后续可再次核对并切换范围模式。" : "Only the specified MCPs or tools will be allowed. You can review and change the scope mode later."}</p>}
    {mode === "account" && (create || before.mode !== mode) && <p className="token-review-important">{zh ? "此令牌将跟随账号当前及后续的 MCP 资源权限，仍受上方功能权限和调用限制约束。" : "This token follows current and future account MCP access, within its functional permissions and call limits."}</p>}
    {scopeChanged && <section className="token-review-permissions"><h3>{zh ? "功能权限" : "Functional permissions"}</h3><div className="token-review-columns">{scopesAdded.length > 0 && <div><h4>{zh ? "新增" : "Added"}</h4>{scopesAdded.map(scope => <code key={scope}>{scope}</code>)}</div>}{scopesRemoved.length > 0 && <div><h4>{zh ? "移除" : "Removed"}</h4>{scopesRemoved.map(scope => <code key={scope}>{scope}</code>)}</div>}</div></section>}
    {changedGroups.map(group => {
      const server = group.server_id
      const added = after.added.filter(id => byId.get(id)?.server_id === server), removed = after.removed.filter(id => byId.get(id)?.server_id === server)
      const previous = before.server_policies.find(item => item.server_id === server), next = after.server_policies.find(item => item.server_id === server)
      const selected = tokenMcpTools(server, after.tool_ids, tools)
      return <section className="token-review-mcp" key={server} aria-label={`${group.server_name || server} ${zh ? "变更" : "changes"}`}>
        <h3>{group.server_name || server}</h3>
        <table className="token-review-table"><thead><tr><th>{zh ? "配置项" : "Setting"}</th><th>{zh ? "修改前" : "Before"}</th><th>{zh ? "修改后" : "After"}</th></tr></thead><tbody><tr><th>{zh ? "授权范围" : "Access scope"}</th><td>{policyLabel(server, before, before.mode)}</td><td>{policyLabel(server, after, mode)}</td></tr></tbody></table>
        {previous?.server_binding && next?.server_binding && previous.server_binding !== next.server_binding && <p className="token-review-important">{zh ? "重新绑定当前服务身份" : "Rebind to the current service identity"}</p>}
        {next && (!previous || previous.access !== next.access) && <p>{next.access === "write" ? zh ? "持续读写包含后续同步且本人获准的写工具，仍受功能权限限制。" : "Continuous read/write includes future synced write tools within your functional permissions." : zh ? "持续只读包含后续同步且本人获准的只读工具。" : "Continuous read-only includes future synced read-only tools within your permissions."}</p>}
        {(added.length > 0 || removed.length > 0 || selected.length > 0) && <div className="token-review-columns">{(added.length > 0 || removed.length > 0) && <div>{added.length > 0 && <ReviewTools title={zh ? "新增工具" : "Added tools"} ids={added} byId={byId} zh={zh} />}{removed.length > 0 && <ReviewTools title={zh ? "移除工具" : "Removed tools"} ids={removed} byId={byId} zh={zh} />}</div>}{selected.length > 0 && <ReviewTools title={zh ? "保存后的指定工具" : "Selected tools after saving"} ids={selected} byId={byId} zh={zh} />}</div>}
      </section>
    })}
    {unknownAdded.length > 0 && <ReviewTools title={zh ? "其他新增工具" : "Other added tools"} ids={unknownAdded} byId={byId} zh={zh} />}
    {unknownRemoved.length > 0 && <ReviewTools title={zh ? "其他移除工具" : "Other removed tools"} ids={unknownRemoved} byId={byId} zh={zh} />}
  </section>
}

function ReviewTools({ title, ids, byId, zh }: { title: string; ids: string[]; byId: Map<string, OAuthTool>; zh: boolean }) {
  const paging = useListPage(ids, ids.join(","), 20)
  return <section className="token-review-tools"><h4>{title}{ids.length > 20 ? ` (${ids.length})` : ""}</h4><ul>{paging.items.map(id => <li key={id}><span>{byId.get(id)?.name || id}</span>{byId.has(id) && byId.get(id)?.name !== id && <code>{id}</code>}</li>)}</ul>{paging.pageCount > 1 && <Pagination size="small" aria-label={`${title} ${zh ? "分页" : "pages"}`} current={paging.page} total={paging.total} pageSize={20} showSizeChanger={false} onChange={paging.setPage} />}</section>
}

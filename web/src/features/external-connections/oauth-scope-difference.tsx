import { useMemo, useState } from "react"
import { Input, Table, Tag } from "antd"
import type { OAuthDifferenceSummary, OAuthTool, ScopeSnapshot } from "./oauth-api"

export function scopeDifference(before: ScopeSnapshot[], selected: string[], catalog: OAuthTool[]) {
  const previous = new Map(before.map(tool => [tool.id, tool]))
  const chosen = new Set(selected)
  const added = catalog.filter(tool => {
    const old = previous.get(tool.id)
    return chosen.has(tool.id) && (!old || old.snapshot !== tool.snapshot || old.access !== tool.access || old.server_id !== tool.server_id)
  })
  const changed = new Set(added.map(tool => tool.id))
  const removed = before.filter(tool => !chosen.has(tool.id) || changed.has(tool.id))
  return { added, removed }
}

export function ScopeDifference({ before, selected, catalog, zh, summary, addedIds, removedIds }: { before: ScopeSnapshot[]; selected: string[]; catalog: OAuthTool[]; zh: boolean; summary?: OAuthDifferenceSummary; addedIds?: string[]; removedIds?: string[] }) {
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const changes = useMemo(() => scopeDifference(before, selected, catalog), [before, selected, catalog])
  const chosen = new Set(selected)
  const writeCount = catalog.filter(tool => chosen.has(tool.id) && tool.access === "write").length
  const names = new Map(catalog.map(tool => [tool.id, tool]))
  const previous = new Map(before.map(tool => [tool.id, tool]))
  const counts = summary || { added: changes.added.length, removed: changes.removed.length, added_write: changes.added.filter(tool => tool.access === "write").length, removed_write: changes.removed.filter(tool => tool.access === "write").length, write: writeCount }
  const rows = summary ? [...(addedIds || []).map(id => ({ key: `added:${id}`, tool: names.get(id) || { id, name: id, server_id: "", server_name: null, access: undefined }, added: true })), ...(removedIds || []).map(id => ({ key: `removed:${id}`, tool: previous.get(id) || { id, name: id, server_id: "", server_name: null, access: undefined }, added: false }))] : [...changes.added.map(tool => ({ key: `added:${tool.id}`, tool, added: true })), ...changes.removed.map(tool => ({ key: `removed:${tool.id}`, tool: { ...names.get(tool.id), ...tool }, added: false }))]
  const search = query.trim().toLocaleLowerCase()
  const filtered = rows.filter(row => `${row.tool.name || ""} ${row.tool.id} ${row.tool.server_name || ""} ${row.tool.server_id}`.toLocaleLowerCase().includes(search))
  return <section aria-label={zh ? "工具变更明细" : "Tool change details"} className="oauth-scope-difference">
    <p role="status">{zh ? `新增 / 重新确认 ${counts.added} 个工具（写入 ${counts.added_write}）；从当前连接移除 ${counts.removed} 个（写入 ${counts.removed_write}）；更新后共有 ${counts.write} 个写工具。` : `${counts.added} added / reconfirmed tools (${counts.added_write} write); ${counts.removed} removed (${counts.removed_write} write); ${counts.write} write tools after update.`}</p>
    {summary && <p className="oauth-muted">{zh ? "计数由服务端核对完整选择；明细按工具 ID 列出，未读取的摘要不猜测权限。" : "Counts cover the complete server-checked selection. Details list tool IDs; unloaded summaries do not infer access."}</p>}
    <Input aria-label={zh ? "搜索工具变更" : "Search tool changes"} allowClear value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} />
    <Table rowKey="key" size="small" dataSource={filtered} scroll={{ x: 540, y: "clamp(180px, 30dvh, 320px)" }} tableLayout="fixed"
      pagination={{ pageSize: 50, current: Math.min(page, Math.max(1, Math.ceil(filtered.length / 50))), showSizeChanger: false, onChange: setPage, showTotal: total => `${total}` }}
      columns={[{ title: zh ? "变更" : "Change", width: 120, render: (_, row) => <Tag color={row.added ? "blue" : undefined}>{row.added ? zh ? "新增 / 确认" : "Add / confirm" : zh ? "移除" : "Remove"}</Tag> },
        { title: "MCP", width: 140, render: (_, row) => <span className="oauth-wrap">{row.tool.server_id}</span> },
        { title: zh ? "工具" : "Tool", render: (_, row) => <div className="oauth-wrap">{row.tool.name || row.tool.id}<div className="oauth-muted">{row.tool.id}</div></div> },
        { title: zh ? "权限" : "Access", width: 110, render: (_, row) => <Tag color={row.tool.access === "write" ? "orange" : row.tool.access === "read" ? "blue" : undefined}>{row.tool.access === "write" ? zh ? "写入" : "Write" : row.tool.access === "read" ? zh ? "只读" : "Read" : zh ? "摘要未读取" : "Not loaded"}</Tag> }]} />
  </section>
}

import { useEffect, useRef, useState } from "react"
import { Button, Table } from "antd"
import { FormDialog } from "@/components/form-dialog"
import { oauthError, oauthRequest, type OAuthScopeCatalog, type OAuthScopeOptions, type OAuthScopeUnavailableServer } from "./oauth-api"

const reasons: Record<OAuthScopeUnavailableServer["reasons"][number]["code"], [string, string]> = {
  classification_not_published: ["工具策略已变化，请刷新可授权范围", "Tool policy changed; refresh available scope"],
  classification_unavailable: ["当前工具访问策略不可用", "The current tool access policy is unavailable"],
  local_policy_disabled: ["此工具已被本地策略停用", "This tool is disabled by local policy"],
  grant_scope_ceiling: ["超出此授权的原有 OAuth scope 上限", "Outside this grant's original OAuth scope ceiling"],
  client_scope_ceiling: ["当前客户端不允许所需 OAuth scope", "The client currently disallows the required OAuth scope"],
}

/** Read-only explanation of server-provided, owner-visible exclusions. */
export function ScopeAvailability({ options, zh, grantId }: { options: Omit<OAuthScopeOptions, "tools"> | OAuthScopeCatalog; zh: boolean; grantId?: string }) {
  const [open, setOpen] = useState(false)
  const [loaded, setLoaded] = useState<OAuthScopeCatalog | null>(null)
  const [cursors, setCursors] = useState<string[]>([""])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const generation = useRef(0)
  const paged = "catalog_revision" in options
  const revision = paged ? options.catalog_revision : ""
  const servers = paged ? (loaded?.items || []) as OAuthScopeUnavailableServer[] : options.unavailable_servers || []
  const count = paged ? options.unavailable_counts.tools : servers.reduce((sum, server) => sum + server.reasons.reduce((total, reason) => total + reason.count, 0), 0)
  const serverCount = paged ? options.unavailable_counts.mcps : servers.length
  async function load(nextCursors: string[]) {
    if (!grantId || !paged) return
    const current = ++generation.current
    setLoading(true); setError("")
    const params = new URLSearchParams({ view: "unavailable", limit: "15", catalog_revision: revision })
    if (nextCursors.at(-1)) params.set("cursor", nextCursors.at(-1)!)
    try {
      const result = await oauthRequest<OAuthScopeCatalog>(`/v1/auth/oauth/grants/${grantId}/scope-catalog?${params}`)
      if (current === generation.current) { setLoaded(result); setCursors(nextCursors) }
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { if (current === generation.current) setLoading(false) }
  }
  useEffect(() => { if (open && paged) void load([""]); return () => { generation.current++ } }, [open, revision, grantId])
  if (!count) return null
  return <div className="oauth-scope-availability">
    <div className="oauth-actions"><span>{zh ? `不可授权 ${count} 工具 · ${serverCount} 个本人可见 MCP` : `${count} tools unavailable · ${serverCount} owner-visible MCP${serverCount === 1 ? "" : "s"}`}</span><Button type="link" size="small" onClick={() => setOpen(true)}>{zh ? "查看不可授权原因" : "Why unavailable"}</Button></div>
    <FormDialog open={open} title={zh ? "不可授权原因" : "Unavailable scope reasons"} closeLabel={zh ? "关闭" : "Close"} onClose={() => setOpen(false)} className="oauth-client-dialog" footer={<Button type="text" onClick={() => setOpen(false)}>{zh ? "关闭" : "Close"}</Button>}>
      <p>{zh ? "以下仅统计本人当前可见工具。新工具自动同步；本地策略、本人权限及 OAuth scope 决定哪些工具可以授权。刷新后保留已选草稿。" : "These counts cover tools currently visible to you. New tools sync automatically; local policy, your permissions and OAuth scopes determine available access. Refreshing retains your selection draft."}</p>
      {options.can_review_classifications && <Button type="link" href="#/toolClassifications" target="_blank" rel="noopener noreferrer">{zh ? "在新页查看工具策略" : "View tool policies in a new tab"}</Button>}
      {error && <p role="alert">{error}</p>}
      <Table<OAuthScopeUnavailableServer> rowKey="server_id" size="small" loading={loading} dataSource={servers} tableLayout="fixed" scroll={{ y: "40dvh" }} pagination={paged ? false : { pageSize: 15, showSizeChanger: false }} columns={[
        { title: "MCP", width: 240, render: (_, server) => <div className="oauth-wrap">{server.server_name || server.server_id}{server.server_name && <div className="oauth-muted">{server.server_id}</div>}</div> },
        { title: zh ? "原因 / 工具数" : "Reason / tool count", render: (_, server) => <div className="oauth-wrap">{server.reasons.map(reason => <p key={reason.code}>{reasons[reason.code]?.[zh ? 0 : 1] || reason.code} · {reason.count}</p>)}</div> },
      ]} />
      {paged && <div className="oauth-paged-navigation"><span>{zh ? `第 ${cursors.length} 页` : `Page ${cursors.length}`}</span><div className="oauth-actions"><Button disabled={loading || cursors.length === 1} onClick={() => void load(cursors.slice(0, -1))}>{zh ? "上一页" : "Previous page"}</Button><Button disabled={loading || !loaded?.next_cursor} onClick={() => void load([...cursors, loaded!.next_cursor!])}>{zh ? "下一页" : "Next page"}</Button></div></div>}
    </FormDialog>
  </div>
}

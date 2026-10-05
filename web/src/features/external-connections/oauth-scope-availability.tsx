import { useState } from "react"
import { Button, Table } from "antd"
import { FormDialog } from "@/components/form-dialog"
import type { OAuthScopeOptions, OAuthScopeUnavailableServer } from "./oauth-api"

const reasons: Record<OAuthScopeUnavailableServer["reasons"][number]["code"], [string, string]> = {
  classification_not_published: ["分类尚未发布；需审核并发布", "Classification is unpublished; review and publish it"],
  classification_unavailable: ["没有有效的已发布读写分类", "No valid published read/write classification"],
  grant_scope_ceiling: ["超出此授权的原有 OAuth scope 上限", "Outside this grant's original OAuth scope ceiling"],
  client_scope_ceiling: ["当前客户端不允许所需 OAuth scope", "The client currently disallows the required OAuth scope"],
}

/** Read-only explanation of server-provided, owner-visible exclusions. */
export function ScopeAvailability({ options, zh }: { options: OAuthScopeOptions; zh: boolean }) {
  const [open, setOpen] = useState(false)
  const servers = options.unavailable_servers || []
  const count = servers.reduce((sum, server) => sum + server.reasons.reduce((total, reason) => total + reason.count, 0), 0)
  if (!count) return null
  return <div className="oauth-scope-availability">
    <div className="oauth-actions"><span>{zh ? `不可授权 ${count} 工具 · ${servers.length} 个本人可见 MCP` : `${count} tools unavailable · ${servers.length} owner-visible MCPs`}</span><Button type="link" size="small" onClick={() => setOpen(true)}>{zh ? "查看不可授权原因" : "Why unavailable"}</Button></div>
    <FormDialog open={open} title={zh ? "不可授权原因" : "Unavailable scope reasons"} closeLabel={zh ? "关闭" : "Close"} onClose={() => setOpen(false)} className="oauth-client-dialog" footer={<Button type="text" onClick={() => setOpen(false)}>{zh ? "关闭" : "Close"}</Button>}>
      <p>{zh ? "以下仅统计本人当前可见工具。分类审核和发布与发现、API Token 调用及 OAuth 授权相互独立。处理后回到授权窗口刷新；已选草稿会保留。" : "These counts cover tools currently visible to you. Classification review and publication are separate from discovery, API-token invocation and OAuth consent. Return and refresh after review; your selection draft is retained."}</p>
      {options.can_review_classifications && <Button type="link" href="#/toolClassifications" target="_blank" rel="noopener noreferrer">{zh ? "在新页审核工具分类" : "Review tool classifications in a new tab"}</Button>}
      <Table<OAuthScopeUnavailableServer> rowKey="server_id" size="small" dataSource={servers} tableLayout="fixed" scroll={{ y: "40dvh" }} pagination={{ pageSize: 15, showSizeChanger: false }} columns={[
        { title: "MCP", width: 240, render: (_, server) => <div className="oauth-wrap">{server.server_name || server.server_id}<div className="oauth-muted">{server.server_id}</div></div> },
        { title: zh ? "原因 / 工具数" : "Reason / tool count", render: (_, server) => <div className="oauth-wrap">{server.reasons.map(reason => <p key={reason.code}>{reasons[reason.code]?.[zh ? 0 : 1] || reason.code} · {reason.count}</p>)}</div> },
      ]} />
    </FormDialog>
  </div>
}

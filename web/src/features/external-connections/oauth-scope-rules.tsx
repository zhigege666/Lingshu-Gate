import { Button, Popover } from "antd"
import { InfoCircleOutlined } from "@ant-design/icons"
import type { OAuthGrant, OAuthScopeOptions } from "./oauth-api"

/** Compact grant summary; disclosure is read-only and never changes the draft. */
export function ScopeRules({ options, grant, loading, added, addedWrite, removed, zh, open, onOpenChange }: { options: Pick<OAuthScopeOptions, "scopes" | "effective_scopes" | "family_scope_limits"> | null; grant: OAuthGrant; loading: boolean; added: number; addedWrite: number; removed: number; zh: boolean; open: boolean; onOpenChange: (open: boolean) => void }) {
  const scopes = options?.scopes || grant.scopes
  return <div className="oauth-scope-rule-row">
    <span className="oauth-scope-rule-summary oauth-muted" role="status">{loading ? zh ? "正在读取本人可授权范围…" : "Loading your available scope…" : `${zh ? "OAuth 上限" : "OAuth ceiling"}: ${scopes.join(" · ") || "—"} · ${options ? zh ? "本人当前获准且已发布的工具" : "Currently permitted, published tools" : zh ? "可授权目录尚未读取，请刷新" : "Catalog not loaded; refresh available scope"}`}</span>
    <Popover trigger="click" placement="bottomLeft" arrow={false} open={open} onOpenChange={onOpenChange} getPopupContainer={trigger => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} title={zh ? "范围与授权规则" : "Scope and authorization rules"} content={<div className="oauth-scope-info">
      <p className="oauth-wrap">{grant.client_name} · {grant.resource}</p>
      <p>{zh ? "现有 OAuth scope 上限：" : "Existing OAuth scope ceiling: "}{scopes.join(" · ") || "—"}{options && <><br />{zh ? "当前客户端允许：" : "Currently allowed by client: "}{options.effective_scopes.join(" · ") || "—"}</>}</p>
      <p>{zh ? "各令牌族仍受自己的 scope 上限约束；仅有 tools.read 的令牌不能调用新增写工具。" : "Each token family keeps its own scope ceiling; a tools.read-only token cannot invoke newly added write tools."}{options && options.family_scope_limits.length > 0 && <> {options.family_scope_limits.map(limit => `${limit.count} × ${limit.scopes.join(" + ") || "—"}`).join("; ")}</>}</p>
      <p>{zh ? "OAuth 仅提供本人当前获准、已发布且符合 scope 上限的工具。管理员 API Token 调用成功不代表工具分类已发布。" : "OAuth offers currently permitted, published tools within scope ceilings. A successful admin API-token call does not establish published classification."}</p>
      {!grant.scope_currently_authorized && <p>{zh ? `原工具中当前仍获准 ${grant.effective_tool_count} 项；更新只接受当前可授权工具。` : `${grant.effective_tool_count} original tools remain authorized; updates accept currently available tools.`}</p>}
      <p>{zh ? `新增 / 重新确认 ${added} 个工具（写入 ${addedWrite}）；从当前连接移除 ${removed} 个。保存前将核对完整差异。` : `${added} added / reconfirmed tools (${addedWrite} write); ${removed} removed. Review the complete difference before saving.`}</p>
    </div>}>
      <Button type="text" size="small" className="oauth-scope-info-trigger" aria-label={zh ? "查看范围与授权规则" : "Scope details"} aria-expanded={open} icon={<InfoCircleOutlined aria-hidden />} />
    </Popover>
  </div>
}

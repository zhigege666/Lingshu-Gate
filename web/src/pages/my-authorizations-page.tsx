import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Dropdown, Input, Radio, Table, Tag } from "antd"
import { api, type PersonalToken } from "@/api/client"
import { useConfirm } from "@/components/confirm-dialog"
import { FormDialog } from "@/components/form-dialog"
import { PageHeader } from "@/components/page-shell"
import { PageRefreshContext, usePageRefresh } from "@/components/page-refresh"
import { McpClientSettingsDialog } from "@/features/mcp-client-settings-dialog"
import { TokenScopeSummary } from "@/pages/personal-tokens-page"
import { BuiltinOAuthGrants, type OAuthGrantAction } from "@/pages/oauth-grants"
import { ExternalIdentityGrants } from "@/pages/external-connections-page"
import { oauthRequest, oauthError, type OAuthGrant } from "@/features/external-connections/oauth-api"
import { externalRequest, externalError } from "@/features/external-connections/api"
import type { Grant, GrantList } from "@/features/external-connections/model"
import { TokenAuthorizationDialog } from "@/features/external-connections/token-authorization-dialog"
import { DiscoveryModeDialog, discoveryLabel } from "@/features/external-connections/discovery-mode-dialog"
import { formatDateTime } from "@/lib/utils"
import type { Locale, TFunction } from "@/i18n"
import { authorizationRows, type AuthorizationRow, type Kind } from "@/features/external-connections/my-authorizations-model"
import "@/features/external-connections/authorization-editor.css"

export function MyAuthorizationsPage({ locale, t, initialKind = "all" }: { locale: Locale; t: TFunction; initialKind?: Kind | "all" }) {
  const zh = locale === "zh-CN"
  const [tokens, setTokens] = useState<PersonalToken[]>([]), [builtin, setBuiltin] = useState<OAuthGrant[]>([]), [external, setExternal] = useState<Grant[]>([])
  const [errors, setErrors] = useState<Partial<Record<Kind, string>>>({}), [busy, setBusy] = useState(false)
  const [kind, setKind] = useState<Kind | "all">(initialKind), [state, setState] = useState("active"), [purpose, setPurpose] = useState("all"), [query, setQuery] = useState("")
  const [tokenTarget, setTokenTarget] = useState<PersonalToken | null>(null), [creating, setCreating] = useState(false)
  const [oauthAction, setOauthAction] = useState<OAuthGrantAction>(), [externalAction, setExternalAction] = useState<{ grant?: Grant; action: "edit" | "revoke"; nonce: number }>()
  const [details, setDetails] = useState<AuthorizationRow | null>(null), [guide, setGuide] = useState(false)
  const [discoveryTarget, setDiscoveryTarget] = useState<AuthorizationRow | null>(null)
  const generation = useRef(0), serial = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const kindLabel = (value: Kind) => ({ api: zh ? "API 令牌" : "API token", builtin: "Gate OAuth", external: zh ? "外部 OAuth" : "External OAuth" })[value]
  const stateLabel = (value: string) => ({ active: zh ? "有效" : "Active", revoked: zh ? "已撤销" : "Revoked", expired: zh ? "已过期" : "Expired", disabled: zh ? "已关闭" : "Disabled" })[value] || value
  const load = useCallback(async () => {
    const current = ++generation.current; setBusy(true)
    const results = await Promise.allSettled([api.personalTokens(), oauthRequest<{ grants: OAuthGrant[] }>("/v1/auth/oauth/grants"), externalRequest<GrantList>("/v1/auth/external-grants")])
    if (current !== generation.current) return
    const nextErrors: Partial<Record<Kind, string>> = {}
    if (results[0].status === "fulfilled") setTokens(results[0].value.tokens); else nextErrors.api = String(results[0].reason)
    if (results[1].status === "fulfilled") setBuiltin(results[1].value.grants); else nextErrors.builtin = oauthError(results[1].reason, zh)
    if (results[2].status === "fulfilled") setExternal(results[2].value.grants); else nextErrors.external = externalError(results[2].reason, zh)
    setErrors(nextErrors); setBusy(false)
  }, [zh])
  useEffect(() => { void load(); return () => { generation.current++ } }, [load])
  usePageRefresh(load, busy || Boolean(tokenTarget) || creating || Boolean(details) || Boolean(discoveryTarget))
  const rows = useMemo(() => authorizationRows(tokens, builtin, external, zh), [tokens, builtin, external, zh])
  const filtered = rows.filter(row => (kind === "all" || row.kind === kind) && (state === "all" || row.status === state) && (purpose === "all" || row.purpose === purpose) && `${row.name} ${row.id} ${row.identifier}`.toLowerCase().includes(query.toLowerCase()))
  function act(row: AuthorizationRow, action: "view" | "edit" | "revoke") {
    if (row.kind === "builtin") { setOauthAction({ grant: row.source as OAuthGrant, action, nonce: ++serial.current }); return }
    if (action === "view") { setDetails(row); return }
    if (row.kind === "external") { setExternalAction({ grant: row.source as Grant, action, nonce: ++serial.current }); return }
    if (action === "edit") setTokenTarget(row.source as PersonalToken)
    else void (async () => { if (!(await confirm({ title: zh ? "撤销授权？" : "Revoke authorization?", description: `${row.name} · ${row.identifier}`, destructive: true }))) return; setBusy(true); try { await api.revokePersonalToken(row.id); await load() } catch (cause) { setErrors(current => ({ ...current, api: String(cause) })) } finally { setBusy(false) } })()
  }
  return <div className="flex min-w-0 flex-col gap-4">
    <PageHeader title={zh ? "我的授权" : "My authorizations"} closeLabel={t("close")} helpLabel={t("pageHelp")} helpContent={<p>{zh ? "API 令牌只在创建时显示明文；OAuth 从客户端发起。持续授权在当前权限及 OAuth scope 内纳入后续已发布工具。" : "API token secrets are shown once at creation. Start OAuth from the client. Continuous authorization includes future published tools within account permissions and OAuth scopes."}</p>} actions={<><McpClientSettingsDialog locale={locale} t={t} /><Dropdown menu={{ items: [{ key: "api", label: zh ? "创建 API 令牌" : "Create API token" }, { key: "oauth", label: zh ? "OAuth 接入说明" : "OAuth connection guide" }, { key: "external", label: zh ? "配置外部身份授权" : "Configure external authorization" }], onClick: ({ key }) => { if (key === "api") setCreating(true); else if (key === "oauth") setGuide(true); else setExternalAction({ action: "edit", nonce: ++serial.current }) } }}><Button type="primary" disabled={busy}>{zh ? "新增授权" : "New authorization"}</Button></Dropdown></>} />
    {Object.entries(errors).map(([source, message]) => <Alert key={source} type="error" title={`${kindLabel(source as Kind)} ${zh ? "读取失败" : "load failed"}`} description={message} action={<Button onClick={() => void load()}>{t("retry")}</Button>} />)}
    <div className="authorization-toolbar"><Input.Search aria-label={zh ? "搜索授权" : "Search authorizations"} placeholder={zh ? "搜索名称、客户端或 ID" : "Search name, client or ID"} allowClear value={query} onChange={event => setQuery(event.target.value)} /><Radio.Group aria-label={zh ? "授权方式" : "Authorization type"} value={kind} onChange={event => setKind(event.target.value)} options={[{ value: "all", label: zh ? "全部" : "All" }, ...(["api", "builtin", "external"] as Kind[]).map(value => ({ value, label: kindLabel(value) }))]} /><Radio.Group aria-label={zh ? "用途" : "Purpose"} value={purpose} onChange={event => setPurpose(event.target.value)} options={[{ value: "all", label: zh ? "全部" : "All" }, { value: "business", label: zh ? "业务" : "Business" }, { value: "management", label: zh ? "管理" : "Management" }]} /><Radio.Group aria-label={zh ? "授权状态" : "Authorization status"} value={state} onChange={event => setState(event.target.value)} options={[{ value: "active", label: zh ? "有效" : "Active" }, { value: "expired", label: zh ? "已过期" : "Expired" }, { value: "revoked", label: zh ? "已撤销" : "Revoked" }, { value: "all", label: zh ? "全部" : "All" }]} /></div>
    {Object.keys(errors).length > 0 && <span role="status">{zh ? `已加载 ${rows.length} 条` : `${rows.length} loaded`}</span>}
    <Table<AuthorizationRow> rowKey="key" size="small" dataSource={filtered} loading={busy} scroll={{ x: 1150 }} pagination={{ pageSize: 15, hideOnSinglePage: true, showSizeChanger: false, showTotal: total => Object.keys(errors).length ? zh ? `已加载 ${rows.length} 条 · 匹配 ${total} 条` : `${rows.length} loaded · ${total} matches` : zh ? `共 ${total} 条` : `${total} total` }} columns={[
      { title: zh ? "授权名称" : "Authorization name", render: (_, row) => <><Button type="link" onClick={() => act(row, "view")}>{row.name}</Button><div className="text-xs text-muted-foreground">{row.identifier}</div></> },
      { title: zh ? "授权方式" : "Type", render: (_, row) => <>{kindLabel(row.kind)}{row.purpose === "management" && <Tag>{zh ? "管理" : "Management"}</Tag>}</> },
      { title: zh ? "访问范围" : "Access scope", dataIndex: "scope" },
      { title: zh ? "工具发现" : "Tool discovery", render: (_, row) => {
        const mode = "tool_discovery_mode" in row.source && row.source.tool_discovery_mode === "direct" ? "direct" : "on_demand"
        return row.purpose === "management" ? zh ? "固定管理工具" : "Fixed management tools" : <Button type="link" disabled={busy || row.status !== "active" || Boolean(errors[row.kind])} onClick={() => setDiscoveryTarget(row)}>{discoveryLabel(mode, zh)}</Button>
      } },
      { title: zh ? "调用配额" : "Call limits", render: (_, row) => row.rate === null ? zh ? "未设置" : "Not set" : <>{row.rate} / min<div>{zh ? "并发" : "Concurrent"} {row.concurrency ?? "—"}</div></> },
      { title: t("status"), render: (_, row) => <Tag color={row.status === "active" ? "green" : undefined}>{stateLabel(row.status)}</Tag> },
      { title: zh ? "有效期" : "Expires at", render: (_, row) => row.expiry ? formatDateTime(row.expiry) : zh ? "永久有效" : "Never" },
      { title: t("actions"), width: 250, render: (_, row) => <div className="flex flex-wrap gap-2"><Button size="small" disabled={busy} onClick={() => act(row, "view")}>{zh ? "详情" : "Details"}</Button>{row.status === "active" && <><Button size="small" disabled={busy || Boolean(errors[row.kind])} onClick={() => act(row, "edit")}>{zh ? "调整授权" : "Adjust"}</Button><Button size="small" danger disabled={busy || Boolean(errors[row.kind])} onClick={() => act(row, "revoke")}>{zh ? "撤销" : "Revoke"}</Button></>}</div> },
    ]} />
    <TokenAuthorizationDialog target={tokenTarget} create={creating} locale={locale} t={t} onClose={() => { setTokenTarget(null); setCreating(false) }} onSaved={() => void load()} />
    <DiscoveryModeDialog target={discoveryTarget} locale={locale} t={t} onClose={() => setDiscoveryTarget(null)} onSaved={() => void load()} />
    <PageRefreshContext.Provider value={null}><BuiltinOAuthGrants embedded locale={locale} t={t} action={oauthAction} onChanged={() => void load()} />
    <ExternalIdentityGrants embedded locale={locale} t={t} action={externalAction} onChanged={() => void load()} /></PageRefreshContext.Provider>
    <FormDialog open={Boolean(details)} title={zh ? "授权详情" : "Authorization details"} closeLabel={t("close")} onClose={() => setDetails(null)} footer={<Button onClick={() => setDetails(null)}>{t("close")}</Button>}>{details && <div className="space-y-3"><p>{details.name} · {kindLabel(details.kind)}</p><Input readOnly aria-label="ID" value={details.id} /><p>{details.scope}</p>{details.kind === "api" && <><TokenScopeSummary scopes={(details.source as PersonalToken).scopes} locale={locale} /><p>{zh ? "最近使用" : "Last used"}: {(details.source as PersonalToken).last_used_at ? formatDateTime((details.source as PersonalToken).last_used_at!) : zh ? "未提供" : "Not provided"}</p><McpClientSettingsDialog locale={locale} t={t} /></>}</div>}</FormDialog>
    <FormDialog open={guide} title={zh ? "OAuth 接入说明" : "OAuth connection guide"} closeLabel={t("close")} onClose={() => setGuide(false)} footer={<Button onClick={() => setGuide(false)}>{t("close")}</Button>}><p>{zh ? "在 MCP 客户端添加 Gate 的 MCP 接入地址，选择 OAuth 并在浏览器中完成本人授权。" : "Add the Gate MCP endpoint in your MCP client, select OAuth, then complete authorization in your browser."}</p><McpClientSettingsDialog locale={locale} t={t} /></FormDialog>
    {confirmDialog}
  </div>
}

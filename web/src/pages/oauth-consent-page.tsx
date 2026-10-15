import { useEffect, useRef, useState } from "react"
import { Alert, Button, Form, Input, Radio, Select, Spin, Tag } from "antd"
import { useConsoleDesign } from "@/components/console-design-provider"
import { McpAuthorizationEditor, QuotaFields, validQuotas, policyGroups, type McpServerPolicy, type McpAuthorizationMode } from "@/features/external-connections/mcp-authorization-editor"
import "@/features/external-connections/authorization-editor.css"
import { OAuthToolPicker } from "@/features/external-connections/oauth-tool-picker"
import { oauthError, oauthRequest, OAuthRequestError, type ConsentContext } from "@/features/external-connections/oauth-api"
import { ManagementTargetsEditor } from "@/features/external-connections/management-targets-editor"
import { managementTargets, newManagementTarget, type ManagementTargetRow } from "@/features/external-connections/management-targets-model"

export function OAuthConsentPage() {
  const { locale, setLocale } = useConsoleDesign()
  const zh = locale === "zh-CN"
  const [requestId] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("request") || "")
  const [context, setContext] = useState<ConsentContext | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [targets, setTargets] = useState<ManagementTargetRow[]>(() => [newManagementTarget()])
  const [days, setDays] = useState(7)
  const [rate, setRate] = useState<number | null>(6000)
  const [concurrency, setConcurrency] = useState<number | null>(100)
  const [policies, setPolicies] = useState<McpServerPolicy[]>([])
  const [modes, setModes] = useState<Record<string, McpAuthorizationMode>>({})
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [targetError, setTargetError] = useState("")
  const [terminal, setTerminal] = useState(false)
  const lock = useRef(false)
  const version = useRef(0)
  const actionGeneration = useRef(0)
  const userId = useRef<string | null>(null)
  const offeredSnapshots = useRef(new Map<string, string>())

  function adopt(next: ConsentContext) {
    setContext(next)
    if (next.resource_kind === "management" && !context) { setRate(30); setConcurrency(1) }
    const snapshots = new Map(next.tools.map(tool => [tool.id, tool.snapshot]))
    const previousSnapshots = offeredSnapshots.current
    if (next.user && userId.current && next.user.id !== userId.current) { setSelected([]); setPolicies([]); setModes({}); setTargets([newManagementTarget()]); setTargetError("") }
    else if (next.user) setSelected(current => current.filter(id => snapshots.has(id) && snapshots.get(id) === previousSnapshots.get(id)))
    // Keep selections while the same account reauthenticates after expiry.
    if (next.user) { userId.current = next.user.id; offeredSnapshots.current = snapshots }
    setTerminal(next.completed)
  }
  async function refresh() {
    if (!requestId) { setTerminal(true); setError(zh ? "请从客户端发起 OAuth 连接后打开此页。" : "Open this page by starting an OAuth connection from the client."); setLoading(false); return }
    const current = ++version.current
    setLoading(true)
    try {
      const next = await oauthRequest<ConsentContext>(`/oauth/context?request_id=${encodeURIComponent(requestId)}`)
      if (current === version.current) { adopt(next); setError("") }
    } catch (cause) {
      if (current === version.current) {
        setError(oauthError(cause, zh))
        if (cause instanceof OAuthRequestError && [404, 410].includes(cause.status)) setTerminal(true)
      }
    } finally { if (current === version.current) setLoading(false) }
  }
  useEffect(() => { void refresh(); return () => { version.current++; actionGeneration.current++ } }, [])

  async function act(action: "login" | "logout" | "decision", deny = false) {
    if (lock.current || !context) return
    const current = ++actionGeneration.current
    version.current++
    lock.current = true
    setBusy(true); setError("")
    try {
      const base = { request_id: requestId, csrf: context.csrf }
      if (action === "login") {
        const next = await oauthRequest<ConsentContext>("/oauth/login", { ...base, username, password })
        if (current !== actionGeneration.current) return
        adopt(next)
        setPassword("")
      } else if (action === "logout") {
        await oauthRequest("/oauth/logout", base)
        if (current !== actionGeneration.current) return
        userId.current = null; setSelected([]); setPolicies([]); setModes({}); setTargets([newManagementTarget()]); setTargetError(""); setPassword("")
        await refresh()
      } else {
        const management = !deny && context.resource_kind === "management" ? { management_targets: managementTargets(targets) } : {}
        const result = await oauthRequest<{ redirect: string }>("/oauth/decision", { ...base, deny, tool_ids: deny ? [] : selected, ...(context.resource_kind !== "management" ? { server_policies: deny ? [] : policies } : {}), grant_days: days, rate_per_minute: rate, concurrency, ...management })
        if (current !== actionGeneration.current) return
        setTerminal(true)
        // The server returns only the pre-registered exact HTTPS callback.
        window.location.assign(result.redirect)
      }
    } catch (cause) {
      if (current !== actionGeneration.current) return
      if (cause instanceof OAuthRequestError && cause.code === "invalid_management_targets") setTargetError(oauthError(cause, zh))
      else setError(oauthError(cause, zh))
      if (cause instanceof OAuthRequestError && cause.code === "login_required") setContext(current => current ? { ...current, user: null } : current)
      if (cause instanceof OAuthRequestError && ["authorization_completed", "authorization_expired", "authorization_changed"].includes(cause.code)) setTerminal(true)
    } finally { lock.current = false; if (current === actionGeneration.current) setBusy(false) }
  }

  return <main className="oauth-public">
    <header className="oauth-public-header"><strong>Lingshu Gate</strong><Select aria-label={zh ? "界面语言" : "Interface language"} value={locale} onChange={setLocale} options={[{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]} /></header>
    <h1>{zh ? "授权连接" : "Authorize connection"}</h1>
    {error && <Alert type="error" showIcon title={error} action={!terminal && <Button disabled={busy || loading} onClick={() => void refresh()}>{zh ? "刷新授权信息" : "Refresh authorization details"}</Button>} />}
    {loading && <div role="status" className="oauth-loading"><Spin /> {zh ? "正在读取授权请求…" : "Loading authorization request…"}</div>}
    {!loading && terminal && <Alert type="info" title={context?.completed ? (zh ? "此授权请求已处理。返回客户端查看连接结果；失败时重新发起授权。" : "This authorization request was processed. Return to the client to check the connection; start a new authorization if it failed.") : (zh ? "请返回客户端重新发起连接。" : "Return to the client to start a new connection.")} />}
    {!loading && context && !terminal && <>
      <section className="oauth-client" aria-label={zh ? "请求连接的客户端" : "Client requesting access"}><h2>{context.client.name}</h2><div className="oauth-muted oauth-wrap">{context.client.id}</div><p className="oauth-wrap">{zh ? "请求访问：" : "Requests access to: "}{context.resource}</p><div>{context.scopes.map(scope => <Tag key={scope}>{scope === "operations.manage" ? zh ? "外部配置管理" : "External configuration management" : scope === "tools.invoke" ? zh ? "写入工具" : "Write tools" : zh ? "只读工具" : "Read tools"}</Tag>)}</div></section>
      {!context.user ? <section className="oauth-login"><h2>{zh ? "登录已有 Gate 账号" : "Sign in to your Gate account"}</h2><p>{context.resource_kind === "management" ? zh ? "使用当前有效的管理员账号登录，再选择管理工具和精确目标。" : "Sign in with a current administrator account, then choose management tools and exact targets." : zh ? "登录后选择允许此客户端使用的 MCP 和工具。" : "After signing in, choose the MCPs and tools this client may use."}</p>
        <Form layout="horizontal" className="oauth-inline-form" onFinish={() => void act("login")}>
          <Form.Item label={zh ? "用户名" : "Username"} htmlFor="oauth-username"><Input id="oauth-username" autoComplete="username" maxLength={100} value={username} disabled={busy} onChange={event => setUsername(event.target.value)} /></Form.Item>
          <Form.Item label={zh ? "密码" : "Password"} htmlFor="oauth-password"><Input.Password id="oauth-password" autoComplete="current-password" maxLength={1024} value={password} disabled={busy} onChange={event => setPassword(event.target.value)} /></Form.Item>
          <div className="oauth-actions"><Button disabled={busy} onClick={() => void act("decision", true)}>{zh ? "取消连接" : "Cancel connection"}</Button><Button type="primary" htmlType="submit" loading={busy} disabled={!username.trim() || !password}>{zh ? "登录" : "Sign in"}</Button></div>
        </Form>
      </section> : <div className="oauth-consent-layout">
        <section><div className="oauth-user"><span>{zh ? "当前用户：" : "Current user: "}<strong>{context.user.display_name || context.user.username}</strong> (@{context.user.username})</span><Button disabled={busy} onClick={() => void act("logout")}>{zh ? "切换账号" : "Switch account"}</Button></div><p>{context.resource_kind === "management" ? zh ? "这是独立的管理员管理连接，仅显示当前管理 scope 允许的四个配置工具。明确选择工具，并填写本次允许创建或更新的精确服务 ID。" : "This is a separate administrator management connection. Only the four configuration tools allowed by the current scopes are shown. Explicitly select tools and exact server IDs allowed for create or update." : zh ? "只显示你当前获准且已发布的工具。跨页选择；持续授权按所选读写级别纳入未来工具。" : "Only currently authorized, published tools are shown. Select across pages; Continuous authorization includes future tools at the chosen access level."}</p>{context.resource_kind === "management" && <><ManagementTargetsEditor rows={targets} onChange={rows => { setTargets(rows); setTargetError("") }} zh={zh} disabled={busy} />{targetError && <Alert type="error" title={targetError} />}</>}{context.resource_kind === "management" ? <OAuthToolPicker tools={context.tools} selected={selected} onChange={setSelected} zh={zh} disabled={busy} /> : <><McpAuthorizationEditor groups={policyGroups(context.tools, policies)} policies={policies} modes={modes} canWrite={context.scopes.includes("tools.invoke")} disabled={busy} zh={zh} onMode={(server, mode) => { setModes(current => ({ ...current, [server]: mode })); setPolicies(current => [...current.filter(policy => policy.server_id !== server), ...(mode === "continuous" ? [{ server_id: server, mode: "continuous" as const, access: "read" as const }] : [])]); if (mode !== "selected") setSelected(current => current.filter(id => !context.tools.some(tool => tool.id === id && tool.server_id === server))) }} onAccess={(server, access) => setPolicies(current => current.map(policy => policy.server_id === server ? { ...policy, access } : policy))} />{Object.values(modes).includes("selected") && <OAuthToolPicker tools={context.tools.filter(tool => modes[tool.server_id] === "selected")} selected={selected} onChange={setSelected} zh={zh} disabled={busy} />}</>}</section>
        <aside className="oauth-consent-summary"><h2>{zh ? "本次授权" : "This authorization"}</h2><Form layout="horizontal" className="oauth-inline-form">
          <Form.Item label={zh ? "授权有效期" : "Grant validity"}><Radio.Group aria-label={zh ? "授权有效期" : "Grant validity"} disabled={busy} value={days} onChange={event => setDays(Number(event.target.value))} options={[1, 7, 30].map(value => ({ value, label: zh ? `${value} 天` : `${value} days` }))} /></Form.Item>
          <QuotaFields rate={rate} concurrency={concurrency} onRate={setRate} onConcurrency={setConcurrency} disabled={busy} zh={zh} />
        </Form><p>{zh ? "到期（UTC）：" : "Expires (UTC): "}{new Date(Date.now() + days * 86400000).toISOString().slice(0, 19).replace("T", " ")}</p><p>{zh ? `访问令牌最长 ${context.access_seconds / 60} 分钟；刷新令牌族最长 ${context.refresh_days} 天，均不超过授权到期时间。` : `Access tokens last up to ${context.access_seconds / 60} minutes; refresh families last up to ${context.refresh_days} days. Both stop at grant expiry.`}</p><p className="oauth-muted">{context.resource_kind === "management" ? zh ? "你可在私有控制台的“我的授权”中确认调整精确目标或撤销授权。目标变更不会增加已同意的工具、JWT 或令牌族 scope；旧配置计划失效。配额在单 Core 进程中计数，重启后重置。" : "Confirm exact target changes or revoke this grant under My authorizations in the private console. Target changes cannot add consented tools or JWT/family scopes; existing configuration plans become stale. Quotas are counted in one Core process and reset on restart." : zh ? "你可在内部控制台的“我的授权”中确认增加或减少现有 OAuth scope 内的工具，或撤销授权。调用仍受当前角色和资源权限约束；配额在单 Core 进程中计数，重启后重置。" : "Confirm additions or removals within existing OAuth scopes, or revoke this grant, under My authorizations in the private console. Calls remain subject to current role and resource permissions. Quotas are counted in one Core process and reset on restart."}</p><div className="oauth-actions"><Button disabled={busy} onClick={() => void act("decision", true)}>{zh ? "取消" : "Cancel"}</Button><Button type="primary" loading={busy} disabled={(!selected.length && !policies.length) || !validQuotas(rate, concurrency) || Boolean(error)} onClick={() => void act("decision")}>{zh ? "允许授权" : "Allow authorization"}</Button></div></aside>
      </div>}
    </>}
  </main>
}

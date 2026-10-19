import { useEffect, useRef, useState } from "react"
import { Alert, Button, Form, Input, Radio, Spin, Tag } from "antd"
import { useConsoleDesign } from "@/components/console-design-provider"
import { McpAuthorizationEditor, QuotaSettings, validQuotas, policyGroups, selectCurrentTools, currentAuthorizationSummary, type CurrentToolAccess, type McpServerPolicy, type McpAuthorizationMode } from "@/features/external-connections/mcp-authorization-editor"
import "@/features/external-connections/authorization-editor.css"
import { OAuthToolPicker } from "@/features/external-connections/oauth-tool-picker"
import { oauthError, oauthRequest, OAuthRequestError, type ConsentContext } from "@/features/external-connections/oauth-api"
import { ManagementTargetsEditor } from "@/features/external-connections/management-targets-editor"
import { managementTargets, newManagementTarget, type ManagementTargetRow } from "@/features/external-connections/management-targets-model"

type ConsentDetails = ConsentContext & { default_rate_per_minute?: number; default_concurrency?: number; server_bindings?: Record<string, string> }

export function OAuthConsentPage() {
  const { locale, setLocale } = useConsoleDesign()
  const zh = locale === "zh-CN"
  const [requestId] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("request") || "")
  const [context, setContext] = useState<ConsentDetails | null>(null)
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
  const limitsInitialized = useRef(false)

  function adopt(next: ConsentDetails) {
    setContext(next)
    if (!limitsInitialized.current) {
      setRate(next.default_rate_per_minute ?? (next.resource_kind === "management" ? 30 : 6000))
      setConcurrency(next.default_concurrency ?? (next.resource_kind === "management" ? 1 : 100))
      limitsInitialized.current = true
    }
    const snapshots = new Map(next.tools.map(tool => [tool.id, tool.snapshot]))
    const previousSnapshots = offeredSnapshots.current
    if (next.user && userId.current && next.user.id !== userId.current) { setSelected([]); setPolicies([]); setModes({}); setTargets([newManagementTarget()]); setTargetError("") }
    else if (next.user) setSelected(current => current.filter(id => snapshots.has(id) && snapshots.get(id) === previousSnapshots.get(id)))
    // Keep selections while the same account reauthenticates after expiry.
    if (next.user) { userId.current = next.user.id; offeredSnapshots.current = snapshots }
    setTerminal(next.completed)
  }

  function chooseCurrent(access: CurrentToolAccess, serverId?: string) {
    if (!context || busy) return
    const next = selectCurrentTools({ tools: context.tools, selected, policies, modes, access, serverId })
    setSelected(next.selected); setPolicies(next.policies); setModes(next.modes)
  }
  const summary = currentAuthorizationSummary(context?.tools || [], selected, policies)
  const expiresLocal = new Intl.DateTimeFormat(locale, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }).format(new Date(Date.now() + days * 86400000))
  async function refresh() {
    if (!requestId) { setTerminal(true); setError(zh ? "请从客户端发起 OAuth 连接后打开此页。" : "Open this page by starting an OAuth connection from the client."); setLoading(false); return }
    const current = ++version.current
    setLoading(true)
    try {
      const next = await oauthRequest<ConsentDetails>(`/oauth/context?request_id=${encodeURIComponent(requestId)}`)
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
        const next = await oauthRequest<ConsentDetails>("/oauth/login", { ...base, username, password })
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
    <header className="oauth-public-header"><strong>Lingshu Gate</strong><Radio.Group aria-label={zh ? "界面语言" : "Interface language"} value={locale} onChange={event => setLocale(event.target.value)} options={[{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]} /></header>
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
        <section className="oauth-scope-workspace">
          <div className="oauth-user"><span>{zh ? "当前用户：" : "Current user: "}<strong>{context.user.display_name || context.user.username}</strong> (@{context.user.username})</span><Button disabled={busy} onClick={() => void act("logout")}>{zh ? "切换账号" : "Switch account"}</Button></div>
          {context.resource_kind === "management" ? <>
            <p>{zh ? "选择管理工具，并填写允许创建或更新的精确服务 ID。" : "Select management tools and the exact server IDs permitted for create or update."}</p>
            <ManagementTargetsEditor rows={targets} onChange={rows => { setTargets(rows); setTargetError("") }} zh={zh} disabled={busy} />
            {targetError && <Alert type="error" title={targetError} />}
            <OAuthToolPicker tools={context.tools} selected={selected} onChange={setSelected} zh={zh} disabled={busy} />
          </> : <>
            <div className="oauth-scope-actions" role="group" aria-label={zh ? "批量选择当前工具" : "Select current tools in bulk"}>
              <Button disabled={busy || !context.tools.some(tool => tool.access === "read")} onClick={() => chooseCurrent("read")}>{zh ? "选择所有 MCP 当前只读工具" : "Select current read tools across all MCPs"}</Button>
              <Button disabled={busy || !context.tools.length} onClick={() => chooseCurrent("all")}>{zh ? "选择所有 MCP 当前全部工具" : "Select all current tools across all MCPs"}</Button>
              <Button disabled={busy || (!selected.length && !policies.length)} onClick={() => { setSelected([]); setPolicies([]); setModes({}) }}>{zh ? "清空选择" : "Clear selection"}</Button>
            </div>
            <p className="oauth-muted">{zh ? "批量选择覆盖当前全部页，仅保存现在可用的工具；之后新增的工具需再次选择。也可按 MCP 单独设置持续授权。" : "Batch selection covers every page and saves only the tools available now. Future tools require a new selection. Continuous authorization can be enabled explicitly for each MCP."}</p>
            <McpAuthorizationEditor groups={policyGroups(context.tools, policies).map(group => ({ ...group, server_binding: context.server_bindings?.[group.server_id] }))} policies={policies} modes={modes} selectionCounts={summary.byServer} onSelectCurrent={(server, access) => chooseCurrent(access, server)} canWrite={context.scopes.includes("tools.invoke")} disabled={busy} zh={zh} onMode={(server, mode) => { setModes(current => ({ ...current, [server]: mode })); setPolicies(current => [...current.filter(policy => policy.server_id !== server), ...(mode === "continuous" ? [{ server_id: server, server_binding: context.server_bindings?.[server], mode: "continuous" as const, access: "read" as const }] : [])]); if (mode !== "selected") setSelected(current => current.filter(id => !context.tools.some(tool => tool.id === id && tool.server_id === server))) }} onAccess={(server, access) => setPolicies(current => current.map(policy => policy.server_id === server ? { ...policy, access } : policy))} />
            {Object.values(modes).includes("selected") && <OAuthToolPicker tools={context.tools.filter(tool => modes[tool.server_id] === "selected")} selected={selected} onChange={setSelected} zh={zh} disabled={busy} compact />}
          </>}
        </section>
        <aside className="oauth-consent-summary"><h2>{zh ? "本次授权" : "This authorization"}</h2>
          <div className="oauth-scope-summary" aria-live="polite" aria-atomic="true"><div className="oauth-selection-counts"><strong>{summary.servers} MCP</strong><strong>{zh ? `${summary.tools} 个当前工具` : `${summary.tools} current tools`}</strong></div><div><Tag>{zh ? `只读 ${summary.read}` : `${summary.read} read`}</Tag><Tag color={summary.write ? "warning" : undefined}>{zh ? `写入 ${summary.write}` : `${summary.write} write`}</Tag></div>{summary.continuous > 0 && <p>{zh ? `${summary.continuous} 个 MCP 持续授权，包含所选访问级别的未来工具。` : `${summary.continuous} MCPs include future tools at the selected access level.`}</p>}</div>
          <Form layout="horizontal" className="oauth-inline-form">
          <Form.Item label={zh ? "授权有效期" : "Grant validity"}><Radio.Group aria-label={zh ? "授权有效期" : "Grant validity"} disabled={busy} value={days} onChange={event => setDays(Number(event.target.value))} options={[1, 7, 30].map(value => ({ value, label: zh ? `${value} 天` : `${value} days` }))} /></Form.Item>
        </Form>
          <p className="oauth-expiry-local">{zh ? "预计到期（本地）：" : "Estimated expiry (local): "}<time dateTime={new Date(Date.now() + days * 86400000).toISOString()}>{expiresLocal}</time></p>
          <QuotaSettings rate={rate} concurrency={concurrency} onRate={setRate} onConcurrency={setConcurrency} disabled={busy} zh={zh} singleColumn />
          <p className="oauth-muted">{zh ? "之后可在“我的授权”中调整或撤销，调用始终受当前角色和资源权限约束。" : "Adjust or revoke access later in My authorizations. Calls remain subject to your current role and resource permissions."}</p>
          <details><summary>{zh ? "令牌与授权规则" : "Token and grant rules"}</summary><p>{zh ? `访问令牌最长 ${context.access_seconds / 60} 分钟；刷新令牌族最长 ${context.refresh_days} 天，均不超过授权到期时间。配额在单 Core 进程中计数，重启后重置。` : `Access tokens last up to ${context.access_seconds / 60} minutes; refresh families last up to ${context.refresh_days} days. Both stop at grant expiry. Quotas are counted in one Core process and reset on restart.`}</p>{context.resource_kind === "management" && <p>{zh ? "精确目标的变更不能增加已同意的工具或 scope，已有配置计划会失效。" : "Changes to exact targets cannot add consented tools or scopes and invalidate existing configuration plans."}</p>}</details>
          <div className="oauth-actions"><Button disabled={busy} onClick={() => void act("decision", true)}>{zh ? "取消" : "Cancel"}</Button><Button type="primary" loading={busy} disabled={(!selected.length && !policies.length) || !validQuotas(rate, concurrency) || Boolean(error)} onClick={() => void act("decision")}>{zh ? "允许授权" : "Allow authorization"}</Button></div>
        </aside>
      </div>}
    </>}
  </main>
}

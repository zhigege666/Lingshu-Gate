import { useEffect, useId, useRef, useState } from "react"
import { Radio, Select } from "antd"
import type { Credential } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { InlineServiceCredential } from "@/components/inline-service-credential"
import { credentialHttpOrigin } from "@/features/credential-writes"
import { httpAuthHeaders, inferHttpAuth, type HttpAuthKind, type HttpAuthSelection } from "@/features/mcp-config/http-auth"

export type HttpAuthDraftReason = "credential" | "authentication" | null
const errors: Record<string, [string, string]> = {
  draft_changed: ["配置草稿已变化，未覆盖新的内容。已保存凭据仍然保留，请重新选择。", "The draft changed and was not overwritten. Saved credentials remain available; select again."],
  credential_required: ["请选择凭据，或新增一个。", "Select a credential or create one."],
  invalid_auth_header: ["请输入有效的自定义头名，不能使用协议保留头。", "Enter a valid custom header name, not a reserved protocol header."],
  header_conflict: ["此请求头已经存在，请在高级请求头中核对，避免覆盖。", "This header already exists. Review advanced headers before replacing it."],
  duplicate_headers: ["存在大小写重复的请求头，请先在高级请求头中修正。", "Duplicate case-insensitive headers must be corrected in advanced headers first."],
  custom_headers_required: ["现有鉴权包含多项或特殊配置，已完整保留。请先在高级请求头中明确调整。", "Existing authentication contains multiple or special headers and has been retained. Adjust it explicitly in advanced headers first."],
}

/** Presets edit only their owned header. Secrets and unfinished choices never enter the manifest. */
export function McpHttpAuthEditor({ value, serverId, endpoint, zh, disabled, credentials, loading, loadError, canCreate,
  onChange, onCreated, onReload, onPendingChange, onDraftChange, onAdvanced, onHomeTemplate }: {
  value: unknown; serverId: string; endpoint: unknown; zh: boolean; disabled: boolean
  credentials: Credential[]; loading: boolean; loadError: boolean; canCreate: boolean
  onChange: (headers: Record<string, string>) => boolean; onCreated: (credential: Credential) => void
  onReload: () => void; onPendingChange: (pending: boolean) => void
  onDraftChange: (reason: HttpAuthDraftReason) => void; onAdvanced: () => void; onHomeTemplate: () => void
}) {
  const id = useId()
  const inferred = inferHttpAuth(value)
  const valueKey = JSON.stringify(value)
  const [draft, setDraft] = useState<{ key: string | undefined; selection: HttpAuthSelection } | null>(null)
  const selection = draft && draft.key === valueKey ? draft.selection : inferred
  const [source, setSource] = useState<"existing" | "new">("existing")
  const [error, setError] = useState<string | null>(null)
  const [homeHelp, setHomeHelp] = useState(false)
  const [focusSequence, setFocusSequence] = useState(0)
  const pendingFocus = useRef(false)
  const callbacks = useRef({ onDraftChange })
  callbacks.current = { onDraftChange }
  const incomplete = Boolean(draft && draft.key === valueKey && !["none", "custom"].includes(selection.kind))
  const reason: HttpAuthDraftReason = source === "new" ? "credential" : incomplete ? "authentication" : null
  useEffect(() => { callbacks.current.onDraftChange(reason) }, [reason])
  useEffect(() => () => callbacks.current.onDraftChange(null), [])
  const origin = credentialHttpOrigin(endpoint)
  const matches = (credential: Credential) => Boolean(origin && credential.http_scopes?.some(scope => scope.server_id === serverId && scope.origin === origin))
  const selectedCredential = credentials.find(item => item.id === selection.credentialId)
  const editablePreset = ["bearer", "api_key", "basic"].includes(selection.kind)
  const controlsLocked = disabled || source === "new"

  function change(next: HttpAuthSelection) {
    if (disabled) return
    setError(null)
    if (next.kind === "custom") {
      setDraft({ key: valueKey, selection: next }); onAdvanced(); return
    }
    if (next.kind !== "none" && !next.credentialId) { setDraft({ key: valueKey, selection: next }); return }
    try {
      if (!onChange(httpAuthHeaders(value, inferred, next))) throw new Error("draft_changed")
      setDraft(null)
    } catch (err) {
      setDraft(next.kind === "none" ? null : { key: valueKey, selection: next })
      setError(err instanceof Error ? err.message : "custom_headers_required")
    }
  }

  useEffect(() => {
    // Credential completion and the parent pending lock settle separately.
    // Focus only after the existing selector is mounted and enabled.
    if (!pendingFocus.current || source !== "existing" || disabled || loading || !editablePreset) return
    const frame = requestAnimationFrame(() => {
      const input = document.getElementById(`${id}-credential`) as HTMLInputElement | null
      if (input && !input.disabled) {
        input.focus()
        pendingFocus.current = false
      }
    })
    return () => cancelAnimationFrame(frame)
  }, [source, disabled, loading, editablePreset, focusSequence, id, selection.credentialId])
  function focusCredential() {
    pendingFocus.current = true
    setFocusSequence(sequence => sequence + 1)
  }
  function chooseKind(kind: HttpAuthKind) {
    if (controlsLocked) return
    change({ kind, credentialId: "", headerName: kind === "api_key" ? "X-API-Key" : "Authorization" })
  }

  // A successful explicit credential write may finish while parent inputs are locked.
  // The parent owns target/revision protection and accepts only the reference.
  function created(credential: Credential) {
    onCreated(credential)
    try {
      if (!onChange(httpAuthHeaders(value, inferred, { ...selection, credentialId: credential.id }))) throw new Error("draft_changed")
      setDraft(null); setError(null); setSource("existing"); focusCredential()
    } catch (err) {
      setSource("existing")
      setDraft({ key: valueKey, selection: { ...selection, credentialId: credential.id } })
      setError(err instanceof Error ? err.message : "custom_headers_required")
    }
  }

  return <section className="manifest-auth" aria-label={zh ? "HTTP 鉴权" : "HTTP authentication"}>
    <div className="manifest-field">
      <Label htmlFor={`${id}-kind`}>{zh ? "鉴权方式" : "Authentication"}</Label>
      <div className="manifest-field-control">
        <Radio.Group id={`${id}-kind`} aria-label={zh ? "鉴权方式" : "Authentication"} value={selection.kind} disabled={controlsLocked}
          options={[{ value: "none", label: zh ? "无鉴权" : "None" }, { value: "bearer", label: "Bearer Token" }, { value: "api_key", label: "API Key" }, { value: "basic", label: "Basic" }, { value: "custom", label: zh ? "自定义" : "Custom" }]}
          onChange={event => chooseKind(event.target.value as HttpAuthKind)} />
        <div className="manifest-auth-template">
          <span className="text-xs text-muted-foreground">{zh ? "快捷模板" : "Quick template"}</span>
          <Button type="button" size="sm" variant="outline" disabled={controlsLocked} onClick={() => {
            setHomeHelp(true); onHomeTemplate(); chooseKind("bearer")
          }}>Home</Button>
        </div>
        {homeHelp && <div className="manifest-auth-help" role="note">
          <p>{zh ? "Home 管理中心 → 数据源与 MCP → MCP 与访问令牌 → 创建令牌。填写 Home 自己签发的 PAT，不是登录密码或 GitHub Token。" : "Home Admin → Data sources and MCP → MCP and access tokens → Create token. Use Home's own PAT, not a login password or GitHub token."}</p>
          <p>{zh ? "MCP 地址通常以 /mcp 结尾；维护书签请选择空间范围。模板只填写草稿，不发送令牌。" : "The MCP endpoint normally ends with /mcp. Select a space-scoped token for bookmarks. The template edits the draft only; it sends no token."}</p>
        </div>}
        {selection.kind === "none" && <p className="text-xs text-muted-foreground">{zh ? "不添加鉴权头。服务如要求令牌，请选择 Bearer Token 或 API Key。" : "No authentication header is added. Choose Bearer Token or API Key when required by the service."}</p>}
        {selection.kind === "custom" && <p className="text-xs text-muted-foreground">{zh ? "保留当前请求头，不猜测掩码中的鉴权格式。" : "Existing headers are retained; authentication is not guessed from masked values."} <button type="button" className="text-primary underline" disabled={disabled} onClick={onAdvanced}>{zh ? "编辑高级请求头" : "Edit advanced headers"}</button></p>}
      </div>
    </div>
    {selection.kind === "api_key" && <div className="manifest-field">
      <Label htmlFor={`${id}-header`}>{zh ? "密钥头名称" : "API key header"}</Label>
      <div className="manifest-field-control">
        <Radio.Group aria-label={zh ? "常用密钥头" : "Common API key headers"} value={["X-API-Key", "Api-Key"].includes(selection.headerName) ? selection.headerName : "custom"} disabled={controlsLocked}
          options={[{ value: "X-API-Key", label: "X-API-Key" }, { value: "Api-Key", label: "Api-Key" }, { value: "custom", label: zh ? "自定义头名" : "Custom name" }]}
          onChange={event => change({ ...selection, headerName: event.target.value === "custom" ? "" : event.target.value as string })} />
        {!["X-API-Key", "Api-Key"].includes(selection.headerName) && <Input id={`${id}-header`} aria-label={zh ? "密钥头名称" : "API key header"} value={selection.headerName} disabled={controlsLocked} autoComplete="off" placeholder="X-Service-Token" onChange={event => change({ ...selection, headerName: event.target.value })} />}
      </div>
    </div>}
    {editablePreset && <>
      <div className="manifest-field">
        <Label htmlFor={`${id}-source`}>{zh ? "服务凭据" : "Service credential"}</Label>
        <div className="manifest-field-control">
          <Radio.Group id={`${id}-source`} aria-label={zh ? "凭据来源" : "Credential source"} value={source} disabled={controlsLocked}
            options={[{ value: "existing", label: zh ? "已有凭据" : "Existing credential" }, { value: "new", label: zh ? "新增凭据" : "New credential", disabled: !canCreate }]}
            onChange={event => {
              if (event.target.value === "new") {
                try { httpAuthHeaders(value, inferred, { ...selection, credentialId: "validation-only" }) }
                catch (err) { setError(err instanceof Error ? err.message : "custom_headers_required"); return }
              }
              setSource(event.target.value as "existing" | "new"); setError(null)
            }} />
          {source === "existing" && <>
            <Select id={`${id}-credential`} className="w-full" showSearch optionFilterProp="label" aria-label={zh ? "选择服务凭据" : "Select service credential"}
              value={selection.credentialId || undefined} disabled={disabled || loading} loading={loading}
              placeholder={zh ? "搜索适用于此服务的凭据" : "Search credentials for this service"}
              options={credentials.map(item => ({ value: item.id, label: `${item.name} · ${item.id}${matches(item) ? "" : zh ? "（目标不匹配）" : " (different target)"}`, disabled: !matches(item) }))}
              onChange={credentialId => change({ ...selection, credentialId })} />
            {loadError ? <p role="alert" className="text-xs text-destructive">{zh ? "凭据列表加载失败，未将其当作空列表。" : "The credential list could not be loaded; this is not an empty list."} <button type="button" className="underline" disabled={disabled || loading} onClick={onReload}>{zh ? "重新加载" : "Reload"}</button></p>
              : !loading && !credentials.some(matches) && <p className="text-xs text-muted-foreground">{zh ? "没有匹配此服务和地址的凭据。填写完整地址后新增，或在凭据管理中核对使用范围。" : "No credential matches this service and address. Enter the full endpoint and create one, or review its usage scope in credential management."}</p>}
            {!loadError && selectedCredential && !matches(selectedCredential) && <p role="alert" className="text-xs text-warning">{zh ? "已保留原凭据引用，但其目标范围与当前地址不匹配，请重新选择。" : "The original reference is retained, but its target scope does not match this endpoint. Select a matching credential."}</p>}
            {selection.kind === "basic" && <p className="text-xs text-muted-foreground">{zh ? "已有 Basic 凭据应保存编码后的用户名与密码。新增凭据可直接填写用户名和密码，由 Gate 表单完成编码。" : "An existing Basic credential must contain the encoded username and password. Create a new credential to enter them separately; the form handles encoding."}</p>}
            {selection.credentialId && !incomplete && <p className="text-xs text-muted-foreground">{zh ? "已自动生成鉴权头，无需点击添加。秘密值不会进入配置。" : "The authentication header is set automatically; no Add step is needed. The secret stays outside the configuration."}</p>}
          </>}
        </div>
      </div>
      {source === "new" && <InlineServiceCredential serverId={serverId} endpoint={endpoint} disabled={disabled} zh={zh}
        format={selection.kind === "basic" ? "basic" : selection.kind === "bearer" ? "bearer" : "raw"}
        onCreated={created} onPendingChange={onPendingChange} onCancel={() => { setSource("existing"); focusCredential() }} />}
    </>}
    {error && <p role="alert" className="manifest-auth-error text-sm text-destructive">{errors[error]?.[zh ? 0 : 1] || (zh ? "鉴权配置未能更新，当前值已保留。" : "Authentication could not be updated; the current values are retained.")}</p>}
  </section>
}

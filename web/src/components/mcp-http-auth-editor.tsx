import { useEffect, useId, useRef, useState } from "react"
import { Radio, Select } from "antd"
import type { ConfigurationCredentialWrite, Credential } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { InlineServiceCredential } from "@/components/inline-service-credential"
import { InlineCredentialTarget } from "@/components/inline-credential-target"
import { credentialDraftTarget, currentCredentialDraft, type ConfigurationCredentialDraft } from "@/features/mcp-config/credential-draft"
import { credentialMatchesHttpTarget } from "@/features/credential-writes"
import { httpAuthHeaders, inferHttpAuth, type HttpAuthKind, type HttpAuthSelection } from "@/features/mcp-config/http-auth"

export type HttpAuthDraftReason = "credential" | "authentication" | "target" | null
const errors: Record<string, [string, string]> = {
  draft_changed: ["配置草稿已变化，请核对当前凭据与目标后再保存。", "The draft changed. Review the credential and target before saving."],
  credential_required: ["请选择凭据，或新增一个。", "Select a credential or create one."],
  invalid_auth_header: ["请输入有效的自定义头名，不能使用协议保留头。", "Enter a valid custom header name, not a reserved protocol header."],
  header_conflict: ["此请求头已经存在，请在高级请求头中核对，避免覆盖。", "This header already exists. Review advanced headers before replacing it."],
  duplicate_headers: ["存在大小写重复的请求头，请先在高级请求头中修正。", "Duplicate case-insensitive headers must be corrected in advanced headers first."],
  custom_headers_required: ["现有鉴权包含多项或特殊配置，已完整保留。请先在高级请求头中明确调整。", "Existing authentication contains multiple or special headers and has been retained. Adjust it explicitly in advanced headers first."],
}

/** Presets edit only their owned header. Secrets and unfinished choices never enter the manifest. */
export function McpHttpAuthEditor({ value, serverId, endpoint, savedService = true, serverBinding, zh, disabled, credentials, loading, loadError, canCreate,
  onChange, credentialDraft, onCredentialDraftChange, onReload, onDraftChange, onAdvanced, onHomeTemplate }: {
  value: unknown; serverId: string; endpoint: unknown; savedService?: boolean; serverBinding?: string | null; zh: boolean; disabled: boolean
  credentials: Credential[]; loading: boolean; loadError: boolean; canCreate: boolean
  onChange: (headers: Record<string, string>) => boolean
  credentialDraft: ConfigurationCredentialDraft | null; onCredentialDraftChange: (draft: ConfigurationCredentialDraft | null) => void
  onReload: () => void
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
  const stagedReady = currentCredentialDraft(credentialDraft, serverId, endpoint, value)
  const priorHeaders = useRef<Record<string, string>>({})
  const matches = (credential: Credential) => stagedReady && credentialDraft?.write.credential_id === credential.id || credentialMatchesHttpTarget(credential, serverId, endpoint, savedService, serverBinding)
  const selectedCredential = credentials.find(item => item.id === selection.credentialId)
  const needsTarget = Boolean(selectedCredential && !matches(selectedCredential) && !loadError && !loading)
  const reason: HttpAuthDraftReason = source === "new" ? stagedReady && credentialDraft?.write.kind === "create" ? null : "credential" : needsTarget ? "target" : incomplete ? "authentication" : null
  useEffect(() => { callbacks.current.onDraftChange(reason) }, [reason])
  useEffect(() => () => callbacks.current.onDraftChange(null), [])
  const editablePreset = ["bearer", "api_key", "basic"].includes(selection.kind)
  const controlsLocked = disabled || source === "new" || Boolean(credentialDraft)

  function change(next: HttpAuthSelection) {
    if (disabled) return
    setError(null)
    if (credentialDraft && (next.credentialId !== credentialDraft.write.credential_id || ["none", "custom"].includes(next.kind))) onCredentialDraftChange(null)
    if (next.kind === "custom") {
      setDraft({ key: valueKey, selection: next }); onAdvanced(); return
    }
    if (next.kind !== "none" && !next.credentialId) { setDraft({ key: valueKey, selection: next }); return }
    try {
      const headers = httpAuthHeaders(value, inferred, next)
      const credential = credentials.find(item => item.id === next.credentialId)
      if (next.kind !== "none" && credential && !matches(credential)) {
        setDraft({ key: valueKey, selection: next }); return
      }
      if (!onChange(headers)) throw new Error("draft_changed")
      setDraft(null)
    } catch (err) {
      setDraft(next.kind === "none" ? null : { key: valueKey, selection: next })
      setError(err instanceof Error ? err.message : "custom_headers_required")
    }
  }

  // An explicitly selected target may have been saved despite a lost response.
  // A metadata reload can finish attaching that selection without another grant.
  const selectedReady = Boolean(incomplete && selectedCredential && matches(selectedCredential) && !loading && !loadError)
  useEffect(() => {
    if (selectedReady && source === "existing" && !disabled) change(selection)
  }, [selectedReady, source, disabled, valueKey, selection.kind, selection.credentialId, selection.headerName])

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

  function stage(write: ConfigurationCredentialWrite | null) {
    if (!write) { onCredentialDraftChange(null); return }
    try {
      if (!credentialDraft && source !== "new") priorHeaders.current = (value || {}) as Record<string, string>
      if (!onChange(httpAuthHeaders(value, inferred, { ...selection, credentialId: write.credential_id }))) throw new Error("draft_changed")
      onCredentialDraftChange({ write, targetKey: credentialDraftTarget(serverId, endpoint) })
      setDraft(null); setError(null)
    } catch (err) {
      onCredentialDraftChange(null)
      setError(err instanceof Error ? err.message : "custom_headers_required")
    }
  }
  function discardCredential() {
    if (!onChange(priorHeaders.current)) { setError("draft_changed"); return }
    onCredentialDraftChange(null); setDraft(null); setSource("existing"); setError(null); focusCredential()
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
        {selection.kind === "custom" && <p className="text-xs text-muted-foreground">{zh ? "保留现有请求头。若要改用已有凭据，请选择上方的鉴权方式，再选择凭据；特殊鉴权可在高级请求头中调整。" : "Existing headers are retained. To use an existing credential, choose an authentication type above and select the credential. Use advanced headers for other authentication."} <button type="button" className="text-primary underline" disabled={disabled} onClick={onAdvanced}>{zh ? "编辑高级请求头" : "Edit advanced headers"}</button></p>}
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
                priorHeaders.current = (value || {}) as Record<string, string>
                try { httpAuthHeaders(value, inferred, { ...selection, credentialId: "validation-only" }) }
                catch (err) { setError(err instanceof Error ? err.message : "custom_headers_required"); return }
              }
              setSource(event.target.value as "existing" | "new"); setError(null)
            }} />
          {!canCreate && <p className="text-xs text-muted-foreground">{zh ? "当前账号不能新增凭据或扩展其用途；请由共享凭据管理员完成授权。已有引用会保留。" : "This account cannot create credentials or extend their use. A shared-credential administrator must authorize changes. Existing references are retained."}</p>}
          {source === "existing" && <>
            <Select id={`${id}-credential`} className="w-full" showSearch optionFilterProp="label" aria-label={zh ? "选择服务凭据" : "Select service credential"}
              getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!}
              value={selection.credentialId || undefined} disabled={disabled || loading} loading={loading}
              placeholder={zh ? "选择凭据，缺少的目标授权可在此补齐" : "Choose a credential; authorize this target here if needed"}
              options={credentials.map(item => ({ value: item.id, label: `${item.name} · ${item.id}${matches(item) ? "" : zh ? "（需授权此目标）" : " (authorize this target)"}`, disabled: !matches(item) && !canCreate }))}
              onChange={credentialId => change({ ...selection, credentialId })} />
            {loadError ? <p role="alert" className="text-xs text-destructive">{zh ? "凭据列表加载失败，未将其当作空列表。" : "The credential list could not be loaded; this is not an empty list."} <button type="button" className="underline" disabled={disabled || loading} onClick={onReload}>{zh ? "重新加载" : "Reload"}</button></p>
              : !loading && credentials.length === 0 && <p className="text-xs text-muted-foreground">{canCreate
                ? (zh ? "尚无可选择的共享凭据。可在上方选择新增凭据。" : "No shared credentials are available. Choose New credential above to create one.")
                : (zh ? "尚无可选择的共享凭据。请由管理员配置后重新加载。" : "No shared credentials are available. Ask an administrator to configure one, then reload.")}</p>}
            {!loadError && !loading && credentials.length > 0 && !selectedCredential && canCreate && <p className="text-xs text-muted-foreground">{zh ? "选择已有凭据后，Gate 会检查当前服务和地址；缺少授权时可在此完成。" : "Choose an existing credential. Gate checks this service and origin and lets you authorize a missing target here."}</p>}
            {needsTarget && selectedCredential && <InlineCredentialTarget credential={selectedCredential} serverId={serverId} endpoint={endpoint} zh={zh}
              disabled={disabled || loading} canManage={canCreate} onStaged={stage} onReload={onReload} />}
            {credentialDraft?.write.kind === "authorize" && <div className="text-xs text-muted-foreground">
              <p>{stagedReady ? zh ? "此用途将在保存配置时授权。" : "This use will be authorized when you save the configuration." : zh ? "目标已改变，请重新核对或取消此授权草稿。" : "The target changed. Review or cancel this grant draft."}</p>
              <div className="flex flex-wrap gap-2"><button type="button" className="underline" disabled={disabled} onClick={discardCredential}>{zh ? "取消此授权草稿" : "Cancel this grant draft"}</button>
                <button type="button" className="underline" disabled={disabled || loading} onClick={() => { onCredentialDraftChange(null); setDraft({ key: valueKey, selection }); onReload() }}>{zh ? "重新读取并复核凭据" : "Reload and review credential"}</button></div>
            </div>}
            {selection.kind === "basic" && <p className="text-xs text-muted-foreground">{zh ? "已有 Basic 凭据应保存编码后的用户名与密码。新增凭据可直接填写用户名和密码，由 Gate 表单完成编码。" : "An existing Basic credential must contain the encoded username and password. Create a new credential to enter them separately; the form handles encoding."}</p>}
            {selection.credentialId && !incomplete && !needsTarget && <p className="text-xs text-muted-foreground">{zh ? "已自动生成鉴权头，无需点击添加。秘密值不会进入配置。" : "The authentication header is set automatically; no Add step is needed. The secret stays outside the configuration."}</p>}
          </>}
        </div>
      </div>
      {source === "new" && <InlineServiceCredential serverId={serverId} endpoint={endpoint} disabled={disabled} zh={zh}
        format={selection.kind === "basic" ? "basic" : selection.kind === "bearer" ? "bearer" : "raw"}
        onDraftChange={stage} onCancel={discardCredential} />}
    </>}
    {error && <p role="alert" className="manifest-auth-error text-sm text-destructive">{errors[error]?.[zh ? 0 : 1] || (zh ? "鉴权配置未能更新，当前值已保留。" : "Authentication could not be updated; the current values are retained.")}</p>}
  </section>
}

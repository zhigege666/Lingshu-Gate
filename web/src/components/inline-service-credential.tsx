import { useEffect, useId, useRef, useState } from "react"
import { api, type Credential } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { credentialHttpOrigin, credentialWriteKey } from "@/features/credential-writes"
import { prepareHttpSecret } from "@/features/mcp-config/http-auth"

/** Only an explicit encrypted credential write receives secrets; the parent receives metadata. */
export function InlineServiceCredential({ serverId, endpoint, disabled, zh, format, onCreated, onPendingChange, onCancel }: {
  serverId: string; endpoint: unknown; disabled: boolean; zh: boolean; format: "raw" | "bearer" | "basic"
  onCreated: (credential: Credential) => void; onPendingChange: (pending: boolean) => void; onCancel: () => void
}) {
  const id = useId()
  const [name, setName] = useState(() => `${serverId || "HTTP"} ${format === "basic" ? "Basic" : format === "bearer" ? "Token" : "API Key"}`)
  const [credentialId, setCredentialId] = useState(() => `${(serverId || "http").replace(/[^A-Za-z0-9_.-]/g, "-").slice(0, 80)}-auth-${credentialWriteKey().slice(-12)}`)
  const [secret, setSecret] = useState("")
  const [username, setUsername] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [invalidField, setInvalidField] = useState<string | null>(null)
  const [idOpen, setIdOpen] = useState(false)
  const operationKey = useRef<string | null>(null)
  const saving = useRef(false)
  const mounted = useRef(true)
  const target = credentialHttpOrigin(endpoint)
  const targetKey = `${serverId}\n${target}\n${format}`
  const latestTarget = useRef(targetKey)
  latestTarget.current = targetKey
  const pendingCallback = useRef(onPendingChange)
  pendingCallback.current = onPendingChange
  useEffect(() => { operationKey.current = null }, [credentialId, name, secret, username, targetKey])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pendingCallback.current(false) } }, [])
  const validTarget = Boolean(target && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(serverId))

  function invalid(field: string, message: string) {
    setInvalidField(field); setError(message)
    if (field === "id") setIdOpen(true)
    window.setTimeout(() => document.getElementById(`${id}-${field}`)?.focus(), 0)
  }
  function discard() {
    if (pending || disabled) return
    setSecret(""); setUsername(""); setError(null); onCancel()
  }
  async function create() {
    if (disabled || saving.current || !validTarget) return
    setInvalidField(null); setError(null)
    if (!/^[A-Za-z0-9_.-]{1,128}$/.test(credentialId)) {
      invalid("id", zh ? "凭据 ID 只能包含字母、数字、点、下划线和短横线。" : "Use letters, numbers, dots, underscores or hyphens for the credential ID."); return
    }
    if (!name.trim()) { invalid("name", zh ? "请填写凭据名称。" : "Enter a credential name."); return }
    let value: string
    try { value = prepareHttpSecret(format, secret, username) }
    catch (err) {
      const userError = err instanceof Error && err.message === "invalid_basic_username"
      invalid(userError ? "username" : "value", userError
        ? (zh ? "请填写用户名，不能包含冒号或换行。" : "Enter a username without colons or line breaks.")
        : (zh ? "请填写有效秘密值，不能使用掩码或换行。Bearer Token 不能包含空格。" : "Enter a valid secret, not a mask or line breaks. Bearer tokens cannot contain spaces.")); return
    }
    saving.current = true; setPending(true); onPendingChange(true)
    const snapshotTarget = targetKey
    try {
      operationKey.current ||= credentialWriteKey()
      const credential = await api.createCredential({ credential_id: credentialId, name: name.trim(), value, description: "", idempotency_key: operationKey.current,
        http_scopes: [{ server_id: serverId, origin: target! }] })
      if (!mounted.current) return
      setSecret(""); setUsername("")
      if (latestTarget.current !== snapshotTarget) {
        setError(zh ? "凭据已保存，但配置目标已变化。请取消此表单并在已有凭据中核对，未自动绑定新目标。" : "The credential was saved, but the target changed. Cancel this form and review existing credentials; it was not attached to the new target."); return
      }
      onCreated(credential)
    } catch {
      if (mounted.current) setError(zh ? "凭据未能确认保存。输入已保留；请检查权限、标识是否重复及凭据列表，再重试。相同输入会沿用本次操作标识。" : "Credential save could not be confirmed. Inputs are retained. Check permission, duplicate IDs and the credential list before retrying. Unchanged input reuses this operation key.")
    } finally {
      saving.current = false
      if (mounted.current) setPending(false)
      onPendingChange(false)
    }
  }

  const field = (suffix: string, label: string, content: React.ReactNode) => <div className="manifest-field"><Label htmlFor={`${id}-${suffix}`}>{label}</Label><div className="manifest-field-control">{content}</div></div>
  return <section className="manifest-inline-credential" aria-label={zh ? "新增服务凭据" : "New service credential"}>
    {field("name", zh ? "凭据名称" : "Credential name", <Input id={`${id}-name`} value={name} disabled={disabled || pending} aria-invalid={invalidField === "name" || undefined} autoComplete="off" onChange={event => { setName(event.target.value); setInvalidField(null); setError(null) }} />)}
    {format === "basic" && field("username", zh ? "用户名" : "Username", <Input id={`${id}-username`} value={username} disabled={disabled || pending} autoComplete="off" aria-invalid={invalidField === "username" || undefined} onChange={event => { setUsername(event.target.value); setInvalidField(null); setError(null) }} />)}
    {field("value", format === "basic" ? (zh ? "密码" : "Password") : format === "bearer" ? "Token" : "API Key", <>
      <Input id={`${id}-value`} type="password" autoComplete="new-password" value={secret} disabled={disabled || pending} aria-invalid={invalidField === "value" || undefined} onChange={event => { setSecret(event.target.value); setInvalidField(null); setError(null) }} />
      <p className="text-xs text-muted-foreground">{format === "basic" ? (zh ? "自动生成 Basic 编码并加密保存，不需要填写 Base64。" : "Basic encoding is generated and stored encrypted; no manual Base64 is needed.") : format === "bearer" ? (zh ? "粘贴令牌即可；多粘贴一次的 Bearer 前缀会自动去除。" : "Paste the token. A single pasted Bearer prefix is removed automatically.") : (zh ? "仅通过凭据接口加密保存，配置中只保留引用。" : "Saved encrypted through the credential API; only its reference enters the configuration.")}</p>
    </>)}
    <div className="manifest-auth-aligned">
      <details open={idOpen} onToggle={event => setIdOpen(event.currentTarget.open)}>
        <summary className="text-xs cursor-pointer">{zh ? "凭据标识（自动生成，可修改）" : "Credential ID (generated, editable)"}</summary>
        <div className="mt-2"><Label htmlFor={`${id}-id`} className="sr-only">{zh ? "凭据 ID" : "Credential ID"}</Label><Input id={`${id}-id`} value={credentialId} disabled={disabled || pending} autoComplete="off" aria-invalid={invalidField === "id" || undefined} onChange={event => { setCredentialId(event.target.value); setInvalidField(null); setError(null) }} /></div>
      </details>
      <p className="text-xs text-muted-foreground break-all">{zh ? "仅用于" : "Only for"} <code>{serverId || "—"}</code> · <code>{target || "—"}</code></p>
      <p className="text-xs text-muted-foreground">{zh ? "凭据独立保存。取消配置不会删除已保存凭据。" : "Credentials are saved separately. Cancelling the configuration does not delete them."}</p>
      {!validTarget && <p className="text-xs text-warning">{zh ? "请先填写有效服务 ID 和完整 MCP 地址。" : "Enter a valid service ID and full MCP endpoint first."}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap gap-2"><Button type="button" size="sm" disabled={disabled || pending || !validTarget} onClick={() => void create()}>{pending ? (zh ? "保存凭据中…" : "Saving credential…") : (zh ? "保存凭据并使用" : "Save and use credential")}</Button><Button type="button" variant="ghost" size="sm" disabled={disabled || pending} onClick={discard}>{zh ? "取消并清除输入" : "Cancel and clear input"}</Button></div>
    </div>
  </section>
}

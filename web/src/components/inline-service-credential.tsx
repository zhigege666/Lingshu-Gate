import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import type { ConfigurationCredentialWrite } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { credentialHttpOrigin, credentialWriteKey, validHttpServiceId } from "@/features/credential-writes"
import { prepareHttpSecret } from "@/features/mcp-config/http-auth"

/** Secrets stay in this edit session until the parent submits one config save. */
export function InlineServiceCredential({ serverId, endpoint, disabled, zh, format, onDraftChange, onCancel }: {
  serverId: string; endpoint: unknown; disabled: boolean; zh: boolean; format: "raw" | "bearer" | "basic"
  onDraftChange: (write: ConfigurationCredentialWrite | null) => void; onCancel: () => void
}) {
  const id = useId()
  const [name, setName] = useState(() => `${serverId || "HTTP"} ${format === "basic" ? "Basic" : format === "bearer" ? "Token" : "API Key"}`)
  const [credentialId, setCredentialId] = useState(() => `${(serverId || "http").replace(/[^A-Za-z0-9_.-]/g, "-").slice(0, 80)}-auth-${credentialWriteKey().slice(-12)}`)
  const [secret, setSecret] = useState("")
  const [username, setUsername] = useState("")
  const [idOpen, setIdOpen] = useState(false)
  const callback = useRef(onDraftChange)
  callback.current = onDraftChange
  const origin = credentialHttpOrigin(endpoint)
  const validTarget = Boolean(origin && validHttpServiceId(serverId))
  let error = "", prepared = ""
  if (!/^[A-Za-z0-9_.-]{1,512}$/.test(credentialId)) error = zh ? "请填写有效凭据 ID。" : "Enter a valid credential ID."
  else if (!name.trim()) error = zh ? "请填写凭据名称。" : "Enter a credential name."
  else if (secret) {
    try { prepared = prepareHttpSecret(format, secret, username) }
    catch { error = zh ? "请填写有效秘密值；Basic 用户名不能含冒号，秘密不能是掩码或包含换行。" : "Enter a valid secret. Basic usernames cannot include colons; secrets cannot be masks or include line breaks." }
  }
  useEffect(() => {
    if (disabled) return
    callback.current(validTarget && prepared && !error ? { kind: "create", credential_id: credentialId, name: name.trim(), value: prepared,
      target: { server_id: serverId, origin: origin! } } : null)
  }, [credentialId, name, prepared, error, serverId, origin, endpoint, validTarget, disabled])
  const field = (suffix: string, label: string, content: ReactNode) => <div className="manifest-field"><Label htmlFor={`${id}-${suffix}`}>{label}</Label><div className="manifest-field-control">{content}</div></div>
  return <section className="manifest-inline-credential" aria-label={zh ? "新增服务凭据" : "New service credential"}>
    {field("name", zh ? "凭据名称" : "Credential name", <Input id={`${id}-name`} value={name} disabled={disabled} autoComplete="off" onChange={event => setName(event.target.value)} />)}
    {format === "basic" && field("username", zh ? "用户名" : "Username", <Input id={`${id}-username`} value={username} disabled={disabled} autoComplete="off" onChange={event => setUsername(event.target.value)} />)}
    {field("value", format === "basic" ? (zh ? "密码" : "Password") : format === "bearer" ? "Token" : "API Key", <>
      <Input id={`${id}-value`} type="password" autoComplete="new-password" value={secret} disabled={disabled} onChange={event => setSecret(event.target.value)} />
      {format === "basic" && <p className="text-xs text-muted-foreground">{zh ? "表单自动生成 Basic 编码，无需填写 Base64。" : "The form generates Basic encoding; no manual Base64 is needed."}</p>}
    </>)}
    <div className="manifest-auth-aligned">
      <details open={idOpen} onToggle={event => setIdOpen(event.currentTarget.open)}>
        <summary className="text-xs cursor-pointer">{zh ? "凭据标识（自动生成，可修改）" : "Credential ID (generated, editable)"}</summary>
        <div className="mt-2"><Label htmlFor={`${id}-id`} className="sr-only">{zh ? "凭据 ID" : "Credential ID"}</Label><Input id={`${id}-id`} value={credentialId} disabled={disabled} autoComplete="off" onChange={event => setCredentialId(event.target.value)} /></div>
      </details>
      <p className="text-xs text-muted-foreground break-all">{zh ? "保存时创建并仅授权给" : "Created on save, authorized only for"} <code>{serverId || "—"}</code> · <code>{origin || "—"}</code></p>
      <p className="text-xs text-muted-foreground">{zh ? "凭据与配置一起保存；取消编辑不会创建凭据。秘密值不进入配置。" : "The credential is saved with the configuration. Cancelling creates no credential. The secret stays outside the manifest."}</p>
      {!validTarget && <p className="text-xs text-warning">{zh ? "请先填写有效服务 ID 和完整 MCP 地址。" : "Enter a valid service ID and full MCP endpoint first."}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={() => { setSecret(""); setUsername(""); onCancel() }}>{zh ? "取消新增凭据" : "Cancel new credential"}</Button>
    </div>
  </section>
}

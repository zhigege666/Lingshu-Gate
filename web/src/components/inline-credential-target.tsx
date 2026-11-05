import type { ConfigurationCredentialWrite, Credential } from "@/api/client"
import { Button } from "@/components/ui/button"
import { credentialHttpOrigin, credentialHttpTarget } from "@/features/credential-writes"

/** A staged, revision-checked grant. This component never sends a write request. */
export function InlineCredentialTarget({ credential, serverId, endpoint, zh, disabled, canManage, onStaged, onReload }: {
  credential: Credential; serverId: string; endpoint: unknown; zh: boolean; disabled: boolean; canManage: boolean
  onStaged: (write: ConfigurationCredentialWrite) => void; onReload: () => void
}) {
  const origin = credentialHttpOrigin(endpoint)
  let targetError: string | null = null
  try {
    credentialHttpTarget(credential, serverId, endpoint)
    if (!credential.http_scopes_revision) targetError = "missing_revision"
  } catch (err) { targetError = err instanceof Error ? err.message : "invalid_credential_target" }
  return <section className="manifest-auth-help space-y-2" aria-label={zh ? "凭据使用授权" : "Credential target authorization"}>
    <p>{zh ? "此凭据需要授权给当前配置。授权将在保存配置时生效，取消编辑不会改变已有授权。" : "This credential needs authorization for the current configuration. It takes effect when the configuration is saved; cancelling leaves existing grants unchanged."}</p>
    <p className="break-all"><strong>{credential.name}</strong> · <code>{credential.id}</code></p>
    <p className="break-all">{zh ? "仅授权给" : "Authorize only for"} <code>{serverId || "—"}</code> · <code>{origin || "—"}</code></p>
    {!canManage && <p role="note">{zh ? "当前账号不能管理共享凭据，请由凭据管理员授权。" : "A shared-credential administrator must authorize this use."}</p>}
    {targetError && <p role="alert" className="text-warning">{targetError === "credential_target_limit"
      ? (zh ? "此凭据已达到 100 个 HTTP 目标上限，请调整用途或选择其他凭据。" : "This credential has reached its 100 HTTP target limit. Adjust its uses or choose another credential.")
      : targetError === "missing_revision" ? (zh ? "缺少当前授权版本，请重新读取凭据。" : "The current authorization revision is missing. Reload the credential.")
      : (zh ? "请先填写有效服务 ID 和完整 MCP 地址。" : "Enter a valid service ID and full MCP endpoint first.")}</p>}
    <div className="flex flex-wrap gap-2">
      {canManage && <Button type="button" size="sm" disabled={disabled || Boolean(targetError)} onClick={() => onStaged({ kind: "authorize", credential_id: credential.id,
        target: credentialHttpTarget(credential, serverId, endpoint), expected_revision: credential.updated_at, expected_http_scopes_revision: credential.http_scopes_revision! })}>{zh ? "保存时授权此用途" : "Authorize this use on save"}</Button>}
      {(targetError || !canManage) && <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={onReload}>{zh ? "重新读取凭据" : "Reload credential"}</Button>}
    </div>
  </section>
}

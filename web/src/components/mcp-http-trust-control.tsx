import { useEffect, useRef, useState } from "react"
import { api, type HttpTrustSaveOptions, type McpHttpTrustPolicy } from "@/api/client"
import { Button } from "@/components/ui/button"
import { privateHttpOrigin } from "@/features/mcp-config/http-trust"
import { REDACTED_ENDPOINT } from "@/features/mcp-config/model"

export type HttpTrustEditorState = { targetKey: string; ready: boolean; options: HttpTrustSaveOptions; credentialOrigin?: string | null }
export function httpTrustTargetKey(serverId: string, endpoint: unknown) { return JSON.stringify([serverId, endpoint]) }

/** Saving owns new permissions. Only an explicit revocation writes independently. */
export function McpHttpTrustControl({ serverId, endpoint, draftRevision, canManage, saved, locked, zh, denied = false, precheckSequence = 0, onBusyChange, onStateChange, onPolicyUpdated }: {
  serverId: string; endpoint: unknown; draftRevision: number; canManage: boolean; saved: boolean; locked: boolean; zh: boolean; denied?: boolean; precheckSequence?: number
  onBusyChange: (busy: boolean) => void; onStateChange: (state: HttpTrustEditorState) => void; onPolicyUpdated: () => Promise<unknown>
}) {
  const directOrigin = privateHttpOrigin(endpoint)
  const maskedTarget = saved && endpoint === REDACTED_ENDPOINT
  const targetKey = httpTrustTargetKey(serverId, endpoint)
  const [record, setRecord] = useState<{ targetKey: string; policy: McpHttpTrustPolicy } | null>(null)
  const policy = record?.targetKey === targetKey ? record.policy : null
  const origin = directOrigin || (maskedTarget ? policy?.configured_origin : null)
  const needsPolicy = Boolean(directOrigin || maskedTarget)
  const credentialOrigin = maskedTarget ? policy?.configured_endpoint_origin || (origin ? `http://${origin.ip}:${origin.port}` : null) : null
  const [restore, setRestore] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState(false)
  const [readAttempt, setReadAttempt] = useState(0)
  const latest = useRef({ targetKey, draftRevision })
  latest.current = { targetKey, draftRevision }
  const busy = useRef(false)
  const deniedCheck = denied ? precheckSequence : 0
  const revoked = policy?.revoked || policy?.state === "revoked"
  const needsReview = policy?.needs_review || policy?.state === "needs_review"
  const authorized = !denied && !revoked && !needsReview && policy?.state === "active" && Boolean(origin && policy.origins.some(item => item.ip === origin.ip && item.port === origin.port))

  useEffect(() => { setRestore(false); setConfirmRevoke(false) }, [draftRevision, targetKey])
  useEffect(() => {
    setRecord(null); setError(null); setLoading(false); setConfirmRevoke(false); setRestore(false)
    if (!canManage || !needsPolicy || !/^[A-Za-z0-9_.-]{1,128}$/.test(serverId)) return
    const controller = new AbortController()
    let active = true
    const timer = window.setTimeout(() => {
      controller.abort()
      if (active) setError(zh ? "读取连接许可超时，请重试。" : "Reading connection permission timed out. Retry.")
    }, 10_000)
    setLoading(true)
    void api.mcpHttpTrust(serverId, controller.signal).then(result => {
      if (!controller.signal.aborted && latest.current.targetKey === targetKey) setRecord({ targetKey, policy: result })
    }).catch(err => {
      if (!controller.signal.aborted && latest.current.targetKey === targetKey) setError(err instanceof Error ? err.message : (zh ? "无法读取连接许可。" : "Could not read connection permission."))
    }).finally(() => {
      if (active && latest.current.targetKey === targetKey) setLoading(false)
      window.clearTimeout(timer)
    })
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [targetKey, canManage, serverId, needsPolicy, zh, readAttempt, deniedCheck, denied])

  useEffect(() => {
    onStateChange({ targetKey, ready: !needsPolicy || !canManage || Boolean(policy && !loading && !pending && !error), credentialOrigin,
      options: !canManage && needsPolicy ? { http_trust_action: "preserve" } : origin && policy ? {
      expected_http_trust_revision: policy.revision, http_trust_action: restore ? "restore" : "auto",
    } : {} })
  }, [targetKey, canManage, needsPolicy, policy, loading, pending, error, restore, credentialOrigin, onStateChange])
  useEffect(() => () => onBusyChange(false), [onBusyChange])

  if (!origin && !(maskedTarget && canManage && !policy)) return null
  async function revoke() {
    if (!policy || !origin || !confirmRevoke || busy.current || locked || latest.current.targetKey !== targetKey) return
    const snapshot = { targetKey, draftRevision, policy }
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 10_000)
    busy.current = true; setPending(true); onBusyChange(true); setError(null)
    try {
      const result = await api.replaceMcpHttpTrust(serverId, [], policy.revision, controller.signal)
      if (latest.current.targetKey !== snapshot.targetKey || latest.current.draftRevision !== snapshot.draftRevision) return
      setRecord({ targetKey, policy: result }); setConfirmRevoke(false); setRestore(false)
      await onPolicyUpdated()
    } catch (err) {
      if (latest.current.targetKey === snapshot.targetKey) {
        setRecord(null); setConfirmRevoke(false)
        setError(err instanceof Error ? err.message : (zh ? "撤销结果未知，请读取最新状态后核对。" : "Revocation result is unknown. Reload the current state to reconcile."))
      }
    } finally { window.clearTimeout(timer); busy.current = false; setPending(false); onBusyChange(false) }
  }

  const status = loading ? (zh ? "正在读取连接许可…" : "Reading connection permission…")
    : revoked ? (zh ? "连接许可已撤销；普通保存不会恢复。" : "Connection permission was revoked. A normal save will not restore it.")
    : needsReview ? (zh ? "现有连接许可需要核对；请确认当前服务和地址后再恢复。" : "The existing permission needs review. Verify this service and address before restoring it.")
    : authorized ? (zh ? "此服务已获准连接该地址。" : "This service may connect to this address.")
    : canManage && policy ? (zh ? "保存配置时会为此服务建立该地址的精确许可。" : "Saving this configuration establishes permission for this service and exact address.")
    : canManage ? (zh ? "读取当前许可后即可核对保存方式。" : "Read the current permission to review the save behavior.")
    : (zh ? "新增私网目标需由管理员保存；现有连接许可保持不变。" : "An administrator must save a new private target. Existing connection permission is preserved.")

  return <div className="manifest-http-permission space-y-2 text-xs">
    <p>{status}</p>
    {origin && <p className="text-muted-foreground">{zh ? "HTTP 不加密，请使用受信任的内网。仅保存不会连接远端服务。" : "HTTP is unencrypted; use a trusted internal network. Saving alone does not connect to the remote service."}</p>}
    {canManage && origin && <details>
      <summary className="cursor-pointer text-muted-foreground">{zh ? "连接许可详情" : "Connection permission details"}</summary>
      <div className="mt-2 space-y-2">
        <p className="break-all">{zh ? "服务" : "Service"}: <code>{serverId}</code> · {zh ? "地址" : "Address"}: <code>{origin.ip}:{origin.port}</code>{policy && <> · {zh ? "版本" : "Revision"}: {policy.revision}</>}</p>
        {!error && <Button type="button" size="sm" variant="ghost" disabled={pending || loading || locked} onClick={() => setReadAttempt(attempt => attempt + 1)}>{zh ? "刷新连接许可" : "Refresh connection permission"}</Button>}
        {(revoked || needsReview) && !restore && <Button type="button" size="sm" variant="outline" disabled={locked || loading || !policy || Boolean(error)} onClick={() => setRestore(true)}>{zh ? "保存时恢复此地址连接许可" : "Restore this address permission on save"}</Button>}
        {restore && <div role="status" className="space-y-2"><p>{zh ? "本次保存将恢复上述服务和地址的连接许可。是否连接由保存方式决定。" : "This save will restore connection permission for the service and address above. The selected save behavior controls whether it connects."}</p><Button type="button" size="sm" variant="ghost" disabled={locked} onClick={() => setRestore(false)}>{zh ? "取消恢复" : "Cancel restoration"}</Button></div>}
        {saved && authorized && !confirmRevoke && <Button type="button" size="sm" variant="outline" disabled={locked || loading} onClick={() => setConfirmRevoke(true)}>{zh ? "撤销连接许可" : "Revoke connection permission"}</Button>}
        {confirmRevoke && <section role="group" aria-label={zh ? "确认撤销连接许可" : "Confirm connection revocation"} className="space-y-2 border-t pt-2">
          <p>{zh ? `撤销 ${serverId} 的连接许可后，后续请求将被阻止；配置草稿保留。已经发出的请求无法撤回。` : `Revoking ${serverId}'s connection permission blocks subsequent requests and keeps this configuration draft. Requests already sent cannot be recalled.`}</p>
          <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="destructive" disabled={locked || pending} onClick={() => void revoke()}>{pending ? (zh ? "撤销中…" : "Revoking…") : (zh ? "确认撤销" : "Confirm revocation")}</Button><Button type="button" size="sm" variant="ghost" disabled={pending} onClick={() => setConfirmRevoke(false)}>{zh ? "取消" : "Cancel"}</Button></div>
        </section>}
      </div>
    </details>}
    {error && <div><p role="alert" className="text-destructive">{error}</p><Button type="button" size="sm" variant="ghost" disabled={pending || loading || locked} onClick={() => setReadAttempt(attempt => attempt + 1)}>{zh ? "重新读取连接许可" : "Reload connection permission"}</Button></div>}
  </div>
}

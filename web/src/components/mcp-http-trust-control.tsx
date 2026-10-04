import { useEffect, useRef, useState } from "react"
import { api } from "@/api/client"
import { Button } from "@/components/ui/button"
import { privateHttpOrigin } from "@/features/mcp-config/http-trust"

type Policy = { revision: number; origins: Array<{ ip: string; port: number }> }
type Intent = Policy & { serverId: string; ip: string; port: number; draftRevision: number }

/** Inline confirmation keeps the draft and the Dialog's single scroll region. */
export function McpHttpTrustControl({ serverId, endpoint, draftRevision, canManage, locked, zh, approved = false, denied = false, precheckSequence = 0, onBusyChange, onApproved }: {
  serverId: string; endpoint: unknown; draftRevision: number; canManage: boolean; locked: boolean; zh: boolean; approved?: boolean; denied?: boolean; precheckSequence?: number
  onBusyChange: (busy: boolean) => void; onApproved: () => Promise<unknown>
}) {
  const origin = privateHttpOrigin(endpoint)
  const targetKey = JSON.stringify([serverId, origin?.ip, origin?.port])
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [intent, setIntent] = useState<Intent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState(false)
  const [readAttempt, setReadAttempt] = useState(0)
  const latest = useRef({ targetKey, draftRevision })
  latest.current = { targetKey, draftRevision }
  const busy = useRef(false)
  const deniedCheck = denied ? precheckSequence : 0

  useEffect(() => { setIntent(null); setError(null) }, [draftRevision])
  useEffect(() => {
    setPolicy(null); setIntent(null); setError(null); setLoading(false)
    if (!canManage || !origin || !/^[A-Za-z0-9_.-]{1,128}$/.test(serverId)) return
    const controller = new AbortController()
    let active = true
    const timer = window.setTimeout(() => { controller.abort(); if (active) setError(zh ? "读取授权状态超时，请重试。" : "Reading authorization timed out. Retry.") }, 10_000)
    setLoading(true)
    void api.mcpHttpTrust(serverId, controller.signal).then(result => {
      if (!controller.signal.aborted && latest.current.targetKey === targetKey) setPolicy(result)
    }).catch(err => { if (!controller.signal.aborted && latest.current.targetKey === targetKey) setError(err instanceof Error ? err.message : (zh ? "无法读取地址授权。" : "Could not read address authorization.")) })
      .finally(() => { if (active && latest.current.targetKey === targetKey) setLoading(false); window.clearTimeout(timer) })
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [targetKey, canManage, serverId, zh, readAttempt, deniedCheck, denied]) // Each explicit denial invalidates cached policy once; failed reads require an explicit retry.
  useEffect(() => () => onBusyChange(false), [onBusyChange])

  if (!origin) return null
  const authorized = !denied && (approved || Boolean(policy?.origins.some(item => item.ip === origin.ip && item.port === origin.port)))
  async function authorize() {
    if (!intent || busy.current || locked || latest.current.draftRevision !== intent.draftRevision || latest.current.targetKey !== targetKey) return
    const selected = intent
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 10_000)
    busy.current = true; setPending(true); onBusyChange(true); setError(null)
    try {
      // Read the revision again before the explicit write; concurrent changes fail CAS.
      const current = await api.mcpHttpTrust(selected.serverId, controller.signal)
      if (latest.current.draftRevision !== selected.draftRevision || latest.current.targetKey !== targetKey) return
      if (current.revision !== selected.revision) throw new Error(zh ? "地址授权已变化，请重新核对并确认。" : "Address authorization changed. Review and confirm again.")
      await api.updateMcpHttpTrust(selected.serverId, selected.ip, selected.port, current.revision, current.origins, controller.signal)
      if (latest.current.draftRevision !== selected.draftRevision || latest.current.targetKey !== targetKey) return
      setPolicy({ revision: current.revision + 1, origins: [...current.origins, { ip: selected.ip, port: selected.port }] }); setIntent(null)
      await onApproved()
    } catch (err) {
      if (latest.current.draftRevision === selected.draftRevision && latest.current.targetKey === targetKey) {
        setIntent(null); setPolicy(null)
        setError(err instanceof Error ? err.message : (zh ? "地址授权失败，请读取最新状态后重试。" : "Address authorization failed. Reload the current state before retrying."))
      }
    } finally { window.clearTimeout(timer); busy.current = false; setPending(false); onBusyChange(false) }
  }
  return <div className="space-y-2 text-xs">
    <p className={authorized ? "text-muted-foreground" : "text-destructive"}>{authorized ? (zh ? "此内网地址已授权。" : "This internal address is authorized.") : loading ? (zh ? "正在核对内网地址授权…" : "Checking internal address authorization…") : policy || denied ? (zh ? "此内网地址尚未授权。" : "This internal address is not authorized.") : (zh ? "内网 HTTP 地址需要管理员授权。" : "Internal HTTP addresses require administrator authorization.")}</p>
    {!canManage && !authorized && <p className="text-muted-foreground">{zh ? "请联系 Gate 管理员授权此地址。" : "Contact a Gate administrator to authorize this address."}</p>}
    {canManage && !authorized && !intent && <Button type="button" size="sm" variant="outline" disabled={locked || loading || pending || !policy} onClick={() => {
      if (policy) setIntent({ ...policy, serverId, ...origin, draftRevision })
    }}>{zh ? "授权此地址" : "Authorize this address"}</Button>}
    {intent && intent.draftRevision === draftRevision && <section className="space-y-2 border-t pt-2" role="group" aria-label={zh ? "确认内网地址授权" : "Confirm internal address authorization"}>
      <p>{zh ? "服务 ID" : "Service ID"}: <code>{intent.serverId}</code> · IP: <code>{intent.ip}</code> · {zh ? "端口" : "Port"}: <code>{intent.port}</code></p>
      <p>{zh ? "HTTP 不加密，仅用于受信任内网。此授权独立于配置保存，不会启动或连接服务。" : "HTTP is unencrypted and only suitable for a trusted internal network. This authorization is separate from saving configuration and does not start or connect the service."}</p>
      <div className="flex gap-2"><Button type="button" size="sm" disabled={pending || locked} onClick={() => void authorize()}>{pending ? (zh ? "授权中…" : "Authorizing…") : (zh ? "确认授权此地址" : "Confirm address authorization")}</Button><Button type="button" size="sm" variant="ghost" disabled={pending} onClick={() => setIntent(null)}>{zh ? "取消授权" : "Cancel authorization"}</Button></div>
    </section>}
    {error && <div><p role="alert" className="text-destructive">{error}</p>{canManage && <Button type="button" size="sm" variant="ghost" disabled={pending || loading || locked} onClick={() => setReadAttempt(attempt => attempt + 1)}>{zh ? "重新读取授权状态" : "Reload authorization state"}</Button>}</div>}
  </div>
}

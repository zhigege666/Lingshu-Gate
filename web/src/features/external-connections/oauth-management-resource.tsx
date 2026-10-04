import { useEffect, useRef, useState } from "react"
import { Alert, Button, Switch } from "antd"
import { useConfirm } from "@/components/confirm-dialog"
import { oauthError, oauthRequest, type OAuthManagementConfig } from "./oauth-api"
import type { TFunction } from "@/i18n"

export function OAuthManagementResource({ businessReady, keysReady, zh, t, onNotice, onPendingChange }: {
  businessReady: boolean; keysReady: boolean; zh: boolean; t: TFunction; onNotice: (notice: string) => void; onPendingChange: (pending: boolean) => void
}) {
  const [config, setConfig] = useState<OAuthManagementConfig | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const generation = useRef(0)
  const lock = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t)
  async function load() {
    const current = ++generation.current
    setBusy(true); setError("")
    try { const next = await oauthRequest<OAuthManagementConfig>("/v1/auth/oauth/management/config"); if (current === generation.current) setConfig(next) }
    catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { if (current === generation.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [businessReady])
  useEffect(() => { onPendingChange(busy); return () => onPendingChange(false) }, [busy, onPendingChange])
  async function change(enabled: boolean) {
    if (lock.current || !config) return
    lock.current = true; setBusy(true); setError(""); onNotice("")
    const current = generation.current
    try {
      if (!(await confirm({ title: enabled ? zh ? "启用独立管理 OAuth？" : "Enable separate management OAuth?" : zh ? "关闭管理 OAuth？" : "Disable management OAuth?",
        description: enabled ? `${config.resource} — ${zh ? "客户端须新建管理连接，请求 operations.manage，由当前管理员明确同意四个配置工具及精确目标。业务连接不会升级。此操作不验证实际客户端请求。" : "The client must create a new management connection requesting operations.manage. A current administrator explicitly approves the four configuration tools and exact targets. Business connections are unchanged. This does not verify a real client's request."}` : zh ? "仅撤销管理资源的令牌族；业务连接保持原有范围。" : "Revoke only management-resource token families; business connections keep their existing scope.",
        confirmText: enabled ? zh ? "启用管理资源" : "Enable management resource" : zh ? "关闭管理资源" : "Disable management resource", cancelText: t("cancel"), destructive: !enabled }))) return
      if (current !== generation.current) return
      const body = { enabled, expected_revision: config.revision }
      const ticket = await oauthRequest<{ csrf: string }>("/v1/auth/oauth/management/csrf?action=config", body)
      if (current !== generation.current) return
      const next = await oauthRequest<OAuthManagementConfig>("/v1/auth/oauth/management/config", body, "POST", { "X-CSRF-Token": ticket.csrf })
      if (current === generation.current) { setConfig(next); onNotice(zh ? "管理资源状态已保存；实际客户端连接尚未验证。" : "Management resource state saved; real client connectivity remains unverified.") }
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { lock.current = false; if (current === generation.current) setBusy(false) }
  }
  return <section className="oauth-admin-panel">
    <h2>{zh ? "独立管理连接" : "Separate management connection"}</h2>
    <p>{zh ? "管理地址固定为 /mcp/manage，默认关闭；普通 /mcp 继续使用现有业务授权。管理连接只允许四个外部配置工具，须逐项同意创建/更新目标。" : "Management uses /mcp/manage and is disabled by default. Ordinary /mcp keeps its business authorization. Management allows only four external configuration tools with individually approved create/update targets."}</p>
    <div className="oauth-actions"><label className="flex items-center gap-2"><span>{zh ? "启用管理 OAuth" : "Enable management OAuth"}</span><Switch aria-label={zh ? "启用管理 OAuth" : "Enable management OAuth"} checked={Boolean(config?.enabled)} disabled={busy || !config || (!config.enabled && (!businessReady || !keysReady))} onChange={value => void change(value)} /></label><Button disabled={busy} onClick={() => void load()}>{zh ? "重读管理状态" : "Reload management state"}</Button></div>
    <p className="oauth-wrap">{config?.resource || (zh ? "先保存内置 OAuth 的可信地址。" : "Save trusted built-in OAuth URLs first.")}</p>
    {!businessReady || !keysReady ? <p>{zh ? "先启用内置 OAuth，并确认活动签名密钥；未知状态不能新启用管理资源。" : "Enable built-in OAuth and confirm an active signing key first. Unknown status cannot enable management."}</p> : null}
    {error && <Alert type="error" title={error} action={<Button disabled={busy} onClick={() => void load()}>{t("retry")}</Button>} />}
    {confirmDialog}
  </section>
}

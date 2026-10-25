import { useEffect, useRef, useState } from "react"
import { Alert, Button, Switch, Tag, Tooltip } from "antd"
import { ReloadOutlined } from "@ant-design/icons"
import { useConfirm } from "@/components/confirm-dialog"
import { oauthError, oauthRequest, type OAuthManagementConfig } from "./oauth-api"
import type { TFunction } from "@/i18n"

export function OAuthManagementResource({ businessReady, keysReady, refreshVersion, zh, t, onNotice, onPendingChange }: {
  businessReady: boolean; keysReady: boolean; refreshVersion: number; zh: boolean; t: TFunction; onNotice: (notice: string) => void; onPendingChange: (pending: boolean) => void
}) {
  const [config, setConfig] = useState<OAuthManagementConfig | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const generation = useRef(0)
  const lock = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t)
  async function load() {
    const current = ++generation.current
    setBusy(true); setLoading(true); setError("")
    try { const next = await oauthRequest<OAuthManagementConfig>("/v1/auth/oauth/management/config"); if (current === generation.current) setConfig(next) }
    catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { if (current === generation.current) { setBusy(false); setLoading(false) } }
  }
  useEffect(() => { void load(); return () => { generation.current++ } }, [businessReady, refreshVersion])
  useEffect(() => { onPendingChange(busy); return () => onPendingChange(false) }, [busy, onPendingChange])
  async function change(enabled: boolean) {
    if (lock.current || !config || (enabled && (loading || Boolean(error) || !businessReady || !keysReady))) return
    lock.current = true; setBusy(true); setError(""); onNotice("")
    const current = generation.current
    try {
      if (!(await confirm({ title: enabled ? zh ? "启用独立管理 OAuth？" : "Enable separate management OAuth?" : zh ? "关闭管理 OAuth？" : "Disable management OAuth?",
        description: enabled ? `${config.resource} — ${zh ? "客户端须新建管理连接，请求 operations.manage，由当前管理员明确同意所需管理工具及精确目标；管理凭据还需 credentials.manage.system。业务连接不会升级。此操作不验证实际客户端请求。" : "The client must create a new management connection requesting operations.manage. A current administrator explicitly approves the required management tools and exact targets; credential management additionally requires credentials.manage.system. Business connections are unchanged. This does not verify a real client's request."}` : zh ? "仅撤销管理资源的令牌族；业务连接保持原有范围。" : "Revoke only management-resource token families; business connections keep their existing scope.",
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
  const status = loading ? zh ? "读取中" : "Loading" : error || !config ? zh ? "状态读取失败" : "Status unavailable"
    : !config.enabled ? zh ? "已关闭" : "Disabled" : config.active ? zh ? "已生效" : "Active" : zh ? "已配置，未生效" : "Configured, inactive"
  return <section className="oauth-admin-panel oauth-management-panel" aria-label={zh ? "独立管理连接" : "Separate management connection"}>
    <div className="oauth-panel-heading">
      <h2>{zh ? "独立管理连接" : "Separate management connection"}</h2>
      <div className="oauth-management-header-actions">
        <Tag className="oauth-management-status" role="status" color={error || (!loading && config?.enabled && !config.active) ? "orange" : !loading && config?.active && !error ? "green" : undefined}>{status}</Tag>
        <Tooltip title={zh ? "重读管理状态" : "Reload management state"} trigger={["hover", "focus"]}><Button size="small" type="text" icon={<ReloadOutlined />} aria-label={zh ? "重读管理状态" : "Reload management state"} disabled={busy} onClick={() => void load()} /></Tooltip>
      </div>
    </div>
    <div className="oauth-management-toggle">
      <label><span>{zh ? "启用管理 OAuth" : "Enable management OAuth"}</span><Switch aria-label={zh ? "启用管理 OAuth" : "Enable management OAuth"} aria-describedby="oauth-management-apply-help" checked={Boolean(config?.enabled)} disabled={busy || !config || (!config.enabled && (Boolean(error) || !businessReady || !keysReady))} onChange={value => void change(value)} /></label>
      <span id="oauth-management-apply-help" className="oauth-muted">{zh ? "确认后立即生效" : "Applies immediately after confirmation"}</span>
    </div>
    {error && <Alert type="error" showIcon title={error} description={config ? zh ? `上次读取：${config.enabled ? config.active ? "已生效" : "已配置，未生效" : "已关闭"}。` : `Last read: ${config.enabled ? config.active ? "active" : "configured, inactive" : "disabled"}.` : undefined} />}
    <p className="oauth-management-boundary">{zh ? "管理外部 HTTP MCP 和共享凭据，分别授予工具、范围与精确目标。" : "Manage external HTTP MCPs and shared credentials with explicitly selected tools, scopes and exact targets."}</p>
    {(!businessReady || !keysReady) && <p className="oauth-management-prerequisite">{zh ? "需先启用内置 OAuth，并确认活动签名密钥。" : "Enable built-in OAuth and confirm an active signing key first."}</p>}
    {config?.resource && <div className="oauth-management-footer"><p className="oauth-wrap">{config.resource}</p></div>}
    {confirmDialog}
  </section>
}

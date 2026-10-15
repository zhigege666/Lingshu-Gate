import { useCallback, useEffect, useRef, useState } from "react"
import { Button, Radio } from "antd"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import type { Locale, TFunction } from "@/i18n"
import type { ToolDiscoveryMode } from "@/features/mcp-client-settings"
import { OAuthRequestError, oauthRequest } from "./oauth-api"
import type { AuthorizationRow } from "./my-authorizations-model"

type Setting = { tool_discovery_mode: ToolDiscoveryMode; discovery_revision: number; csrf: string }

export function discoveryLabel(mode: ToolDiscoveryMode, zh: boolean) {
  return mode === "direct" ? zh ? "完整工具列表" : "Full tool list" : zh ? "按需发现" : "On demand"
}

export function DiscoveryModeDialog({ target, locale, t, onClose, onSaved }: {
  target: AuthorizationRow | null; locale: Locale; t: TFunction; onClose: () => void; onSaved: () => void
}) {
  const zh = locale === "zh-CN"
  const [saved, setSaved] = useState<Setting | null>(null), [mode, setMode] = useState<ToolDiscoveryMode>("on_demand")
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [refreshRequired, setRefreshRequired] = useState(false)
  const generation = useRef(0)
  const { confirm, confirmDialog } = useConfirm(t)
  const path = target ? `/v1/auth/authorizations/${target.kind}/${encodeURIComponent(target.id)}/discovery` : ""
  const dirty = Boolean(saved && saved.tool_discovery_mode !== mode)
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose })
  const load = useCallback(async (preserve = false) => {
    if (!path) return
    const current = ++generation.current
    setBusy(true); setError(null)
    try {
      const next = await oauthRequest<Setting>(path)
      if (generation.current !== current) return
      setSaved(next); if (!preserve) setMode(next.tool_discovery_mode)
      setRefreshRequired(false)
    } catch {
      if (generation.current === current) { setError(zh ? "读取失败，请重试。" : "Unable to load. Retry."); setRefreshRequired(true) }
    } finally { if (generation.current === current) setBusy(false) }
  }, [path, zh])
  useEffect(() => {
    setSaved(null); setMode("on_demand"); setRefreshRequired(false); setError(null)
    void load()
    return () => { generation.current++ }
  }, [load])

  async function save() {
    if (!saved || !target || busy || refreshRequired) return
    const current = generation.current
    const body = { tool_discovery_mode: mode, expected_revision: saved.discovery_revision, csrf: saved.csrf }
    setBusy(true); setError(null)
    let writing = false
    try {
      const preview = await oauthRequest<{ csrf: string; previous: ToolDiscoveryMode; tool_discovery_mode: ToolDiscoveryMode }>(`${path}-preview`, body)
      if (generation.current !== current) return
      if (!(await confirm({ title: zh ? "确认调整工具发现？" : "Confirm tool discovery change?", description: `${target.name} · ${discoveryLabel(preview.previous, zh)} → ${discoveryLabel(preview.tool_discovery_mode, zh)}` }))) {
        await load(true); return
      }
      if (generation.current !== current) return
      writing = true
      await oauthRequest(path, { ...body, csrf: preview.csrf })
      if (generation.current !== current) return
      onSaved(); onClose()
    } catch (cause) {
      if (generation.current !== current) return
      const unknown = writing && (!(cause instanceof OAuthRequestError) || cause.status === 0)
      setError(unknown ? zh ? "保存结果未知，请刷新核对后再操作。" : "Save outcome unknown. Refresh before another write."
        : zh ? "设置或会话已变化，请刷新核对后重试。" : "Settings or session changed. Refresh before retrying.")
      setRefreshRequired(true)
    } finally { if (generation.current === current) setBusy(false) }
  }

  return <><FormDialog open={Boolean(target)} title={zh ? "工具发现" : "Tool discovery"} closeLabel={t("close")} onClose={() => void close()} pending={busy} dirty={dirty} error={error}
    footer={<><Button disabled={busy} onClick={() => void close()}>{t("cancel")}</Button><Button disabled={busy} onClick={() => void load(true)}>{zh ? "刷新" : "Refresh"}</Button><Button type="primary" disabled={busy || !dirty || refreshRequired} onClick={() => void save()}>{t("save")}</Button></>}>
    <p className="mb-4 text-sm text-muted-foreground">{target?.name}</p>
    <div className="authorization-field"><label id="authorization-discovery-label">{zh ? "工具发现" : "Tool discovery"}</label>
      <Radio.Group aria-labelledby="authorization-discovery-label" value={saved ? mode : undefined} disabled={busy || !saved || refreshRequired} onChange={event => setMode(event.target.value)}>
        <Radio value="on_demand">{discoveryLabel("on_demand", zh)}</Radio><Radio value="direct">{discoveryLabel("direct", zh)}</Radio>
      </Radio.Group>
    </div>
  </FormDialog>{confirmDialog}</>
}

import { useEffect, useRef, useState } from "react"
import { Radio } from "antd"
import { api, type ConfigSaveOptions, type McpServer } from "@/api/client"
import { McpConfigEditor } from "@/components/mcp-config-editor"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { configurationResultError, readConfigurationRuntime } from "./configuration-result"
import type { Locale, TFunction } from "@/i18n"

/** Service-owned edit session. Snapshot is never replaced by background refresh. */
export function ServiceConfigDrawer({ server, manifest, configDigest, canManageHttpTrust = false, canManageCredentials = false, locale, t, onClose, onSaved, returnFocusFallback }: {
  server: McpServer; manifest: Record<string, unknown>; locale: Locale; t: TFunction
  configDigest?: string; canManageHttpTrust?: boolean; canManageCredentials?: boolean
  onClose: () => void; onSaved: () => Promise<void>
  returnFocusFallback?: () => void
}) {
  const zh = locale === "zh-CN"
  const [initial] = useState(() => JSON.stringify(manifest, null, 2))
  const [value, setValue] = useState(initial)
  const [pending, setPending] = useState(false)
  const [entryDirty, setEntryDirty] = useState(false)
  const [apply, setApply] = useState(() => manifest.enabled !== false)
  let enabled = false
  try { enabled = JSON.parse(value).enabled !== false } catch { /* Validation owns invalid JSON. */ }
  const shouldApply = apply && enabled
  const [footer, setFooter] = useState<HTMLDivElement | null>(null)
  const [returnFocus] = useState(() => document.activeElement instanceof HTMLElement ? document.activeElement : null)
  const saveReturnFocus = useRef<HTMLElement | null>(null)
  useEffect(() => {
    // Footer controls are portaled; remember native focus before precheck disables them.
    const rememberFocus = (event: FocusEvent) => { if (event.target instanceof HTMLElement) saveReturnFocus.current = event.target }
    footer?.addEventListener("focusin", rememberFocus)
    return () => footer?.removeEventListener("focusin", rememberFocus)
  }, [footer])
  const saving = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t, true)
  const dirty = entryDirty || value !== initial
  const close = useDraftCloseGuard({ dirty, pending, locale, confirm, onClose })
  const action = shouldApply ? server.launch_type === "external"
    ? (zh ? "保存并重新连接" : "Save and reconnect")
    : server.status === "running" ? (zh ? "保存并重启" : "Save and restart") : (zh ? "保存并启动" : "Save and start")
    : (zh ? "仅保存（未生效）" : "Save only (not applied)")
  async function save(text = value, httpTrust: ConfigSaveOptions = {}) {
    if (saving.current) return
    saving.current = true
    try {
      const current = shouldApply ? await readConfigurationRuntime(server.id, api.servers, zh) : undefined
      const interruptAction = current?.launch_type === "external" ? (zh ? "保存并重新连接" : "Save and reconnect") : (zh ? "保存并重启" : "Save and restart")
      if (current?.status === "running" && !(await confirm({
        title: `${interruptAction} · ${server.id}`,
        description: zh ? "现有连接会中断，运行中的调用可能失败。配置保存后会自动重连并同步工具。" : "Existing connections will be interrupted and active calls may fail. The service will reconnect and synchronize tools after saving.",
        confirmText: interruptAction,
        returnFocus: saveReturnFocus.current,
      }))) return
      const parsed = JSON.parse(text) as Record<string, unknown>
      const credentials: Record<string, string> = {}
      if (parsed.user_credential_values !== undefined) {
        const raw = parsed.user_credential_values
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("user_credential_values must be an object")
        for (const [key, secret] of Object.entries(raw)) {
          if (typeof secret !== "string") throw new Error(`user_credential_values.${key} must be a string`)
          credentials[key] = secret
        }
      }
      delete parsed.user_credential_values
      if (!httpTrust.credential_write) setValue(JSON.stringify(parsed, null, 2))
      const response = await api.updateConfig(server.id, parsed, shouldApply, shouldApply, credentials, configDigest, httpTrust)
      const error = configurationResultError(response, server.id, shouldApply, zh)
      if (error) throw new Error(error)
      await onSaved()
      onClose()
    } finally { saving.current = false }
  }
  return <>
    <FormDialog className="service-config-dialog" bodyClassName="service-config-dialog-body" open
      title={`${zh ? "修改配置" : "Edit configuration"} · ${server.id}`} closeLabel={t("close")}
      onClose={() => void close()} dirty={dirty} pending={pending}
      onCloseAutoFocus={event => {
        event.preventDefault()
        if (returnFocus?.isConnected && !returnFocus.matches("body, html, :disabled") && returnFocus.getClientRects().length > 0) returnFocus.focus()
        else returnFocusFallback?.()
      }}
      footer={<div ref={setFooter} className="w-full" />}>
      <div className="service-config-save-intent">
        <Radio.Group aria-label={zh ? "保存方式" : "Save behavior"} value={shouldApply} onChange={event => setApply(event.target.value as boolean)} disabled={pending} options={[
          { value: true, disabled: !enabled, label: server.status === "running" ? (zh ? "保存后重启 / 重连" : "Restart / reconnect after saving") : (zh ? "保存后启动" : "Start after saving") },
          { value: false, label: zh ? "仅保存（未生效）" : "Save only (not applied)" },
        ]} />
        <p className="text-xs text-muted-foreground">{shouldApply ? (zh ? "保存时自动校验，连接后自动同步工具。" : "Configuration is validated on save; tools synchronize after connection.") : (zh ? "配置将保存为草稿，当前实例保持不变。" : "Save a configuration draft without changing the running instance.")}</p>
      </div>
      <McpConfigEditor locale={locale} selectedConfigId={server.id} savedConfigDigest={configDigest} value={value} onChange={setValue} onSave={save}
        canManageHttpTrust={canManageHttpTrust}
        canManageCredentials={canManageCredentials}
        onClose={() => void close()} onPendingChange={setPending} onDraftDirtyChange={setEntryDirty}
        footerContainer={footer} busy={false} saveLabel={action} />
    </FormDialog>
    {confirmDialog}
  </>
}

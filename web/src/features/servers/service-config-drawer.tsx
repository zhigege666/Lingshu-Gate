import { useContext, useEffect, useRef, useState } from "react"
import { Alert, Drawer, Radio } from "antd"
import { api, type McpServer } from "@/api/client"
import { McpConfigEditor } from "@/components/mcp-config-editor"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { configurationResultError } from "./configuration-result"
import type { Locale, TFunction } from "@/i18n"

/** Service-owned edit session. Snapshot is never replaced by background refresh. */
export function ServiceConfigDrawer({ server, manifest, locale, t, onClose, onSaved }: {
  server: McpServer; manifest: Record<string, unknown>; locale: Locale; t: TFunction
  onClose: () => void; onSaved: () => Promise<void>
}) {
  const zh = locale === "zh-CN"
  const [initial] = useState(() => JSON.stringify(manifest, null, 2))
  const [value, setValue] = useState(initial)
  const [pending, setPending] = useState(false)
  const [entryDirty, setEntryDirty] = useState(false)
  const [apply, setApply] = useState(true)
  const [footer, setFooter] = useState<HTMLDivElement | null>(null)
  const saving = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t)
  const register = useContext(EditorNavigationContext)
  const dirty = entryDirty || value !== initial
  useEffect(() => register?.({ dirty, pending }), [register, dirty, pending])
  const close = useDraftCloseGuard({ dirty, pending, locale, confirm, onClose })
  const action = apply ? server.launch_type === "external"
    ? (zh ? "保存并重新连接" : "Save and reconnect")
    : server.status === "running" ? (zh ? "保存并重启" : "Save and restart") : (zh ? "保存并启动" : "Save and start")
    : (zh ? "仅保存（未生效）" : "Save only (not applied)")
  async function save(text = value) {
    if (saving.current) return
    saving.current = true
    try {
      if (!(await confirm({
        title: `${action} · ${server.id}`,
        description: !apply ? (zh ? "覆盖已保存配置；运行实例暂不改变。请核对凭据引用与权限声明。" : "Overwrite the saved configuration without changing the runtime. Review credential references and access declarations.") : zh ? "将替换此服务的运行配置并建立新的运行实例；现有连接会中断。静态预检查不是连接测试。" : "Replace this service's runtime configuration and start a new instance. Existing connections will be interrupted. Static validation is not a connection test.",
        confirmText: action,
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
      setValue(JSON.stringify(parsed, null, 2))
      const response = await api.updateConfig(server.id, parsed, apply, apply, credentials)
      const error = configurationResultError(response, server.id, apply, zh)
      if (error) throw new Error(error)
      await onSaved()
      onClose()
    } finally { saving.current = false }
  }
  return <>
    <Drawer className="service-config-drawer" zIndex={40} open title={`${zh ? "修改配置" : "Edit configuration"} · ${server.id}`} size={760}
      onClose={() => void close()} maskClosable={!pending} keyboard={!pending} closable={!pending}
      footer={<div ref={setFooter} />}>
      <Alert type="info" showIcon title={zh ? "保存与运行状态" : "Save and runtime state"} description={zh ? "仅保存不会改变当前运行实例。保存并启动/重启会应用新配置；失败时请检查服务状态，勿盲目重试。" : "Saving alone does not change the current runtime. Saving and starting/restarting applies the configuration. If activation fails, inspect the service before retrying."} />
      <Radio.Group value={apply} onChange={event => setApply(event.target.value as boolean)} disabled={pending} style={{ marginBlock: 16 }} options={[
        { value: true, label: zh ? "保存并应用启动" : "Save, apply and start" },
        { value: false, label: zh ? "仅保存（未生效）" : "Save only (not applied)" },
      ]} />
      <McpConfigEditor locale={locale} selectedConfigId={server.id} value={value} onChange={setValue} onSave={save}
        onClose={() => void close()} onPendingChange={setPending} onDraftDirtyChange={setEntryDirty}
        footerContainer={footer} busy={false} saveLabel={action} />
    </Drawer>
    {confirmDialog}
  </>
}

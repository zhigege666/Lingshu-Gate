import { useState } from "react"
import { FormDialog } from "@/components/form-dialog"
import { McpConfigEditor } from "@/components/mcp-config-editor"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { prepareUploadManifest } from "@/components/uploads/upload-state"
import type { Locale, TFunction } from "@/i18n"

export function DeliveryConfigEditor({ manifest, locale, t, onClose, onSave }: { manifest: Record<string, unknown>; locale: Locale; t: TFunction; onClose: () => void; onSave: (manifest: Record<string, unknown>) => void | Promise<void> }) {
  const [initial] = useState(() => JSON.stringify(manifest, null, 2))
  const [value, setValue] = useState(initial)
  const [pending, setPending] = useState(false)
  const [entryDirty, setEntryDirty] = useState(false)
  const [footer, setFooter] = useState<HTMLDivElement | null>(null)
  const [returnFocus] = useState(() => document.activeElement instanceof HTMLElement ? document.activeElement : null)
  const { confirm, confirmDialog } = useConfirm(t, true)
  const dirty = entryDirty || initial !== value
  const close = useDraftCloseGuard({ dirty, pending, locale, confirm, onClose })
  const zh = locale === "zh-CN"
  return <>
    <FormDialog open onClose={() => void close()} title={zh ? "交付运行配置" : "Delivery runtime configuration"} closeLabel={t("close")} dirty={dirty} pending={pending} className="max-w-5xl"
      onCloseAutoFocus={event => { if (returnFocus?.isConnected && !returnFocus.matches(":disabled")) { event.preventDefault(); returnFocus.focus() } }}
      description={zh ? "此配置将在部署预览与确认后，和构建产物一起应用。个人凭据请在个人绑定中设置。" : "This configuration is applied together with the build artifact after deployment preview and confirmation. Set personal credentials in personal bindings."}
      footer={<div className="w-full" ref={setFooter} />}>
      <McpConfigEditor locale={locale} selectedConfigId="" value={value} onChange={setValue} busy={false} loadCredentials={false} backendPrecheck={false}
        saveLabel={zh ? "保存交付草稿" : "Save delivery draft"} onPendingChange={setPending} onDraftDirtyChange={setEntryDirty} footerContainer={footer} onClose={() => void close()}
        onSave={async text => { const prepared = prepareUploadManifest(text || value); setValue(JSON.stringify(prepared.manifest, null, 2)); if (Object.keys(prepared.credentialValues).length) throw new Error(zh ? "请在个人凭据中设置一次性秘密，不在交付草稿中保存。" : "Set secrets in personal credentials, not in the delivery draft."); await onSave(prepared.manifest); onClose() }} />
    </FormDialog>
    {confirmDialog}
  </>
}

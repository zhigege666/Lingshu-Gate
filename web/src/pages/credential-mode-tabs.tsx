import { useContext, useEffect, useState, type ReactNode } from "react"
import { Tabs } from "antd"
import { EditorNavigationContext, useEditorNavigationGuards } from "@/components/editor-navigation-guard"
import { useConfirm } from "@/components/confirm-dialog"
import type { BusinessCredentialScope } from "@/api/business-credentials"
import type { Locale, TFunction } from "@/i18n"
import { BusinessCredentialsPanel } from "./business-credentials-panel"

/** Only switches credential domains; each mounted page retains its own loader and authorization. */
export function CredentialModeTabs({ locale, t, scope, serviceCredentials }: {
  locale: Locale; t: TFunction; scope: BusinessCredentialScope; serviceCredentials: ReactNode
}) {
  const [mode, setMode] = useState("service")
  const guards = useEditorNavigationGuards()
  const parent = useContext(EditorNavigationContext)
  const { confirm, confirmDialog } = useConfirm(t)
  const zh = locale === "zh-CN"
  useEffect(() => parent?.({ dirty: guards.anyDirty, pending: guards.anyPending }), [parent, guards.anyDirty, guards.anyPending])
  return <EditorNavigationContext.Provider value={guards.providerValue}>
    <Tabs className="credential-mode-tabs" activeKey={mode} destroyOnHidden onChange={async next => {
      if (guards.anyPending || next === mode) return
      if (guards.anyDirty && !(await confirm({ title: zh ? "放弃修改并切换凭据类型？" : "Discard edits and switch credential type?",
        description: zh ? "当前表单中尚未保存的输入将被清除。" : "Unsaved input in the current form will be cleared.",
        confirmText: zh ? "放弃修改" : "Discard edits", cancelText: t("cancel"), destructive: true }))) return
      setMode(next)
    }} items={[
      { key: "service", label: zh ? "服务凭据" : "Service credentials", disabled: guards.anyPending && mode !== "service", children: serviceCredentials },
      { key: "business", label: zh ? "业务账号" : "Business accounts", disabled: guards.anyPending && mode !== "business", children: <BusinessCredentialsPanel locale={locale} t={t} scope={scope} /> },
    ]} />{confirmDialog}
  </EditorNavigationContext.Provider>
}

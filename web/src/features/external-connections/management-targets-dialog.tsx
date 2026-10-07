import { useEffect, useRef, useState, type ComponentProps } from "react"
import { Alert, Button } from "antd"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { ManagementTargetsEditor } from "./management-targets-editor"
import { managementTargetRows, managementTargets, type ManagementTargetRow } from "./management-targets-model"
import { oauthError, oauthRequest, type ManagementTargetOptions, type ManagementTargetPreview, type OAuthGrant } from "./oauth-api"
import type { Locale, TFunction } from "@/i18n"

export function ManagementTargetsDialog({ grant, locale, t, onClose, onSaved, onCloseAutoFocus }: {
  grant: OAuthGrant | null; locale: Locale; t: TFunction; onClose: () => void; onSaved: (grant: OAuthGrant) => void; onCloseAutoFocus?: ComponentProps<typeof FormDialog>["onCloseAutoFocus"]
}) {
  const zh = locale === "zh-CN"
  const [options, setOptions] = useState<ManagementTargetOptions | null>(null)
  const [rows, setRows] = useState<ManagementTargetRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const baseline = useRef("[]")
  const generation = useRef(0)
  const lock = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t, true)
  const dirty = JSON.stringify(rows) !== baseline.current
  function closeEditor() { generation.current++; onClose() }
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: closeEditor })
  async function load() {
    if (!grant || lock.current) return
    const current = ++generation.current
    setBusy(true); setError(""); setOptions(null)
    try {
      const next = await oauthRequest<ManagementTargetOptions>(`/v1/auth/oauth/grants/${grant.id}/management-targets`)
      if (current === generation.current) { const saved = managementTargetRows(next.targets); baseline.current = JSON.stringify(saved); setRows(saved); setOptions(next) }
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { if (current === generation.current) setBusy(false) }
  }
  useEffect(() => { setRows([]); baseline.current = "[]"; void load(); return () => { generation.current++ } }, [grant?.id])
  async function reload() {
    if (dirty && !(await confirm({ title: zh ? "重新读取已保存目标？" : "Reload saved targets?", description: zh ? "当前未保存修改将放弃。" : "Discard the current unsaved edits.", confirmText: zh ? "重新读取" : "Reload", cancelText: t("cancel") }))) return
    await load()
  }
  async function save() {
    if (!grant || !options || lock.current) return
    const current = generation.current
    lock.current = true; setBusy(true); setError("")
    try {
      const body = { expected_revision: options.expected_revision, expected_target_revision: options.expected_target_revision, targets: managementTargets(rows, true) }
      const path = `/v1/auth/oauth/grants/${grant.id}/management-targets`
      const preview = await oauthRequest<ManagementTargetPreview>(path + "/preview", { ...body, csrf: options.csrf })
      if (current !== generation.current) return
      if (!(await confirm({ title: zh ? "确认管理目标变更？" : "Confirm management target changes?", description: zh ? "仅改变此管理授权的精确创建/更新目标。旧计划失效，JWT 和令牌族的 scope、四个工具及业务授权均不扩展。" : "Change only this management grant's exact create/update targets. Existing plans become stale. JWT/family scopes, tool rights and business grants remain unchanged.",
        details: <><h3>{zh ? "当前目标" : "Current targets"}</h3><ManagementTargetsEditor rows={managementTargetRows(preview.previous_targets)} onChange={() => undefined} zh={zh} readOnly /><h3>{zh ? "确认后目标" : "Targets after confirmation"}</h3><ManagementTargetsEditor rows={managementTargetRows(preview.targets)} onChange={() => undefined} zh={zh} readOnly /></>, confirmText: zh ? "确认并更新" : "Confirm update", cancelText: t("cancel") }))) return
      if (current !== generation.current) return
      const next = await oauthRequest<OAuthGrant>(path, { ...body, confirmation: preview.confirmation })
      if (current === generation.current) { baseline.current = JSON.stringify(rows); onSaved(next); closeEditor() }
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
    finally { lock.current = false; if (current === generation.current) setBusy(false) }
  }
  return <><FormDialog open={Boolean(grant)} className="oauth-grant-scope-dialog" bodyClassName="oauth-management-target-body" title={zh ? "调整管理目标" : "Adjust management targets"} closeLabel={t("close")} onClose={() => void close()} onCloseAutoFocus={onCloseAutoFocus} dirty={dirty} pending={busy} error={error}
    footer={<><Button disabled={busy} onClick={() => void reload()}>{zh ? "重新读取已保存目标" : "Reload saved targets"}</Button><Button disabled={busy} onClick={() => void close()}>{t("close")}</Button><Button type="primary" disabled={busy || !options || !dirty} onClick={() => void save()}>{zh ? "核对目标变更" : "Review target changes"}</Button></>}>
    {grant && <p className="oauth-wrap">{grant.client_name} · {grant.resource}</p>}
    {busy && !options && <p role="status">{zh ? "正在读取已授权目标…" : "Loading authorized targets…"}</p>}
    {options && <><Alert type="info" title={zh ? "只改变精确目标；权限上限保持不变" : "Exact targets only; scope ceilings stay unchanged"} description={options.scopes.join(" · ")} /><ManagementTargetsEditor rows={rows} onChange={setRows} zh={zh} disabled={busy} /></>}
  </FormDialog>{confirmDialog}</>
}

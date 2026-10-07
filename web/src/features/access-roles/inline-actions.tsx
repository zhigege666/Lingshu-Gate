import { Button } from "@/components/ui/button"
import type { Locale, TFunction } from "@/i18n"
import { canDeleteAccessItem, type AccessItem } from "./model"
import { accessRolesCopy } from "./presentation"

export function AccessInlineActions({ item, locale, t, busy, onView, onEdit, onCopy, onToggle, onDelete }: {
  item: AccessItem
  locale: Locale
  t: TFunction
  busy: boolean
  onView: () => void
  onEdit: () => void
  onCopy: () => void
  onToggle: () => void
  onDelete: () => void
}) {
  const c = accessRolesCopy[locale]
  const deleteHint = canDeleteAccessItem(item) ? undefined : "member_count" in item ? c.assignedRole : c.referencedType
  return <div className="access-inline-actions" role="group" aria-label={`${item.name} ${t("actions")}`}>
    <Button variant="ghost" size="sm" aria-label={`${c.view} ${item.name}`} onClick={onView}>{c.view}</Button>
    <Button variant="ghost" size="sm" aria-label={`${t("edit")} ${item.name}`} disabled={busy} onClick={onEdit}>{t("edit")}</Button>
    <Button variant="ghost" size="sm" aria-label={`${c.copy} ${item.name}`} disabled={busy} onClick={onCopy}>{c.copy}</Button>
    {!item.is_system && <>
      <Button variant="ghost" size="sm" aria-label={`${item.enabled ? c.disable : c.enable} ${item.name}`} disabled={busy} onClick={onToggle}>{item.enabled ? c.disable : c.enable}</Button>
      <span title={deleteHint}>
        <Button variant="ghost" size="sm" className="text-destructive" aria-label={`${t("delete")} ${item.name}`} title={deleteHint} disabled={busy || !canDeleteAccessItem(item)} onClick={onDelete}>{t("delete")}</Button>
      </span>
    </>}
  </div>
}

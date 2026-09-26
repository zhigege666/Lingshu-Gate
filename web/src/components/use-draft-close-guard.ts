import { useRef } from "react"
import type { useConfirm } from "@/components/confirm-dialog"
import type { Locale } from "@/i18n"

export const draftCloseCopy = {
  "zh-CN": { title: "放弃尚未保存的修改？", description: "关闭后将清除本次尚未保存的输入。", discard: "放弃修改", keep: "继续编辑" },
  "en-US": { title: "Discard unsaved changes?", description: "Closing clears the unsaved input from this attempt.", discard: "Discard changes", keep: "Continue editing" },
} satisfies Record<Locale, Record<string, string>>

/** Only handles the close decision; each domain clears its own draft and secrets. */
export function useDraftCloseGuard({ dirty, pending, locale, confirm, onClose }: {
  dirty: boolean
  pending: boolean
  locale: Locale
  confirm: ReturnType<typeof useConfirm>["confirm"]
  onClose: () => void
}) {
  const asking = useRef(false)
  return async () => {
    if (pending || asking.current) return
    asking.current = true
    try {
      const c = draftCloseCopy[locale]
      if (dirty && !(await confirm({ title: c.title, description: c.description, confirmText: c.discard, cancelText: c.keep, destructive: true }))) return
      onClose()
    } finally { asking.current = false }
  }
}

import { useCallback, useRef, useState, type ReactElement } from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import type { TFunction } from "@/i18n"

type ConfirmOptions = {
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  destructive?: boolean
}

/**
 * Promise-based confirm dialog. Replaces window.confirm with a themed AlertDialog.
 * Usage: const { confirm, confirmDialog } = useConfirm(t); render {confirmDialog};
 * then `if (!(await confirm({ title }))) return`.
 */
export function useConfirm(t: TFunction): { confirm: (options: ConfirmOptions) => Promise<boolean>; confirmDialog: ReactElement } {
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<ConfirmOptions>({ title: "" })
  const resolver = useRef<((value: boolean) => void) | null>(null)

  const settle = useCallback((result: boolean) => {
    setOpen(false)
    resolver.current?.(result)
    resolver.current = null
  }, [])

  const confirm = useCallback((next: ConfirmOptions) => {
    setOptions(next)
    setOpen(true)
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve
    })
  }, [])

  const confirmDialog = (
    <AlertDialog open={open} onOpenChange={(next) => { if (!next) settle(false) }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{options.title}</AlertDialogTitle>
          {options.description ? <AlertDialogDescription className="whitespace-pre-line">{options.description}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => settle(false)}>{options.cancelText ?? t("cancel")}</AlertDialogCancel>
          <AlertDialogAction variant={options.destructive ? "danger" : "default"} onClick={() => settle(true)}>{options.confirmText ?? t("confirm")}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )

  return { confirm, confirmDialog }
}

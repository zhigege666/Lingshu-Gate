import { useContext, useEffect, useId, type ComponentProps, type ReactNode } from "react"
import { EditorNavigationContext } from "@/components/editor-navigation-guard"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

type FormDialogProps = {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  closeLabel: string
  pending?: boolean
  dirty?: boolean
  className?: string
  children: ReactNode
  footer: ReactNode
  error?: string | null
  onCloseAutoFocus?: ComponentProps<typeof DialogContent>["onCloseAutoFocus"]
}

/**
 * Shared editing frame for role, permission type, and configuration forms.
 * Keeps actions and persistent failures outside the scrolling fields. The caller
 * owns draft protection, submission, field validation, and secret lifecycles.
 */
export function FormDialog({ open, onClose, title, description, closeLabel, pending = false, dirty = false, className, children, footer, error, onCloseAutoFocus }: FormDialogProps) {
  const descriptionId = useId()
  const registerExit = useContext(EditorNavigationContext)
  useEffect(() => {
    if (open) return registerExit?.({ dirty, pending })
  }, [open, dirty, pending, registerExit])
  return <Dialog open={open} onOpenChange={next => { if (!next && !pending) onClose() }}>
    <DialogContent className={cn("max-h-[calc(100dvh-2rem)] gap-4", className)} closeDisabled={pending} closeLabel={closeLabel} aria-busy={pending}
      aria-describedby={description ? descriptionId : undefined}
      onCloseAutoFocus={onCloseAutoFocus}
      onEscapeKeyDown={event => { if (pending) event.preventDefault() }}
      onPointerDownOutside={event => { if (pending) event.preventDefault() }}>
      <DialogHeader className="shrink-0"><DialogTitle className="whitespace-normal leading-snug">{title}</DialogTitle>{description && <DialogDescription id={descriptionId}>{description}</DialogDescription>}</DialogHeader>
      <DialogBody>{children}</DialogBody>
      {error && <Alert variant="destructive" role="alert" className="max-h-[20dvh] shrink-0 overflow-y-auto"><AlertDescription>{error}</AlertDescription></Alert>}
      {footer && <DialogFooter className="shrink-0 border-t pt-4">{footer}</DialogFooter>}
    </DialogContent>
  </Dialog>
}

import { useEffect } from "react"
import { createPortal } from "react-dom"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"

export type ToastTone = "info" | "success" | "error"
export type ToastState = { message: string; tone?: ToastTone } | null

const TONE_CLASS: Record<ToastTone, string> = {
  info: "border-l-4 border-l-primary",
  success: "border-l-4 border-l-success",
  error: "border-l-4 border-l-destructive",
}

export function Toaster({ toast, onClose, duration = 4000 }: { toast: ToastState; onClose: () => void; duration?: number }) {
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(onClose, duration)
    return () => clearTimeout(timer)
  }, [toast, duration, onClose])

  if (!toast) return null
  return createPortal(
    <div className="fixed bottom-4 right-4 z-[60] w-[calc(100%-2rem)] max-w-sm">
      <div className={cn("flex items-start gap-3 rounded-lg border bg-popover px-4 py-3 text-sm text-popover-foreground shadow-lg animate-in fade-in-0 slide-in-from-bottom-2", TONE_CLASS[toast.tone || "info"])}>
        <div className="min-h-0 max-h-40 min-w-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words">{toast.message}</div>
        <button type="button" onClick={onClose} className="shrink-0 text-muted-foreground hover:text-foreground" aria-label="Close"><X className="size-4" /></button>
      </div>
    </div>,
    document.body,
  )
}

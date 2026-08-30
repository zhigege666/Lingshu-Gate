import { useState } from "react"
import { Check, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn, prettyJson } from "@/lib/utils"

/**
 * Unified read-only panel for JSON / text output with a copy button and scroll area.
 * Pass either `text` (raw string) or `data` (serialized via prettyJson).
 */
export function JsonPanel({ text, data, maxHeight = "max-h-[420px]", className }: { text?: string; data?: unknown; maxHeight?: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  const content = text !== undefined ? text : data !== undefined ? prettyJson(data) : ""

  async function copy() {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className={cn("relative overflow-hidden rounded-lg border bg-muted", className)}>
      <Button type="button" size="sm" variant="secondary" onClick={copy} className="absolute right-2 top-2 z-10 h-7 gap-1.5 px-2 text-xs shadow-sm" aria-label="Copy">
        {copied ? <Check /> : <Copy />}
      </Button>
      <ScrollArea className={cn("w-full", maxHeight)}>
        <pre className="p-3 pr-12 text-xs text-foreground">{content || "-"}</pre>
      </ScrollArea>
    </div>
  )
}

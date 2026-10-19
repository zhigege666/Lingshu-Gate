import { useEffect, useRef, useState } from "react"
import { Check, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn, prettyJson } from "@/lib/utils"

/**
 * Unified read-only panel for JSON / text output with a copy button and scroll area.
 * Pass either `text` (raw string) or `data` (serialized via prettyJson).
 */
export function JsonPanel({ text, data, maxHeight = "max-h-[420px]", className, copyLabel = "Copy" }: { text?: string; data?: unknown; maxHeight?: string; className?: string; copyLabel?: string }) {
  const [copied, setCopied] = useState(false)
  const [copying, setCopying] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const copyingRef = useRef(false)
  const mounted = useRef(true)
  const content = text !== undefined ? text : data !== undefined ? prettyJson(data) : ""
  const currentContent = useRef(content)
  currentContent.current = content
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { setCopied(false); setCopyError(false) }, [content])
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(timer)
  }, [copied])

  async function copy() {
    if (copyingRef.current) return
    const snapshot = content
    copyingRef.current = true; setCopying(true); setCopyError(false)
    try {
      await navigator.clipboard.writeText(snapshot)
      if (mounted.current && currentContent.current === snapshot) setCopied(true)
    } catch {
      if (mounted.current && currentContent.current === snapshot) { setCopied(false); setCopyError(true) }
    } finally {
      copyingRef.current = false
      if (mounted.current) setCopying(false)
    }
  }

  return (
    <div className={cn("relative overflow-hidden rounded-lg border bg-muted", className)}>
      <Button type="button" size="sm" variant="secondary" onClick={copy} disabled={copying} className="absolute right-2 top-2 z-10 gap-2 px-2 text-xs shadow-sm" aria-label={copyLabel}>
        {copied ? <Check /> : <Copy />}
      </Button>
      {copyError && <p role="alert" className="json-panel-copy-error p-3 pr-12 text-xs text-destructive">{copyLabel === "复制" ? "复制失败，请重试；也可以选中下方内容手动复制。" : "Copy failed. Retry, or select the content below to copy it manually."}</p>}
      <ScrollArea className={cn("w-full", maxHeight)}>
        <pre className="p-3 pr-12 text-xs text-foreground">{content || "-"}</pre>
      </ScrollArea>
    </div>
  )
}

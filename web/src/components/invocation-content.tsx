import { useEffect, useRef, useState } from "react"
import { Alert, Button } from "antd"
import { request } from "@/api/http"
import type { Locale } from "@/i18n"
import { InvocationPayloadPanel, payloadText, type InvocationDetail } from "./invocation-payload-panel"

/** Administrator-only consumer; backend rechecks audit.payload.read on every read and copy. */
export function InvocationContent({ auditId, locale }: { auditId: string; locale: Locale }) {
  const zh = locale === "zh-CN"
  const [detail, setDetail] = useState<InvocationDetail | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  useEffect(() => { setDetail(null); setError(""); setBusy(false); generation.current++; return () => { generation.current++ } }, [auditId])
  async function load(side?: "input" | "output") {
    const revision = ++generation.current
    setBusy(true); if (!side) setDetail(null); setError("")
    try {
      const result = await request<InvocationDetail>(`/v1/access/invocation-audits/${encodeURIComponent(auditId)}`)
      if (revision !== generation.current) throw new Error("Selection changed")
      setDetail(result)
      if (side) {
        const text = payloadText(result[side])
        if (text === null) throw new Error("Recorded content unavailable")
        await navigator.clipboard.writeText(text)
      }
    } catch (cause) {
      if (revision === generation.current) { setDetail(null); setError(String(cause)) }
      if (side) throw cause
    } finally { if (revision === generation.current) setBusy(false) }
  }
  return <div className="space-y-3 lg:col-span-2">
    <p className="text-sm text-muted-foreground">{zh ? "输入/输出需独立的审计内容权限。默认只记摘要；开启内容记录后也仅展示已脱敏、限长的保留部分。" : "Input/output requires separate audit content permission. Recording defaults to metadata only; enabled content is redacted and bounded."}</p>
    <Button loading={busy} onClick={() => void load()}>{zh ? "读取输入/输出" : "Read input/output"}</Button>
    {error && <Alert type="error" title={error} />}
    {detail && <>
      <InvocationPayloadPanel title={zh ? "输入" : "Input"} payload={detail.input} locale={locale} onCopy={() => load("input")} />
      <InvocationPayloadPanel title={zh ? "输出" : "Output"} payload={detail.output} locale={locale} onCopy={() => load("output")} />
    </>}
  </div>
}

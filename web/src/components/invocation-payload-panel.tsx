import { useMemo, useState } from "react"
import { Alert, Button, Input } from "antd"
import type { Locale } from "@/i18n"

export type PayloadEnvelope = {
  status: "recorded" | "not_recorded" | "not_invoked" | "truncated" | "serialization_error"
  value?: unknown
  reasons?: string[]
}
export type InvocationDetail = {
  audit: { id: string; tool_id: string; created_at: string; outcome: string }
  input: PayloadEnvelope; output: PayloadEnvelope; recording_mode: "metadata_only" | "redacted"
}

export function payloadText(payload: PayloadEnvelope): string | null {
  return Object.prototype.hasOwnProperty.call(payload, "value") ? JSON.stringify(payload.value, null, 2) ?? null : null
}

/** Read-only recorded data. The caller must reauthorize each copy, and clear stale details on failure. */
export function InvocationPayloadPanel({ title, payload, locale, onCopy }: {
  title: string; payload: PayloadEnvelope; locale: Locale; onCopy: () => Promise<void>
}) {
  const zh = locale === "zh-CN"
  const [query, setQuery] = useState("")
  const [copying, setCopying] = useState(false)
  const [feedback, setFeedback] = useState("")
  const [copyError, setCopyError] = useState(false)
  const text = payloadText(payload)
  const lines = useMemo(() => (text ?? "").split("\n").filter(line => !query || line.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [text, query])
  const statuses = zh ? {
    recorded: "已记录（已脱敏）", not_recorded: "未记录：历史记录或记录策略未开启，不可补取原文。",
    not_invoked: "未执行：未保存调用内容。", truncated: "内容已截断，仅展示和复制保留部分。", serialization_error: "序列化失败，无法提供完整内容。",
  } : {
    recorded: "Recorded (redacted)", not_recorded: "Not recorded: historical record or recording disabled. Original content cannot be recovered.",
    not_invoked: "Not invoked: content was not recorded.", truncated: "Truncated: only retained content is displayed and copied.", serialization_error: "Serialization failed; complete content is unavailable.",
  }
  async function copy() {
    if (copying) return
    setCopying(true); setFeedback("")
    try { await onCopy(); setCopyError(false); setFeedback(zh ? "已复制保留内容" : "Retained content copied") }
    catch { setCopyError(true); setFeedback(zh ? "复制失败。请检查访问权限或浏览器剪贴板权限后重试。" : "Copy failed. Check access and browser clipboard permissions, then retry.") }
    finally { setCopying(false) }
  }
  return <section className="min-w-0 space-y-2" aria-label={title}>
    <h3 className="font-medium">{title}</h3>
    <p className="text-sm text-muted-foreground">{statuses[payload.status]}</p>
    {text !== null && <>
      <div className="flex flex-wrap gap-2">
        <Input.Search className="min-w-0 flex-1" aria-label={`${title} ${zh ? "搜索 JSON 行" : "Search JSON lines"}`} placeholder={zh ? "搜索已记录 JSON 行" : "Search recorded JSON lines"} value={query} onChange={event => setQuery(event.target.value)} allowClear />
        <Button loading={copying} onClick={() => void copy()}>{zh ? "复制 JSON" : "Copy JSON"}</Button>
      </div>
      <details open><summary className="cursor-pointer">{zh ? "查看 JSON" : "View JSON"}{query && ` · ${lines.length} ${zh ? "行匹配" : "matching lines"}`}</summary>
        <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded border p-3 text-xs">{lines.length ? lines.join("\n") : (zh ? "无匹配行" : "No matching lines")}</pre>
      </details>
      {query && <p className="text-xs text-muted-foreground">{zh ? "搜索仅过滤显示行；复制包含全部已保留、已脱敏内容。" : "Search filters displayed lines only. Copy includes all retained, redacted content."}</p>}
    </>}
    {feedback && <Alert type={copyError ? "error" : "success"} title={feedback} />}
  </section>
}

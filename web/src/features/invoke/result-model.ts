/** Display-only decoding: never execute markup, load remote media or mutate the response. */
export function readableResult(raw: string): { value: unknown; text: string; structured: boolean; duration?: number } {
  let value: unknown
  try { value = JSON.parse(raw) } catch { return { value: raw, text: raw, structured: false } }
  const envelope = value && typeof value === "object" ? value as Record<string, unknown> : null
  const result = envelope?.result
  if (result && typeof result === "object") {
    const payload = result as Record<string, unknown>
    if (Array.isArray(payload.content)) {
      const blocks = payload.content.map(block => {
        if (block?.type === "text" && typeof block.text === "string") {
          try { return JSON.parse(block.text) } catch { return block.text }
        }
        // Non-text blocks remain metadata; the viewer does not fetch URLs or render HTML.
        return block
      })
      value = payload.structuredContent !== undefined
        ? { structuredContent: payload.structuredContent, content: blocks }
        : blocks.length === 1 ? blocks[0] : blocks
      if (payload.isError === true) value = { isError: true, content: value }
    } else value = result
    if (envelope?.error !== undefined) value = { error: envelope.error, result: value }
  }
  return { value, text: typeof value === "string" ? value : JSON.stringify(value, null, 2), structured: value !== null && typeof value === "object", duration: typeof envelope?.duration_ms === "number" ? envelope.duration_ms : undefined }
}

export function resultMatches(text: string, query: string, limit = 5000) {
  if (!query) return { positions: [] as number[], capped: false }
  const matcher = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "giu")
  const positions: number[] = []
  for (;;) {
    const match = matcher.exec(text)
    if (!match) return { positions, capped: false }
    if (positions.length === limit) return { positions, capped: true }
    positions.push(match.index)
  }
}

export function resultWindow(text: string, activeOffset = 0, limit = 32000) {
  const start = Math.max(0, Math.min(Math.max(0, text.length - limit), activeOffset - Math.floor(limit / 2)))
  return { start, end: Math.min(text.length, start + limit), text: text.slice(start, start + limit) }
}

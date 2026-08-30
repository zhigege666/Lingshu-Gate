import { Fragment, type ReactNode } from "react"

/**
 * Highlights the subsequence of `text` that matches `query` (case-insensitive),
 * mirroring cmdk's fuzzy matching. Falls back to plain text when there is no match.
 */
export function HighlightText({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase()
  if (!q) return <>{text}</>

  const lower = text.toLowerCase()
  const matched: boolean[] = new Array(text.length).fill(false)
  let qi = 0
  for (let i = 0; i < text.length && qi < q.length; i++) {
    if (lower[i] === q[qi]) {
      matched[i] = true
      qi += 1
    }
  }
  if (qi < q.length) return <>{text}</>

  const nodes: ReactNode[] = []
  for (let i = 0; i < text.length; i++) {
    nodes.push(
      matched[i]
        ? <mark key={i} className="bg-transparent font-semibold text-primary">{text[i]}</mark>
        : <Fragment key={i}>{text[i]}</Fragment>,
    )
  }
  return <>{nodes}</>
}

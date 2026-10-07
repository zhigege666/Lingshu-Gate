import { useEffect, useMemo, useRef, useState } from "react"
import { Button, Input, Segmented, Switch } from "antd"
import { ChevronDown, ChevronUp, Search } from "lucide-react"
import type { Locale } from "@/i18n"
import { readableResult, resultMatches, resultWindow } from "./result-model"
import "./result-viewer.css"

const COPY = {
  "zh-CN": { content: "可读内容", raw: "原始响应", search: "搜索当前结果", previous: "上一处匹配", next: "下一处匹配", noMatches: "无匹配", clear: "清除搜索", wrap: "自动换行", tree: "结构视图", text: "文本视图", collapse: "折叠节点", expand: "展开一层", more: "再显示 100 项", items: "项", empty: "空内容", window: "长结果仅展示当前片段；搜索覆盖完整当前结果，顶部复制保留完整原始响应", elapsed: "耗时", mode: "结果显示方式" },
  "en-US": { content: "Readable content", raw: "Raw response", search: "Search current result", previous: "Previous match", next: "Next match", noMatches: "No matches", clear: "Clear search", wrap: "Wrap lines", tree: "Tree", text: "Text", collapse: "Collapse nodes", expand: "Expand one level", more: "Show 100 more", items: "items", empty: "Empty content", window: "Showing a window of this long result. Search covers the complete current result; the top copy action preserves the full raw response.", elapsed: "Duration", mode: "Result display mode" },
}

function ResultNode({ value, label, depth, expand, c }: { value: unknown; label: string; depth: number; expand: boolean; c: typeof COPY[Locale] }) {
  const [open, setOpen] = useState(depth < (expand ? 2 : 0))
  const [limit, setLimit] = useState(100)
  const object = value !== null && typeof value === "object"
  if (!object) return <div className="result-tree-leaf"><span>{label}: </span><code>{JSON.stringify(value)}</code></div>
  const entries = Object.entries(value as Record<string, unknown>)
  return <div className="result-tree-node">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}><span aria-hidden="true">{open ? "▾" : "▸"}</span> {label} <span className="result-node-summary">{Array.isArray(value) ? "[]" : "{}"} · {entries.length} {c.items}</span></button>
    {open && <div className="result-tree-children">{entries.slice(0, limit).map(([key, child]) => <ResultNode key={key} label={key} value={child} depth={depth + 1} expand={expand} c={c} />)}{entries.length > limit && <Button size="small" onClick={() => setLimit(limit + 100)}>{c.more} ({entries.length - limit})</Button>}</div>}
  </div>
}

export function ResultViewer({ raw, locale }: { raw: string; locale: Locale }) {
  const c = COPY[locale]
  const [mode, setMode] = useState("content")
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const [chunk, setChunk] = useState(0)
  const [wrap, setWrap] = useState(true)
  const [tree, setTree] = useState(true)
  const [expansion, setExpansion] = useState({ open: true, version: 0 })
  const region = useRef<HTMLDivElement>(null)
  const parsed = useMemo(() => readableResult(raw), [raw])
  const text = mode === "raw" ? raw : parsed.text
  const matches = useMemo(() => resultMatches(text, query), [text, query])
  const current = Math.min(active, Math.max(0, matches.positions.length - 1))
  const windowed = resultWindow(text, query ? matches.positions[current] || 0 : chunk * 32000 + 16000)
  useEffect(() => { setActive(0); setChunk(0) }, [text, query])
  useEffect(() => { region.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" }) }, [current, query, mode])
  function move(delta: number) { if (matches.positions.length) setActive((current + delta + matches.positions.length) % matches.positions.length) }
  const parts = []; let cursor = windowed.start
  for (const [index, start] of matches.positions.entries()) {
    if (start < windowed.start || start >= windowed.end) continue
    parts.push(text.slice(cursor, start), <mark key={start} data-active={index === current}>{text.slice(start, start + query.length)}</mark>)
    cursor = start + query.length
  }
  parts.push(text.slice(cursor, windowed.end))
  const showTree = mode === "content" && parsed.structured && tree && !query && text.length <= 32000
  return <div className="result-viewer">
    <div className="result-viewer-toolbar">
      <Segmented aria-label={c.mode} value={mode} onChange={value => setMode(String(value))} options={[{ value: "content", label: c.content }, { value: "raw", label: c.raw }]} />
      {parsed.duration !== undefined && <span className="result-viewer-meta">{c.elapsed}: {parsed.duration} ms</span>}
      <label className="result-wrap"><Switch size="small" checked={wrap} onChange={setWrap} aria-label={c.wrap} />{c.wrap}</label>
    </div>
    <div className="result-search-toolbar">
      <Input prefix={<Search size={15} />} aria-label={c.search} placeholder={c.search} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); move(event.shiftKey ? -1 : 1) } else if (event.key === "Escape") setQuery("") }} />
      {query && <><span role="status">{matches.positions.length ? `${current + 1} / ${matches.positions.length}${matches.capped ? "+" : ""}` : c.noMatches}</span><Button aria-label={c.previous} title={c.previous} icon={<ChevronUp size={15} />} disabled={!matches.positions.length} onClick={() => move(-1)} /><Button aria-label={c.next} title={c.next} icon={<ChevronDown size={15} />} disabled={!matches.positions.length} onClick={() => move(1)} /><Button size="small" onClick={() => setQuery("")}>{c.clear}</Button></>}
      {!query && mode === "content" && parsed.structured && text.length <= 32000 && <><Button size="small" onClick={() => setTree(!tree)}>{tree ? c.text : c.tree}</Button>{tree && <Button size="small" onClick={() => setExpansion({ open: !expansion.open, version: expansion.version + 1 })}>{expansion.open ? c.collapse : c.expand}</Button>}</>}
    </div>
    {text.length > 32000 && <p className="result-window-note">{c.window} ({windowed.start + 1}–{windowed.end} / {text.length})</p>}
    {text.length > 32000 && !query && <div className="result-search-toolbar"><Button size="small" disabled={chunk === 0} onClick={() => setChunk(chunk - 1)}>{locale === "zh-CN" ? "上一段" : "Previous section"}</Button><Button size="small" disabled={windowed.end >= text.length} onClick={() => setChunk(chunk + 1)}>{locale === "zh-CN" ? "下一段" : "Next section"}</Button></div>}
    <div ref={region} className="result-content-scroll" tabIndex={0} aria-label={mode === "content" ? c.content : c.raw}>
      {showTree ? <ResultNode key={expansion.version} label="$" value={parsed.value} depth={0} expand={expansion.open} c={c} /> : <pre style={{ whiteSpace: wrap ? "pre-wrap" : "pre" }}>{windowed.start > 0 ? "…\n" : ""}{text ? parts : c.empty}{windowed.end < text.length ? "\n…" : ""}</pre>}
    </div>
  </div>
}

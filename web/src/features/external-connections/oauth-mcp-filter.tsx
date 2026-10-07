import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"
import { Button, Radio, Select } from "antd"
import { oauthError, oauthRequest, type OAuthScopeCatalog, type OAuthScopeGroup } from "./oauth-api"

type Choice = { id: string; name?: string | null }
/** Radix's document capture runs before the selector's React Escape handler. */
export function preventOAuthMcpPopupDismiss(event: { target: EventTarget | null; preventDefault: () => void }) {
  if (event.target instanceof Element && event.target.closest('[data-oauth-mcp-popup="open"]')) event.preventDefault()
}
/** Small directories use radios; remote directories load bounded owner-visible choices. */
export function OAuthMcpFilter({ choices, remote, value, onChange, disabled, zh }: {
  choices?: Choice[]; remote?: { grantId: string; revision: string; count: number }
  value: string; onChange: (id: string) => void; disabled: boolean; zh: boolean
}) {
  const [groups, setGroups] = useState<Choice[]>([])
  const [query, setQuery] = useState("")
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [opened, setOpened] = useState(false)
  const selector = useRef<HTMLDivElement>(null)
  const actions = useRef<HTMLDivElement>(null)
  const retryCursor = useRef<string | undefined>(undefined)
  const keyboardHelp = useId()
  const generation = useRef(0)
  useEffect(() => { generation.current++; setGroups([]); setCursor(null); setQuery(""); setError(""); setLoading(false); setOpened(false) }, [remote?.grantId, remote?.revision])
  useEffect(() => () => { generation.current++ }, [])
  async function load(search: string, nextCursor?: string) {
    if (!remote) return
    const current = ++generation.current
    setLoading(true); setError("")
    const params = new URLSearchParams({ view: "groups", query: search, limit: "15", catalog_revision: remote.revision })
    if (nextCursor) params.set("cursor", nextCursor)
    try {
      const result = await oauthRequest<OAuthScopeCatalog>(`/v1/auth/oauth/grants/${remote.grantId}/scope-catalog?${params}`)
      if (current !== generation.current) return
      const next = (result.items as OAuthScopeGroup[]).map(group => ({ id: group.server_id, name: group.server_name }))
      setGroups(previous => nextCursor ? [...previous, ...next] : next); setCursor(result.next_cursor)
    } catch (cause) { if (current === generation.current) { retryCursor.current = nextCursor; setError(oauthError(cause, zh)) } }
    finally { if (current === generation.current) setLoading(false) }
  }
  useEffect(() => {
    if (remote && remote.count <= 4) void load("")
  }, [remote?.grantId, remote?.revision, remote?.count])
  const items = choices || groups
  const labels = items.map(item => item.name || item.id)
  const shortLabels = labels.every(label => label.length <= 24) && new Set(labels).size === labels.length
  const short = choices ? choices.length <= 4 && shortLabels : Boolean(remote && remote.count <= 4 && items.length === remote.count && shortLabels)
  const label = zh ? "按 MCP 筛选" : "Filter by MCP"
  function focusFilter() { selector.current?.querySelector<HTMLInputElement>('[role="combobox"]')?.focus({ preventScroll: true }) }
  function leaveSelector(direction: number) {
    const input = selector.current?.querySelector<HTMLInputElement>('[role="combobox"]')
    const container = selector.current?.closest('[role="dialog"]') || document
    const tabbable = Array.from(container.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href], [tabindex]'))
      .filter(element => element.tabIndex >= 0 && !element.matches(':disabled') && element.getClientRects().length > 0 && !actions.current?.contains(element))
    setOpened(false)
    tabbable[tabbable.indexOf(input!) + direction]?.focus({ preventScroll: true })
  }
  function onFilterKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!opened || event.key !== "Tab" || !(event.target as HTMLElement).matches('[role="combobox"]') || !actions.current) return
    // Select handles Tab as option selection before a popup button can receive it.
    event.preventDefault(); event.stopPropagation()
    const first = actions.current.querySelector<HTMLButtonElement>('button:not(:disabled)')
    if (event.shiftKey || !first) leaveSelector(event.shiftKey ? -1 : 1)
    else first.focus({ preventScroll: true })
  }
  function onActionKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    // These are directory actions outside the listbox, not selectable MCPs.
    event.stopPropagation()
    if (event.key === "Escape") { event.preventDefault(); setOpened(false); focusFilter() }
    else if (event.key === "Tab") {
      event.preventDefault()
      const buttons = Array.from(actions.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])
      const index = buttons.indexOf(event.target as HTMLButtonElement)
      const next = buttons[index + (event.shiftKey ? -1 : 1)]
      if (next) next.focus({ preventScroll: true })
      else if (event.shiftKey) focusFilter()
      else leaveSelector(1)
    }
  }
  function loadFromAction(nextCursor?: string) { focusFilter(); void load(query, nextCursor) }
  if (short) return <Radio.Group className="oauth-mcp-chips" aria-label={label} value={value} disabled={disabled} onChange={event => onChange(event.target.value)} optionType="button" options={[{ value: "", label: zh ? "全部 MCP" : "All MCPs" }, ...items.map(item => ({ value: item.id, label: item.name || item.id, title: item.id }))]} />
  return <div className="oauth-mcp-selector" ref={selector} data-oauth-mcp-popup={opened ? "open" : undefined} onKeyDownCapture={onFilterKeyDown}><span id={keyboardHelp} className="sr-only">{zh ? "方向键选择 MCP；Tab 进入加载或重试操作；Escape 关闭列表。" : "Use arrow keys to choose an MCP, Tab for load or retry actions, and Escape to close the list."}</span><Select aria-label={label} aria-describedby={remote ? keyboardHelp : undefined} showSearch={{ filterOption: !remote ? (input, option) => String(option?.searchText || "").toLowerCase().includes(input.toLowerCase()) : false, onSearch: text => { setQuery(text); if (remote) void load(text) } }} value={value} disabled={disabled} loading={loading} open={opened}
    getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!}
    onOpenChange={next => { setOpened(next); if (next && !opened && remote) { setQuery(""); void load("") } }} onChange={id => onChange(id)}
    options={[{ value: "", label: zh ? "全部 MCP" : "All MCPs", searchText: "", name: "" }, ...(value && !items.some(item => item.id === value) ? [{ value, label: value, searchText: value, name: "" }] : []), ...items.map(item => ({ value: item.id, label: item.id, searchText: `${item.name || ""} ${item.id}`, name: item.name || "" }))]}
    optionRender={option => <span title={option.data.name || undefined}>{option.label}</span>}
    popupRender={menu => <>{menu}{(error || cursor) && <div ref={actions} role="group" data-oauth-mcp-popup={opened ? "open" : undefined} aria-label={zh ? "MCP 目录操作" : "MCP catalog actions"} onKeyDownCapture={onActionKeyDown} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && !selector.current?.contains(event.relatedTarget)) setOpened(false) }}>{error && <div className="oauth-selector-feedback" role="alert">{error}<Button size="small" disabled={loading} onMouseDown={event => event.preventDefault()} onClick={() => loadFromAction(retryCursor.current)}>{zh ? "重试" : "Retry"}</Button></div>}{cursor && <Button className="oauth-selector-more" type="text" disabled={loading} onMouseDown={event => event.preventDefault()} onClick={() => loadFromAction(cursor)}>{zh ? "加载更多 MCP" : "Load more MCPs"}</Button>}</div>}</>} /></div>
}

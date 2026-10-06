import { useEffect, useRef, useState } from "react"
import { Button, Radio, Select } from "antd"
import { oauthError, oauthRequest, type OAuthScopeCatalog, type OAuthScopeGroup } from "./oauth-api"

type Choice = { id: string; name?: string | null }
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
  const generation = useRef(0)
  useEffect(() => { generation.current++; setGroups([]); setCursor(null); setQuery(""); setError(""); setLoading(false) }, [remote?.grantId, remote?.revision])
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
    } catch (cause) { if (current === generation.current) setError(oauthError(cause, zh)) }
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
  if (short) return <Radio.Group className="oauth-mcp-chips" aria-label={label} value={value} disabled={disabled} onChange={event => onChange(event.target.value)} optionType="button" options={[{ value: "", label: zh ? "全部 MCP" : "All MCPs" }, ...items.map(item => ({ value: item.id, label: item.name || item.id, title: item.id }))]} />
  return <Select aria-label={label} showSearch={{ filterOption: !remote ? (input, option) => String(option?.searchText || "").toLowerCase().includes(input.toLowerCase()) : false, onSearch: text => { setQuery(text); if (remote) void load(text) } }} value={value} disabled={disabled} loading={loading}
    getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!}
    onOpenChange={opened => { if (opened && remote) { setQuery(""); void load("") } }} onChange={id => onChange(id)}
    options={[{ value: "", label: zh ? "全部 MCP" : "All MCPs", searchText: "", name: "" }, ...(value && !items.some(item => item.id === value) ? [{ value, label: value, searchText: value, name: "" }] : []), ...items.map(item => ({ value: item.id, label: item.id, searchText: `${item.name || ""} ${item.id}`, name: item.name || "" }))]}
    optionRender={option => <span title={option.data.name || undefined}>{option.label}</span>}
    popupRender={menu => <>{menu}{error && <div className="oauth-selector-feedback" role="alert">{error}<Button size="small" disabled={loading} onClick={() => void load(query)}>{zh ? "重试" : "Retry"}</Button></div>}{cursor && <Button className="oauth-selector-more" type="text" disabled={loading} onMouseDown={event => event.preventDefault()} onClick={() => void load(query, cursor)}>{zh ? "加载更多 MCP" : "Load more MCPs"}</Button>}</>} />
}

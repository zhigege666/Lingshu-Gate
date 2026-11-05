import { useEffect, useRef, useState, type ComponentProps } from "react"
import { Alert, Button } from "antd"
import { McpAuthorizationEditor } from "./mcp-authorization-editor"
import { oauthError, oauthRequest, type OAuthScopeCatalog, type OAuthScopeGroup } from "./oauth-api"

type Props = Omit<ComponentProps<typeof McpAuthorizationEditor>, "groups" | "remote"> & {
  grantId: string; revision: string; refreshKey: number
  onGroups: (groups: OAuthScopeGroup[]) => void
}

/** Load only the service page being inspected; the parent retains all authorization drafts. */
export function OAuthPagedMcpEditor({ grantId, revision, refreshKey, onGroups, ...props }: Props) {
  const [groups, setGroups] = useState<OAuthScopeGroup[]>([])
  const [query, setQuery] = useState("")
  const [cursors, setCursors] = useState([""])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const generation = useRef(0)
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retry = useRef({ query: "", cursors: [""] })
  async function load(search: string, pages: string[]) {
    if (debounce.current) clearTimeout(debounce.current)
    const current = ++generation.current
    retry.current = { query: search, cursors: pages }
    setLoading(true); setError("")
    const params = new URLSearchParams({ view: "groups", limit: "10", query: search, catalog_revision: revision })
    if (pages.at(-1)) params.set("cursor", pages.at(-1)!)
    try {
      const result = await oauthRequest<OAuthScopeCatalog>(`/v1/auth/oauth/grants/${grantId}/scope-catalog?${params}`)
      if (current !== generation.current) return
      const items = result.items as OAuthScopeGroup[]
      setGroups(items); setCursors(pages); setNextCursor(result.next_cursor); setTotal(result.matching_counts.mcps)
      onGroups(items)
    } catch (cause) {
      if (current === generation.current) { setGroups([]); setNextCursor(null); setError(oauthError(cause, props.zh)) }
    } finally { if (current === generation.current) setLoading(false) }
  }
  useEffect(() => {
    setQuery(""); setGroups([]); setCursors([""]); setNextCursor(null)
    void load("", [""])
    return () => { generation.current++; if (debounce.current) clearTimeout(debounce.current) }
  }, [grantId, revision, refreshKey])
  function search(value: string) {
    setQuery(value); generation.current++; setLoading(true); setError("")
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(() => void load(value, [""]), 250)
  }
  return <div className="oauth-paged-mcp-editor">
    <McpAuthorizationEditor {...props} groups={groups} remote={{ query, page: cursors.length, total, loading, hasNext: Boolean(nextCursor), onQuery: search, onPrevious: () => void load(query, cursors.slice(0, -1)), onNext: () => { if (nextCursor) void load(query, [...cursors, nextCursor]) } }} />
    {error && <Alert type="error" title={error} action={<Button disabled={loading || props.disabled} onClick={() => void load(retry.current.query, retry.current.cursors)}>{props.zh ? "重试读取 MCP" : "Retry MCP page"}</Button>} />}
  </div>
}

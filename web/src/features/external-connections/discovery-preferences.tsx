import { useEffect, useRef, useState } from "react"
import { Alert, Button, Checkbox, Input, Radio, Select, Tag } from "antd"
import { oauthRequest } from "./oauth-api"

export type Pin = { kind: "tool" | "group"; tool_ref: string }
export type Budget = { schema_version: 1; enabled: boolean; max_characters: number }
export const DEFAULT_BUDGET: Budget = { schema_version: 1, enabled: false, max_characters: 8192 }
type Choice = Pin & { name: string }
const keyOf = (pin: Pin) => `${pin.kind}:${pin.tool_ref}`

export function PinPicker({ pins, onChange, zh, disabled }: {
  pins: Pin[]; onChange: (pins: Pin[]) => void; zh: boolean; disabled: boolean
}) {
  const [kind, setKind] = useState<Pin["kind"]>("tool")
  const [query, setQuery] = useState(""), [groupQuery, setGroupQuery] = useState("")
  const [group, setGroup] = useState<string | undefined>()
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([])
  const [selectedGroupName, setSelectedGroupName] = useState("")
  const [choices, setChoices] = useState<Choice[]>([]), [known, setKnown] = useState<Record<string, string>>({})
  const [unavailable, setUnavailable] = useState<string[]>([])
  const [cursor, setCursor] = useState<string | null>(null), [groupCursor, setGroupCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false), [groupsLoading, setGroupsLoading] = useState(false)
  const [searched, setSearched] = useState(false), [groupsSearched, setGroupsSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0), groupGeneration = useRef(0)
  const pinIdentity = JSON.stringify(pins)
  const groupOptions = group && !groups.some(item => item.id === group) ? [...groups, { id: group, name: selectedGroupName }] : groups

  useEffect(() => {
    let current = true
    const selected = JSON.parse(pinIdentity) as Pin[]
    if (!selected.length) { setUnavailable([]); return }
    void oauthRequest<{ available_to_current_user: Choice[] }>("/v1/catalog/pins/preview", { pinned_tools: selected }).then(result => {
      if (!current) return
      const available = new Set(result.available_to_current_user.map(keyOf))
      setUnavailable(selected.filter(pin => !available.has(keyOf(pin))).map(keyOf))
      setKnown(previous => ({ ...previous, ...Object.fromEntries(result.available_to_current_user.map(pin => [keyOf(pin), pin.name])) }))
    }).catch(() => { if (current) setError(zh ? "无法核对所选工具，请重新搜索。" : "Unable to verify selected tools. Search again.") })
    return () => { current = false }
  }, [pinIdentity, zh])
  useEffect(() => () => { generation.current++; groupGeneration.current++ }, [])

  async function search(nextCursor: string | null = null) {
    if (disabled || loading || kind === "group" && !group) return
    const current = ++generation.current
    setLoading(true); setSearched(false); setError(null)
    try {
      const result = await oauthRequest<{ tools: { tool_ref: string; name: string }[]; next_cursor: string | null }>("/v1/catalog/search", {
        query, limit: 20, ...(kind === "group" ? { group_id: group } : {}), ...(nextCursor ? { cursor: nextCursor } : {}),
      })
      if (generation.current !== current) return
      const values = result.tools.map(tool => ({ kind, tool_ref: tool.tool_ref, name: tool.name }))
      setChoices(values); setCursor(result.next_cursor); setSearched(true)
      setKnown(previous => ({ ...previous, ...Object.fromEntries(values.map(value => [keyOf(value), value.name])) }))
    } catch { if (generation.current === current) setError(zh ? "目录已变化或无法读取，请重新搜索。" : "The directory changed or could not be loaded. Search again.") }
    finally { if (generation.current === current) setLoading(false) }
  }
  async function searchGroups(nextCursor: string | null = null) {
    if (disabled || groupsLoading) return
    const current = ++groupGeneration.current
    setGroupsLoading(true); setGroupsSearched(false); setError(null)
    try {
      const result = await oauthRequest<{ groups: { id: string; name: string }[]; next_cursor: string | null }>("/v1/catalog/groups", {
        query: groupQuery, limit: 20, ...(nextCursor ? { cursor: nextCursor } : {}),
      })
      if (groupGeneration.current === current) { setGroups(result.groups); setGroupCursor(result.next_cursor); setGroupsSearched(true) }
    } catch { if (groupGeneration.current === current) setError(zh ? "无法读取可见分组，请重试。" : "Unable to load visible groups. Retry.") }
    finally { if (groupGeneration.current === current) setGroupsLoading(false) }
  }
  function resetSearch() { generation.current++; setChoices([]); setCursor(null); setLoading(false); setSearched(false); setError(null) }
  function resetGroupSearch() { groupGeneration.current++; setGroups([]); setGroupCursor(null); setGroupsLoading(false); setGroupsSearched(false); setGroup(undefined); resetSearch() }
  function toggle(choice: Choice, checked: boolean) {
    if (disabled) return
    onChange(checked ? pins.length < 20 ? [...pins, { kind: choice.kind, tool_ref: choice.tool_ref }] : pins
      : pins.filter(pin => keyOf(pin) !== keyOf(choice)))
  }

  return <div className="space-y-3 min-w-0">
    <div className="flex items-center justify-between gap-3"><span className="text-sm">{zh ? `已固定 ${pins.length}/20` : `${pins.length}/20 pinned`}</span>
      <Button size="small" disabled={disabled || !pins.length} onClick={() => onChange([])}>{zh ? "清空" : "Clear"}</Button></div>
    {pins.length > 0 && <div className="max-h-28 overflow-y-auto flex flex-wrap gap-1" aria-label={zh ? "已固定工具" : "Pinned tools"}>
      {pins.map(pin => <Tag key={keyOf(pin)} color={unavailable.includes(keyOf(pin)) ? "warning" : undefined} closable={!disabled}
        title={`${pin.kind} · ${pin.tool_ref}${unavailable.includes(keyOf(pin)) ? zh ? " · 当前用户不可用" : " · Unavailable to current user" : ""}`}
        className="max-w-full inline-flex" onClose={event => { event.preventDefault(); onChange(pins.filter(item => keyOf(item) !== keyOf(pin))) }}>
        <span className="truncate">{pin.kind === "group" ? zh ? "组 · " : "Group · " : ""}{known[keyOf(pin)] || pin.tool_ref}</span>
        {unavailable.includes(keyOf(pin)) && <span className="shrink-0 ml-1">{zh ? "（当前不可用）" : "(Unavailable)"}</span>}
      </Tag>)}
    </div>}
    <Radio.Group aria-label={zh ? "工具类型" : "Tool type"} value={kind} disabled={disabled} onChange={event => { setKind(event.target.value); resetSearch() }}>
      <Radio value="tool">{zh ? "实例工具" : "Instance tool"}</Radio><Radio value="group">{zh ? "逻辑组工具" : "Logical group tool"}</Radio>
    </Radio.Group>
    {kind === "group" && <div className="space-y-2">
      <Input.Search aria-label={zh ? "搜索分组" : "Search groups"} placeholder={zh ? "分组名称" : "Group name"} value={groupQuery} maxLength={128}
        onChange={event => { setGroupQuery(event.target.value); resetGroupSearch() }} onSearch={() => void searchGroups()} loading={groupsLoading} disabled={disabled} enterButton={zh ? "查找组" : "Find groups"} />
      <div className="flex gap-2"><Select className="min-w-0 flex-1" aria-label={zh ? "选择分组" : "Select group"} placeholder={zh ? "选择可见分组" : "Select a visible group"}
        value={group} options={groupOptions.map(item => ({ value: item.id, label: item.name }))} disabled={disabled || groupsLoading}
        getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!}
        onChange={value => { setGroup(value); setSelectedGroupName(groupOptions.find(item => item.id === value)?.name || value); resetSearch() }} />
        {groupCursor && <Button disabled={disabled || groupsLoading} onClick={() => void searchGroups(groupCursor)}>{zh ? "下一页组" : "Next groups"}</Button>}</div>
      {groupsSearched && !groupsLoading && groups.length === 0 && <p role="status" className="text-xs text-muted-foreground">{zh ? "没有可见的匹配分组，请调整名称后重试。" : "No visible groups match. Change the name and search again."}</p>}
    </div>}
    <Input.Search aria-label={zh ? "搜索固定工具" : "Search tools to pin"} placeholder={zh ? "工具名称或关键词" : "Tool name or keywords"} value={query} maxLength={256}
      onChange={event => { setQuery(event.target.value); resetSearch() }} onSearch={() => void search()} loading={loading}
      disabled={disabled || kind === "group" && !group} enterButton={zh ? "搜索工具" : "Search tools"} />
    {choices.length > 0 && <div className="max-h-48 overflow-y-auto rounded border p-2 space-y-2" aria-label={zh ? "搜索结果" : "Search results"}>
      {choices.map(choice => <div key={keyOf(choice)} className="min-w-0"><Checkbox checked={pins.some(pin => keyOf(pin) === keyOf(choice))}
        disabled={disabled || loading || pins.length >= 20 && !pins.some(pin => keyOf(pin) === keyOf(choice))}
        onChange={event => toggle(choice, event.target.checked)}><span title={choice.tool_ref} className="break-all">{choice.name} <span className="text-xs text-muted-foreground">· {choice.tool_ref}</span></span></Checkbox></div>)}
    </div>}
    {searched && !loading && choices.length === 0 && <p role="status" className="text-xs text-muted-foreground">{zh ? "没有可见的匹配工具，请调整关键词后重试。" : "No visible tools match. Change the keywords and search again."}</p>}
    {cursor && <Button size="small" disabled={disabled || loading} onClick={() => void search(cursor)}>{zh ? "下一页工具" : "Next tools"}</Button>}
    {error && <Alert type="error" showIcon title={error} />}
    <p className="text-xs text-muted-foreground">{zh ? "固定只改变按需列表。实际可用范围取决于此授权；组工具调用仍须明确选择实例和会话。" : "Pins change the on-demand list. This authorization still limits access; group calls require an explicit instance and session."}</p>
  </div>
}

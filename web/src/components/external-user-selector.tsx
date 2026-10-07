import { useEffect, useId, useRef, useState } from "react"
import { Button, Select } from "antd"
import { externalRequest as request, externalError } from "@/features/external-connections/api"
import { bindingUserLabel, type BindingUser } from "@/features/external-connections/model"

export function ExternalUserSelector({ value, onChange, disabled, zh }: {
  value: BindingUser | null; onChange: (user: BindingUser | null) => void; disabled: boolean; zh: boolean
}) {
  const labelId = useId()
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const [users, setUsers] = useState<BindingUser[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [retry, setRetry] = useState(0)
  const generation = useRef(0)
  useEffect(() => {
    const version = ++generation.current
    const controller = new AbortController()
    setLoading(true); setError(""); setUsers([]); setTotal(0)
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ q: query, offset: String(offset), limit: "40" })
      void request<{ users: BindingUser[]; total: number }>(`/v1/auth/external-subject-links/user-options?${params}`, { signal: controller.signal })
        .then(result => { if (version === generation.current) { setUsers(result.users); setTotal(result.total) } })
        .catch(cause => { if (version === generation.current && !controller.signal.aborted) setError(externalError(cause, zh)) })
        .finally(() => { if (version === generation.current) setLoading(false) })
    }, query ? 200 : 0)
    return () => { generation.current++; controller.abort(); window.clearTimeout(timer) }
  }, [query, offset, retry, zh])
  const options = users.map(user => ({ value: user.id, label: `${bindingUserLabel(user)} · ${user.id}` }))
  if (value && !options.some(item => item.value === value.id)) options.unshift({ value: value.id, label: `${bindingUserLabel(value)} · ${value.id}` })
  return <div className="flex flex-col gap-2">
    <label id={labelId}>{zh ? "Gate 用户" : "Gate user"}</label>
    <Select aria-labelledby={labelId} aria-label={zh ? "Gate 用户" : "Gate user"} value={value?.id} disabled={disabled}
      getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!}
      showSearch filterOption={false} searchValue={query} onSearch={next => { setQuery(next); setOffset(0) }}
      allowClear loading={loading} options={options} virtual listHeight={224}
      placeholder={zh ? "搜索名称、用户名或 ID" : "Search name, username or ID"}
      onChange={id => { onChange(users.find(user => user.id === id) || (value?.id === id ? value : null)); setQuery(""); setOffset(0) }}
      notFoundContent={loading ? (zh ? "加载中…" : "Loading…") : error ? (zh ? "加载失败" : "Unable to load") : (zh ? "没有可绑定的匹配用户" : "No matching active users")}
      popupRender={menu => <>{menu}<div className="flex items-center justify-between gap-2 border-t p-2" onMouseDown={event => event.preventDefault()}>
        <Button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 40))}>{zh ? "上一页" : "Previous"}</Button>
        <span role="status">{loading ? "…" : `${total ? offset + 1 : 0}–${Math.min(offset + users.length, total)} / ${total}`}</span>
        <Button disabled={loading || offset + 40 >= total} onClick={() => setOffset(offset + 40)}>{zh ? "下一页" : "Next"}</Button>
      </div></>} />
    {error && <div role="alert">{error}<Button onClick={() => setRetry(value => value + 1)}>{zh ? "重试" : "Retry"}</Button></div>}
  </div>
}

import { useEffect, useRef, useState } from "react"
import { Alert, Button, Empty, Input, Pagination, Radio, Table, Tag, message } from "antd"
import { mcpGroupsApi, type McpGroup, type McpGroupInstance, type McpGroupSummary } from "@/api/mcp-groups"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { useConfirm } from "@/components/confirm-dialog"
import { localizeStatus, type Locale, type TFunction } from "@/i18n"
import { McpGroupEditor } from "./group-editor"
import { groupCopy, groupError } from "./group-copy"

export function McpGroupsView({ locale, t, serverIds, onSelectInstance, onBusyChange, canWrite }: {
  locale: Locale; t: TFunction; serverIds: Set<string>; onSelectInstance: (id: string) => void; onBusyChange: (busy: boolean) => void; canWrite: boolean
}) {
  const c = groupCopy(locale)
  const [query, setQuery] = useState(""), [state, setState] = useState("active"), [page, setPage] = useState(1)
  const [list, setList] = useState<{ groups: McpGroupSummary[]; total: number } | null>(null)
  const [loading, setLoading] = useState(false), [listError, setListError] = useState("")
  const [selection, setSelection] = useState<string | null>(null)
  const [detail, setDetail] = useState<McpGroup | null>(null), [detailError, setDetailError] = useState("")
  const [instances, setInstances] = useState<{ instances: McpGroupInstance[]; total: number } | null>(null)
  const [membersLoading, setMembersLoading] = useState(false)
  const [memberError, setMemberError] = useState("")
  const [memberQuery, setMemberQuery] = useState(""), [memberPage, setMemberPage] = useState(1)
  const [editing, setEditing] = useState<{ group: McpGroup | null } | null>(null)
  const [refresh, setRefresh] = useState(0), [busy, setBusy] = useState(false), [mutationError, setMutationError] = useState("")
  const listGeneration = useRef(0), detailGeneration = useRef(0), membersGeneration = useRef(0), alive = useRef(true), lock = useRef(false)
  const mutation = useRef<AbortController | null>(null)
  const fallbackFocus = useRef<HTMLButtonElement>(null)
  const { confirm, confirmDialog } = useConfirm(t, true)
  const [toast, toastContext] = message.useMessage()
  useEffect(() => { alive.current = true; return () => { alive.current = false; mutation.current?.abort() } }, [])
  useEffect(() => { onBusyChange(busy || Boolean(editing)); return () => onBusyChange(false) }, [busy, editing, onBusyChange])
  useEffect(() => {
    const controller = new AbortController(), current = ++listGeneration.current
    setLoading(true); setList(null); setListError("")
    void mcpGroupsApi.list({ q: query, status: state, offset: (page - 1) * 20, limit: 20 }, controller.signal)
      .then(next => { if (alive.current && current === listGeneration.current) { setList(next); if (page > 1 && (page - 1) * 20 >= next.total) setPage(Math.max(1, Math.ceil(next.total / 20))) } })
      .catch(cause => { if (alive.current && current === listGeneration.current) setListError(groupError(cause, locale)) })
      .finally(() => { if (alive.current && current === listGeneration.current) setLoading(false) })
    return () => { listGeneration.current++; controller.abort() }
  }, [query, state, page, refresh, locale])
  useEffect(() => {
    const controller = new AbortController(), current = ++detailGeneration.current
    setDetail(null); setDetailError(""); setMutationError("")
    if (selection && selection !== "__ungrouped") void mcpGroupsApi.detail(selection, controller.signal)
      .then(next => { if (alive.current && current === detailGeneration.current && next.id === selection) setDetail(next) })
      .catch(cause => { if (alive.current && current === detailGeneration.current) setDetailError(groupError(cause, locale)) })
    return () => { detailGeneration.current++; controller.abort() }
  }, [selection, refresh, locale])
  useEffect(() => {
    const controller = new AbortController(), current = ++membersGeneration.current
    setInstances(null); setMemberError(""); setMembersLoading(Boolean(selection))
    if (selection) void mcpGroupsApi.instances({ q: memberQuery, offset: (memberPage - 1) * 20, limit: 20,
      ...(selection === "__ungrouped" ? { ungrouped: true } : { group_id: selection }) }, controller.signal)
      .then(next => { if (alive.current && current === membersGeneration.current) { setInstances(next); if (memberPage > 1 && (memberPage - 1) * 20 >= next.total) setMemberPage(Math.max(1, Math.ceil(next.total / 20))) } })
      .catch(cause => { if (alive.current && current === membersGeneration.current) setMemberError(groupError(cause, locale)) })
      .finally(() => { if (alive.current && current === membersGeneration.current) setMembersLoading(false) })
    return () => { membersGeneration.current++; controller.abort() }
  }, [selection, memberQuery, memberPage, refresh, locale])
  function choose(id: string) { setSelection(id); setMemberPage(1); setMemberQuery("") }
  async function refreshDirectory() {
    if (lock.current) return
    lock.current = true; setBusy(true); setMutationError("")
    const controller = new AbortController(); mutation.current = controller
    try {
      await mcpGroupsApi.instances({ limit: 1, refresh: true }, controller.signal)
      if (alive.current) setRefresh(value => value + 1)
    } catch (cause) { if (alive.current) setMutationError(groupError(cause, locale)) }
    finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  async function remove() {
    if (!detail || lock.current) return
    lock.current = true; setBusy(true); setMutationError("")
    const target = detail, controller = new AbortController(); mutation.current = controller
    try {
      if (!(await confirm({ title: `${c.deleteTitle} · ${target.name}`, description: c.metadata, confirmText: c.delete, cancelText: t("cancel"), destructive: true }))) return
      if (!alive.current) return
      await mcpGroupsApi.delete(target.id, target.revision, controller.signal)
      if (alive.current) { setSelection(null); setDetail(null); setRefresh(value => value + 1); void toast.success(c.deleted, 3); fallbackFocus.current?.focus() }
    } catch (cause) { if (alive.current) setMutationError(groupError(cause, locale)) }
    finally { lock.current = false; if (alive.current) setBusy(false) }
  }
  return <>
    <aside className="service-directory" aria-label={c.groups}>
      <div className="service-directory-header">
        <div className="service-directory-title"><h2>{c.groups}</h2>{canWrite && <Button disabled={busy} onClick={() => setEditing({ group: null })}>{c.newGroup}</Button>}</div>
        <PageToolbar query={query} onQueryChange={value => { setQuery(value); setPage(1) }} placeholder={c.searchGroups} clearLabel={t("clearSearch")} />
        <Radio.Group aria-label={c.state} value={state} disabled={busy} options={[{ value: "active", label: c.active }, { value: "archived", label: c.archived }, { value: "all", label: c.all }]} onChange={event => { setState(String(event.target.value)); setPage(1) }} />
        <Button block disabled={busy} aria-pressed={selection === "__ungrouped"} onClick={() => choose("__ungrouped")}>{c.ungrouped}</Button>
      </div>
      {listError && <Alert role="alert" type="error" showIcon title={listError} action={<Button onClick={() => setRefresh(value => value + 1)}>{c.retry}</Button>} />}
      <div className="service-directory-list" aria-busy={loading}>
        {list?.groups.map(item => <button className="service-entry" key={item.id} disabled={busy} aria-pressed={selection === item.id} data-active={selection === item.id} onClick={() => choose(item.id)}>
          <span><span className="service-entry-name" title={item.name}>{item.name}</span><span className="service-entry-subtitle" title={item.id}>{item.id}</span></span>
          <span className="service-entry-meta"><Tag>{item.status === "active" ? c.active : c.archived}</Tag><span>{item.member_count}</span></span>
        </button>)}
        {!loading && !listError && list?.groups.length === 0 && <Empty description={query ? c.noMatches : c.empty} image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </div>
      <div className="service-directory-footer"><Pagination simple current={page} total={list?.total ?? 0} pageSize={20} showSizeChanger={false} disabled={busy || loading} onChange={setPage} /></div>
    </aside>
    <section className="service-detail mcp-group-detail" aria-label={c.groups}>
      <PageHeader closeLabel={t("close")} variant="detail" title={selection === "__ungrouped" ? c.ungrouped : detail?.name || c.groups} description={detail?.id} titleExtra={detail && <Tag>{detail.status === "active" ? c.active : c.archived}</Tag>}
        actions={<><Button ref={fallbackFocus} disabled={busy} onClick={() => void refreshDirectory()}>{c.refresh}</Button>{detail && canWrite && <><Button disabled={busy} onClick={() => setEditing({ group: detail })}>{c.edit}</Button><Button danger disabled={busy} onClick={() => void remove()}>{c.delete}</Button></>}</>} />
      <p className="service-description mcp-group-policy">{c.metadata}</p>
      {detail?.description && <p className="mcp-group-policy">{detail.description}</p>}
      {(detailError || memberError || mutationError) && <Alert role="alert" type="error" showIcon title={mutationError || detailError || memberError} action={<Button disabled={busy} onClick={() => setRefresh(value => value + 1)}>{c.retry}</Button>} />}
      {!selection ? <Empty description={c.select} image={Empty.PRESENTED_IMAGE_SIMPLE} /> : <>
        <div className="mcp-group-query"><Input.Search aria-label={c.searchInstances} placeholder={c.searchInstances} maxLength={200} value={memberQuery} allowClear disabled={busy} onChange={event => { setMemberQuery(event.target.value); setMemberPage(1) }} /><span role="status">{instances?.total ?? 0} {c.instances}</span></div>
        <div className="mcp-group-members-scroll"><Table<McpGroupInstance> rowKey="instance_id" size="small" dataSource={instances?.instances ?? []} loading={membersLoading} pagination={false} locale={{ emptyText: c.noMatches }} columns={[
          { title: c.name, width: "30%", ellipsis: true, render: (_, item) => item.available && serverIds.has(item.instance_id) ? <Button type="link" className="mcp-group-instance-link" disabled={busy} onClick={() => onSelectInstance(item.instance_id)} title={item.name}>{item.name}</Button> : <span title={item.name}>{item.name}</span> },
          { title: c.instanceId, dataIndex: "instance_id", width: "30%", ellipsis: true },
          { title: c.state, render: (_, item) => <Tag color={item.available ? undefined : "warning"}>{item.available ? item.status === "not_loaded" ? c.notLoaded : localizeStatus(t, item.status) : c.missing}</Tag> },
          { title: c.groups, render: (_, item) => <span className="mcp-group-tags" title={item.groups.map(group => group.name).join("; ")}>{item.groups.slice(0, 3).map(group => <Tag key={group.id}>{group.name}</Tag>)}{item.groups.length > 3 && <Tag>+{item.groups.length - 3}</Tag>}</span> },
        ]} /></div>
        <Pagination aria-label={c.paging} current={memberPage} total={instances?.total ?? 0} pageSize={20} showSizeChanger={false} disabled={busy || membersLoading} onChange={setMemberPage} />
      </>}
    </section>
    {editing && <McpGroupEditor key={editing.group?.id || "create"} group={editing.group} locale={locale} t={t} onClose={() => setEditing(null)} returnFocusFallback={() => fallbackFocus.current?.focus()} onSaved={next => { setSelection(next.id); setDetail(next); setRefresh(value => value + 1); void toast.success(c.saved, 3) }} />}
    {toastContext}{confirmDialog}
  </>
}

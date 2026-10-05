import { useEffect, useId, useRef, useState } from "react"
import { Alert, Button, Input, Pagination, Radio, Table, Tag } from "antd"
import { canonicalGroupBody, mcpGroupsApi, type McpGroup, type McpGroupDraft, type McpGroupInstance } from "@/api/mcp-groups"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import type { Locale, TFunction } from "@/i18n"
import { groupCopy, groupError } from "./group-copy"
import { forgetGroupCreation, rememberGroupCreation, type GroupCreationScope } from "./group-create-recovery"

export function McpGroupEditor({ group, locale, t, onClose, onSaved, returnFocusFallback, recoveryScope, onRecoveryChange }: {
  group: McpGroup | null; locale: Locale; t: TFunction; onClose: () => void; onSaved: (group: McpGroup) => void
  returnFocusFallback: () => void
  recoveryScope: GroupCreationScope; onRecoveryChange: () => void
}) {
  const c = groupCopy(locale), id = useId()
  const [snapshot, setSnapshot] = useState(group)
  const [name, setName] = useState(group?.name ?? "")
  const [description, setDescription] = useState(group?.description ?? "")
  const [status, setStatus] = useState<"active" | "archived">(group?.status ?? "active")
  const [selected, setSelected] = useState<string[]>(group?.members.map(item => item.instance_id) ?? [])
  const [missing, setMissing] = useState<string[]>(group?.members.filter(item => item.available === false || item.status === "missing").map(item => item.instance_id) ?? [])
  const [reconfirmed, setReconfirmed] = useState<string[]>([])
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [catalog, setCatalog] = useState<{ instances: McpGroupInstance[]; total: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [catalogError, setCatalogError] = useState("")
  const [error, setError] = useState("")
  const [pending, setPending] = useState(false)
  const [creationUnknown, setCreationUnknown] = useState(false), [creationInfo, setCreationInfo] = useState("")
  const createAttempt = useRef<{ key: string; fingerprint: string; body: McpGroupDraft } | null>(null)
  const seenRefresh = useRef(0)
  const lock = useRef(false), generation = useRef(0), alive = useRef(true)
  const writeController = useRef<AbortController | null>(null)
  const [returnFocus] = useState(() => document.activeElement instanceof HTMLElement ? document.activeElement : null)
  const baseline = useRef(JSON.stringify([group?.name ?? "", group?.description ?? "", group?.status ?? "active", [...selected].sort()]))
  const dirty = baseline.current !== JSON.stringify([name, description, status, [...selected].sort()]) || reconfirmed.length > 0
  const { confirm, confirmDialog } = useConfirm(t, true)
  const close = useDraftCloseGuard({ dirty: dirty || creationUnknown, pending, locale,
    confirm: options => confirm(creationUnknown ? { ...options, description: c.createClose } : options),
    onClose: () => { if (creationUnknown && createAttempt.current) clearRecovery(); onClose() } })
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; writeController.current?.abort() } }, [])
  useEffect(() => {
    const controller = new AbortController(), current = ++generation.current
    const forceRefresh = seenRefresh.current !== refresh; seenRefresh.current = refresh
    setLoading(true); setCatalog(null); setCatalogError("")
    void mcpGroupsApi.instances({ q: query, offset: (page - 1) * 20, limit: 20, refresh: forceRefresh }, controller.signal)
      .then(next => { if (alive.current && current === generation.current) setCatalog(next) })
      .catch(cause => { if (alive.current && current === generation.current) setCatalogError(groupError(cause, locale)) })
      .finally(() => { if (alive.current && current === generation.current) setLoading(false) })
    return () => { generation.current++; controller.abort() }
  }, [query, page, refresh, locale])

  function clearRecovery() {
    const cleared = !createAttempt.current || forgetGroupCreation(recoveryScope, createAttempt.current.key)
    onRecoveryChange()
    return cleared
  }
  function adoptCreated(next: McpGroup) {
    const cleared = clearRecovery()
    setSnapshot(next); setCreationUnknown(false); setCreationInfo(c.createRecovered + (cleared ? "" : ` ${c.recoveryUnavailable}`)); setError("")
    baseline.current = JSON.stringify([next.name, next.description, next.status, next.members.map(item => item.instance_id).sort()])
    setMissing(next.members.filter(item => selected.includes(item.instance_id) && (item.available === false || item.status === "missing")).map(item => item.instance_id))
  }
  async function checkCreation() {
    if (lock.current || !createAttempt.current) return
    lock.current = true; setPending(true); setError("")
    const controller = new AbortController(); writeController.current = controller
    try { const next = await mcpGroupsApi.createResult(createAttempt.current.key, controller.signal); if (alive.current) adoptCreated(next) }
    catch (cause) { if (alive.current) setError(groupError(cause, locale)) }
    finally { lock.current = false; if (alive.current) setPending(false) }
  }
  async function save(retryOriginal = false) {
    if (lock.current || (!retryOriginal && !name.trim()) || selected.length > 1000) return
    let body: McpGroupDraft = { name, description, status, members: [...selected].sort(),
      reconfirm_members: reconfirmed.filter(item => selected.includes(item)), confirmed: true,
      ...(snapshot ? { expected_revision: snapshot.revision } : {}) }
    if (!snapshot) {
      const fingerprint = canonicalGroupBody(body)
      if (!createAttempt.current) createAttempt.current = { key: crypto.randomUUID().replace(/-/g, ""), fingerprint, body }
      else if (!retryOriginal && createAttempt.current.fingerprint !== fingerprint) { setError(c.createChanged); setCreationUnknown(true); return }
      body = { ...(retryOriginal ? createAttempt.current.body : body), request_key: createAttempt.current.key }
    }
    const wasUnknown = creationUnknown
    lock.current = true; setPending(true); setError("")
    const controller = new AbortController(); writeController.current = controller
    try {
      const next = await mcpGroupsApi.save(snapshot?.id, body, controller.signal)
      if (alive.current) {
        if (retryOriginal) adoptCreated(next)
        else { if (!snapshot) clearRecovery(); baseline.current = JSON.stringify([name, description, status, [...selected].sort()]); onSaved(next); onClose() }
      }
    } catch (cause) { if (alive.current) {
      let feedback = groupError(cause, locale)
      if (!snapshot) {
        const message = cause instanceof Error ? cause.message : String(cause)
        const rejected = !wasUnknown && /invalid_group_request|group_instance_unavailable|group_capacity|group_request_capacity|group_admin_required|group_connection_invalid|csrf/.test(message)
        if (rejected) createAttempt.current = null
        else if (createAttempt.current) {
          if (!rememberGroupCreation(recoveryScope, createAttempt.current.key)) setCreationInfo(c.recoveryUnavailable)
          onRecoveryChange()
        }
        setCreationUnknown(!rejected)
        if (!rejected && !/group_request_conflict|group_request_deleted|group_request_timeout/.test(message)) feedback = `${c.createUnconfirmed} ${feedback}`
      }
      setError(feedback)
    } }
    finally { lock.current = false; if (alive.current) setPending(false) }
  }
  async function reload() {
    if (!snapshot || lock.current) return
    if (dirty && !(await confirm({ title: c.reloadTitle, description: c.reloadHint, confirmText: c.reload, cancelText: t("cancel") }))) return
    if (!alive.current) return
    lock.current = true; setPending(true); setError("")
    const controller = new AbortController(); writeController.current = controller
    try {
      const next = await mcpGroupsApi.detail(snapshot.id, controller.signal)
      if (alive.current) {
        setSnapshot(next); setName(next.name); setDescription(next.description); setStatus(next.status); setCreationInfo("")
        setSelected(next.members.map(item => item.instance_id)); setMissing(next.members.filter(item => item.available === false || item.status === "missing").map(item => item.instance_id)); setReconfirmed([])
        baseline.current = JSON.stringify([next.name, next.description, next.status, next.members.map(item => item.instance_id).sort()]); setRefresh(value => value + 1)
      }
    } catch (cause) { if (alive.current) setError(groupError(cause, locale)) }
    finally { lock.current = false; if (alive.current) setPending(false) }
  }
  function remove(id: string) { setSelected(values => values.filter(value => value !== id)); setMissing(values => values.filter(value => value !== id)); setReconfirmed(values => values.filter(value => value !== id)) }
  return <>
    <FormDialog open title={snapshot ? c.edit : c.newGroup} description={c.metadata} closeLabel={t("close")}
      className="mcp-group-dialog" bodyClassName="mcp-group-dialog-body" dirty={dirty} pending={pending} error={error}
      onClose={() => void close()} onCloseAutoFocus={event => { event.preventDefault(); if (returnFocus?.isConnected) returnFocus.focus(); else returnFocusFallback() }}
      footer={<><Button disabled={pending} onClick={() => void close()}>{t("cancel")}</Button>{creationUnknown && !snapshot && <><Button disabled={pending} onClick={() => void checkCreation()}>{c.checkCreate}</Button><Button disabled={pending} onClick={() => void save(true)}>{c.retryCreate}</Button></>}{snapshot && <Button disabled={pending} onClick={() => void reload()}>{c.reload}</Button>}<Button type="primary" aria-label={c.save} aria-busy={pending} loading={pending} disabled={pending || !name.trim() || selected.length > 1000} onClick={() => void save()}>{c.save}</Button></>}>
      {creationInfo && <Alert type="info" showIcon title={creationInfo} />}
      <div className="mcp-group-form-row"><label htmlFor={`${id}-name`}>{c.name}</label><Input id={`${id}-name`} autoFocus maxLength={128} value={name} disabled={pending} onChange={event => setName(event.target.value)} /></div>
      <div className="mcp-group-form-row"><label htmlFor={`${id}-description`}>{c.description}</label><Input id={`${id}-description`} maxLength={500} value={description} disabled={pending} onChange={event => setDescription(event.target.value)} /></div>
      <div className="mcp-group-form-row"><span id={`${id}-state`}>{c.state}</span><Radio.Group aria-labelledby={`${id}-state`} disabled={pending} value={status} options={[{ value: "active", label: c.active }, { value: "archived", label: c.archived }]} onChange={event => setStatus(event.target.value as "active" | "archived")} /></div>
      <div className="mcp-group-member-heading"><h3>{c.members}</h3><span role="status">{selected.length} {c.selected}</span></div>
      <p className="text-xs text-muted-foreground">{c.memberLimit}</p>
      {missing.length > 0 && <Alert type="warning" showIcon title={c.missing} description={<>{c.missingHint}<div className="mcp-group-missing">{missing.map(value => <Tag key={value} closable={!pending} onClose={event => { event.preventDefault(); remove(value) }}>{value}</Tag>)}</div></>} />}
      <div className="mcp-group-query"><Input.Search aria-label={c.searchInstances} placeholder={c.searchInstances} value={query} maxLength={200} allowClear disabled={pending} onChange={event => { setQuery(event.target.value); setPage(1) }} /><Button disabled={pending || loading} onClick={() => setRefresh(value => value + 1)}>{c.refresh}</Button></div>
      {catalogError && <Alert role="alert" type="error" showIcon title={catalogError} action={<Button disabled={pending} onClick={() => setRefresh(value => value + 1)}>{c.retry}</Button>} />}
      <Table<McpGroupInstance> size="small" rowKey="instance_id" loading={loading} dataSource={catalog?.instances ?? []} pagination={false}
        locale={{ emptyText: catalogError ? c.failed : c.noMatches }}
        rowSelection={{ selectedRowKeys: selected, preserveSelectedRowKeys: true,
          onChange: keys => { const next = keys.map(String); if (next.length <= 1000) { setSelected(next); setReconfirmed(values => values.filter(value => next.includes(value))); setMissing(values => values.filter(value => next.includes(value))) } },
          onSelect: (record, checked) => { if (checked && snapshot?.members.some(item => item.instance_id === record.instance_id && (item.available === false || item.status === "missing"))) { setReconfirmed(values => [...new Set([...values, record.instance_id])]); setMissing(values => values.filter(value => value !== record.instance_id)) } },
          onSelectAll: (checked, _rows, changed) => { if (checked) { const restored = changed.filter(row => snapshot?.members.some(item => item.instance_id === row.instance_id && (item.available === false || item.status === "missing"))).map(row => row.instance_id); setReconfirmed(values => [...new Set([...values, ...restored])]); setMissing(values => values.filter(value => !restored.includes(value))) } },
          getCheckboxProps: record => ({ disabled: pending || (!selected.includes(record.instance_id) && selected.length >= 1000), name: record.instance_id, "aria-label": `${record.name} · ${record.instance_id}` }),
        }} columns={[
          { title: c.name, dataIndex: "name", ellipsis: true },
          { title: c.instanceId, dataIndex: "instance_id", ellipsis: true },
          { title: c.groups, render: (_, record) => <span className="mcp-group-tags" title={record.groups.map(item => item.name).join("; ")}>{record.groups.slice(0, 3).map(item => <Tag key={item.id}>{item.name}</Tag>)}{record.groups.length > 3 && <Tag>+{record.groups.length - 3}</Tag>}</span> },
        ]} />
      <Pagination className="mcp-group-pagination" aria-label={c.paging} current={page} total={catalog?.total ?? 0} pageSize={20} showSizeChanger={false} disabled={pending || loading} onChange={setPage} />
    </FormDialog>
    {confirmDialog}
  </>
}

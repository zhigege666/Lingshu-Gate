import { useEffect, useRef, useState } from "react"
import { Alert, InputNumber, Select } from "antd"
import { retentionApi, type RetentionJob, type RetentionPolicy, type RetentionPreview, type RetentionSnapshot } from "@/api/retention"
import { Button } from "@/components/ui/button"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { JsonPanel } from "@/components/json-panel"
import { retentionCopy } from "@/features/retention/copy"
import { assertPreview, assertSaved, assertSnapshot, assertJob, defaultRetentionDraft, policyDraft, retentionFields, samePolicy, shortensPolicy, validPolicy } from "@/features/retention/model"
import type { TFunction } from "@/i18n"

/** Mounted only by a capability-gated caller. No requests until explicitly opened. */
export function RetentionPolicySettings({ t }: { t: TFunction }) {
  const locale = t("all") === "全部" ? "zh-CN" : "en-US"
  const c = retentionCopy[locale]
  const [open, setOpen] = useState(false)
  const [snapshot, setSnapshot] = useState<RetentionSnapshot | null>(null)
  const [draft, setDraft] = useState<RetentionPolicy>(defaultRetentionDraft)
  const [baseline, setBaseline] = useState<RetentionPolicy>(defaultRetentionDraft)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")
  const [job, setJob] = useState<RetentionJob | null>(null)
  const owner = useRef(0)
  const pending = useRef(false)
  const draftRef = useRef(draft)
  draftRef.current = draft
  const dirty = !samePolicy(draft, baseline)
  const { confirm, confirmDialog } = useConfirm(t)
  useEffect(() => () => { owner.current++ }, [])
  const close = useDraftCloseGuard({ dirty, pending: busy, locale, confirm, onClose: () => {
    owner.current++; setOpen(false); setSnapshot(null); setError(""); setMessage(""); setJob(null)
  } })
  function failure(cause: unknown) {
    const text = cause instanceof Error ? cause.message : String(cause)
    setError(text === "retention_preview_stale" ? c.previewStale : text === "retention_save_unconfirmed" ? c.saveFailed : text)
    setSnapshot(null); setJob(null); setMessage("")
  }
  async function load(reset: boolean) {
    if (pending.current) return
    pending.current = true
    const revision = ++owner.current
    const preserve = !reset && dirty
    setBusy(true); setError(""); setMessage(""); setSnapshot(null)
    try {
      const value = await retentionApi.policy()
      if (revision !== owner.current) return
      assertSnapshot(value)
      setSnapshot(value); setBaseline(policyDraft(value))
      if (!preserve) setDraft(policyDraft(value))
      else setMessage(c.retained)
    } catch (cause) { if (revision === owner.current) failure(cause) }
    finally { pending.current = false; if (revision === owner.current) setBusy(false) }
  }
  function show() { setOpen(true); setJob(null); setDraft(defaultRetentionDraft); setBaseline(defaultRetentionDraft); void load(true) }
  async function save() {
    if (pending.current || !snapshot) return
    const candidate = policyDraft(draftRef.current)
    if (!validPolicy(candidate)) { setError(c.invalid); return }
    const before = snapshot
    pending.current = true; setBusy(true); setError(""); setMessage("")
    const revision = ++owner.current
    try {
      let confirmedPreviewId: string | undefined
      if (shortensPolicy(before, candidate)) {
        const preview = await retentionApi.preview(candidate)
        if (revision !== owner.current) return
        assertPreview(preview, before, candidate)
        if (!(await confirm({ title: c.shrinkTitle, description: c.shrinkDescription, details: <Impact preview={preview} before={before} locale={locale} />, destructive: true }))) return
        if (revision !== owner.current) return
        assertPreview(preview, before, candidate)
        confirmedPreviewId = preview.preview_id
      }
      const result = await retentionApi.save(candidate, before.revision, confirmedPreviewId)
      if (revision !== owner.current) return
      assertSaved(result, before, candidate)
      setSnapshot(result); setBaseline(policyDraft(result)); setDraft(policyDraft(result)); setMessage(c.saved); setJob(null)
    } catch (cause) { if (revision === owner.current) failure(cause) }
    finally { pending.current = false; if (revision === owner.current) setBusy(false) }
  }
  async function cleanup() {
    if (pending.current || !snapshot || !snapshot.worker_enabled || dirty || (job && ["queued", "running", "retry"].includes(job.state))) return
    const before = snapshot
    pending.current = true; setBusy(true); setError(""); setMessage("")
    const revision = ++owner.current
    try {
      const preview = await retentionApi.preview(policyDraft(before))
      if (revision !== owner.current) return
      assertPreview(preview, before, before)
      if (!(await confirm({ title: c.cleanupTitle, description: c.cleanupDescription, details: <Impact preview={preview} locale={locale} />, destructive: true }))) return
      if (revision !== owner.current) return
      assertPreview(preview, before, before)
      const result = await retentionApi.cleanup(preview)
      if (revision !== owner.current) return
      assertJob(result, before.revision)
      setJob(result)
    } catch (cause) { if (revision === owner.current) failure(cause) }
    finally { pending.current = false; if (revision === owner.current) setBusy(false) }
  }
  async function refreshJob() {
    if (pending.current || !job) return
    const id = job.id
    pending.current = true; setBusy(true); setError("")
    const revision = ++owner.current
    try {
      const result = await retentionApi.job(id)
      if (revision !== owner.current) return
      assertJob(result)
      if (result.id !== id) throw new Error(c.reloadRequired)
      setJob(result)
    } catch (cause) { if (revision === owner.current) failure(cause) }
    finally { pending.current = false; if (revision === owner.current) setBusy(false) }
  }
  async function cancelJob() {
    if (pending.current || !job || !["queued", "running", "retry"].includes(job.state)) return
    const id = job.id
    pending.current = true; setBusy(true); setError("")
    const revision = ++owner.current
    try {
      if (!(await confirm({ title: c.jobCancelTitle, description: c.jobCancelDescription }))) return
      if (revision !== owner.current) return
      const result = await retentionApi.cancel(id)
      if (revision !== owner.current) return
      assertJob(result)
      if (result.id !== id) throw new Error(c.reloadRequired)
      setJob(result)
    } catch (cause) { if (revision === owner.current) failure(cause) }
    finally { pending.current = false; if (revision === owner.current) setBusy(false) }
  }
  const labels = { runtime_logs_retention_days: c.logs, events_retention_days: c.events, call_records_retention_days: c.calls }
  return <>
    <Button variant="outline" onClick={show}>{c.title}</Button>
    <FormDialog open={open} title={c.title} description={c.description} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} pending={busy} error={error} className="max-w-3xl" footer={<>
      <Button variant="outline" disabled={busy} onClick={() => void close()}>{c.cancel}</Button>
      <Button type="submit" form="retention-policy-form" disabled={busy || !snapshot || !dirty || !validPolicy(draft)}>{c.save}</Button>
    </>}>
      {!snapshot ? <div className="space-y-3"><p role="status">{busy ? c.loading : c.reloadRequired}</p>{!busy && <Button onClick={() => void load(false)}>{c.refresh}</Button>}</div> : <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2"><span>{c.revision}: {snapshot.revision}</span><Button variant="outline" disabled={busy} onClick={() => void load(false)}>{c.refresh}</Button></div>
        {message && <Alert type="success" title={message} />}
        <form id="retention-policy-form" className="space-y-4" onSubmit={event => { event.preventDefault(); void save() }}>
          <p className="text-sm">{c.defaults}</p>
          <div className="grid gap-4 sm:grid-cols-3">{retentionFields.map(field => <label key={field} className="flex min-w-0 flex-col gap-2 text-sm"><span>{labels[field]}</span><InputNumber aria-label={labels[field]} className="w-full" min={1} max={3650} precision={0} disabled={busy} value={draft[field]} onChange={value => setDraft(current => ({ ...current, [field]: value ?? 0 }))} /></label>)}</div>
          <label className="flex flex-col gap-2 text-sm"><span>{c.mode}</span><Select getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!} aria-label={c.mode} disabled={busy} value={draft.payload_mode} options={[{ value: "metadata_only", label: c.metadata }, { value: "redacted", label: c.redacted }]} onChange={payload_mode => setDraft(current => ({ ...current, payload_mode }))} /></label>
          <Alert type="warning" showIcon title={c.privacy} />
        </form>
        <section className="space-y-3 border-t pt-4" aria-label={c.cleanup}>
          <Alert type={snapshot.worker_enabled ? "info" : "warning"} title={snapshot.worker_enabled ? c.enabled : c.disabled} />
          {dirty && <p className="text-sm">{c.cleanDraft}</p>}
          <Button variant="destructive" disabled={busy || dirty || !snapshot.worker_enabled || Boolean(job && ["queued", "running", "retry"].includes(job.state))} onClick={() => void cleanup()}>{c.cleanup}</Button>
          {job && <div className="space-y-2" aria-live="polite">
            <Alert type={job.state === "failed" || job.state === "cancelled" ? "error" : job.state === "succeeded" ? "success" : "info"} title={job.state === "cancelled" ? c.jobCancelled : job.state === "failed" ? c.jobFailed : job.state === "succeeded" ? c.jobDone : c.queued} />
            <p className="break-all text-sm">{c.job}: {job.id} · {job.state}</p><p className="text-sm">{c.noPolling}</p>
            <Button variant="outline" disabled={busy} onClick={() => void refreshJob()}>{c.jobRefresh}</Button>
            {["queued", "running", "retry"].includes(job.state) && <Button variant="outline" disabled={busy} onClick={() => void cancelJob()}>{c.jobCancel}</Button>}
            <details><summary>{c.result}</summary><JsonPanel copyLabel={t("copy")} data={job} /></details>
          </div>}
        </section>
      </div>}
    </FormDialog>{confirmDialog}
  </>
}

function Impact({ preview, before, locale }: { preview: RetentionPreview; before?: RetentionPolicy; locale: "zh-CN" | "en-US" }) {
  const c = retentionCopy[locale]
  const names = { logs: c.logs, events: c.events, invocation_audits: c.calls }
  const fields = { logs: "runtime_logs_retention_days", events: "events_retention_days", invocation_audits: "call_records_retention_days" } as const
  return <div className="space-y-3 text-sm"><p>{c.revision}: {preview.revision}</p><dl className="space-y-3">{(["logs", "events", "invocation_audits"] as const).map(table => <div className="rounded border p-3" key={table}><dt className="font-medium">{names[table]}</dt><dd>{before && `${before[fields[table]]} → `}{preview.policy[fields[table]]} {c.days}</dd><dd>{c.cutoff}: <span className="break-all">{preview.cutoffs[table]}</span></dd><dd>{c.count}: {preview.counts[table]}</dd></div>)}</dl><p>{c.expires}: {preview.expires_at}</p><p>{c.notCount}</p></div>
}

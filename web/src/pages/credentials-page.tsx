import { useRemainingViewport } from "@/components/use-remaining-viewport"
import "./maintenance-lists.css"
import { ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import { usePageRefresh } from "@/components/page-refresh"
import { useEffect, useMemo, useRef, useState } from "react"
import { KeyRound, Plus } from "lucide-react"
import { api, type Credential, type CredentialSaveRequest } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { FormDialog } from "@/components/form-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { FilterRadio } from "@/components/filter-radio"
import { Toaster } from "@/components/ui/toast"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"
import { CredentialModeTabs } from "@/pages/credential-mode-tabs"
import { credentialWriteKey } from "@/features/credential-writes"

const emptyForm: CredentialSaveRequest = {
  name: "",
  value: "",
  description: "",
}

export function CredentialsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  return <CredentialModeTabs locale={locale} t={t} scope="shared" serviceCredentials={<SharedServiceCredentialsPage locale={locale} t={t} />} />
}

function SharedServiceCredentialsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = locale === "zh-CN" ? { secretMode: "凭据值处理", keep: "保持现有凭据值", replace: "替换凭据值", keepHint: "保存名称或说明时将保留现有秘密。旧秘密不会显示。", replaceHint: "输入新的凭据值；保存失败时保留本次输入以便重试。" } : { secretMode: "Credential value", keep: "Keep current secret", replace: "Replace secret", keepHint: "Saving the name or description keeps the existing secret. Its value is never shown.", replaceHint: "Enter a new secret. A failed save keeps this attempt's input for retry." }
  const remainingViewport = useRemainingViewport()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [selectedRevision, setSelectedRevision] = useState("")
  const [editorOpen, setEditorOpen] = useState(false)
  const createTrigger = useRef<HTMLButtonElement>(null)
  const editorReturnFocus = useRef<HTMLButtonElement | null>(null)
  const [form, setForm] = useState<CredentialSaveRequest>({ ...emptyForm })
  const [secretMode, setSecretMode] = useState<"keep" | "replace">("replace")
  const [formError, setFormError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const [latestCredential, setLatestCredential] = useState<Credential | null>(null)
  const baseline = useRef({ ...emptyForm })
  const saving = useRef(false)
  const writeKey = useRef<string | null>(null)
  const deleteAttempts = useRef(new Map<string, { revision: string; key: string }>())
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ title: string; body: unknown } | null>(null)
  const [query, setQuery] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)
  const closeEditor = useDraftCloseGuard({ dirty: JSON.stringify(form) !== JSON.stringify(baseline.current) || (Boolean(selectedId) && secretMode !== "keep"), pending: busy, locale, confirm, onClose: () => { setEditorOpen(false); setForm({ ...emptyForm }); setFormError(null) } })
  const filteredCredentials = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return credentials
    return credentials.filter((credential) => `${credential.id} ${credential.name} ${credential.description || ""}`.toLowerCase().includes(needle))
  }, [credentials, query])

  const paging = useListPage(filteredCredentials, query)

  usePageRefresh(load, busy)
  useEffect(() => { void load() }, [])
  useEffect(() => { writeKey.current = null }, [form, secretMode, selectedId, selectedRevision])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      setCredentials(await api.credentials())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function edit(credential: Credential, trigger: HTMLButtonElement) {
    // 编辑操作常驻行内，关闭弹窗后回到本次编辑按钮。
    editorReturnFocus.current = trigger
    if (busy) return
    setFormError(null)
    setShowValidation(false)
    setLatestCredential(null)
    setSecretMode("keep")
    baseline.current = { name: credential.name, value: null, description: credential.description, http_scopes: credential.http_scopes || [] }
    setSelectedId(credential.id)
    setSelectedRevision(credential.updated_at)
    setForm({ ...baseline.current })
    setEditorOpen(true)
  }

  function createNew() {
    editorReturnFocus.current = createTrigger.current
    if (busy) return
    setFormError(null)
    setShowValidation(false)
    setLatestCredential(null)
    setSecretMode("replace")
    baseline.current = { ...emptyForm }
    setSelectedId("")
    setSelectedRevision("")
    setForm({ ...emptyForm })
    setEditorOpen(true)
  }

  async function save() {
    if (busy || saving.current) return
    setShowValidation(true)
    if (nameInvalid || valueInvalid) {
      document.getElementById(nameInvalid ? "credential-name" : "credential-value")?.focus()
      return
    }
    saving.current = true
    setBusy(true)
    setFormError(null)
    setMessage(null)
    try {
      writeKey.current ||= credentialWriteKey()
      const payload: CredentialSaveRequest = { ...form, value: selectedId && secretMode === "keep" ? null : form.value || null, idempotency_key: writeKey.current,
        ...(selectedId ? { expected_revision: selectedRevision } : {}) }
      if (selectedId && JSON.stringify(form.http_scopes) === JSON.stringify(baseline.current.http_scopes)) delete payload.http_scopes
      else if (payload.http_scopes) payload.http_scopes = payload.http_scopes.map(({ server_id, origin }) => ({ server_id, origin }))
      const credential = selectedId ? await api.updateCredential(selectedId, payload) : await api.createCredential(payload)
      setSelectedId(credential.id)
      setSelectedRevision(credential.updated_at)
      setForm({ name: credential.name, value: null, description: credential.description })
      setMessage(`${t("saved")}: ${credential.id}${credential.value_saved ? (locale === "zh-CN" ? "；后续请求使用新凭据，连接尚未验证。" : "; subsequent requests use the new credential. The connection has not been verified.") : ""}`)
      await load()
      setEditorOpen(false)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  async function remove(id: string) {
    const credential = credentials.find(item => item.id === id)
    if (!credential || busy) return
    if (!(await confirm({ title: t("confirmDeleteCredential"), description: id, destructive: true }))) return
    setBusy(true)
    setError(null)
    try {
      let attempt = deleteAttempts.current.get(id)
      if (!attempt || attempt.revision !== credential.updated_at) {
        attempt = { revision: credential.updated_at, key: credentialWriteKey() }
        deleteAttempts.current.set(id, attempt)
      }
      await api.deleteCredential(id, attempt.revision, attempt.key)
      deleteAttempts.current.delete(id)
      setMessage(`${t("deleted")}: ${id}`)
      if (selectedId === id) {
        setSelectedId("")
        setForm({ ...emptyForm })
        setEditorOpen(false)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function copyReference(id: string) {
    const reference = credentialRef(id)
    try {
      await navigator.clipboard.writeText(reference)
      setMessage(`${t("copied")}: ${reference}`)
    } catch {
      setDetail({ title: `${t("copyRef")}: ${id}`, body: { reference, env_example: `API_KEY=${reference}` } })
    }
  }

  async function readLatestCredential() {
    if (busy || !selectedId) return
    setBusy(true)
    try { setLatestCredential(await api.credential(selectedId)) }
    catch (err) { setFormError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  function showDetail(credential: Credential) {
    setDetail({ title: credential.id, body: { credential, reference: credentialRef(credential.id) } })
  }

  const nameInvalid = form.name.trim() === ""
  const valueInvalid = (!selectedId || secretMode === "replace") && ((form.value || "").trim() === "" || form.value === "***")

  return (
    <div ref={remainingViewport} className="maintenance-list-page flex flex-col gap-4">
      <PageHeader closeLabel={t("close")}
        eyebrow={t("secretsCenter")}
        title={t("credentials")}
        description={t("credentialsDesc")}
        helpLabel={t("pageHelp")}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("name")}`} resultCount={filteredCredentials.length} resultLabel={t("credentials")} clearLabel={t("clearSearch")} />}
        actions={<Button ref={createTrigger} onClick={createNew} disabled={busy}><Plus />{t("newCredential")}</Button>}
      />
      {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription><Button variant="outline" size="sm" className="mt-2" disabled={busy} onClick={() => void load()}>{t("refresh")}</Button></Alert>}
      <FormDialog dirty={JSON.stringify(form) !== JSON.stringify(baseline.current) || (Boolean(selectedId) && secretMode !== "keep")} open={editorOpen} onClose={() => void closeEditor()} title={selectedId ? t("editCredential") : t("newCredential")} description={t("credentialsDesc")} closeLabel={t("close")} pending={busy} error={formError}
        onCloseAutoFocus={event => { event.preventDefault(); (editorReturnFocus.current?.isConnected ? editorReturnFocus.current : createTrigger.current)?.focus() }}
        footer={<><Button variant="outline" onClick={() => void closeEditor()} disabled={busy}>{t("cancel")}</Button><Button type="submit" form="credential-editor" disabled={busy}><KeyRound />{t("save")}</Button></>}>
        <form id="credential-editor" onSubmit={event => { event.preventDefault(); void save() }} className="flex flex-col gap-4">
          {formError && selectedId && <section className="space-y-2 text-xs">
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void readLatestCredential()}>{locale === "zh-CN" ? "读取当前凭据版本" : "Read current credential revision"}</Button>
            {latestCredential && <><p>{locale === "zh-CN" ? "当前已保存版本" : "Current saved revision"}: {latestCredential.updated_at}</p><p>{locale === "zh-CN" ? "名称 / 说明" : "Name / description"}: {latestCredential.name} / {latestCredential.description || "—"}</p><p>{locale === "zh-CN" ? "HTTP 用途" : "HTTP targets"}: {(latestCredential.http_scopes || []).map(scope => `${scope.server_id} → ${scope.origin}`).join("; ") || "—"}</p><p>{locale === "zh-CN" ? "核对差异后，可用该版本提交当前表单；保持凭据值会保留服务器当前的秘密。" : "After reviewing differences, use this revision with your current form. Keeping the secret preserves the value currently stored on the server."}</p><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setSelectedRevision(latestCredential.updated_at); writeKey.current = null; setFormError(null); setLatestCredential(null) }}>{locale === "zh-CN" ? "使用此版本继续编辑" : "Use this revision and continue editing"}</Button></>}
          </section>}
          <Field id="credential-name" label={t("name")}><Input id="credential-name" value={form.name} disabled={busy} aria-required="true" aria-invalid={showValidation && nameInvalid || undefined} aria-describedby={showValidation && nameInvalid ? "credential-name-error" : undefined} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} placeholder="SERVICE_PASSWORD" />{showValidation && nameInvalid && <span id="credential-name-error" className="text-xs text-destructive">{t("required")}</span>}</Field>
          {selectedId && <Field id="credential-secret-mode" label={c.secretMode} help={`${c.keepHint} ${t("credentialRefHint")}`} helpId="credential-secret-mode-hint" zh={locale === "zh-CN"}><FilterRadio id="credential-secret-mode" hideLabel label={c.secretMode} aria-describedby="credential-secret-mode-hint" value={secretMode} disabled={busy} onChange={value => { const mode = value as "keep" | "replace"; setSecretMode(mode); setForm(current => ({ ...current, value: mode === "keep" ? null : "" })) }} options={[{ value: "keep", label: c.keep }, { value: "replace", label: c.replace }]} /></Field>}
          {(!selectedId || secretMode === "replace") && <Field id="credential-value" label={t("credentialValue")} help={selectedId ? c.replaceHint : `${c.replaceHint} ${t("credentialRefHint")}`} helpId="credential-value-hint" zh={locale === "zh-CN"}><Input id="credential-value" type="password" autoComplete="new-password" value={form.value || ""} disabled={busy} aria-required="true" aria-invalid={showValidation && valueInvalid || undefined} aria-describedby={showValidation && valueInvalid ? "credential-value-error credential-value-hint" : "credential-value-hint"} onChange={event => setForm(current => ({ ...current, value: event.target.value }))} />{showValidation && valueInvalid && <span id="credential-value-error" className="text-xs text-destructive">{t("required")}</span>}</Field>}
          <Field id="credential-description" label={t("description")}><Textarea id="credential-description" value={form.description || ""} disabled={busy} onChange={event => setForm(current => ({ ...current, description: event.target.value }))} /></Field>
          <Field id="credential-http-scopes" label={locale === "zh-CN" ? "HTTP MCP 用途" : "HTTP MCP targets"}>
            <div id="credential-http-scopes" className="space-y-2">
              <p className="text-xs text-muted-foreground">{locale === "zh-CN" ? "指定可使用此凭据的服务 ID 和源地址（协议、主机、端口）。留空时不能用于新的 HTTP MCP 连接；Git、构建等其他用途保持各自规则。" : "Choose the service ID and origin (scheme, host and port) allowed to use this credential. Empty targets cannot authorize new HTTP MCP connections; Git and build credentials retain their own rules."}</p>
              {(form.http_scopes || []).map((scope, index) => <div key={index} className="flex flex-wrap items-center gap-2">
                <Input className="min-w-0 flex-1" aria-label={`${locale === "zh-CN" ? "允许的服务 ID" : "Allowed service ID"} ${index + 1}`} placeholder="service-id" value={scope.server_id} disabled={busy} onChange={event => setForm(current => ({ ...current, http_scopes: current.http_scopes?.map((item, i) => i === index ? { ...item, server_id: event.target.value, server_binding: undefined } : item) }))} />
                <Input className="min-w-0 flex-[2]" aria-label={`${locale === "zh-CN" ? "允许的源地址" : "Allowed origin"} ${index + 1}`} placeholder="https://service.example:443" value={scope.origin} disabled={busy} onChange={event => setForm(current => ({ ...current, http_scopes: current.http_scopes?.map((item, i) => i === index ? { ...item, origin: event.target.value, server_binding: undefined } : item) }))} />
                <Button type="button" variant="ghost" size="sm" disabled={busy} aria-label={`${locale === "zh-CN" ? "移除 HTTP 用途" : "Remove HTTP target"} ${index + 1}`} onClick={() => setForm(current => ({ ...current, http_scopes: current.http_scopes?.filter((_, i) => i !== index) }))}>{locale === "zh-CN" ? "移除" : "Remove"}</Button>
              </div>)}
              <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setForm(current => ({ ...current, http_scopes: [...(current.http_scopes || []), { server_id: "", origin: "" }] }))}>{locale === "zh-CN" ? "添加 HTTP 用途" : "Add HTTP target"}</Button>
            </div>
          </Field>
        </form>
      </FormDialog>

        <Card className="maintenance-list-card">
          <CardContent className="maintenance-list-content p-3 md:p-4">
            <ListViewport viewport={paging.viewport} label={t("toolShowing")}>
            <Table className="maintenance-table maintenance-credential-table">
              <TableHeader><TableRow><TableHead>{t("id")}</TableHead><TableHead>{t("name")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>{t("updatedAt")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {filteredCredentials.length === 0 ? <TableEmptyRow colSpan={5} title={busy ? t("loadingData") : error ? t("error") : query.trim() ? t("noMatchingRecords") : t("noData")} /> : paging.items.map((credential) => <TableRow key={credential.id} className={selectedId === credential.id ? "cursor-pointer bg-accent/50" : "cursor-pointer"} onClick={() => showDetail(credential)}>
                  <TableCell><button type="button" className="text-left text-primary underline-offset-4 hover:underline focus-visible:underline" onClick={() => showDetail(credential)}><code>{credential.id}</code></button><div className="text-xs text-muted-foreground">{credential.value_masked}</div><div className="maintenance-row-summary">{credential.name}</div></TableCell>
                  <TableCell>{credential.name}</TableCell>
                  <TableCell>{credential.description || "-"}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{formatDateTime(credential.updated_at)}</TableCell>
                  <TableCell onClick={(event) => event.stopPropagation()}><ActionMenu inline label={t("actions")}><ActionMenuItem disabled={busy} onClick={(event) => edit(credential, event.currentTarget)}>{t("edit")}</ActionMenuItem><ActionMenuItem onClick={() => void copyReference(credential.id)}>{t("copyRef")}</ActionMenuItem><ActionMenuItem onClick={() => showDetail(credential)}>{t("detail")}</ActionMenuItem><ActionMenuItem destructive disabled={busy} onClick={() => void remove(credential.id)}>{t("delete")}</ActionMenuItem></ActionMenu></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
            </ListViewport>
            <ListPagination paging={paging} t={t} />
          </CardContent>
        </Card>

      <Dialog open={detail !== null} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent closeLabel={t("close")} className="max-w-2xl">
          <DialogHeader><DialogTitle>{detail?.title || ""}</DialogTitle><DialogDescription>{t("credentialResultDesc")}</DialogDescription></DialogHeader>
          <DialogBody><JsonPanel copyLabel={t("copy")} data={detail?.body} maxHeight="max-h-[60vh]" /></DialogBody>
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <Toaster toast={message ? { message, tone: "success" } : null} onClose={() => setMessage(null)} />
    </div>
  )
}

function credentialRef(id: string) {
  return `\${credential:${id}}`
}

function Field({ label, id, help, helpId, zh, children }: { label: string; id: string; help?: React.ReactNode; helpId?: string; zh?: boolean; children: React.ReactNode }) {
  return <div className="gate-form-row"><Label className="gate-form-label flex-nowrap whitespace-nowrap" htmlFor={id} help={help} helpLabel={label} helpId={helpId} zh={zh}>{label}</Label><div className="gate-form-control">{children}</div></div>
}

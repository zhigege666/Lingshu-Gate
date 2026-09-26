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

const emptyForm: CredentialSaveRequest = {
  name: "",
  value: "",
  description: "",
}

export function CredentialsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = locale === "zh-CN" ? { secretMode: "凭据值处理", keep: "保持现有凭据值", replace: "替换凭据值", keepHint: "保存名称或说明时将保留现有秘密。旧秘密不会显示。", replaceHint: "输入新的凭据值；保存失败时保留本次输入以便重试。" } : { secretMode: "Credential value", keep: "Keep current secret", replace: "Replace secret", keepHint: "Saving the name or description keeps the existing secret. Its value is never shown.", replaceHint: "Enter a new secret. A failed save keeps this attempt's input for retry." }
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [editorOpen, setEditorOpen] = useState(false)
  const createTrigger = useRef<HTMLButtonElement>(null)
  const editorReturnFocus = useRef<HTMLButtonElement | null>(null)
  const [form, setForm] = useState<CredentialSaveRequest>({ ...emptyForm })
  const [secretMode, setSecretMode] = useState<"keep" | "replace">("replace")
  const [formError, setFormError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const baseline = useRef({ ...emptyForm })
  const saving = useRef(false)
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

  usePageRefresh(load, busy)
  useEffect(() => { void load() }, [])

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

  function edit(credential: Credential, menuItem: HTMLButtonElement) {
    // 菜单项打开弹窗后会卸载，关闭时应回到仍在表格中的菜单按钮。
    const menuId = menuItem.closest('[role="menu"]')?.id
    editorReturnFocus.current = Array.from(document.querySelectorAll<HTMLButtonElement>('button[aria-controls]'))
      .find(button => button.getAttribute("aria-controls") === menuId) || createTrigger.current
    if (busy) return
    setFormError(null)
    setShowValidation(false)
    setSecretMode("keep")
    baseline.current = { name: credential.name, value: "***", description: credential.description }
    setSelectedId(credential.id)
    setForm({ name: credential.name, value: "***", description: credential.description })
    setEditorOpen(true)
  }

  function createNew() {
    editorReturnFocus.current = createTrigger.current
    if (busy) return
    setFormError(null)
    setShowValidation(false)
    setSecretMode("replace")
    baseline.current = { ...emptyForm }
    setSelectedId("")
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
      const payload = { ...form, value: selectedId && secretMode === "keep" ? "***" : form.value || null }
      const credential = selectedId ? await api.updateCredential(selectedId, payload) : await api.createCredential(payload)
      setSelectedId(credential.id)
      setForm({ name: credential.name, value: "***", description: credential.description })
      setMessage(`${t("saved")}: ${credential.id}`)
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
    if (!(await confirm({ title: t("confirmDeleteCredential"), description: id, destructive: true }))) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteCredential(id)
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

  function showDetail(credential: Credential) {
    setDetail({ title: credential.id, body: { credential, reference: credentialRef(credential.id) } })
  }

  const nameInvalid = form.name.trim() === ""
  const valueInvalid = (!selectedId || secretMode === "replace") && (form.value || "").trim() === ""

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
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
          <div className="flex flex-col gap-2"><Label htmlFor="credential-name">{t("name")}</Label><Input id="credential-name" value={form.name} disabled={busy} aria-required="true" aria-invalid={showValidation && nameInvalid || undefined} aria-describedby={showValidation && nameInvalid ? "credential-name-error" : undefined} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} placeholder="SERVICE_PASSWORD" />{showValidation && nameInvalid && <span id="credential-name-error" className="text-xs text-destructive">{t("required")}</span>}</div>
          {selectedId && <div className="flex flex-col gap-2"><Label htmlFor="credential-secret-mode">{c.secretMode}</Label><select id="credential-secret-mode" className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={secretMode} disabled={busy} onChange={event => { const mode = event.target.value as "keep" | "replace"; setSecretMode(mode); setForm(current => ({ ...current, value: mode === "keep" ? "***" : "" })) }}><option value="keep">{c.keep}</option><option value="replace">{c.replace}</option></select></div>}
          {selectedId && secretMode === "keep" ? <p className="text-sm text-muted-foreground">{c.keepHint}</p> : <div className="flex flex-col gap-2"><Label htmlFor="credential-value">{t("credentialValue")}</Label><Input id="credential-value" type="password" autoComplete="new-password" value={form.value || ""} disabled={busy} aria-required="true" aria-invalid={showValidation && valueInvalid || undefined} aria-describedby="credential-value-hint" onChange={event => setForm(current => ({ ...current, value: event.target.value }))} /><p id="credential-value-hint" className="text-xs text-muted-foreground">{c.replaceHint}</p>{showValidation && valueInvalid && <span className="text-xs text-destructive">{t("required")}</span>}</div>}
          <div className="flex flex-col gap-2"><Label htmlFor="credential-description">{t("description")}</Label><Textarea id="credential-description" value={form.description || ""} disabled={busy} onChange={event => setForm(current => ({ ...current, description: event.target.value }))} /></div>
          <p className="text-xs text-muted-foreground">{t("credentialRefHint")}</p>
        </form>
      </FormDialog>

        <Card>
          <CardContent className="overflow-x-auto p-3 md:p-4">
            <Table>
              <TableHeader><TableRow><TableHead>{t("id")}</TableHead><TableHead>{t("name")}</TableHead><TableHead>{t("description")}</TableHead><TableHead>{t("updatedAt")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {filteredCredentials.length === 0 ? <TableEmptyRow colSpan={5} title={busy ? t("loadingData") : error ? t("error") : t("noData")} /> : filteredCredentials.map((credential) => <TableRow key={credential.id} className={selectedId === credential.id ? "cursor-pointer bg-accent/50" : "cursor-pointer"} onClick={() => showDetail(credential)}>
                  <TableCell><button type="button" className="text-left text-primary underline-offset-4 hover:underline focus-visible:underline" onClick={() => showDetail(credential)}><code>{credential.id}</code></button><div className="text-xs text-muted-foreground">{credential.value_masked}</div></TableCell>
                  <TableCell>{credential.name}</TableCell>
                  <TableCell>{credential.description || "-"}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{formatDateTime(credential.updated_at)}</TableCell>
                  <TableCell onClick={(event) => event.stopPropagation()}><ActionMenu label={t("actions")}><ActionMenuItem disabled={busy} onClick={(event) => edit(credential, event.currentTarget)}>{t("edit")}</ActionMenuItem><ActionMenuItem onClick={() => void copyReference(credential.id)}>{t("copyRef")}</ActionMenuItem><ActionMenuItem onClick={() => showDetail(credential)}>{t("detail")}</ActionMenuItem><ActionMenuItem destructive disabled={busy} onClick={() => void remove(credential.id)}>{t("delete")}</ActionMenuItem></ActionMenu></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

      <Dialog open={detail !== null} onOpenChange={(open) => { if (!open) setDetail(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>{detail?.title || ""}</DialogTitle><DialogDescription>{t("credentialResultDesc")}</DialogDescription></DialogHeader>
          <DialogBody><JsonPanel data={detail?.body} maxHeight="max-h-[60vh]" /></DialogBody>
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
